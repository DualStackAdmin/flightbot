#!/usr/bin/env bash
# FlightBot: Linux serverdə quraşdırma (repo klonlandıqdan sonra bir əmr).
#
#   git clone git@github.com:<siz>/flightbot.git /opt/flightbot && cd /opt/flightbot
#   ./scripts/install.sh
#
# Qeyri-interaktiv (CI/avtomatlaşdırma):  BOT_TOKEN=... [TRAVELPAYOUTS_TOKEN=...] ./scripts/install.sh
# Yalnız .env yaratmaq (Docker-siz sınaq): INSTALL_DRY_RUN=1 BOT_TOKEN=123:abc ./scripts/install.sh
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

set_env() {  # set_env KEY VALUE: .env-də KEY= sətrini əvəz edir (yoxdursa əlavə edir)
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

get_env() { grep -E "^$1=" .env | head -n1 | cut -d= -f2- | sed 's/[[:space:]]*#.*$//'; }

ask() {  # ask "sual" DEĞİŞKƏN_ADI  (tty yoxdursa boş qaytarır)
  local prompt="$1" answer=""
  if [ -t 0 ]; then read -r -p "$prompt " answer || true; fi
  printf '%s' "$answer"
}

dc() {  # docker compose (istifadəçi docker qrupunda deyilsə sudo ilə)
  if docker info >/dev/null 2>&1; then docker compose "$@"; else sudo docker compose "$@"; fi
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then return 0; fi
  if [ "$DRY_RUN" = 1 ]; then warn "docker/compose tapılmadı (dry-run: keçilir)"; return 0; fi
  command -v curl >/dev/null 2>&1 || die "curl lazımdır (apt install curl)"
  say "Docker tapılmadı, rəsmi skriptlə quraşdırılır (get.docker.com)..."
  curl -fsSL https://get.docker.com | sh
  if [ "$(id -u)" -ne 0 ]; then
    sudo usermod -aG docker "$USER" || true
    warn "İstifadəçi 'docker' qrupuna əlavə olundu. Növbəti girişdən sonra sudo-suz işləyəcək."
  fi
  docker compose version >/dev/null 2>&1 || sudo docker compose version >/dev/null 2>&1 \
    || die "docker compose plugin tapılmadı"
}

# ---------------------------------------------------------------- .env
if [ -f .env ]; then
  say ".env artıq var, toxunulmur (yeniləmək üçün onu silin və ya əl ilə redaktə edin)"
else
  say ".env yaradılır"
  cp .env.example .env
  chmod 600 .env

  token="${BOT_TOKEN:-}"
  [ -n "$token" ] || token="$(ask 'Telegram BOT_TOKEN (@BotFather):')"
  [ -n "$token" ] || die "BOT_TOKEN lazımdır (BOT_TOKEN=... ./scripts/install.sh)"
  set_env BOT_TOKEN "$token"

  set_env POSTGRES_PASSWORD "$(rand_hex)"
  set_env WEBHOOK_SECRET "$(rand_hex)"
  set_env ENV prod

  tp="${TRAVELPAYOUTS_TOKEN:-}"
  if [ -z "$tp" ]; then tp="$(ask 'Travelpayouts API token (boş buraxsanız DEMO rejimi: saxta qiymətlər):')"; fi
  if [ -n "$tp" ]; then
    set_env PROVIDER travelpayouts
    set_env TRAVELPAYOUTS_TOKEN "$tp"
  else
    set_env PROVIDER fake
    warn "DEMO rejimi (PROVIDER=fake): qiymətlər saxtadır. Real data üçün .env-də TRAVELPAYOUTS_TOKEN təyin edib 'docker compose up -d' edin."
  fi
fi

[ -n "$(get_env BOT_TOKEN)" ] || die ".env-də BOT_TOKEN boşdur"

if [ "$DRY_RUN" = 1 ]; then
  say "DRY-RUN: .env hazırdır, Docker addımları keçildi."
  exit 0
fi

# ---------------------------------------------------------------- docker
ensure_docker
say "Konteynerlər qurulur və işə salınır (ilk dəfə bir neçə dəqiqə çəkə bilər)..."
dc up -d --build

say "Sağlamlıq yoxlanılır..."
for _ in $(seq 1 60); do
  if dc ps --format '{{.Service}} {{.Status}}' | grep -E '^(bot|worker) ' | grep -q 'healthy'; then
    ok=1; break
  fi
  sleep 3
done
dc ps
if [ "${ok:-0}" = 1 ]; then say "Hazırdır. Botunuza Telegram-da /start yazın."
else warn "Konteynerlər hələ 'healthy' olmayıb. Loglara baxın: docker compose logs -f bot worker"; fi

cat <<'MSG'

Faydalı əmrlər:
  docker compose logs -f bot worker     # loglar
  ./scripts/update.sh                   # GitHub-dan yeniləmə
  docker compose exec worker python -m flightbot.cli stats
  docker compose exec worker python -m flightbot.cli grant-pro <telegram_id> --days 30
MSG
