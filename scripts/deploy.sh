#!/bin/bash
# deploy.sh — 一键部署：在 VPS 上同步 + 应用修复 + 重启 collector
#
# 用法:
#   bash scripts/deploy.sh           # 默认：git pull + post-deploy + 重启 + healthcheck
#   bash scripts/deploy.sh --no-restart  # 只 pull + post-deploy，不重启容器
#
# 流程：
#   1. 验证在 git 仓库里
#   2. git fetch + git pull origin main
#   3. bash scripts/post-deploy.sh（权限修复、依赖检查）
#   4. docker compose up -d --no-deps collector（可选）
#   5. bash scripts/healthcheck.sh（DNS + API 端到端验证）

set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/unified-collector}"
BRANCH="${BRANCH:-main}"
RESTART=1

for arg in "$@"; do
  case "$arg" in
    --no-restart) RESTART=0 ;;
    --restart)    RESTART=1 ;;
    --help|-h)
      grep '^#' "$0" | head -20
      exit 0
      ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

cd "$REPO_DIR"

echo "📦 deploy 开始：$(date -u +%FT%TZ)"

# 1. 在 git 仓库
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "❌ ERROR: $REPO_DIR 不是 git 仓库" >&2
  exit 1
fi

# 2. 检查工作区干净（避免意外覆盖未 push 的改动）
if ! git diff --quiet HEAD 2>/dev/null; then
  echo "⚠️  工作区有未提交改动："
  git status -s | head -5
  echo "请先 commit + push，或用 git stash。"
  exit 2
fi

# 3. fetch + pull
echo "📥 git fetch origin $BRANCH..."
git fetch origin "$BRANCH"

# 检测远端是否有新 commit
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/"$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "  → 工作区已是最新（$LOCAL），跳过 pull"
else
  echo "📥 git pull origin $BRANCH..."
  git pull --no-edit origin "$BRANCH"
fi

# 4. post-deploy
echo "🔧 post-deploy..."
bash scripts/post-deploy.sh

# 5. 重启 collector（可选）
if [ "$RESTART" -eq 1 ]; then
  echo "🔄 重启 collector (no-deps)..."
  docker compose up -d --no-deps collector
  # 容器启动需要几秒，先等健康检查通过
  echo "  → 等待 healthcheck..."
  for i in $(seq 1 30); do
    if curl -sfS -m 3 http://localhost:8100/api/v1/health >/dev/null 2>&1; then
      echo "  ✅ collector 健康（尝试 $i 次）"
      break
    fi
    sleep 1
  done
fi

# 6. healthcheck
echo ""
echo "🩺 healthcheck..."
bash scripts/healthcheck.sh

echo ""
echo "✅ deploy 完成：$(date -u +%FT%TZ)"
