import asyncio
import aiohttp
import orjson
import json
import redis
import time
from config import *
import db_module
import runtime_config
import token_counter
import usage_module

# 初始化Redis连接
r = redis.Redis(**REDIS_CONFIG)

# 为每个模型维护计数器和差值统计
model_counters = {model_name: {"counter": 0} for model_name in runtime_config.get_models().keys()}

class ModelScheduler:
    def __init__(self, model_name: str, queue_name: str):
        self.model_name = model_name
        self.queue_name = queue_name
        self.lock = asyncio.Lock()
        self.pending_requests = 0
        self.low_priority_pending_requests = 0

        # 提取 api_url 和 custom_model_name，metrics_url 通过拼接获取
        model_config = runtime_config.get_models().get(model_name, {})
        if model_config.get("type") == "multi-queue":
            queues = model_config.get("queues", [])
            for q in queues:
                if q.get("queue_name") == queue_name:
                    self.api_url = q.get("api_url")
                    self.metrics_url = f"{self.api_url}/metrics"
                    self.custom_model_name = q.get("model_name")
                    self.api_key = q.get("api_key") or model_config.get("api_key")
                    break
        else:
            self.api_url = model_config.get("api_url")
            self.metrics_url = f"{self.api_url}/metrics"
            self.custom_model_name = model_config.get("model_name")
            self.api_key = model_config.get("api_key")

        logger.info(f"[ModelScheduler]:{model_name}, queue: {queue_name}")
        
    async def get_gpu_cache_usage(self) -> tuple:
        """获取指定模型的GPU缓存使用率和等待请求数"""
        if not self.metrics_url:
            return 0.0, 0, 0
        
        gpu_usage = 0.0
        num_requests_running = 0
        num_requests_waiting = 0
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.metrics_url, timeout=2) as resp:
                    text = await resp.text()
                    
                    # 按顺序查找三个指标（metrics 中这三个指标连续出现）
                    found_count = 0
                    for line in text.splitlines():
                        if found_count >= 3:
                            break
                        
                        # vllm
                        # if line.startswith('vllm:num_requests_running{') and f'engine="0"' in line:
                        #     num_requests_running = int(float(line.split()[-1]))
                        #     found_count += 1
                        # elif line.startswith('vllm:num_requests_waiting{') and f'engine="0"' in line:
                        #     num_requests_waiting = int(float(line.split()[-1]))
                        #     found_count += 1
                        # elif line.startswith('vllm:kv_cache_usage_perc{') and f'engine="0"' in line:
                        #     gpu_usage = round(float(line.split()[-1]), 3)
                        #     found_count += 1

                        # SGlang
                        if line.startswith('sglang:num_running_reqs{') and f'tp_rank="0"' in line:
                            num_requests_running = int(float(line.split()[-1]))
                            found_count += 1
                        elif line.startswith('sglang:num_queue_reqs{') and f'tp_rank="0"' in line:
                            num_requests_waiting = int(float(line.split()[-1]))
                            found_count += 1
                        elif line.startswith('sglang:utilization{') and f'tp_rank="0"' in line:
                            gpu_usage = round(float(line.split()[-1]), 3)
                            found_count += 1
                    
                    return gpu_usage, num_requests_running, num_requests_waiting
        except Exception as e:
            logger.error(f"[{self.model_name}, queue: {self.queue_name}] 获取GPU使用率时出错: {e}")
            return 0.0, 0, 0
    
    async def increment_pending_request(self, is_low_priority=False):
        """增加未收到响应的请求数"""
        async with self.lock:
            if is_low_priority:
                self.low_priority_pending_requests += 1
            else:
                self.pending_requests += 1
            
    async def decrement_pending_request(self, is_low_priority=False):
        """减少未收到响应的请求数"""
        async with self.lock:
            if is_low_priority:
                if self.low_priority_pending_requests > 0:
                    self.low_priority_pending_requests -= 1
            else:
                if self.pending_requests > 0:
                    self.pending_requests -= 1
            
    async def send_to_llm(self, req_id: str, body: bytes, req_headers: dict, stream: bool = False, is_low_priority=False, request_path: str = "/v1/chat/completions"):
        """将请求发送到指定的大模型"""
        await self.increment_pending_request(is_low_priority)

        try:
            # 根据请求路径拼接完整的 API URL
            api_url = f"{self.api_url}{request_path}"
            llm_start_time = time.time()
            
            # 处理请求头
            req_headers.pop('content-length', None)
            from urllib.parse import urlparse
            req_headers['host'] = urlparse(api_url).netloc
            if self.api_key:
                # User keys authenticate this gateway; model api_key authenticates the downstream provider.
                req_headers.pop('authorization', None)
                req_headers.pop('Authorization', None)
                req_headers['Authorization'] = f"Bearer {self.api_key}"

            timeout = aiohttp.ClientTimeout(total=1800, connect=180, sock_read=1800)

            # 替换模型名称（需要时才解析和重新序列化）
            if self.custom_model_name:
                try:
                    body_dict = orjson.loads(body)
                except orjson.JSONDecodeError as e:
                    logger.error(f"[{req_id}] orjson.loads 解析失败: {e}，尝试使用标准 json 库")
                    try:
                        body_dict = json.loads(body.decode('utf-8'))
                    except json.JSONDecodeError as e2:
                        logger.error(f"[{req_id}] json.loads 也解析失败: {e2}")
                        raise
                body_dict["model"] = self.custom_model_name
                body = orjson.dumps(body_dict)
            
            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, data=body, headers=req_headers, timeout=timeout) as resp:
                    if stream:
                        response_text_parts = []
                        try:
                            async for chunk in resp.content.iter_chunked(128):
                                response_text_parts.append(_extract_stream_text(chunk))
                                r.rpush(f"stream:{req_id}", chunk)
                        finally:
                            r.setex(f"stream_done:{req_id}", 60, "1")
                            await self.decrement_pending_request(is_low_priority)
                        
                        if PERFORMANCE_STATS["enabled"]:
                            logger.info(f"ReqID: {req_id}, LLMProcessingTime: {time.time() - llm_start_time:.3f}s")
                        
                        return {"content": b"", "response_text": "".join(response_text_parts), "status": resp.status, "headers": dict(resp.headers), "stream": True}
                    else:
                        response_body = await resp.read()
                        await self.decrement_pending_request(is_low_priority)
                        
                        if PERFORMANCE_STATS["enabled"]:
                            logger.info(f"ReqID: {req_id}, LLMProcessingTime: {time.time() - llm_start_time:.3f}s")
                        
                        r.setex(f"result:{req_id}", 60, response_body)
                        return {"content": response_body, "status": resp.status, "headers": dict(resp.headers), "stream": False}
        except Exception as e:
            await self.decrement_pending_request(is_low_priority)
            llm_processing_time = time.time() - llm_start_time
            logger.error(f"[ERROR] ReqID: {req_id}, LLMProcessingTime: {llm_processing_time:.3f}s, Error: {str(e)}")
            error_response = f'{{"error": {{"message": "大模型处理超时: {str(e)}", "type": "timeout_error", "code": "504"}}}}'.encode()
            r.setex(f"result:{req_id}", 60, error_response)
            return {"content": error_response, "status": 500, "headers": {}, "stream": False}


def get_hash_value(hash_data, key):
    """从哈希数据中安全地获取值"""
    if isinstance(key, str):
        byte_key = key.encode()
        if byte_key in hash_data:
            return hash_data[byte_key]
    
    if key in hash_data:
        return hash_data[key]
    return None


def _should_process_low_priority(counters: dict) -> bool:
    """判断是否应该处理低优先级请求"""
    scheduler_config = runtime_config.scheduler_config()
    high_low_ratio = int(scheduler_config.get("high_low_ratio", 5))
    return counters["counter"] > 0 and counters["counter"] % high_low_ratio == 0


def _get_next_request(queue_name: str, counters: dict, scheduler: ModelScheduler = None):
    """根据优先级和插入顺序获取下一个要处理的请求"""
    scheduler_config = runtime_config.scheduler_config()
    thresholds = scheduler_config.get("priority_thresholds", {})
    high_priority_max = int(thresholds.get("high_priority_max", 3))
    low_priority_min = int(thresholds.get("low_priority_min", 4))
    low_priority_max_pending = int(scheduler_config.get("low_priority_max_pending", 3))
    
    # 先判断是否要获取低优先级
    if _should_process_low_priority(counters):
        if scheduler is None or scheduler.low_priority_pending_requests <= low_priority_max_pending:
            low_priority_items = r.zrangebyscore(queue_name, low_priority_min, "+inf", withscores=True)
            if low_priority_items:
                req_id = low_priority_items[0][0]
                if isinstance(req_id, bytes):
                    req_id = req_id.decode('utf-8')
                return req_id, low_priority_items[0][1]
    
    # 尝试获取高优先级
    high_priority_items = r.zrangebyscore(queue_name, 0, high_priority_max, withscores=True)
    if high_priority_items:
        req_id = high_priority_items[0][0]
        if isinstance(req_id, bytes):
            req_id = req_id.decode('utf-8')
        return req_id, high_priority_items[0][1]
    
    # 如果没有高优先级则获取低优先级
    if scheduler is None or scheduler.low_priority_pending_requests <= low_priority_max_pending:
        low_priority_items = r.zrangebyscore(queue_name, low_priority_min, "+inf", withscores=True)
        if low_priority_items:
            req_id = low_priority_items[0][0]
            if isinstance(req_id, bytes):
                req_id = req_id.decode('utf-8')
            return req_id, low_priority_items[0][1]
    
    return None, None


async def model_scheduler_task(model_name: str, queue_name: str):
    """为单个模型运行的调度任务"""
    global model_counters
    
    scheduler = ModelScheduler(model_name, queue_name)
    counters = model_counters[model_name]
    
    while True:
        try:
            scheduler_config = runtime_config.scheduler_config()
            sleep_interval = float(scheduler_config.get("sleep_interval", 0.2))
            gpu_threshold = float(scheduler_config.get("gpu_threshold", 0.7))
            min_waiting_requests = int(scheduler_config.get("min_waiting_requests", 2))
            max_pending_requests = int(scheduler_config.get("max_pending_requests", 30))
            queue_length = r.zcard(queue_name)
            # 负载计算已移至 QueueMiddleware 中处理（入队数 - 完成数）
            if queue_length == 0:
                await asyncio.sleep(sleep_interval)
                continue
            
            gpu_usage, num_requests_running, num_requests_waiting = await scheduler.get_gpu_cache_usage()
            logger.info(f"[{scheduler.queue_name}] GPU:{gpu_usage}, wait:{num_requests_waiting}, run:{num_requests_running}, Hpending:{scheduler.pending_requests}, Lpending:{scheduler.low_priority_pending_requests},queue:{queue_length}")

            # 异步写入数据库
            asyncio.create_task(db_module.write_scheduler_monitor_data(
                model_name=queue_name,
                gpu_usage=gpu_usage,
                num_requests_waiting=num_requests_waiting,
                pending_requests=scheduler.pending_requests,
                low_priority_pending_requests=scheduler.low_priority_pending_requests,
                num_requests_running=num_requests_running,
                queue_length=queue_length
            ))

            # GPU负载过高或未收到响应的请求数过多时不处理新请求
            if gpu_usage >= gpu_threshold or num_requests_waiting > min_waiting_requests or scheduler.pending_requests > max_pending_requests:
                await asyncio.sleep(5 * sleep_interval)
                continue
            
            req_id, priority_score = _get_next_request(queue_name, counters, scheduler)
            if not req_id:
                await asyncio.sleep(5 * sleep_interval)
                continue
            
            priority = int(priority_score) if priority_score is not None else 0
            # 确保req_id是字符串格式
            if isinstance(req_id, bytes):
                req_id = req_id.decode('utf-8')
            r.zrem(queue_name, req_id)
            
            # 异步处理请求
            asyncio.create_task(_process_request_by_id_with_scheduler(req_id, queue_name, counters, model_name, scheduler))
            
        except asyncio.CancelledError:
            logger.info(f"模型 {model_name} 的调度任务已被取消")
            r.delete(queue_name)
            break
        except Exception as e:
            logger.error(f"模型 {model_name} 的调度任务出错: {e}")
            r.delete(queue_name)
            await asyncio.sleep(float(runtime_config.scheduler_config().get("sleep_interval", 0.2)))


def bytes_to_str(value):
    """将bytes或str转换为str"""
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return value


def bytes_to_int(value, default: int = 0) -> int:
    try:
        value = bytes_to_str(value)
        return int(value) if value not in (None, "") else default
    except Exception:
        return default


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
            data = json.loads(payload)
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


async def _process_request_by_id_with_scheduler(req_id: str, queue_name: str, counters: dict, model_name: str, scheduler: ModelScheduler):
    """根据请求ID处理请求"""
    meta_data = r.hgetall(f"request_meta:{req_id}")
    body_data = r.hgetall(f"request_body:{req_id}")
    
    if not meta_data or not body_data:
        logger.error(f"[{req_id}] Data missing!")
        r.zrem(queue_name, req_id)
        return False
    
    r.delete(f"request_meta:{req_id}", f"request_body:{req_id}")
    
    priority = int(bytes_to_str(get_hash_value(meta_data, "priority")))
    stream_str = bytes_to_str(get_hash_value(body_data, "stream"))
    stream = stream_str and stream_str.lower() == 'true'
    
    # 获取请求路径，用于选择正确的 API URL
    request_path = bytes_to_str(get_hash_value(body_data, "request_path")) or "/v1/chat/completions"
    
    body = get_hash_value(body_data, "body")
    if isinstance(body, bytes):
        body = body  # 保持bytes格式
    elif isinstance(body, str):
        body = body.encode('utf-8')
    
    # 获取请求头
    headers_value = get_hash_value(body_data, "headers")
    req_headers = orjson.loads(headers_value) if isinstance(headers_value, bytes) else orjson.loads(headers_value.encode() if isinstance(headers_value, str) else b'{}')
    
    thresholds = runtime_config.scheduler_config().get("priority_thresholds", {})
    is_low_priority = priority >= int(thresholds.get("low_priority_min", 4))
    result = await scheduler.send_to_llm(req_id, body, req_headers, stream, is_low_priority, request_path)
    
    if result:
        await _schedule_usage_record(req_id, result, body, meta_data, model_name, scheduler)
        counters["counter"] += 1
        return True
    else:
        return False


async def _schedule_usage_record(req_id: str, result: dict, body: bytes, meta_data: dict, model_name: str, scheduler: ModelScheduler):
    model_config = runtime_config.get_models().get(model_name, {})
    prompt_tokens = bytes_to_int(get_hash_value(meta_data, "prompt_tokens"))
    completion_tokens = 0
    assistant_response = ""
    if result.get("stream"):
        assistant_response = result.get("response_text", "")
        _, completion_tokens, _ = token_counter.completion_usage_from_text(assistant_response, model_config, prompt_tokens)
    else:
        upstream_prompt, upstream_completion, _, assistant_response = token_counter.extract_usage_from_response(result.get("content") or b"")
        if upstream_prompt:
            prompt_tokens = upstream_prompt
        if upstream_completion:
            completion_tokens = upstream_completion
        elif assistant_response:
            _, completion_tokens, _ = token_counter.completion_usage_from_text(assistant_response, model_config, prompt_tokens)

    username = bytes_to_str(get_hash_value(meta_data, "username")) or "unknown"
    user_id_raw = bytes_to_str(get_hash_value(meta_data, "user_id"))
    user_id = int(user_id_raw) if user_id_raw else None
    enqueue_time = float(bytes_to_str(get_hash_value(meta_data, "enqueue_time")) or time.time())
    latency_ms = int((time.time() - enqueue_time) * 1000)

    asyncio.create_task(usage_module.record_usage_and_conversation(
        user_id=user_id,
        username=username,
        ip_address=bytes_to_str(get_hash_value(meta_data, "ip_address")) or None,
        request_id=req_id,
        model_name=model_name,
        upstream_model_name=scheduler.custom_model_name,
        service_name=bytes_to_str(get_hash_value(meta_data, "service_name")) or None,
        model_config=model_config,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        stream=bool(result.get("stream")),
        status_code=result.get("status"),
        latency_ms=latency_ms,
        success=200 <= int(result.get("status") or 500) < 400,
        user_prompt=bytes_to_str(get_hash_value(meta_data, "last_user_prompt")) or "",
        assistant_response=assistant_response,
    ))


def _init_load_queues():
    """初始化负载队列：清空所有队列值，初始化所有配置的队列为0"""
    for model_name, model_config in runtime_config.get_models().items():
        model_counters.setdefault(model_name, {"counter": 0})
        if model_config.get("type") == "multi-queue":
            load_queue_key = model_config.get("load_queue", f"{model_name}-load-queue")
            queues = model_config.get("queues", [])

            # 清空整个负载队列，避免重启后数值遗留
            r.delete(load_queue_key)
            logger.info(f"[main] 清空负载队列 {load_queue_key}")

            # 初始化所有配置的队列为0
            for q in queues:
                queue_name = q.get("queue_name")
                if queue_name:
                    r.zadd(load_queue_key, {queue_name: 0})
                    logger.info(f"[main] 初始化队列 {queue_name} 到 {load_queue_key}")

    logger.info("[main] 负载队列初始化完成")


async def main():
    """主函数：为每个队列创建独立的调度任务（支持 multi-queue）"""
    logger.info("[main] Starting scheduler tasks...")

    # 初始化负载队列：清空旧队列，初始化所有配置的队列
    _init_load_queues()

    tasks = []
    for model_name, model_config in runtime_config.get_models().items():
        model_counters.setdefault(model_name, {"counter": 0})
        # multi-queue 模型：为每个队列创建调度任务
        if model_config.get("type") == "multi-queue":
            queues = model_config.get("queues", [])
            for q in queues:
                queue_name = q.get("queue_name")
                if queue_name:
                    task = asyncio.create_task(model_scheduler_task(model_name, queue_name))
                    tasks.append(task)
        else:
            # 单队列模型：直接创建调度任务
            queue_name = model_config.get("queue_name", f"llm_queue_{model_name.replace('-', '_')}")
            task = asyncio.create_task(model_scheduler_task(model_name, queue_name))
            tasks.append(task)
    
    try:
        await asyncio.gather(*tasks)
    except asyncio.exceptions.CancelledError:
        logger.info("收到中断信号，正在关闭所有调度任务...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("所有调度任务已关闭")


if __name__ == "__main__":
    asyncio.run(main())
