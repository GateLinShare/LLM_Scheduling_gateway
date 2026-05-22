#!/bin/bash

set -e

cd "$(dirname "$0")"

PORT="${PORT:-3100}"
HOSTNAME="${HOSTNAME:-0.0.0.0}"
LOG_FILE="${LOG_FILE:-frontend.log}"

kill_port_users() {
  local pids=""

  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)
  fi

  if [ -z "$pids" ] && command -v ss >/dev/null 2>&1; then
    pids=$(ss -ltnp "sport = :${PORT}" 2>/dev/null | awk 'match($0, /pid=([0-9]+)/, m) { print m[1] }' | sort -u)
  fi

  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r kill -TERM
    sleep 2
  fi

  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)
  fi

  if [ -z "$pids" ] && command -v ss >/dev/null 2>&1; then
    pids=$(ss -ltnp "sport = :${PORT}" 2>/dev/null | awk 'match($0, /pid=([0-9]+)/, m) { print m[1] }' | sort -u)
  fi

  if [ -n "$pids" ]; then
    echo "$pids" | xargs -r kill -KILL
    sleep 1
  fi
}

echo "检查并终止已有前端生产服务..."
kill_port_users

PIDS=$(pgrep -f "next start.*(-p ${PORT}|--port ${PORT}|-H ${HOSTNAME})" || true)
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs -r kill -TERM
  sleep 2
fi

if [ ! -d ".next" ]; then
  echo "未找到 .next 构建目录，先执行 npm run build"
  exit 1
fi

echo "启动前端生产服务: http://${HOSTNAME}:${PORT}"
nohup npm run start -- -H 0.0.0.0 -p "${PORT}" > "${LOG_FILE}" 2>&1 &
echo "前端生产服务已启动，日志: ${LOG_FILE}"
