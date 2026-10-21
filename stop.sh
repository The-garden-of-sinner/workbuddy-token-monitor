#!/usr/bin/env bash
# 停止本地监视服务
set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PIDF="$DIR/.runtime/server.pid"

if [ -f "$PIDF" ]; then
  PID="$(cat "$PIDF" 2>/dev/null || true)"
  if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null && echo "已停止服务 (pid $PID)"
    rm -f "$PIDF"
    exit 0
  fi
fi

if pkill -f "$DIR/server.py" 2>/dev/null; then
  echo "已停止服务"
  rm -f "$PIDF"
  exit 0
fi

echo "没有正在运行的监视服务"
