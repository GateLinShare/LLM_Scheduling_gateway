#!/bin/bash

# 大模型调度网关停止脚本

echo "========================================"
echo "  大模型调度网关停止脚本"
echo "========================================"

# 停止主服务
echo "查找并停止主服务..."
pkill -f "llm-gateway-main"
if [ $? -eq 0 ]; then
    echo "已发送停止信号到主服务进程"
else
    echo "未发现运行中的主服务进程"
fi

# 停止调度器
echo "查找并停止调度器..."
pkill -f "llm-gateway-scheduler"
if [ $? -eq 0 ]; then
    echo "已发送停止信号到调度器进程"
else
    echo "未发现运行中的调度器进程"
fi

# 等待进程结束
sleep 3

# 检查是否还有进程在运行，如果有则强制终止
echo "检查是否还有残留进程..."
MAIN_PIDS=$(pgrep -f "llm-gateway-main")
SCHEDULER_PIDS=$(pgrep -f "llm-gateway-scheduler")

if [ ! -z "$MAIN_PIDS" ] || [ ! -z "$SCHEDULER_PIDS" ]; then
    echo "强制终止仍在运行的进程..."
    [ ! -z "$MAIN_PIDS" ] && pkill -9 -f "llm-gateway-main" 2>/dev/null
    [ ! -z "$SCHEDULER_PIDS" ] && pkill -9 -f "llm-gateway-scheduler" 2>/dev/null
fi

echo ""
echo "服务停止操作已完成"
echo "你可以通过以下命令确认服务是否完全停止:"
echo "  pgrep -f 'llm-gateway-main'"
echo "  pgrep -f 'llm-gateway-scheduler'"