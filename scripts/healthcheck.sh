#!/bin/bash
# healthcheck.sh — 完整健康检查
#
# 检查项：
#   1. 容器 Up 状态（unified-collector）
#   2. 容器内 DNS 解析能力（api.telegram.org / google.com）
#   3. Collector API /health 端点
#   4. 触发一次 collect，验证 fetch/store 链路
#
# 设计原则：
#   - 单项失败立即 exit 1，返回非零码
#   - 不依赖 python3（容器内可能没有），用 docker exec + sh 内置
#   - 输出结构化，可被 cron 当作 alert trigger

set -euo pipefail

CONTAINER="${CONTAINER:-unified-collector}"
API_URL="${COLLECTOR_URL:-https://collector.255202.xyz}"
API_KEY="${API_KEY:-cbtc_2026_k3y}"
REPO_DIR="${REPO_DIR:-/root/unified-collector}"

# 如果 .env 存在，从里面读 API_KEY
if [ -z "${API_KEY:-}" ] && [ -f "$REPO_DIR/.env" ]; then
  API_KEY="$(grep -E '^API_KEY=' "$REPO_DIR/.env" | cut -d= -f2 | tr -d '\r')"
fi

failed=0

echo "════════════════════════════════════════════════"
echo "  Unified Collector Health Check"
echo "════════════════════════════════════════════════"

# 1. 容器状态
echo ""
echo "▸ [1/4] 容器状态"
if docker ps --filter "name=$CONTAINER" --format '{{.Names}}\t{{.Status}}' | grep -q "$CONTAINER.*Up"; then
  docker ps --filter "name=$CONTAINER" --format '  ✅ {{.Names}}: {{.Status}}'
else
  echo "  ❌ $CONTAINER 不在 running 状态"
  docker ps --filter "name=$CONTAINER" --format '  current: {{.Names}}: {{.Status}}'
  failed=1
fi

# 2. DNS 解析（容器内）
echo ""
echo "▸ [2/4] DNS 解析（容器内）"
for host in api.telegram.org google.com; do
  # 用 sh 的 getent 测试，避免依赖 python
  if docker exec "$CONTAINER" sh -c "getent hosts '$host' >/dev/null 2>&1" 2>/dev/null; then
    echo "  ✅ $host"
  else
    echo "  ❌ $host — 容器内 DNS 解析失败"
    failed=1
  fi
done

# 3. API 健康
echo ""
echo "▸ [3/4] Collector API"
HTTP_CODE=$(curl -sS -m 5 -o /dev/null -w '%{http_code}' \
  "$API_URL/api/v1/health" 2>/dev/null || echo 000)
if [ "$HTTP_CODE" = "200" ]; then
  echo "  ✅ $API_URL/api/v1/health → HTTP 200"
else
  echo "  ❌ $API_URL/api/v1/health → HTTP $HTTP_CODE"
  failed=1
fi

# 4. 触发 collect（验证端到端）
echo ""
echo "▸ [4/4] 端到端触发（仅在 1-3 全过才跑）"
if [ "$failed" -eq 0 ]; then
  if bash "$REPO_DIR/scripts/trigger-collect.sh" 2>&1 | tail -10; then
    echo "  ✅ 端到端 OK"
  else
    echo "  ⚠️  触发脚本返回非零（已打印详细输出）"
    failed=1
  fi
else
  echo "  ⏭️  跳过（前置检查未通过）"
fi

echo ""
echo "════════════════════════════════════════════════"
if [ "$failed" -eq 0 ]; then
  echo "  ✅ 全部通过"
  exit 0
else
  echo "  ❌ 有失败项（见上方标记）"
  exit 1
fi
