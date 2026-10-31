#!/usr/bin/env bash
# Create a PRIVATE GitHub repo for this project and push it. Never creates a public repo.
#
#   gh auth login                          # once (in the browser, no token pasting)
#   ./scripts/publish_to_github.sh         # repo name: flightbot
#   ./scripts/publish_to_github.sh my-name
#
# Safety checks: it STOPS if .env or a token is tracked, if the working tree is dirty, or if the repo is public.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

NAME="${1:-flightbot}"
command -v git >/dev/null 2>&1 || die "git is required"
command -v gh  >/dev/null 2>&1 || die "GitHub CLI is required (https://cli.github.com), then: gh auth login"
gh auth status >/dev/null 2>&1 || die "gh is not logged in: gh auth login"
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository"

say "Safety check (tracked files)"
if git ls-files | grep -Eq '(^|/)\.env$'; then die ".env is tracked! git rm --cached .env"; fi
if git grep -nEI '[0-9]{8,10}:[A-Za-z0-9_-]{35}' -- . ':!tests' ':!docs' >/dev/null 2>&1; then
  git grep -nEI '[0-9]{8,10}:[A-Za-z0-9_-]{35}' -- . ':!tests' ':!docs' | sed 's/:[A-Za-z0-9_-]\{35\}/:***/' >&2
  die "Found a Telegram-token-like string. Remove it first (and if a token leaked, /revoke it in BotFather)"
fi
[ -z "$(git status --porcelain)" ] || die "uncommitted changes: git add -A && git commit"

visibility() { gh repo view --json visibility -q .visibility 2>/dev/null || true; }

if git remote get-url origin >/dev/null 2>&1; then
  say "origin already exists: $(git remote get-url origin)"
  vis="$(visibility)"
  [ "$vis" = "PRIVATE" ] || die "repo is not PRIVATE (visibility: ${vis:-unknown}). Push aborted."
  git push -u origin main
else
  say "Creating private repo: $NAME"
  gh repo create "$NAME" --private --source=. --remote=origin --push
  vis="$(visibility)"
  if [ "$vis" != "PRIVATE" ]; then
    say "Visibility is '$vis': switching to private"
    gh repo edit --visibility private --accept-visibility-change-consequences || true
    vis="$(visibility)"
    [ "$vis" = "PRIVATE" ] || die "Repo is NOT private! Close it right now: GitHub Settings -> Danger Zone."
  fi
fi

say "Done. Visibility: PRIVATE"
gh repo view --json url -q .url
echo "To clone on a server see docs/DEPLOY.md (deploy key)"
