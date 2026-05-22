#!/bin/bash

cd "$(dirname "$0")"

PORT="${PORT:-3000}"

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
  fi
}

echo "停止前端生产服务..."
kill_port_users

PIDS=$(pgrep -f "next start.*(-p ${PORT}|--port ${PORT}|-H 0.0.0.0)" || true)
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs -r kill -TERM
  sleep 2
fi

echo "前端生产服务停止命令已执行"
