#!/usr/bin/env bash
# WorkBuddy 用量监视 —— 启动器
#
#   ./run.sh         打开原生桌面面板（PyQt5，无需浏览器）
#   ./run.sh --web   启动本地服务并用浏览器打开（可选模式）
#
set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PORT="${WB_MONITOR_PORT:-8791}"
URL="http://127.0.0.1:${PORT}"
RUNTIME="$DIR/.runtime"
LOG="$RUNTIME/server.log"
PIDF="$RUNTIME/server.pid"

mkdir -p "$RUNTIME" 2>/dev/null || true

pick_python() {
  local p
  # 优先选择带 PyQt5 的解释器（原生窗口需要）
  for p in /usr/bin/python3 /usr/local/bin/python3 \
           "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3; do
    if [ -x "$p" ] && "$p" -c "import PyQt5.QtWidgets" >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  for p in "$HOME"/.workbuddy/binaries/python/versions/*/bin/python3 \
           /usr/bin/python3 \
           /usr/local/bin/python3; do
    if [ -x "$p" ]; then
      echo "$p"
      return 0
    fi
  done
  command -v python3 >/dev/null 2>&1 && { command -v python3; return 0; }
  return 1
}

PY="$(pick_python)" || exit 1
MODE="${1:-}"

# ---------------------------------------------------------------- Web 模式
if [ "$MODE" = "--web" ]; then
  alive() { curl -s --noproxy '*' --max-time 1 "$URL/api/ping" 2>/dev/null | grep -q '"ok"'; }

  if ! alive; then
    nohup "$PY" "$DIR/server.py" --port "$PORT" >"$LOG" 2>&1 &
    echo $! >"$PIDF"
    for _ in $(seq 1 80); do alive && break; sleep 0.1; done
  fi
  if ! alive; then
    command -v notify-send >/dev/null 2>&1 && notify-send "用量监视" "服务启动失败，详见 $LOG"
    exit 1
  fi

  browser_ok() {
    command -v "$1" >/dev/null 2>&1 || return 1
    sh -c 'timeout 4 "$1" --version' _ "$1" >/dev/null 2>&1
  }

  for b in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge; do
    if browser_ok "$b"; then
      "$b" --app="$URL" --class=workbuddy-token-monitor --window-size=1460,980 \
        --no-first-run --no-default-browser-check \
        --proxy-bypass-list="127.0.0.1;localhost" >/dev/null 2>&1 &
      exit 0
    fi
  done
  if browser_ok firefox; then
    firefox --new-window "$URL" >/dev/null 2>&1 &
    exit 0
  fi
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" >/dev/null 2>&1 &
    exit 0
  fi
  command -v notify-send >/dev/null 2>&1 && notify-send "用量监视" "面板地址：$URL"
  exit 0
fi

# ---------------------------------------------------------------- 默认：原生窗口
if ! "$PY" -c "import PyQt5.QtWidgets" >/dev/null 2>&1; then
  # 没有 PyQt5 就退回浏览器模式
  exec "$0" --web
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
  command -v notify-send >/dev/null 2>&1 && \
    notify-send "用量监视" "未检测到图形会话，可运行 ./run.sh --web 用浏览器查看"
  exit 1
fi

exec "$PY" "$DIR/qt_app.py" "$@" 2>>"$RUNTIME/qt.log"
