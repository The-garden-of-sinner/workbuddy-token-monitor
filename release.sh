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

[ -n "$VERSION" ] || { echo "用法：GH_TOKEN=... ./release.sh 1.0.0"; exit 1; }
DEB="$DIR/dist/workbuddy-token-monitor_${VERSION}_all.deb"
[ -f "$DEB" ] || { echo "找不到 $DEB，先运行 ./build_deb.sh $VERSION"; exit 1; }
[ -n "${GH_TOKEN:-}" ] || { echo "请先设置 GH_TOKEN 环境变量"; exit 1; }

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
curl -sS -X POST \
  -H "Authorization: Bearer $GH_TOKEN" \
  -H "Content-Type: application/vnd.debian.binary-package" \
  --data-binary "@$DEB" \
  "https://uploads.github.com/repos/$REPO/releases/$REL_ID/assets?name=$(basename "$DEB")" \
  | /usr/bin/python3 -c 'import json,sys;d=json.load(sys.stdin);print("完成：" + d.get("browser_download_url","(无返回)"))'
