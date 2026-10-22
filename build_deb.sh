#!/usr/bin/env bash
# 构建 .deb 安装包
#   ./build_deb.sh            使用 qt_app.py 里的版本号
#   ./build_deb.sh 1.0.1      指定版本号
set -eu

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PKG="workbuddy-token-monitor"

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  VERSION="$(/usr/bin/python3 -c "import re,sys;print(re.search(r'__version__ = \"([^\"]+)\"', open('$DIR/qt_app.py', encoding='utf-8').read()).group(1))")"
fi

ARCH="all"
STAGE="$DIR/.build/${PKG}_${VERSION}_${ARCH}"
OUT="$DIR/dist/${PKG}_${VERSION}_${ARCH}.deb"

command -v dpkg-deb >/dev/null 2>&1 || { echo "缺少 dpkg-deb"; exit 1; }

rm -rf "$DIR/.build"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/$PKG" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/128x128/apps"

# ---- 程序文件
install -m 644 "$DIR"/*.py "$STAGE/usr/share/$PKG/"
cp -r "$DIR/web" "$STAGE/usr/share/$PKG/"
install -m 644 "$DIR/LICENSE" "$DIR/README.md" "$DIR/README.en.md" "$STAGE/usr/share/$PKG/"
install -m 644 "$DIR/screenshot.png" "$DIR/screenshot-mini.png" "$STAGE/usr/share/$PKG/"
install -m 644 "$DIR/web/icon.png" "$STAGE/usr/share/icons/hicolor/128x128/apps/$PKG.png"

# 去掉开发期产物
rm -rf "$STAGE/usr/share/$PKG/__pycache__" "$STAGE/usr/share/$PKG/.runtime" "$STAGE/usr/share/$PKG/.git"

# ---- 启动器
cat > "$STAGE/usr/bin/$PKG" <<'LAUNCHER'
#!/bin/sh
# WorkBuddy 用量监视 —— 系统级启动器
if ! python3 -c "import PyQt5.QtWidgets" >/dev/null 2>&1; then
  echo "需要 python3-pyqt5：sudo apt install python3-pyqt5" >&2
  exit 1
fi
exec python3 /usr/share/workbuddy-token-monitor/qt_app.py "$@"
LAUNCHER
chmod 755 "$STAGE/usr/bin/$PKG"

# ---- desktop
cat > "$STAGE/usr/share/applications/$PKG.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Version=1.0
Name=WorkBuddy 用量监视
Name[en]=WorkBuddy Token Monitor
GenericName=Token Usage Monitor
Comment=实时监视 WorkBuddy 的 Token 用量、生成吞吐与缓存命中
Comment[en]=Monitor WorkBuddy token usage, throughput and cache hit rate
Exec=$PKG
Icon=$PKG
Terminal=false
StartupNotify=true
Categories=Development;Utility;
Keywords=workbuddy;token;usage;monitor;cache;用量;监控;缓存;
DESKTOP
chmod 644 "$STAGE/usr/share/applications/$PKG.desktop"

# ---- 安装大小
SIZE_KB="$(du -sk "$STAGE/usr" | cut -f1)"

# ---- control
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PKG
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.8), python3-pyqt5
Installed-Size: $SIZE_KB
Maintainer: The-garden-of-sinner <50914620+The-garden-of-sinner@users.noreply.github.com>
Homepage: https://github.com/The-garden-of-sinner/workbuddy-token-monitor
Description: WorkBuddy 用量监视面板
 实时查看 WorkBuddy 的 Token 消耗、生成吞吐与缓存命中率，
 附带积分统计与会话排行。
 .
 数据只读留在本机，不联网、不上传。提供 PyQt5 原生窗口
 与可选的 Web 面板，适合 Chromium 无法启动的国产化环境。
CONTROL

# ---- 维护脚本
cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
POSTINST
chmod 755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
fi
exit 0
POSTRM
chmod 755 "$STAGE/DEBIAN/postrm"

# ---- 构建
mkdir -p "$DIR/dist"
rm -f "$OUT"
dpkg-deb --build --root-owner-group "$STAGE" "$OUT" >/dev/null

echo "已生成：$OUT"
echo "大小：$(du -h "$OUT" | cut -f1)"
echo
echo "安装：sudo dpkg -i $OUT"
echo "卸载：sudo apt remove $PKG"
