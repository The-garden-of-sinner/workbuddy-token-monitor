#!/usr/bin/env bash
# 保存 GitHub token 到本地文件，供 release.sh 使用
# token 不会回显，也不会进 shell history
set -eu

CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/workbuddy-token-monitor"
CONF="$CONF_DIR/token"

mkdir -p "$CONF_DIR"
chmod 700 "$CONF_DIR" 2>/dev/null || true

printf '粘贴 GitHub token（输入不回显，回车结束）：'
if ! IFS= read -rs TOKEN; then
  echo
  echo "读取失败" >&2
  exit 1
fi
echo

TOKEN="$(printf '%s' "$TOKEN" | tr -d '[:space:]')"
if [ -z "$TOKEN" ]; then
  echo "输入为空，已取消" >&2
  exit 1
fi

printf '%s' "$TOKEN" > "$CONF"
chmod 600 "$CONF"

echo "已保存到：$CONF"
echo
echo "校验中…"
CODE="$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/user || echo 000)"

if [ "$CODE" = "200" ]; then
  LOGIN="$(curl -s -H "Authorization: Bearer $TOKEN" https://api.github.com/user \
    | /usr/bin/python3 -c 'import json,sys;print(json.load(sys.stdin).get("login",""))' 2>/dev/null || true)"
  echo "token 有效，账号：${LOGIN:-unknown}"
  echo "接着执行：./release.sh 1.0.0"
else
  echo "token 校验失败（HTTP $CODE）。可能已过期、权限不足或网络不通。" >&2
  rm -f "$CONF"
  exit 1
fi
