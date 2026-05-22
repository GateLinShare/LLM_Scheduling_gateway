# 大模型调度网关

这是一个基于FastAPI的智能调度网关，用于管理多个大语言模型(LLM)的请求分发。它具有优先级队列、负载均衡、流式传输等功能。

## 配置说明

### config.py

> **注意**: 配置文件是 `config.py`，不是 `config.yaml`（此 README 已更新）。

基础配置文件，包含模型配置、Redis连接信息等：

```python
# 模型配置
MODELS = {
    "qwen3-coder": {
        "metrics_url": "http://10.45.155.210:19991/metrics",
        "api_url": "http://10.45.155.210:7102/v1/chat/completions",
        "queue_name": "llm_queue_qwen3_coder"
    },
    # 可以添加更多模型
}

# Redis配置
REDIS_CONFIG = {
    "host": "localhost",
    "port": 6379,
    "decode_responses": False,  # 禁用自动解码，返回原始bytes
    "password": None  # 如需密码，设置环境变量 REDIS_PASSWORD
}

# 默认超时时间（秒）
TIMEOUTS = {
    "high_priority": 600,   # 高优先级请求超时时间
    "low_priority": 7200    # 低优先级请求超时时间（120分钟）
}

# GPU使用率阈值
GPU_THRESHOLD = 0.7  # 70%

# 调度器配置
SCHEDULER = {
    "high_low_ratio": 4,      # 高优先级:低优先级处理比例
    "sleep_interval": 0.2,    # 调度器循环间隔（秒）
    "min_waiting_requests": 1,
    "max_pending_requests": 6,
    "low_priority_max_pending": 2
}

# 默认优先级
DEFAULT_PRIORITY = 3
```

### 多队列模式配置

一个模型可以配置多个子队列，实现负载分发：

```python
MODELS = {
    "testname-coder": {
        "type": "multi-queue",  # 多队列模式
        "queues": [
            {
                "queue_name": "qwen3-coder_queue",  # 子队列名
                "metrics_url": "http://10.45.155.210:19991/metrics",
                "api_url": "http://10.45.155.210:19991/v1/chat/completions",
                "model_name": "qwen3-coder",
                "load_factor": 2.0  # 负载倍率，选中时增加此值的负载
            },
            {
                "queue_name": "llm_queue_minimax_gpu2",
                "metrics_url": "http://10.45.155.212:19991/metrics",
                "api_url": "http://10.45.155.212:19991/v1/chat/completions",
                "model_name": "minimax2.5-212",
                "load_factor": 1.0  # 默认倍率
            },
        ],
        "load_queue": "testname-coder-load-queue"  # Redis 中的负载索引 key
    },
}
```

**配置说明：**

| 字段            | 说明                                                               |
| --------------- | ------------------------------------------------------------------ |
| `type`        | 设置为 `"multi-queue"` 启用多队列模式                            |
| `queues`      | 子队列列表，可配置多个                                             |
| `queue_name`  | 子队列在 Redis 中的名称                                            |
| `load_factor` | 负载倍率，选中时增加负载 = load_factor。倍率越高，被选中的机会越少 |
| `load_queue`  | Redis 中存储各子队列负载的有序集合 key                             |

**负载分发逻辑：**

1. 选择队列时，使用 Redis `ZRANGE` 获取负载最小的子队列
2. 选中后，该队列负载增加 `load_factor` 值
3. 请求完成后，负载减少 `load_factor` 值

**示例：**

- `load_factor: 2.0` 的队列，负载增长更快，被选中的次数更少
- `load_factor: 1.0` 的队列，负载增长更慢，被选中的次数更多

如需更均衡的分配，可设置相同的 `load_factor` 值。

## 启动方式

### 1. 启动 Redis

使用 Docker 启动 Redis：

```bash
docker run -d \
    --name llm-scheduling-redis \
    --restart unless-stopped \
    -p 16379:6379 \
    -v llm-scheduling-redis-data:/data \
    redis:8-alpine
```

如果当前环境无法直接拉取 Docker Hub 镜像，可继续使用已有镜像源：

```bash
docker run -d \
    --name llm-scheduling-redis \
    --restart unless-stopped \
    -p 6379:6379 \
    -v llm-scheduling-redis-data:/data \
    chaitin-registry.cn-hangzhou.cr.aliyuncs.com/basic/redis:8.0-alpine3.21
```

### 2. 启动 PostgreSQL

使用 Docker 启动 PostgreSQL：

```bash
docker run -d \
    --name llm-scheduling-postgres \
    --restart unless-stopped \
    -p 5432:5432 \
    -e POSTGRES_DB=llm_data \
    -e POSTGRES_USER=llm_user \
    -e POSTGRES_PASSWORD=llm_password \
    -v llm-scheduling-postgres-data:/var/lib/postgresql/data \
    postgres:16-alpine
```

后端默认连接配置：

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=llm_data
POSTGRES_USER=llm_user
POSTGRES_PASSWORD=llm_password
```

### 3. docker-compose 示例

```yaml
# docker-compose.yml
version: '3.8'
services:
  redis:
    image: redis:8-alpine
    container_name: llm-scheduling-redis
    ports:
      - "6379:6379"
    volumes:
      - llm-scheduling-redis-data:/data
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    container_name: llm-scheduling-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: llm_data
      POSTGRES_USER: llm_user
      POSTGRES_PASSWORD: llm_password
    volumes:
      - llm-scheduling-postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  llm-scheduling-redis-data:
  llm-scheduling-postgres-data:
```

启动命令：

```bash
docker-compose up -d
```

### 4. 启动网关服务

```bash
cd backend
./start.sh  # 启动主 API（端口 7103）和调度器
```

## API接口

### Chat Completions API

兼容OpenAI的聊天补全接口：

```bash
POST /v1/chat/completions

Headers:
- Content-Type: application/json
- X-Priority: [1-5] (可选，请求优先级，1最高)

Body:
{
  "model": "qwen3-coder",
  "messages": [
    {"role": "user", "content": "你好，介绍一下你自己"}
  ],
  "stream": false
}
```

### 模型列表API

获取可用模型列表：

```bash
GET /v1/models
```

### 队列状态API

获取当前队列状态：

```bash
GET /queue/status
```

### 调度器监控API

获取调度器监控数据：

```bash
GET /scheduler/monitor?minutes=1440
```

## 测试url

```bash
curl -X POST "http://10.45.155.213:7103/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer sk-ALTbgl6ut981w" \
    -H "X-Priority: 1" \
    -d '{
          "model": "qwen3-coder",
          "messages": [
            {
              "role": "user",
              "content": "你好"
            }
          ],
          "stream": true
        }'
```

```bash
curl -X GET "http://10.45.155.213:7203/v1/models"
```

## 注意事项

### 请求头处理

使用 aiohttp 发送请求时，必须移除手动设置的 `content-length` 头，让 aiohttp 自动计算：

```python
headers = dict(request.headers)
headers.pop("host", None)
headers.pop("content-length", None)  # 关键：移除content-length，让aiohttp自动计算
```

原因：手动设置的 `content-length` 可能与 aiohttp 实际计算的值不一致，导致上游 API 返回 400 Bad Request。

### JSON 格式要求

请求体必须使用标准 JSON 格式：

- `true`/`false`/`null`（非 `True`/`False`/`None`）
- 字符串必须用双引号包裹

错误示例：

```json
{
    "stream": True  // 错误：Python 风格
}
```

正确示例：

```json
{
    "stream": true  // 正确：JSON 标准
}
```

## 架构说明

- **双进程架构**: 网关 API 和调度器是独立进程，通过 Redis ZSET 通信
- **优先级队列**: 使用 Redis ZSET，score 为优先级值（1 最高）
- **模型选择**: 通过正则解析请求体中的 `model` 字段确定
- **日志位置**: `backend/logs/app.log`（500MB 轮转，保留 10 天）

## 性能统计

### 网关延迟

网关调度系统会增加约 0.2s 的额外延迟，主要用于：

- 请求体解析和验证
- Redis 数据存储（ZSET、Hash）
- 队列轮询等待
- 流式数据中转

日志示例：

```
[GatewayStats] ReqID: req:1769158613516947617, GatewayTime: 45.123s
[LLMProcessingTime] ReqID: req:1769158613516947617, LLMProcessingTime: 44.923s
```

对比 `GatewayTime` 和 `LLMProcessingTime` 可得出调度系统消耗的时间。
