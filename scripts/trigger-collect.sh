#!/bin/bash
# Trigger daily collection via API
# Usage: bash trigger-collect.sh
#
# 自愈：每次运行主动 chmod +x 自己（一些 rsync/迁移工具会剥离可执行位）
# 哪怕被 `bash trigger-collect.sh` 显式调用也能正常工作。
set -euo pipefail

# 兼容旧部署：跨 sync/迁移工具可能丢失 +x 位，主动尝试设置一次
chmod +x "$0" 2>/dev/null || true

API_URL="${COLLECTOR_URL:-https://collector.255202.xyz}"
API_KEY="${API_KEY:-cbtc_2026_k3y}"

if [ -z "$API_KEY" ]; then
  echo "❌ ERROR: API_KEY 未设置（export API_KEY 或在 .env 中配置）" >&2
  exit 1
fi

echo "🚀 Triggering collection at $(date -u +%FT%TZ 2>/dev/null || date)"

TMP_RESP="$(mktemp -t collect-resp.XXXXXX.json)"
trap 'rm -f "$TMP_RESP"' EXIT

# 触发采集：失败立即报错，不静默继续
if ! curl -sfS -m 60 \
    -X POST "${API_URL}/api/v1/collect" \
    -H "Authorization: Bearer ${API_KEY}" \
    -H "Content-Type: application/json" \
    -o "$TMP_RESP"; then
  echo "❌ ERROR: collector API 调用失败（${API_URL}/api/v1/collect）" >&2
  exit 2
fi

# 解析响应：fetched/stored/errors 三个核心指标
python3 - "$TMP_RESP" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
print(f"📦 采集结果: fetched={d.get('total_fetched', 0)} "
      f"stored={d.get('total_stored', 0)} "
      f"errors={len(d.get('errors', []))}")
PY

# 打印最新统计（数据库总条数）
echo ""
echo "📊 当前数据库统计:"
curl -sfS -m 10 "${API_URL}/api/v1/articles/stats" \
  -H "Authorization: Bearer ${API_KEY}" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(f'  total: {d.get(\"total\", 0)}')
by_cat = d.get('by_category', {}) or {}
for k, v in sorted(by_cat.items(), key=lambda x: -x[1])[:8]:
    print(f'  {k}: {v}')
"
