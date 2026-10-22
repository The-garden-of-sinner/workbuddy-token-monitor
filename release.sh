#!/usr/bin/env bash
# 创建 GitHub Release 并上传 .deb
#
#   GH_TOKEN=ghp_xxx ./release.sh 1.0.0
#
# token 需要 repo 权限（classic）或 Contents: Read and write（fine-grained）。
# 不想用 token 的话，也可以直接在网页上创建 release 并把 dist/ 里的 deb 拖进去。
set -eu

VERSION="${1:-}"
REPO="The-garden-of-sinner/workbuddy-token-monitor"
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

[ -n "$VERSION" ] || { echo "用法：./release.sh 1.0.0（或 GH_TOKEN=... ./release.sh 1.0.0）"; exit 1; }
DEB="$DIR/dist/workbuddy-token-monitor_${VERSION}_all.deb"
[ -f "$DEB" ] || { echo "找不到 $DEB，先运行 ./build_deb.sh $VERSION"; exit 1; }

if [ -z "${GH_TOKEN:-}" ]; then
  for CONF in "${XDG_CONFIG_HOME:-$HOME/.config}/github/token" \
              "${XDG_CONFIG_HOME:-$HOME/.config}/workbuddy-token-monitor/token"; do
    if [ -f "$CONF" ]; then
      GH_TOKEN="$(cat "$CONF")"
      export GH_TOKEN
      break
    fi
  done
fi
[ -n "${GH_TOKEN:-}" ] || { echo "尚未配置 token，请先运行 ./setup_token.sh"; exit 1; }

BODY="$(/usr/bin/python3 - "$VERSION" <<'PY'
import json, sys
v = sys.argv[1]
text = """## 安装

```bash
sudo dpkg -i workbuddy-token-monitor_%s_all.deb
sudo apt -f install
```

装好后从应用菜单打开「WorkBuddy 用量监视」，或终端执行 `workbuddy-token-monitor`。

完整变更见 [CHANGELOG.md](CHANGELOG.md)。
""" % v
print(json.dumps({"tag_name": "v" + v, "name": "v" + v, "body": text,
                  "draft": False, "prerelease": False}, ensure_ascii=False))
PY
)"

START_TS=$(date +%s)
START_TS=$(date +%s)
echo "创建 release v$VERSION ..."
RESP="$(curl -sS -X POST \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/releases" \
  -d "$BODY")"

REL_ID="$(printf '%s' "$RESP" | /usr/bin/python3 -c 'import json,sys;print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
if [ -z "$REL_ID" ]; then
  echo "创建失败："
  printf '%s\n' "$RESP" | head -20
  exit 1
fi
echo "release id = $REL_ID"

echo "上传 $(basename "$DEB") ..."
ASSET="$(curl -sS -X POST \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Content-Type: application/vnd.debian.binary-package" \
  --data-binary "@$DEB" \
  "https://uploads.github.com/repos/$REPO/releases/$REL_ID/assets?name=$(basename "$DEB")")"

ASSET_URL="$(printf '%s' "$ASSET" | /usr/bin/python3 -c 'import json,sys;print(json.load(sys.stdin).get("browser_download_url",""))' 2>/dev/null || true)"
ASSET_SIZE="$(printf '%s' "$ASSET" | /usr/bin/python3 -c 'import json,sys;print("%.1f" % (json.load(sys.stdin).get("size",0)/1024.0))' 2>/dev/null || echo "?")"

if [ -z "$ASSET_URL" ]; then
  echo "上传失败："
  printf '%s\n' "$ASSET" | head -20
  exit 1
fi

echo
echo "✅ 发布完成（$(( $(date +%s) - START_TS ))s）"
echo "   版本页：https://github.com/$REPO/releases/tag/v$VERSION"
echo "   安装包：$ASSET_URL"
echo "   大小  ：$ASSET_SIZE KB"
echo
echo "   安装：sudo dpkg -i $(basename "$DEB")"
