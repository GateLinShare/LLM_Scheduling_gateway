import json
import os
from typing import Any

import tiktoken

import runtime_config
from config import logger


_encoders: dict[str, Any] = {}


def _ensure_cache_dir() -> None:
    cache_dir = runtime_config.token_config().get("tiktoken_cache_dir")
    if cache_dir:
        os.environ["TIKTOKEN_CACHE_DIR"] = os.path.abspath(cache_dir)


def get_encoder(model_name: str):
    _ensure_cache_dir()
    tokenizer_model = model_name or runtime_config.token_config().get("default_tokenizer_model", "gpt-3.5-turbo")
    if tokenizer_model in _encoders:
        return _encoders[tokenizer_model]
    try:
        encoder = tiktoken.encoding_for_model(tokenizer_model)
    except Exception as exc:
        logger.error(f"[token_counter] 获取 {tokenizer_model} 编码器失败，回退 gpt-3.5-turbo: {exc}")
        encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
    _encoders[tokenizer_model] = encoder
    return encoder


def count_text(text: Any, model_name: str) -> int:
    if text is None:
        return 0
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    return len(get_encoder(model_name).encode(text))


def count_input(input_value: Any, model_name: str) -> int:
    if isinstance(input_value, list):
        return sum(count_text(item, model_name) for item in input_value)
    return count_text(input_value, model_name)


def _message_content_tokens(content: Any, model_name: str) -> int:
    if isinstance(content, str):
        return count_text(content, model_name)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    total += count_text(item.get("text", ""), model_name)
                elif "text" in item:
                    total += count_text(item.get("text", ""), model_name)
            else:
                total += count_text(item, model_name)
        return total
    return count_text(content, model_name)


def count_messages(messages: list[dict[str, Any]], model_name: str) -> int:
    tokens_per_message = 4 if model_name == "gpt-3.5-turbo-0301" else 3
    tokens_per_name = -1 if model_name == "gpt-3.5-turbo-0301" else 1
    total = 0
    for message in messages or []:
        total += tokens_per_message
        total += count_text(message.get("role", ""), model_name)
        total += _message_content_tokens(message.get("content"), model_name)
        if message.get("name"):
            total += tokens_per_name + count_text(message.get("name"), model_name)
    return total + 3


def count_prompt_tokens(body: dict[str, Any], model_config: dict[str, Any] | None = None) -> int:
    model_name = (model_config or {}).get("tokenizer_model") or body.get("model") or "gpt-3.5-turbo"
    if "messages" in body:
        return count_messages(body.get("messages") or [], model_name)
    if "prompt" in body:
        return count_input(body.get("prompt"), model_name)
    if "input" in body:
        return count_input(body.get("input"), model_name)
    return 0


def extract_last_user_prompt(body: dict[str, Any]) -> str:
    messages = body.get("messages") or []
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content")
                if isinstance(content, str):
                    return content
                return json.dumps(content, ensure_ascii=False)
    prompt = body.get("prompt")
    if isinstance(prompt, str):
        return prompt
    return ""


def extract_assistant_response(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices") or []
    parts: list[str] = []
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                parts.append(message["content"])
            if isinstance(choice.get("text"), str):
                parts.append(choice["text"])
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "".join(parts)


def extract_usage_from_response(response_body: bytes) -> tuple[int, int, int, str]:
    try:
        data = json.loads(response_body.decode("utf-8"))
    except Exception:
        return 0, 0, 0, ""
    usage = data.get("usage") if isinstance(data, dict) else None
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or prompt + completion)
        return prompt, completion, total, extract_assistant_response(data)
    return 0, 0, 0, extract_assistant_response(data)


def completion_usage_from_text(text: str, model_config: dict[str, Any] | None, prompt_tokens: int) -> tuple[int, int, int]:
    tokenizer_model = (model_config or {}).get("tokenizer_model") or "gpt-3.5-turbo"
    completion = count_text(text, tokenizer_model)
    return prompt_tokens, completion, prompt_tokens + completion

