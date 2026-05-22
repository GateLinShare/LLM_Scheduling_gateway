#!/bin/sh

set -eu

echo "========================================"
echo "  大模型调度网关启动脚本"
echo "========================================"

LOG_DIR="logs"
MAIN_LOG="$LOG_DIR/main.log"
SCHEDULER_LOG="$LOG_DIR/scheduler.log"

mkdir -p "$LOG_DIR"

echo "检查并终止已运行的服务..."

echo "查找并终止主服务进程..."
pkill -f "llm-gateway-main" 2>/dev/null || true

echo "查找并终止调度器进程..."
pkill -f "llm-gateway-scheduler" 2>/dev/null || true

echo "再次检查相关进程..."
MAIN_PIDS=$(pgrep -f "llm-gateway-main" 2>/dev/null || true)
SCHEDULER_PIDS=$(pgrep -f "llm-gateway-scheduler" 2>/dev/null || true)

if [ -n "$MAIN_PIDS" ] || [ -n "$SCHEDULER_PIDS" ]; then
    echo "强制终止剩余的相关进程..."
    [ -n "$MAIN_PIDS" ] && pkill -9 -f "llm-gateway-main" 2>/dev/null || true
    [ -n "$SCHEDULER_PIDS" ] && pkill -9 -f "llm-gateway-scheduler" 2>/dev/null || true
    sleep 1
fi

echo "进程清理完成"

echo "清理旧的日志文件..."
rm -f "$LOG_DIR"/*.log 2>/dev/null || true

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
else
    PYTHON_BIN=python
fi

echo "启动主服务..."
nohup "$PYTHON_BIN" llm-gateway-main.py > "$MAIN_LOG" 2>&1 &
MAIN_PID=$!

sleep 1

if ps -p "$MAIN_PID" >/dev/null 2>&1; then
    echo "主服务已成功启动 (PID: $MAIN_PID)"
else
    echo "警告: 主服务可能启动失败，请检查 $MAIN_LOG"
fi

echo "启动调度器..."
nohup "$PYTHON_BIN" llm-gateway-scheduler.py > "$SCHEDULER_LOG" 2>&1 &
SCHEDULER_PID=$!

sleep 1

if ps -p "$SCHEDULER_PID" >/dev/null 2>&1; then
    echo "调度器已成功启动 (PID: $SCHEDULER_PID)"
else
    echo "警告: 调度器可能启动失败，请检查 $SCHEDULER_LOG"
fi

echo ""
echo "所有服务启动命令已执行"
echo "主服务日志: $MAIN_LOG"
echo "调度器日志: $SCHEDULER_LOG"
echo ""
echo "你可以使用以下命令查看日志:"
echo "  tail -f $MAIN_LOG"
echo "  tail -f $SCHEDULER_LOG"
echo ""
echo "如需停止服务，可以使用:"
echo "  pkill -f 'llm-gateway-main'"
echo "  pkill -f 'llm-gateway-scheduler'"
