#!/usr/bin/env bash
# Layihəni GitHub-da QAPALI (private) repo kimi yaradıb push edir. Heç vaxt açıq repo yaratmır.
#
#   gh auth login                          # bir dəfə (brauzerlə, token yazmadan)
#   ./scripts/publish_to_github.sh         # repo adı: flightbot
#   ./scripts/publish_to_github.sh my-name
#
# Təhlükəsizlik yoxlamaları: .env / token izləndikdə, iş qovluğu çirkli olduqda və ya repo açıq olduqda DAYANIR.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

NAME="${1:-flightbot}"
command -v git >/dev/null 2>&1 || die "git lazımdır"
command -v gh  >/dev/null 2>&1 || die "GitHub CLI lazımdır (https://cli.github.com), sonra: gh auth login"
gh auth status >/dev/null 2>&1 || die "gh daxil olunmayıb: gh auth login"
git rev-parse --git-dir >/dev/null 2>&1 || die "git repo deyil"

say "Təhlükəsizlik yoxlaması (izlənən fayllar)"
if git ls-files | grep -Eq '(^|/)\.env$'; then die ".env izlənir! git rm --cached .env"; fi
if git grep -nEI '[0-9]{8,10}:[A-Za-z0-9_-]{35}' -- . ':!tests' ':!docs' >/dev/null 2>&1; then
  git grep -nEI '[0-9]{8,10}:[A-Za-z0-9_-]{35}' -- . ':!tests' ':!docs' | sed 's/:[A-Za-z0-9_-]\{35\}/:***/' >&2
  die "Telegram token oxşar sətir tapıldı. Əvvəlcə silin (və token sızıbsa BotFather-də /revoke edin)"
fi
[ -z "$(git status --porcelain)" ] || die "commit olunmamış dəyişiklik var: git add -A && git commit"

visibility() { gh repo view --json visibility -q .visibility 2>/dev/null || true; }

if git remote get-url origin >/dev/null 2>&1; then
  say "origin artıq var: $(git remote get-url origin)"
  vis="$(visibility)"
  [ "$vis" = "PRIVATE" ] || die "repo PRIVATE deyil (görünürlük: ${vis:-naməlum}). Push dayandırıldı."
  git push -u origin main
else
  say "Qapalı repo yaradılır: $NAME"
  gh repo create "$NAME" --private --source=. --remote=origin --push
  vis="$(visibility)"
  if [ "$vis" != "PRIVATE" ]; then
    say "Görünürlük '$vis': private-ə çevrilir"
    gh repo edit --visibility private --accept-visibility-change-consequences || true
    vis="$(visibility)"
    [ "$vis" = "PRIVATE" ] || die "Repo PRIVATE deyil! Dərhal GitHub-da Settings -> Danger Zone-dan qapadın."
  fi
fi

say "Hazırdır. Görünürlük: PRIVATE"
gh repo view --json url -q .url
echo "Serverdə klonlamaq üçün: docs/DEPLOY.md (deploy key)"
