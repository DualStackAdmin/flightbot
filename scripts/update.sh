#!/usr/bin/env bash
# Pull the latest version from GitHub and rebuild. Migrations run automatically (the migrate service).
#   ./scripts/update.sh            # only if there is something new
#   ./scripts/update.sh --force    # rebuild even if nothing changed
set -euo pipefail
cd "$(dirname "$0")/.."

dc() { if docker info >/dev/null 2>&1; then docker compose "$@"; else sudo docker compose "$@"; fi; }

git fetch --quiet origin
local_rev="$(git rev-parse HEAD)"
remote_rev="$(git rev-parse '@{u}')"

if [ "$local_rev" = "$remote_rev" ] && [ "${1:-}" != "--force" ]; then
  echo "Already up to date (${local_rev:0:7})."
  exit 0
fi

echo "==> ${local_rev:0:7} -> ${remote_rev:0:7}"
git pull --ff-only
dc up -d --build
echo "==> migration log:"
dc logs migrate --tail=20 || true
dc ps
docker image prune -f >/dev/null 2>&1 || sudo docker image prune -f >/dev/null 2>&1 || true
echo "==> Updated: $(git rev-parse --short HEAD)"
