#!/usr/bin/env bash
# 安装 / 卸载 WorkBuddy 用量监视的桌面启动项
#   ./install.sh              安装（应用菜单 + 桌面快捷方式）
#   ./install.sh --uninstall  卸载

set -u

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
NAME="workbuddy-token-monitor"
APPS_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$APPS_DIR/$NAME.desktop"

desktop_dir() {
  if [ -d "$HOME/桌面" ]; then echo "$HOME/桌面"
  elif [ -d "$HOME/Desktop" ]; then echo "$HOME/Desktop"
  else echo ""; fi
}

uninstall() {
  rm -f "$DESKTOP_FILE"
  local d; d="$(desktop_dir)"
  [ -n "$d" ] && rm -f "$d/$NAME.desktop"
  command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1
  echo "已卸载桌面启动项（服务若在运行，可执行 $DIR/stop.sh 停止）"
}

if [ "${1:-}" = "--uninstall" ]; then
  uninstall
  exit 0
fi

chmod +x "$DIR/run.sh" "$DIR/stop.sh" "$DIR/install.sh" 2>/dev/null
mkdir -p "$APPS_DIR"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=WorkBuddy 用量监视
Name[en]=WorkBuddy Token Monitor
GenericName=Token Usage Monitor
Comment=实时监视 WorkBuddy 的 token 用量、生成吞吐与缓存命中
Exec=$DIR/run.sh
Icon=$DIR/web/icon.png
Terminal=false
StartupNotify=true
StartupWMClass=workbuddy-token-monitor
Categories=Development;Utility;
Keywords=workbuddy;token;usage;monitor;cache;throughput;用量;监控;缓存;
EOF

chmod +x "$DESKTOP_FILE"

D="$(desktop_dir)"
if [ -n "$D" ]; then
  cp -f "$DESKTOP_FILE" "$D/$NAME.desktop"
  chmod +x "$D/$NAME.desktop"
  # 让文件管理器信任该启动器（GNOME 系需要，失败不影响使用）
  gio set "$D/$NAME.desktop" metadata::trusted true >/dev/null 2>&1 || true
  echo "桌面快捷方式：$D/$NAME.desktop"
fi

command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1

echo "应用菜单条目：$DESKTOP_FILE"
echo "双击即可启动；服务关闭命令：$DIR/stop.sh"
