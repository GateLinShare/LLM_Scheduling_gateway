import json
import os
import tempfile
import threading
from copy import deepcopy
from typing import Any

from config import RUNTIME_CONFIG_PATH, TIKTOKEN_CACHE_DIR, logger


_lock = threading.RLock()
_config: dict[str, Any] | None = None
_mtime: float | None = None


def _default_config() -> dict[str, Any]:
    return {
        "models": {},
        "features": {
            "auto_register_enabled": False,
        },
        "token": {
            "tiktoken_cache_dir": TIKTOKEN_CACHE_DIR,
            "default_tokenizer_model": "gpt-3.5-turbo",
        },
        "rate_limit": {
            "window_minutes": 1,
            "request_threshold": 5,
            "downgraded_priority": 4,
            "daily_quota_limit": 20,
            "window_quota_limit": 0.36,
            "window_quota_action": "limit",
            "daily_quota_action": "limit",
        },
        "system": {
            "time_offset_minutes": 0,
        },
        "scheduler": {
            "timeouts": {
                "high_priority": 600,
                "low_priority": 7200,
            },
            "gpu_threshold": 0.7,
            "high_low_ratio": 5,
            "sleep_interval": 0.2,
            "min_waiting_requests": 2,
            "max_pending_requests": 30,
            "low_priority_max_pending": 3,
            "default_priority": 3,
            "priority_thresholds": {
                "high_priority_max": 3,
                "low_priority_min": 4,
            },
        },
    }


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def reload_config(force: bool = False) -> dict[str, Any]:
    global _config, _mtime
    with _lock:
        path = RUNTIME_CONFIG_PATH
        current_mtime = os.path.getmtime(path) if os.path.exists(path) else None
        if not force and _config is not None and current_mtime == _mtime:
            return deepcopy(_config)

        config = _default_config()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = _merge(config, json.load(f))
            except Exception as exc:
                logger.error(f"[runtime_config] 加载动态配置失败，使用默认配置: {exc}")

        _config = config
        _mtime = current_mtime
        return deepcopy(_config)


def get_config() -> dict[str, Any]:
    return reload_config()


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    global _config, _mtime
    with _lock:
        directory = os.path.dirname(RUNTIME_CONFIG_PATH)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".runtime_config.", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(tmp_path, RUNTIME_CONFIG_PATH)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        _config = deepcopy(config)
        _mtime = os.path.getmtime(RUNTIME_CONFIG_PATH)
        return deepcopy(_config)


def get_models(include_disabled: bool = False) -> dict[str, Any]:
    models = get_config().get("models", {})
    if include_disabled:
        return models
    return {name: cfg for name, cfg in models.items() if cfg.get("enabled", True)}


def get_model_config(model_name: str) -> dict[str, Any] | None:
    return get_models().get(model_name)


def upsert_model(model_name: str, model_config: dict[str, Any]) -> dict[str, Any]:
    config = get_config()
    config.setdefault("models", {})[model_name] = model_config
    return save_config(config)


def delete_model(model_name: str) -> bool:
    config = get_config()
    existed = model_name in config.get("models", {})
    config.setdefault("models", {}).pop(model_name, None)
    save_config(config)
    return existed


def auto_register_enabled() -> bool:
    return bool(get_config().get("features", {}).get("auto_register_enabled", False))


def token_config() -> dict[str, Any]:
    return get_config().get("token", {})


def rate_limit_config() -> dict[str, Any]:
    return get_config().get("rate_limit", {})


def time_offset_minutes() -> int:
    try:
        return int(get_config().get("system", {}).get("time_offset_minutes", 0))
    except (TypeError, ValueError):
        return 0


def scheduler_config() -> dict[str, Any]:
    return get_config().get("scheduler", {})
