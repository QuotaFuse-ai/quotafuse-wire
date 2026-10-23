#!/usr/bin/env sh
# QuotaFuse Wire 部署存活检查：
#   1) GET /api/health
#   2) GET /api/status，读取最近一次 run 的状态
#
# 环境变量：
#   QF_WIRE_HEALTH_URL   看板地址，默认 http://127.0.0.1:${QF_WIRE_PORT:-8790}
#   QF_WIRE_API_TOKEN    强制鉴权或远程访问时的只读 Bearer token
#   QF_WIRE_USER         多用户实例中的用户 id（发送 X-QF-User）
#   QF_WIRE_USER_TOKEN   该用户的 API 凭据（发送 X-QF-User-Token）
#
# 退出码：
#   0 健康；1 /api/health 不可用；2 /api/status 不可用；
#   3 最近一次 run 为 partial/unavailable；4 尚无 run 记录
set -eu

BASE_URL="${QF_WIRE_HEALTH_URL:-http://127.0.0.1:${QF_WIRE_PORT:-8790}}"
BASE_URL="${BASE_URL%/}"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

fetch() {
  _url="$1"
  if command -v curl >/dev/null 2>&1; then
    set -- -fsS --max-time 5
    if [ -n "${QF_WIRE_API_TOKEN:-}" ]; then
      set -- "$@" -H "Authorization: Bearer $QF_WIRE_API_TOKEN"
    fi
    if [ -n "${QF_WIRE_USER:-}" ]; then
      set -- "$@" -H "X-QF-User: $QF_WIRE_USER"
    fi
    if [ -n "${QF_WIRE_USER_TOKEN:-}" ]; then
      set -- "$@" -H "X-QF-User-Token: $QF_WIRE_USER_TOKEN"
    fi
    curl "$@" "$_url"
    return
  fi
  if [ -z "$PYTHON" ]; then
    printf '[healthcheck] FAIL 需要 curl 或 python 才能探活\n' >&2
    return 1
  fi
  "$PYTHON" - "$_url" <<'PY'
import os
import sys
import urllib.error
import urllib.request

request = urllib.request.Request(sys.argv[1])
token = os.environ.get("QF_WIRE_API_TOKEN", "").strip()
if token:
    request.add_header("Authorization", "Bearer " + token)
user = os.environ.get("QF_WIRE_USER", "").strip()
if user:
    request.add_header("X-QF-User", user)
user_token = os.environ.get("QF_WIRE_USER_TOKEN", "").strip()
if user_token:
    request.add_header("X-QF-User-Token", user_token)
try:
    with urllib.request.urlopen(request, timeout=5) as response:
        sys.stdout.write(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    sys.stderr.write(f"HTTP {exc.code}\n")
    sys.exit(1)
except Exception as exc:  # noqa: BLE001 - 网络错误统一报连接失败
    sys.stderr.write(f"连接失败: {exc}\n")
    sys.exit(1)
PY
}

run_field() {
  _name="$1"
  if [ -n "$PYTHON" ]; then
    "$PYTHON" -c '
import json
import sys

data = json.load(sys.stdin)
run = data.get("lastRun") or {}
value = run.get(sys.argv[1])
print("" if value is None else value)
' "$_name"
    return
  fi
  sed -n 's/.*"'"$_name"'": "\{0,1\}\([^",}]*\)"\{0,1\}.*/\1/p' | head -n 1
}

if ! HEALTH="$(fetch "$BASE_URL/api/health")"; then
  printf '[healthcheck] FAIL /api/health 不可用（%s）\n' "$BASE_URL" >&2
  exit 1
fi
printf '[healthcheck] ok 健康检查 %s/api/health\n' "$BASE_URL"

if ! STATUS_JSON="$(fetch "$BASE_URL/api/status")"; then
  printf '[healthcheck] FAIL /api/status 不可用（检查 QF_WIRE_USER / QF_WIRE_USER_TOKEN）\n' >&2
  exit 2
fi

RUN_STATUS="$(printf '%s' "$STATUS_JSON" | run_field status)"
RUN_ID="$(printf '%s' "$STATUS_JSON" | run_field runId)"
RUN_DAY="$(printf '%s' "$STATUS_JSON" | run_field day)"
RUN_ITEMS="$(printf '%s' "$STATUS_JSON" | run_field itemCount)"
RUN_FINISHED="$(printf '%s' "$STATUS_JSON" | run_field finishedAt)"

if [ -z "$RUN_STATUS" ]; then
  printf '[healthcheck] FAIL 尚无 run 记录，先运行 qfw run\n' >&2
  exit 4
fi

printf '[healthcheck] run %s：%s（%s，%s 条，完成于 %s）\n' \
  "$RUN_ID" "$RUN_STATUS" "$RUN_DAY" "$RUN_ITEMS" "$RUN_FINISHED"

case "$RUN_STATUS" in
  ok)
    printf '[healthcheck] OK\n'
    exit 0
    ;;
  *)
    printf '[healthcheck] FAIL 最近一次 run 状态为 %s\n' "$RUN_STATUS" >&2
    exit 3
    ;;
esac
