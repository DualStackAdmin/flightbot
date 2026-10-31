#!/usr/bin/env bash
# GitHub-dan ən son versiyanı çəkib yenidən qurur. Miqrasiyalar avtomatik işləyir (migrate servisi).
#   ./scripts/update.sh            # yalnız yenilik varsa
#   ./scripts/update.sh --force    # yenilik olmasa da yenidən qur
set -euo pipefail
cd "$(dirname "$0")/.."

dc() { if docker info >/dev/null 2>&1; then docker compose "$@"; else sudo docker compose "$@"; fi; }

git fetch --quiet origin
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse '@{u}')"

if [ "$local_rev" = "$remote_rev" ] && [ "${1:-}" != "--force" ]; then
  echo "Artıq ən son versiyadır (${local_rev:0:7})."
  exit 0
fi

echo "==> ${local_rev:0:7} -> ${remote_rev:0:7}"
git pull --ff-only
dc up -d --build
echo "==> miqrasiya logu:"
dc logs migrate --tail=20 || true
dc ps
docker image prune -f >/dev/null 2>&1 || sudo docker image prune -f >/dev/null 2>&1 || true
echo "==> Yeniləndi: $(git rev-parse --short HEAD)"
