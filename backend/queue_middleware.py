import asyncio
import time
import orjson
import redis
import aiohttp
from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from config import REDIS_CONFIG, PERFORMANCE_STATS
from config import logger
import auth_module
import runtime_config
import token_counter
import usage_module
from db_module import write_model_usage
from response_utils import create_invalid_model_response

# 初始化Redis连接
r = redis.Redis(**REDIS_CONFIG)

class QueueMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 定义不需要经过队列调度的路径
        exempt_paths = ["/", "/health", "/docs", "/redoc", "/openapi.json", "/v1/models", "/queue/status", "/scheduler/monitor"]
        exempt_prefixes = ["/api/"]
        
        # body = await request.body()
        # body_dict = orjson.loads(body)
        # logger.info(f"[Gateway] Request body: {body_dict}")

        if request.url.path in exempt_paths or any(request.url.path.startswith(prefix) for prefix in exempt_prefixes):
            return await call_next(request)
                
        # 只有/v1/chat/completions和/v1/messages接口需要经过优先级队列调度
        if request.url.path not in ["/v1/chat/completions", "/v1/messages"]:
            return await self._forward_request(request)

        # 记录网关开始处理时间
        gateway_start_time = time.time()

        # 获取请求体
        body = await request.body()

        # 解析请求体
        try:
            body_dict = orjson.loads(body)
            # logger.info(f"[Gateway] Request path: {request.url.path}, body: {body_dict}")  # 打印请求路径和请求体
        except orjson.JSONDecodeError as e:
            body_str = body.decode('utf-8')
            error_pos = e.pos
            start_pos = max(0, error_pos - 30)
            end_pos = min(len(body_str), error_pos + 30)
            context = body_str[start_pos:end_pos]
            error_msg = f"JSON解析错误: {e}，错误位置附近: ...{context}..."
            logger.error(f"[Gateway] {error_msg}")
            return create_invalid_model_response("unknown", error_message=error_msg)
        
        models = runtime_config.get_models()
        model_name = body_dict.get("model", "qwen3-coder")
        stream = body_dict.get("stream", False)
        
        # 检查模型名称是否在配置列表中
        if model_name not in models:
            response = create_invalid_model_response(model_name)
            # 统计网关处理时间
            if PERFORMANCE_STATS["enabled"]:
                gateway_time = time.time() - gateway_start_time
                logger.info(f"GatewayTime: {gateway_time:.3f}s")
            return response
        
        model_config = models[model_name]

        # Generate request ID and get client IP early for rate limiting
        req_id = f"req:{time.time_ns()}"
        client_ip = auth_module.get_client_ip(request)

        # Authenticate and record request for rate limiting
        user = await auth_module.authenticate_request(
            request,
            allow_auto_register=True,
            record_for_rate_limit={
                "request_id": req_id,
                "model_name": model_name,
                "ip_address": client_ip,
            }
        )
        if not user:
            return create_invalid_model_response(
                model_name,
                error_message="未认证或 API key 无效",
                stream=stream,
            )
        # 统一降质触发条件：quota_rejected 或 daily_quota_exceeded
        should_degrade = (user.get("_quota_rejected") or user.get("_daily_quota_exceeded")) and _user_priority(user) != 1
        degrade_config = _degrade_config(model_config) if should_degrade else None
        if should_degrade and not degrade_config:
            return create_invalid_model_response(
                model_name,
                error_message="额度已用完",
                stream=stream,
            )
        if degrade_config:
            response = await self._forward_degraded_request(
                request=request,
                body_dict=body_dict,
                body=body,
                model_name=model_name,
                model_config=model_config,
                degrade_config=degrade_config,
                user=user,
                stream=stream,
                gateway_start_time=gateway_start_time,
            )
            # 添加优先级响应头
            response.headers["X-User-Priority"] = str(_user_priority(user))
            return response
        priority = _user_priority(user)
        prompt_tokens = token_counter.count_prompt_tokens(body_dict, model_config)
        last_user_prompt = token_counter.extract_last_user_prompt(body_dict)

        # 选择队列：支持多队列模式
        load_factor = 1.0
        if model_config.get("type") == "multi-queue":
            load_queue_key = model_config.get("load_queue", f"{model_name}-load-queue")
            queue_name, load_factor, _queue_config = _choose_queue_by_load(model_config, load_queue_key)
            # logger.info(f"[Gateway] 模型 {model_name} 选择队列: {queue_name}, load_factor: {load_factor}")
        else:
            load_queue_key = None
            queue_name = model_config.get("queue_name", f"llm_queue_{model_name}")

        # 异步记录模型使用情况
        asyncio.create_task(self._record_model_usage(request, model_name))

        # 存储原始数据
        r.hset(f"request_body:{req_id}", mapping={
            "body": body,
            "model": model_name,
            "stream": str(stream).lower(),
            "headers": orjson.dumps(dict(request.headers)),
            "request_path": request.url.path  # 存储请求路径，用于选择正确的API URL
        })
        
        # 存储元数据
        r.hset(f"request_meta:{req_id}", mapping={
            "enqueue_time": time.time(),
            "priority": priority,
            "model": model_name or "qwen3-coder",
            "stream": str(stream).lower(),
            "user_id": str(user["id"]),
            "username": user["username"],
            "ip_address": client_ip or "",
            "prompt_tokens": str(prompt_tokens),
            "last_user_prompt": last_user_prompt or "",
            "service_name": self._service_name(request),
        })

        # 入队并增加队列负载计数
        r.zadd(queue_name, {req_id: priority})
        if load_queue_key:
            _increment_queue_load(load_queue_key, queue_name, load_factor)
        r.expire(queue_name, 3600)
        r.expire(f"request_meta:{req_id}", 3600)
        r.expire(f"request_body:{req_id}", 3600)

        scheduler_config = runtime_config.scheduler_config()
        timeouts = scheduler_config.get("timeouts", {})
        thresholds = scheduler_config.get("priority_thresholds", {})
        high_priority_max = int(thresholds.get("high_priority_max", 3))
        timeout = int(timeouts.get("high_priority", 600)) if priority <= high_priority_max else int(timeouts.get("low_priority", 7200))

        if stream:
            # 流式响应立即返回，后台统计
            response = self._handle_streaming_request(
                req_id, queue_name, load_queue_key, timeout, gateway_start_time, load_factor
            )
            # 添加优先级响应头
            response.headers["X-User-Priority"] = str(priority)
            return response
        else:
            response = await self._wait_for_result(req_id, queue_name, load_queue_key, timeout, load_factor)
            # 添加优先级响应头
            response.headers["X-User-Priority"] = str(priority)
            # 统计网关处理时间
            if PERFORMANCE_STATS["enabled"]:
                gateway_time = time.time() - gateway_start_time
                logger.info(f"ReqID: {req_id}, GatewayTime: {gateway_time:.3f}s")
            return response
    
    def _handle_streaming_request(
        self,
        req_id: str,
        queue_name: str,
        load_queue_key: str | None,
        timeout: int,
        gateway_start_time: float,
        load_factor: float = 1.0,
    ):
        """处理流式传输请求（立即返回，后台统计）"""
        async def stream_generator():
            start = time.time()
            try:
                while time.time() - start < timeout:
                    stream_data = r.lpop(f"stream:{req_id}")
                    if stream_data:
                        yield stream_data
                    elif r.exists(f"stream_done:{req_id}"):
                        remaining_data = r.llen(f"stream:{req_id}")
                        if remaining_data == 0:
                            break
                    else:
                        await asyncio.sleep(0.1)
            finally:
                # 减少队列负载计数
                if load_queue_key:
                    _decrement_queue_load(load_queue_key, queue_name, load_factor)

                # 清理Redis中的临时数据
                r.delete(f"stream:{req_id}", f"stream_done:{req_id}", f"stream_model:{req_id}")
                r.zrem(queue_name, req_id)
                r.delete(f"request_meta:{req_id}", f"request_body:{req_id}")

                # 后台统计网关处理时间
                if PERFORMANCE_STATS["enabled"]:
                    gateway_time = time.time() - gateway_start_time
                    logger.info(f"ReqID: {req_id}, GatewayTime: {gateway_time:.3f}s")

        return StreamingResponse(stream_generator(), media_type="text/event-stream")
    
    async def _wait_for_result(self, req_id: str, queue_name: str, load_queue_key: str | None, timeout: int, load_factor: float = 1.0):
        """等待非流式传输请求的结果"""
        start = time.time()
        while time.time() - start < timeout:
            result = r.get(f"result:{req_id}")
            if result:
                # 减少队列负载计数
                if load_queue_key:
                    _decrement_queue_load(load_queue_key, queue_name, load_factor)
                r.delete(f"result:{req_id}")
                if isinstance(result, bytes):
                    result_str = result.decode('utf-8')
                    # logger.info(f"[Gateway] Non-streaming response for {req_id}: {result_str}")
                    if result_str.startswith('{') or result_str.startswith('['):
                        return Response(content=result, status_code=200, media_type="application/json")
                    else:
                        return Response(content=result, status_code=200, media_type="text/plain")
                else:
                    result_str = str(result)
                    logger.info(f"Non-streaming response for {req_id}: {result_str}")
                    return Response(content=result_str, status_code=200, media_type="text/plain")
            await asyncio.sleep(0.1)

        # 超时
        logger.error(f"[_wait_for_result] TIMEOUT for req_id={req_id}")
        # 超时也减少负载计数
        if load_queue_key:
            _decrement_queue_load(load_queue_key, queue_name, load_factor)
        # 清理所有相关的 Redis 键
        r.delete(
            f"result:{req_id}",
            f"stream:{req_id}",
            f"stream_done:{req_id}",
            f"stream_model:{req_id}",
            f"request_meta:{req_id}",
            f"request_body:{req_id}"
        )
        r.zrem(queue_name, req_id)
        return Response(
            content='{"error": {"message": "大模型负载过高", "type": "server_busy", "code": 504}}',
            status_code=429,
            media_type="application/json"
        )

    async def _forward_degraded_request(
        self,
        *,
        request: Request,
        body_dict: dict,
        body: bytes,
        model_name: str,
        model_config: dict,
        degrade_config: dict,
        user: dict,
        stream: bool,
        gateway_start_time: float,
    ):
        target_model = degrade_config.get("model_name")
        body_dict = dict(body_dict)
        body_dict["model"] = target_model
        body = orjson.dumps(body_dict)

        req_id = f"degrade:{time.time_ns()}"
        service_name = self._service_name(request)

        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("content-length", None)

        # 如果降质配置中指定了 API Key，则替换；否则透传原始用户的 API Key
        api_key = degrade_config.get("api_key")
        if api_key:
            headers.pop("authorization", None)
            headers.pop("Authorization", None)
            headers["Authorization"] = f"Bearer {api_key}"
        # 否则保持原始 Authorization header（透传用户 API Key）

        full_url = f"{str(degrade_config.get('api_url')).rstrip('/')}{request.url.path}"
        asyncio.create_task(self._record_model_usage(request, target_model))

        try:
            session = aiohttp.ClientSession()
            response_ctx = session.post(
                full_url,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=1800, connect=180, sock_read=1800),
            )
            resp = await response_ctx.__aenter__()
            content_type = resp.headers.get("content-type", "")
            if stream or "text/event-stream" in content_type:
                async def stream_response():
                    try:
                        async for chunk in resp.content.iter_chunked(128):
                            yield chunk
                    finally:
                        await response_ctx.__aexit__(None, None, None)
                        await session.close()

                return StreamingResponse(stream_response(), media_type=content_type or "text/event-stream")

            status_code = resp.status
            response_headers = dict(resp.headers)
            response_body = await resp.read()
            await response_ctx.__aexit__(None, None, None)
            await session.close()
            return Response(content=response_body, status_code=status_code, headers=response_headers)
        except Exception as e:
            logger.error(f"[degrade] 转发降质模型失败: {e}")
            return Response(
                content=f'{{"error": "降质模型转发失败: {str(e)}"}}',
                status_code=500,
                media_type="application/json",
            )

    
    async def _forward_request(self, request: Request):
        """直接转发非/v1/chat/completions的请求"""
        body = await request.body()
        
        # 检查是否是 JSON 请求（通过 Content-Type 判断）
        content_type = request.headers.get("content-type", "")
        custom_model_name = ""
        
        if "application/json" in content_type:
            try:
                body_dict = orjson.loads(body)
            except orjson.JSONDecodeError as e:
                error_msg = f"JSON解析错误: {str(e)}"
                logger.error(f"[_forward_request] {error_msg}")
                return create_invalid_model_response("unknown", error_message=error_msg)
            
            if request.url.path == "/v1/ocr":
                model_name = "testname-ocr"
            else:
                model_name = body_dict.get("model", "qwen3-coder")

            models = runtime_config.get_models()
            model_config = models.get(model_name, {})
            custom_model_name = model_config.get("model_name")
            if custom_model_name:
                body_dict["model"] = custom_model_name
                body = orjson.dumps(body_dict)
        else:
            # 非 JSON 请求（如 multipart/form-data），直接转发
            if request.url.path == "/v1/ocr":
                model_name = "testname-ocr"
            else:
                model_name = "unknown"

        # 检查模型名称是否在配置列表中
        models = runtime_config.get_models()
        if model_name not in models:
            logger.error(f"[_forward_request] 模型 {model_name} 不在配置列表中")
            return create_invalid_model_response(model_name)

        user = await auth_module.authenticate_request(request, allow_auto_register=True)
        if not user:
            return create_invalid_model_response(
                model_name,
                error_message="未认证或 API key 无效",
                stream=False,
            )
        if _quota_exceeded(user):
            return create_invalid_model_response(
                model_name,
                error_message="额度已用完",
                stream=False,
            )
        if user.get("_quota_rejected"):
            return create_invalid_model_response(
                model_name,
                error_message="使用额度超限，请求被拒绝",
                stream=False,
            )

        # 多队列模型：使用第一个队列的 api_url
        model_config = models[model_name]
        if model_config.get("type") == "multi-queue":
            queues = model_config.get("queues", [])
            if queues:
                queue_config = queues[0]
                api_url = queue_config.get("api_url")
                api_key = queue_config.get("api_key") or model_config.get("api_key")
                custom_model_name = queue_config.get("model_name") or model_name
            else:
                api_url = model_config.get("api_url")
                api_key = model_config.get("api_key")
                custom_model_name = model_config.get("model_name") or model_name
        else:
            api_url = model_config.get("api_url")
            api_key = model_config.get("api_key")
            custom_model_name = model_config.get("model_name") or model_name
        
        asyncio.create_task(self._record_model_usage(request, custom_model_name or model_name))

        # 直接拼接 api_url 和 request_path
        full_url = f"{api_url.rstrip('/')}{request.url.path}"
        
        try:
            headers = dict(request.headers)
            headers.pop("host", None)
            headers.pop("content-length", None)  # 移除content-length，让aiohttp自动计算
            if api_key:
                # User keys authenticate this gateway; model api_key authenticates the downstream provider.
                headers.pop("authorization", None)
                headers.pop("Authorization", None)
                headers["Authorization"] = f"Bearer {api_key}"
            
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=full_url,
                    data=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=180)
                ) as resp:
                    content_type = resp.headers.get("content-type", "")
                    if "text/event-stream" in content_type:
                        async def stream_response():
                            try:
                                async for chunk in resp.content.iter_chunked(1024):
                                    yield chunk
                            except Exception as e:
                                # 客户端主动关闭连接，不是系统错误
                                logger.warning(f"客户端关闭连接: {type(e).__name__}")
                        
                        return StreamingResponse(stream_response(), media_type=resp.headers.get("content-type", "text/event-stream"))
                    else:
                        response_body = await resp.read()
                        return Response(
                            content=response_body,
                            status_code=resp.status,
                            headers=dict(resp.headers)
                        )
        except Exception as e:
            logger.error(f"[_forward_request] Error: {e}")
            return Response(
                content=f'{{"error": "转发请求失败: {str(e)}"}}',
                status_code=500,
                media_type="application/json"
            )
    
    async def _record_model_usage(self, request: Request, model_name: str):
        """异步记录模型使用次数"""
        service_name = self._service_name(request)
        
        await write_model_usage(
            service_name=service_name,
            model_name=model_name,
            count=1,
            request=request
        )

    def _service_name(self, request: Request) -> str:
        x_title = request.headers.get('x-title')
        return "sai_roo_code" if x_title == 'Roo Code' else "sai_llm_gateway"


def _choose_queue_by_load(model_config, load_queue_key: str) -> tuple[str | None, float, dict | None]:
    """根据 Redis 中的负载索引选择负载最小的队列"""
    queues = model_config.get("queues", [])
    if not queues:
        return None, 1.0, None

    # 获取所有队列负载并打印
    all_items = r.zrange(load_queue_key, 0, -1, withscores=True)
    logger.info(f"[队列负载] {load_queue_key} : {all_items}")

    # Redis 已按负载排序，直接返回第一个队列的配置
    if all_items:
        name = all_items[0][0].decode() if isinstance(all_items[0][0], bytes) else all_items[0][0]
        queue = next((q for q in queues if q.get("queue_name") == name), None)
        if queue:
            return queue["queue_name"], queue.get("load_factor", 1.0), queue

    # 兜底返回第一个队列
    return queues[0]["queue_name"], queues[0].get("load_factor", 1.0), queues[0]


def _degrade_config(model_config: dict) -> dict | None:
    degrade = model_config.get("degrade") or {}
    if not degrade.get("enabled"):
        return None
    api_url = (degrade.get("api_url") or "").strip()
    model_name = (degrade.get("model_name") or "").strip()
    if not api_url or not model_name:
        logger.warning(f"降质配置不完整: api_url={api_url}, model_name={model_name}")
        return None
    if not api_url.startswith(("http://", "https://")):
        logger.error(f"降质 API URL 格式错误: {api_url}")
        return None
    return degrade


def _extract_stream_text(chunk: bytes) -> str:
    text = chunk.decode("utf-8", errors="ignore")
    parts = []
    for line in text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = orjson.loads(payload)
        except Exception:
            continue
        choices = data.get("choices") or []
        for choice in choices:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str):
                parts.append(delta["content"])
            if isinstance(choice.get("text"), str):
                parts.append(choice["text"])
    return "".join(parts)


def _increment_queue_load(load_queue_key: str, queue_name: str, load_factor: float = 1.0) -> int:
    """增加队列负载（原子操作）"""
    increment = load_factor if load_factor > 0 else 1.0
    pipeline = r.pipeline()
    pipeline.zincrby(load_queue_key, increment, queue_name)
    pipeline.expire(load_queue_key, 3600)
    results = pipeline.execute()
    load = results[0]
    return max(0, int(load))


def _decrement_queue_load(load_queue_key: str, queue_name: str, load_factor: float = 1.0) -> int:
    """减少队列负载，避免出现负数（原子操作）"""
    decrement = load_factor if load_factor > 0 else 1.0
    pipeline = r.pipeline()
    pipeline.zincrby(load_queue_key, -decrement, queue_name)
    pipeline.zrange(load_queue_key, 0, 0, withscores=True)
    results = pipeline.execute()
    load = results[0]
    if load < 0:
        r.zadd(load_queue_key, {queue_name: 0})
        return 0
    return int(load)


def get_queue_status():
    """获取所有队列状态"""
    result = {}
    
    for model_name, model_config in runtime_config.get_models().items():
        queue_name = model_config.get("queue_name", f"llm_queue_{model_name.replace('-', '_')}")
        queue_length = r.zcard(queue_name)
        queue_items = r.zrange(queue_name, 0, -1, withscores=True)
        
        priority_counts = {}
        for item, score in queue_items:
            priority = int(score) if not isinstance(score, bytes) else int(score.decode('utf-8'))
            priority_counts[priority] = priority_counts.get(priority, 0) + 1
        
        result[model_name] = {
            "queue_length": queue_length,
            "priority_counts": priority_counts
        }
    
    return result


def _quota_exceeded(user: dict) -> bool:
    if user.get("quota_unlimited"):
        return False
    quota_limit = user.get("quota_limit")
    if quota_limit is None:
        return False
    return float(user.get("quota_used") or 0) >= float(quota_limit)


def _user_priority(user: dict) -> int:
    default_priority = int(runtime_config.scheduler_config().get("default_priority", 3))
    try:
        value = int(user.get("priority", default_priority))
    except (TypeError, ValueError):
        return default_priority
    return max(1, min(5, value))
