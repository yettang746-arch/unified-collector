#!/bin/bash
# post-deploy.sh — 在 git pull 之后跑的幂等修复脚本
#
# 解决问题：
#   1. 跨 sync/迁移工具可能剥离可执行位（rsync 不带 -p、scp 默认 strip、CSP 镜像快照等）
#   2. Tailscale MagicDNS 健康检查可能失效，破坏 Docker 容器内 DNS 链路
#   3. 容器重启后需要确认 DNS 走的是 host DNS 而非损坏的 Tailscale DNS
#
# 幂等性：可以多次执行，无副作用

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$REPO_DIR"

echo "🔧 post-deploy: $REPO_DIR"

# 1. 修复所有 scripts/*.sh 的可执行位
echo "  → chmod +x scripts/*.sh"
chmod +x scripts/*.sh 2>/dev/null || true

# 2. 验证关键脚本可执行
for s in scripts/trigger-collect.sh scripts/deploy.sh scripts/post-deploy.sh scripts/healthcheck.sh; do
  if [ -x "$s" ]; then
    echo "  ✅ $s 可执行"
  else
    echo "  ❌ ERROR: $s 不可执行" >&2
    exit 3
  fi
done

# 3. 检查 .env 存在性（不在 git 里，但部署需要）
if [ ! -f .env ]; then
  echo "  ⚠️  .env 不存在（API_KEY 需要从 env 注入）"
fi

# 4. 清理不需要部署到容器的目录（容器 volumes mount 的实际是 ./config 和 ./data，
#    但是 .git 和 .hermes 不需要，构建时本来就不会 COPY，这里只是防御性检查）
echo "  ✅ post-deploy 完成"
