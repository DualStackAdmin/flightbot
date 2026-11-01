#!/usr/bin/env bash
# FlightBot: install on a Linux server (one command after cloning the repo).
#
#   git clone git@github.com:<you>/flightbot.git /opt/flightbot && cd /opt/flightbot
#   ./scripts/install.sh
#
# Non-interactive (CI/automation):  BOT_TOKEN=... [TRAVELPAYOUTS_TOKEN=...] ./scripts/install.sh
# Only create .env (test without Docker): INSTALL_DRY_RUN=1 BOT_TOKEN=123:abc ./scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

say()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

DRY_RUN="${INSTALL_DRY_RUN:-0}"

rand_hex() {
  if command -v openssl >/dev/null 2>&1; then openssl rand -hex 16
  else python3 -c 'import secrets; print(secrets.token_hex(16))'
  fi
}

set_env() {  # set_env KEY VALUE: replaces the KEY= line in .env (appends it if missing)
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//'; }

ask() {  # ask "question": prints nothing and returns an empty answer when there is no tty
  local prompt="$1" answer=""
  if [ -t 0 ]; then read -r -p "$prompt " answer || true; fi
  printf '%s' "$answer"
}

dc() {  # docker compose (via sudo if the user is not in the docker group)
  if docker info >/dev/null 2>&1; then docker compose "$@"; else sudo docker compose "$@"; fi
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then return 0; fi
  if [ "$DRY_RUN" = 1 ]; then warn "docker/compose not found (dry-run: skipping)"; return 0; fi
  command -v curl >/dev/null 2>&1 || die "curl is required (apt install curl)"
  say "Docker not found, installing it with the official script (get.docker.com)..."
  curl -fsSL https://get.docker.com | sh
  if [ "$(id -u)" -ne 0 ]; then
    sudo usermod -aG docker "$USER" || true
    warn "The user was added to the 'docker' group. It works without sudo after your next login."
  fi
  docker compose version >/dev/null 2>&1 || sudo docker compose version >/dev/null 2>&1 \
    || die "docker compose plugin not found"
}

# ---------------------------------------------------------------- .env
if [ -f .env ]; then
  say ".env already exists, leaving it untouched (delete it or edit it by hand to change it)"
else
  say "Creating .env"
  cp .env.example .env
  chmod 600 .env

  token="${BOT_TOKEN:-}"
  [ -n "$token" ] || token="$(ask 'Telegram BOT_TOKEN (from @BotFather):')"
  [ -n "$token" ] || die "BOT_TOKEN is required (BOT_TOKEN=... ./scripts/install.sh)"
  set_env BOT_TOKEN "$token"

  set_env POSTGRES_PASSWORD "$(rand_hex)"
  set_env REDIS_PASSWORD "$(rand_hex)"
  set_env WEBHOOK_SECRET "$(rand_hex)"
  set_env ENV prod

  tp="${TRAVELPAYOUTS_TOKEN:-}"
  if [ -z "$tp" ]; then tp="$(ask 'Travelpayouts API token (leave empty for DEMO mode: fake prices):')"; fi
  if [ -n "$tp" ]; then
    set_env PROVIDER travelpayouts
    set_env TRAVELPAYOUTS_TOKEN "$tp"
  else
    set_env PROVIDER fake
    warn "DEMO mode (PROVIDER=fake): prices are fake. For real data set TRAVELPAYOUTS_TOKEN in .env and run 'docker compose up -d'."
  fi
fi

[ -n "$(get_env BOT_TOKEN)" ] || die "BOT_TOKEN is empty in .env"
if [ -z "$(get_env REDIS_PASSWORD)" ] || [ "$(get_env REDIS_PASSWORD)" = "change-me" ]; then
  say "Adding a random REDIS_PASSWORD to .env (Redis now requires a password)"
  set_env REDIS_PASSWORD "$(rand_hex)"
fi
if [ "$(get_env POSTGRES_PASSWORD)" = "change-me" ]; then
  warn "POSTGRES_PASSWORD is still 'change-me'. For an existing database change it inside Postgres first (ALTER USER), then in .env."
fi

if [ "$DRY_RUN" = 1 ]; then
  say "DRY-RUN: .env is ready, Docker steps skipped."
  exit 0
fi

# ---------------------------------------------------------------- docker
ensure_docker
say "Building and starting containers (the first run can take a few minutes)..."
dc up -d --build

say "Checking health..."
for _ in $(seq 1 60); do
  if dc ps --format '{{.Service}} {{.Status}}' | grep -E '^(bot|worker) ' | grep -q 'healthy'; then
    ok=1; break
  fi
  sleep 3
done
dc ps
if [ "${ok:-0}" = 1 ]; then say "Ready. Send /start to your bot in Telegram."
else warn "Containers are not 'healthy' yet. Check the logs: docker compose logs -f bot worker"; fi

cat <<'MSG'

Useful commands:
  docker compose logs -f bot worker     # logs
  ./scripts/update.sh                   # update from GitHub
  docker compose exec worker python -m flightbot.cli stats
  docker compose exec worker python -m flightbot.cli grant-pro <telegram_id> --days 30
MSG
