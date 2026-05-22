import orjson
import uuid
import time
import runtime_config


def create_invalid_model_response(model_name: str, error_message: str = None, stream: bool = True):
    """构造错误响应（符合 OpenAI 格式）"""
    if error_message:
        message = error_message
    else:
        available_models = ', '.join(runtime_config.get_models().keys())
        message = f"模型名称不可用: {model_name}。可用模型: {available_models}"
    
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:8]}"
    created = int(time.time())
    
    if stream:
        # 流式响应格式 (chat.completion.chunk)
        response_data = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"content": message, "reasoning_content": None},
                "logprobs": None,
                "finish_reason": "stop",
                "stop_reason": None,
                "token_ids": None
            }]
        }
        
        from fastapi.responses import StreamingResponse
        
        async def message_generator():
            yield f"data: {orjson.dumps(response_data).decode()}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(message_generator(), media_type="text/event-stream")
    else:
        # 非流式响应格式 (chat.completion)
        response_data = {
            "id": chunk_id,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message,
                    "reasoning_content": None,
                    "refusal": None,
                    "annotations": None,
                    "audio": None,
                    "function_call": None,
                    "tool_calls": None
                },
                "logprobs": None,
                "finish_reason": "stop",
                "stop_reason": None,
                "token_ids": None
            }],
            "service_tier": None,
            "system_fingerprint": None,
            "usage": {
                "prompt_tokens": 0,
                "total_tokens": 0,
                "completion_tokens": 0,
                "prompt_tokens_details": None
            },
            "prompt_logprobs": None,
            "prompt_token_ids": None,
            "kv_transfer_params": None
        }
        
        from fastapi import Response
        return Response(
            content=orjson.dumps(response_data),
            status_code=200,
            media_type="application/json"
        )
