#!/usr/bin/env bash
# 保存 GitHub token 到本地文件，供 release.sh 使用
# token 不会回显，也不会进 shell history
set -eu

# 通用路径，便于其他工作区的会话直接读取
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/github"
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

  # classic token 会带 x-oauth-scopes；fine-grained 没有这个头
  SCOPES="$(curl -sS -D - -o /dev/null -H "Authorization: Bearer $TOKEN" \
    https://api.github.com/user 2>/dev/null \
    | tr -d '\r' | awk -F': ' 'tolower($1)=="x-oauth-scopes"{print $2}')"

  if [ -n "${SCOPES:-}" ]; then
    echo "权限范围：$SCOPES"
    DANGER=""
    for s in delete_repo admin:org admin:public_key admin:repo_hook admin:gpg_key; do
      case ",$SCOPES," in
        *"$s"*) DANGER="$DANGER $s" ;;
      esac
    done
    if [ -n "$DANGER" ]; then
      echo
      echo "⚠️  包含高风险权限：$DANGER"
      echo "    delete_repo 能删仓库，admin:public_key 能加 SSH 后门，建议撤销重建。"
    fi
  else
    echo "权限范围：（fine-grained token，清单见 GitHub 页面）"
  fi
  echo
  echo "接着执行：./release.sh 1.0.0"
else
  echo "token 校验失败（HTTP $CODE）。可能已过期、权限不足或网络不通。" >&2
  rm -f "$CONF"
  exit 1
fi
