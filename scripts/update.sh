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
# v0.3.1+: Redis requires a password. Older .env files don't have one yet.
if ! grep -qE '^REDIS_PASSWORD=.+' .env; then
  pw="$(openssl rand -hex 16 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(16))')"
  printf 'REDIS_PASSWORD=%s\n' "$pw" >> .env
  echo "==> added a random REDIS_PASSWORD to .env"
fi
dc up -d --build
echo "==> migration log:"
dc logs migrate --tail=20 || true
dc ps
docker image prune -f >/dev/null 2>&1 || sudo docker image prune -f >/dev/null 2>&1 || true
echo "==> Updated: $(git rev-parse --short HEAD)"
