import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request

import db_module
import runtime_config
from config import INITIAL_ADMIN_API_KEY, INITIAL_ADMIN_USERNAME, logger


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def ip_api_key(ip_address: str) -> str:
    return ip_address


async def bootstrap_admin():
    if INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_API_KEY:
        user = await db_module.create_or_update_initial_admin(INITIAL_ADMIN_USERNAME, INITIAL_ADMIN_API_KEY)
        if user:
            logger.info(f"[auth] 初始超级用户已准备: {INITIAL_ADMIN_USERNAME}")


async def authenticate_request(
    request: Request,
    allow_auto_register: bool = True,
    record_for_rate_limit: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Authenticate request and check rate limits.

    Args:
        request: FastAPI request object
        allow_auto_register: Whether to auto-register IP-based users
        record_for_rate_limit: If provided, record this request immediately for rate limiting.
                               Should contain: {"request_id": str, "model_name": str}
    """
    if allow_auto_register and runtime_config.auto_register_enabled():
        ip_address = get_client_ip(request)
        key = ip_api_key(ip_address)
        user = await db_module.get_user_by_api_key(key)
        if user:
            return await _with_effective_priority(user, record_for_rate_limit)
        return await _with_effective_priority(await db_module.get_or_create_ip_user(ip_address, key), record_for_rate_limit)

    token = _bearer_token(request)
    if not token:
        return None
    return await _with_effective_priority(await db_module.get_user_by_api_key(token), record_for_rate_limit)


async def _with_effective_priority(user: dict[str, Any] | None, record_for_rate_limit: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not user:
        return None
    configured_priority = _clamp_int(user.get("priority"), 3, 1, 5)
    user["priority"] = configured_priority
    if configured_priority == 1:
        return user

    # Record request immediately for rate limiting if metadata provided
    if record_for_rate_limit:
        await db_module.record_request_for_rate_limit(
            user_id=user["id"],
            username=user["username"],
            ip_address=record_for_rate_limit.get("ip_address", ""),
            request_id=record_for_rate_limit.get("request_id", ""),
            model_name=record_for_rate_limit.get("model_name", ""),
        )

    config = runtime_config.rate_limit_config()
    window_minutes = _clamp_int(config.get("window_minutes"), 1, 1, 1440)
    request_threshold = _clamp_int(config.get("request_threshold"), 5, 0, 1000000)
    downgraded_priority = _clamp_int(config.get("downgraded_priority"), 4, 1, 5)
    cutoff_time = db_module.adjusted_now() - timedelta(minutes=window_minutes)

    daily_quota_limit = float(config.get("daily_quota_limit", 20))
    window_quota_limit = float(config.get("window_quota_limit", 0.36))
    window_quota_action = config.get("window_quota_action", "limit")
    daily_quota_action = config.get("daily_quota_action", "limit")

    # Calculate day start (1:00 AM boundary)
    now = db_module.adjusted_now()
    today_start = (now - timedelta(hours=1)).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=1)

    # Run both checks in parallel
    request_count_task = asyncio.create_task(db_module.count_user_requests_since(user["id"], cutoff_time))
    quota_task = asyncio.create_task(db_module.check_user_quota_limits(user["id"], cutoff_time, today_start))
    request_count, quota_result = await asyncio.gather(request_count_task, quota_task)

    # Check request count rate limit (uses window action)
    # Note: request_count includes the current request if record_for_rate_limit was provided
    if request_threshold > 0 and request_count > request_threshold:
        if window_quota_action == "reject":
            user["_quota_rejected"] = True
        else:
            user["priority"] = downgraded_priority

    # Check quota limits
    daily_price = quota_result.get("daily_price", 0.0)
    window_price = quota_result.get("window_price", 0.0)

    # Check user's total quota limit (quota_used vs quota_limit)
    if not user.get("quota_unlimited", False):
        quota_limit = float(user.get("quota_limit") or 0)
        quota_used = float(user.get("quota_used") or 0)
        # quota_limit 为 0 表示不允许任何消费，quota_used > 0 即超限
        # quota_limit > 0 时，quota_used >= quota_limit 才超限
        if (quota_limit == 0 and quota_used > 0) or (quota_limit > 0 and quota_used >= quota_limit):
            user["_quota_rejected"] = True

    if window_quota_limit > 0 and window_price >= window_quota_limit:
        if window_quota_action == "reject":
            user["_quota_rejected"] = True
        else:
            user["priority"] = downgraded_priority

    if daily_quota_limit > 0 and daily_price >= daily_quota_limit:
        user["_daily_quota_exceeded"] = True
        if daily_quota_action == "reject":
            user["_quota_rejected"] = True
        else:
            user["priority"] = downgraded_priority

    return user


def _clamp_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


async def require_user(request: Request) -> dict[str, Any]:
    user = await authenticate_request(request, allow_auto_register=False)
    if not user:
        raise HTTPException(status_code=401, detail="未认证或 API key 无效")
    return user


async def require_admin(request: Request) -> dict[str, Any]:
    user = await require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要超级用户权限")
    return user
