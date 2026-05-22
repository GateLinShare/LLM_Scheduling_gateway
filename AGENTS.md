# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## 项目概述

LLM 调度网关 - 基于 FastAPI + Redis 的优先级队列调度系统，用于管理多个 LLM 模型的请求调度。

## 核心命令

### 后端 (Python)
```bash
cd backend
# 启动服务
./start.sh

# 停止服务
./stop.sh

# 手动启动
python llm-gateway-main.py  # 网关 API (端口 7203)
python llm-gateway-scheduler.py  # 调度器进程

# 安装依赖
pip install -r requirements.txt
```

### 前端 (Next.js)
```bash
cd frontend
npm run dev      # 开发模式
npm run build    # 构建生产版本
npm run lint     # ESLint 检查
```

## 关键文件

- **配置**: `backend/config.py` - 模型、Redis、调度器配置
- **网关**: `backend/llm-gateway-main.py` - FastAPI 网关服务
- **调度器**: `backend/llm-gateway-scheduler.py` - 独立调度进程
- **中间件**: `backend/queue_middleware.py` - 优先级队列中间件
- **前端**: `frontend/src/app/page.tsx` - 监控页面

## 模式特定规则

请参考以下模式特定文件获取更详细的非显而易见规则：
- `.roo/rules-code/AGENTS.md` - 编码规则
- `.roo/rules-debug/AGENTS.md` - 调试规则
- `.roo/rules-ask/AGENTS.md` - 文档规则
- `.roo/rules-architect/AGENTS.md` - 架构规则