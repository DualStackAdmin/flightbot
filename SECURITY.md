# Security

## Reporting
The repository is private. Report a suspected vulnerability directly to the owner; do not open a public issue.
If a secret leaks, **rotate it first** (BotFather `/revoke`, a new Travelpayouts token, a new tunnel token,
`WEBHOOK_SECRET`, database passwords), then clean up.

## Threat model (short)
**Assets:** the Telegram bot token, provider token, tunnel token, user data (Telegram ID, settings, watches),
affiliate attribution, the server.
**Entry points:** Telegram updates (webhook or polling), callback data from buttons, provider API responses,
the server (SSH), CI/CD secrets, the GitHub repository.

## Controls in place
- Webhook requests must carry `X-Telegram-Bot-Api-Secret-Token` (401 otherwise; tested).
- Every callback that touches a watch or notification checks ownership; button values (prices, indexes, dates,
  stays) are re-validated server-side because callback data can be forged by modified clients.
- All SQL is parameterized; all provider/user-derived text in messages is HTML-escaped.
- Per-user throttling of updates, and a per-user budget for provider-heavy actions (`/search`, `/explore`).
- Secrets are redacted from logs and Sentry events (including tracebacks: Telegram API URLs contain the bot token).
- Booking buttons only use provider links on trusted hosts (`aviasales.com`, `aviasales.ru`) over HTTPS.
- Docker: no publicly published ports; Postgres and Redis require passwords; app containers are read-only,
  non-root, with all capabilities dropped and `no-new-privileges`.
- `.env` is git-ignored and created with `chmod 600`; `publish_to_github.sh` refuses to push tracked secrets or to a public repo.
- CI runs with read-only repository permissions; the deploy workflow can pin the server's SSH host key.
- `/delete` erases a user's data.

## v0.3.1 review: findings and fixes
| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | The bot's port 8080 was published on all interfaces, so the webhook and `/healthz` were reachable directly, bypassing TLS | `expose` only (Docker network); public access only via Cloudflare Tunnel or Caddy |
| 2 | High | Prometheus was published on `0.0.0.0:9090` without authentication | bound to `127.0.0.1`; use an SSH tunnel or Cloudflare Access |
| 3 | High | Secrets could reach logs/Sentry through exception messages (Telegram API URLs contain the bot token) | redaction processor for logs and Sentry `before_send` |
| 4 | Medium | `POSTGRES_PASSWORD` silently fell back to `flightbot` | required; `install.sh` generates a random one |
| 5 | Medium | Redis had no password | `requirepass` with a random `REDIS_PASSWORD` (`install.sh`/`update.sh` add it to old `.env` files) |
| 6 | Medium | Target prices from buttons were trusted (a forged value could set huge targets) | range validation for target buttons |
| 7 | Medium | Absolute links from the provider were put into buttons unchecked (phishing vector if the API is compromised) | host allowlist + HTTPS; otherwise our own search URL |
| 8 | Medium | No per-user limit on provider-heavy actions (one user/script could burn the shared API quota) | per-user token bucket for `/search` and `/explore` (`SEARCH_BURST`, `SEARCH_PER_MINUTE`) |
| 9 | Low | Containers ran with default capabilities and a writable filesystem | read-only, `cap_drop: ALL`, `no-new-privileges`, tmpfs `/tmp` |
| 10 | Low | Caddy proxied every path (incl. `/healthz`) | only `POST /telegram/webhook` is proxied |
| 11 | Low | CI used default token permissions; deploy trusted the host key on first use | `permissions: contents: read`; optional `DEPLOY_KNOWN_HOSTS` |
| 12 | Ops | A GitHub token was shared in a chat during setup | must be revoked (GitHub → Settings → Developer settings → Tokens) |

## Not done yet (recommended)
- **Dependency pinning:** add a lock file (e.g. `pip-tools`/`uv`) and pin base images by digest; Dependabot is already enabled.
- **Pin `cloudflared`** to a specific version tag in `docker-compose.yml` (currently `latest`, marked TODO).
- **Docker secrets** instead of environment variables for tokens (env vars are visible to `docker inspect`).
- **2FA** on GitHub, Cloudflare, the Telegram account that owns the bot, Travelpayouts and the server provider.
- **Encrypted, off-site Postgres backups** and a tested restore.
- Verify the Telegram webhook IP ranges before enabling the WAF allowlist rule (docs/CLOUDFLARE.md).
