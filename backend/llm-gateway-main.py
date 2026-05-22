from decimal import Decimal
from datetime import datetime
from contextlib import asynccontextmanager
import os
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from queue_middleware import QueueMiddleware
from config import *
import auth_module
import db_module
import runtime_config


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_module.ensure_database()
    await auth_module.bootstrap_admin()
    yield

# 添加新的服务时，注意在中间件添加路径豁免，避免被转发
app = FastAPI(lifespan=lifespan)

# 添加CORS中间件以允许前端跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生产环境中应该指定具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(QueueMiddleware)


def _jsonable(value):
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items() if key != "password_hash"}
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _validate_window(minutes: int | None, days: int | None):
    if minutes is not None and days is not None:
        raise HTTPException(status_code=400, detail="minutes 和 days 只能传一个")
    if minutes is None and days is None:
        minutes = 60
    if minutes is not None and minutes <= 0:
        raise HTTPException(status_code=400, detail="minutes 必须大于 0")
    if days is not None and days <= 0:
        raise HTTPException(status_code=400, detail="days 必须大于 0")
    return minutes, days

@app.get("/")
def health():
    return {"status": "LLM Gateway with Priority Queue"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "LLM Gateway with Priority Queue"}

@app.get("/queue/status")
def queue_status():
    """提供队列状态查询接口"""
    from queue_middleware import get_queue_status
    return get_queue_status()

@app.get("/api/queue/status")
def api_queue_status():
    """提供带前缀的队列状态查询接口"""
    from queue_middleware import get_queue_status
    return get_queue_status()

@app.get("/v1/models")
def list_models():
    """按照OpenAI标准格式返回模型列表"""
    # 构造OpenAI标准格式的模型列表
    models_data = []
    for model_name in runtime_config.get_models().keys():
        models_data.append({
            "id": model_name,
            "object": "model",
            "created": 0,  # 使用固定值，实际应用中可以根据需要设置
            "owned_by": "llm-gateway"
        })
    
    return {
        "object": "list",
        "data": models_data
    }

@app.get("/scheduler/monitor")
async def get_all_scheduler_monitor_data(minutes: int = 1440):
    """获取所有模型的调度器监控数据平均值"""
    import db_module
    dataframes = await db_module.get_all_scheduler_monitor_data_average(minutes)
    # 将DataFrame转换为字典列表以便JSON序列化
    data = []
    for model_name, df in dataframes.items():
        data.extend(df.to_dict('records'))
    return {"minutes": minutes, "data": data}

@app.get("/api/scheduler/monitor")
async def api_get_all_scheduler_monitor_data(minutes: int = 1440):
    return await get_all_scheduler_monitor_data(minutes)

@app.get("/api/me")
async def get_me(request: Request):
    user = await auth_module.require_user(request)
    return _jsonable(user)

@app.post("/api/auth/login")
async def login(request: Request):
    """Login with username and password."""
    body = await request.json()
    username = body.get("username")
    password = body.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="缺少用户名或密码")

    user = await db_module.verify_user_password(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    return _jsonable({"user": user, "api_key": user["api_key"]})

@app.post("/api/users/me/change-password")
async def change_my_password(request: Request):
    """Change current user's password."""
    user = await auth_module.require_user(request)
    body = await request.json()

    old_password = body.get("old_password")
    new_password = body.get("new_password")
    confirm_password = body.get("confirm_password")

    if not old_password or not new_password or not confirm_password:
        raise HTTPException(status_code=400, detail="缺少必要字段")

    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="两次输入的新密码不一致")

    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少为6位")

    result = await db_module.change_user_password(user["id"], old_password, new_password)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    return {"ok": True, "message": "密码修改成功"}

@app.post("/api/users/me/reset-key")
async def reset_my_key(request: Request):
    user = await auth_module.require_user(request)
    api_key = auth_module.generate_api_key()
    updated_user = await db_module.reset_user_key(user["id"], api_key)
    return _jsonable({"user": updated_user, "api_key": api_key})

@app.get("/api/usage/summary")
async def get_usage_summary(
    request: Request,
    minutes: int | None = None,
    days: int | None = None,
    model_name: str | None = None,
    username: str | None = None,
    user_id: int | None = None,
):
    user = await auth_module.require_user(request)
    minutes, days = _validate_window(minutes, days)
    filtered_user_id = user_id if user.get("role") == "admin" else user["id"]
    filtered_username = username if user.get("role") == "admin" else None
    rows = await db_module.get_usage_summary(
        minutes=minutes,
        days=days,
        user_id=filtered_user_id,
        username=filtered_username,
        model_name=model_name,
    )
    return _jsonable({"window": {"minutes": minutes, "days": days}, "data": rows})

@app.get("/api/usage/conversations")
async def get_conversations(
    request: Request,
    minutes: int | None = None,
    days: int | None = None,
    model_name: str | None = None,
    username: str | None = None,
    user_id: int | None = None,
    limit: int = 100,
):
    user = await auth_module.require_user(request)
    minutes, days = _validate_window(minutes, days)
    filtered_user_id = user_id if user.get("role") == "admin" else user["id"]
    filtered_username = username if user.get("role") == "admin" else None
    rows = await db_module.get_conversations(
        minutes=minutes,
        days=days,
        user_id=filtered_user_id,
        username=filtered_username,
        model_name=model_name,
        limit=max(1, min(limit, 500)),
    )
    return _jsonable({"window": {"minutes": minutes, "days": days}, "data": rows})

@app.get("/api/usage/model-hourly")
async def get_model_daily_requests(request: Request):
    user = await auth_module.require_user(request)
    filtered_user_id = None if user.get("role") == "admin" else user["id"]
    rows = await db_module.get_model_daily_requests(user_id=filtered_user_id)
    return _jsonable({"days": 30, "data": rows})

@app.get("/api/admin/models")
async def admin_list_models(request: Request):
    await auth_module.require_admin(request)
    return runtime_config.get_models(include_disabled=True)

@app.post("/api/admin/models")
async def admin_create_model(request: Request):
    await auth_module.require_admin(request)
    body = await request.json()
    model_name = body.pop("model_name", None) or body.pop("id", None)
    if not model_name:
        raise HTTPException(status_code=400, detail="缺少 model_name")
    runtime_config.upsert_model(model_name, body)
    return {"ok": True, "model_name": model_name}

@app.put("/api/admin/models/{model_name}")
async def admin_update_model(model_name: str, request: Request):
    await auth_module.require_admin(request)
    body = await request.json()
    runtime_config.upsert_model(model_name, body)
    return {"ok": True, "model_name": model_name}

@app.delete("/api/admin/models/{model_name}")
async def admin_delete_model(model_name: str, request: Request):
    await auth_module.require_admin(request)
    return {"ok": runtime_config.delete_model(model_name), "model_name": model_name}

@app.post("/api/admin/gateway/restart")
async def admin_restart_gateway(request: Request):
    await auth_module.require_admin(request)
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen(
        ["sh", "-c", "sleep 1; sh start.sh"],
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"ok": True, "message": "网关重启命令已触发"}

@app.get("/api/admin/config")
async def admin_get_config(request: Request):
    await auth_module.require_admin(request)
    return runtime_config.get_config()

@app.put("/api/admin/config")
async def admin_update_config(request: Request):
    await auth_module.require_admin(request)
    body = await request.json()
    return runtime_config.save_config(body)

@app.get("/api/admin/system-time")
async def admin_system_time(request: Request):
    await auth_module.require_admin(request)
    return {"system_time_minute": datetime.now().strftime("%Y-%m-%d %H:%M")}

@app.get("/api/admin/users")
async def admin_list_users(request: Request):
    await auth_module.require_admin(request)
    return _jsonable({"data": await db_module.list_users()})

@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    await auth_module.require_admin(request)
    body = await request.json()
    username = body.get("username")
    if not username:
        raise HTTPException(status_code=400, detail="缺少 username")
    api_key = auth_module.generate_api_key()
    try:
        user = await db_module.create_user(
            username=username,
            api_key=api_key,
            role=body.get("role", "user"),
            priority=body.get("priority", 3),
            quota_unlimited=bool(body.get("quota_unlimited", False)),
            quota_limit=body.get("quota_limit"),
        )
        return _jsonable({"user": user, "api_key": api_key})
    except Exception as e:
        if "duplicate key" in str(e) or "UniqueViolationError" in str(type(e)):
            raise HTTPException(status_code=409, detail=f"用户 {username} 已存在")
        raise

@app.put("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request):
    await auth_module.require_admin(request)
    body = await request.json()
    user = await db_module.update_user(user_id, body)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在或没有可更新字段")
    return _jsonable(user)

@app.post("/api/admin/users/{user_id}/reset-key")
async def admin_reset_user_key(user_id: int, request: Request):
    await auth_module.require_admin(request)
    api_key = auth_module.generate_api_key()
    user = await db_module.reset_user_key(user_id, api_key)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _jsonable({"user": user, "api_key": api_key})

@app.post("/api/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(user_id: int, request: Request):
    """Admin resets user password to default 123456."""
    await auth_module.require_admin(request)
    user = await db_module.admin_reset_user_password(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _jsonable({"user": user, "message": "密码已重置为 123456"})

@app.get("/api/gpu/info")
async def get_gpu_info():
    """获取所有服务器的 GPU 信息，按 servers.json 顺序返回，不含 local"""
    import json
    import sys
    import concurrent.futures
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpu-data"))
    from gpu_monitor import get_remote_gpu_info

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpu-data", "servers.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    servers = config.get("servers", [])
    if not servers:
        return {"servers": {}}

    # 并发查询，收集完成后按 servers.json 顺序构造结果
    ip_order = [s["ip"] for s in servers]
    ip_result: dict[str, list | str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(get_remote_gpu_info, s["ip"], s["username"], s["password"]): s["ip"] for s in servers}
        for future in concurrent.futures.as_completed(futures):
            ip = futures[future]
            try:
                ip_result[ip] = future.result()
            except Exception as e:
                ip_result[ip] = str(e)
    ordered_result = {ip: ip_result[ip] for ip in ip_order}

    return {"servers": ordered_result}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7103)
