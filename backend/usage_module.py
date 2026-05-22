from typing import Any

import db_module
from config import logger


PROMPT_LIMIT = 16 * 1024
RESPONSE_LIMIT = 64 * 1024
DEFAULT_PRICE_MULTIPLIERS = {
    "weekday_peak": 1.5,
    "weekday_flat": 1.0,
    "night": 0.3,
    "weekend": 0.3,
}


def truncate_text(text: str | None, limit: int) -> tuple[str, bool]:
    if not text:
        return "", False
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def calculate_price(model_config: dict[str, Any] | None, prompt_tokens: int, completion_tokens: int) -> tuple[float, float, float, str]:
    price = (model_config or {}).get("price", {})
    multiplier = _current_price_multiplier(model_config)
    input_per_1k = float(price.get("input_per_1k") or 0)
    output_per_1k = float(price.get("output_per_1k") or 0)
    currency = price.get("currency") or "CNY"
    input_price = prompt_tokens / 1000 * input_per_1k * multiplier
    output_price = completion_tokens / 1000 * output_per_1k * multiplier
    return input_price, output_price, input_price + output_price, currency


def _current_price_multiplier(model_config: dict[str, Any] | None) -> float:
    configured = (model_config or {}).get("price_multipliers") or {}
    multipliers = {**DEFAULT_PRICE_MULTIPLIERS, **configured}
    now = db_module.adjusted_now()
    if now.weekday() >= 5:  # 周六周日
        return float(multipliers.get("weekend") or DEFAULT_PRICE_MULTIPLIERS["weekend"])
    hour = now.hour
    if 9 <= hour < 18:  # 工作日高峰 09:00-18:00
        return float(multipliers.get("weekday_peak") or DEFAULT_PRICE_MULTIPLIERS["weekday_peak"])
    if 18 <= hour < 23:  # 工作日平峰 18:00-23:00（修复：原来是 < 24）
        return float(multipliers.get("weekday_flat") or DEFAULT_PRICE_MULTIPLIERS["weekday_flat"])
    # 夜间 23:00-09:00
    return float(multipliers.get("night") or DEFAULT_PRICE_MULTIPLIERS["night"])


async def record_usage_and_conversation(
    *,
    user_id,
    username: str,
    ip_address: str | None,
    request_id: str,
    model_name: str,
    upstream_model_name: str | None,
    service_name: str | None,
    model_config: dict[str, Any] | None,
    prompt_tokens: int,
    completion_tokens: int,
    stream: bool,
    status_code: int | None,
    latency_ms: int | None,
    success: bool,
    user_prompt: str,
    assistant_response: str,
) -> bool:
    try:
        input_price, output_price, total_price, currency = calculate_price(model_config, prompt_tokens, completion_tokens)
        user_prompt, prompt_truncated = truncate_text(user_prompt, PROMPT_LIMIT)
        assistant_response, response_truncated = truncate_text(assistant_response, RESPONSE_LIMIT)
        return await db_module.write_usage_and_conversation(
            user_id=user_id,
            username=username or "unknown",
            ip_address=ip_address,
            request_id=request_id,
            model_name=model_name,
            upstream_model_name=upstream_model_name,
            service_name=service_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input_price=input_price,
            output_price=output_price,
            total_price=total_price,
            currency=currency,
            stream=stream,
            status_code=status_code,
            latency_ms=latency_ms,
            success=success,
            user_prompt=user_prompt,
            assistant_response=assistant_response,
            prompt_truncated=prompt_truncated,
            response_truncated=response_truncated,
        )
    except Exception as exc:
        logger.error(f"[usage] 写入用量/对话失败: {exc}")
        return False
