# Cloudflare setup (recommended for webhook mode)

Goal: the server has **no inbound ports open to the internet** (except SSH, ideally restricted), its IP stays hidden,
and only Telegram can reach the webhook. Nothing in this guide was tested against a live Cloudflare account while
it was written; product names, dashboard paths and plan availability can change, so check the linked docs.

| Need | Cloudflare product | Why |
|---|---|---|
| Publish the webhook without opening ports or exposing the server IP | **Tunnel** (`cloudflared`) | outbound-only connection from the server to Cloudflare |
| Only Telegram may call the webhook, only `POST /telegram/webhook` | **WAF custom rules** | blocks scanners and direct abuse at the edge |
| Absorb floods | **DDoS protection** (on by default for proxied traffic) | |
| Private dashboards (Prometheus/Grafana), optional SSH | **Access** (Cloudflare One) | identity login in front of internal tools |

Docs: [Tunnel](https://developers.cloudflare.com/tunnel/) · [WAF custom rules](https://developers.cloudflare.com/waf/custom-rules/) ·
[Access](https://developers.cloudflare.com/cloudflare-one/access-controls/) · [DDoS](https://developers.cloudflare.com/ddos-protection/)

## 1. Domain on Cloudflare
Add your domain to Cloudflare (DNS managed by Cloudflare). Pick a hostname for the bot, e.g. `bot.example.com`.

## 2. Create the tunnel (remotely managed)
1. Cloudflare dashboard → Zero Trust / Networks → **Tunnels** → Create a tunnel → type *cloudflared*.
2. Copy the **tunnel token** into `.env`: `TUNNEL_TOKEN=...` (it is a secret: never commit it; rotate it if it leaks).
3. Add a **public hostname / published application route**:
   - Hostname: `bot.example.com`
   - Path: `^/telegram/webhook$` (only this path is routed; everything else returns 404 at the edge)
   - Service: `http://bot:8080` (the container name inside the Docker network)
4. In `.env`:
   ```
   BOT_MODE=webhook
   WEBHOOK_BASE_URL=https://bot.example.com
   WEBHOOK_SECRET=<long random, install.sh generates one>
   ```
5. Start: `docker compose --profile tunnel up -d`. Do **not** also start the `webhook` (Caddy) profile.

Telegram requires HTTPS with a valid certificate on port 443: the tunnel's public hostname provides that.
The bot verifies `X-Telegram-Bot-Api-Secret-Token` on every update (a wrong secret returns 401).

## 3. WAF custom rules (Security → WAF → Custom rules)
Replace `bot.example.com` and the path if you changed them.

**Rule A: only the webhook endpoint exists** (action: *Block*)
```
(http.host eq "bot.example.com" and not (http.request.uri.path eq "/telegram/webhook" and http.request.method eq "POST"))
```

**Rule B: only Telegram may call it** (action: *Block*)
```
(http.host eq "bot.example.com" and not ip.src in {149.154.160.0/20 91.108.4.0/22})
```
These are the subnets Telegram documents as the source of webhook requests. **Check Telegram's current Bot API docs
before enabling the rule**; if Telegram adds a range and the rule blocks it, updates stop arriving (watch
`getWebhookInfo` → `last_error_message`).

**Do not challenge the webhook.** Telegram cannot solve a JS challenge or CAPTCHA. If you enable Bot Fight Mode,
"Under Attack" mode or managed challenges on the zone, add a *Skip* rule for
`http.host eq "bot.example.com" and http.request.uri.path eq "/telegram/webhook" and ip.src in {149.154.160.0/20 91.108.4.0/22}`,
or keep this hostname out of those features.

Optional: a rate limiting rule on the webhook path (e.g. by IP). Telegram delivers updates from a few addresses at high
rates, so set it generously or skip it; the bot already throttles per user.

## 4. Server firewall
With the tunnel the server needs no inbound HTTP(S):
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from <your-ip> to any port 22 proto tcp   # or: sudo ufw allow 22/tcp
sudo ufw enable
```
Docker-published ports bypass `ufw`. That's why `docker-compose.yml` publishes nothing publicly (Prometheus is bound to
`127.0.0.1`). Keep it that way when you edit the file.

SSH: key-only login (`PasswordAuthentication no`), no root login. Optionally put SSH behind Cloudflare Access
(SSH through the tunnel) and close port 22 entirely; see the Access docs.

## 5. Dashboards with Access (optional)
To open Prometheus from the browser, add a second public hostname (e.g. `metrics.example.com` → `http://prometheus:9090`)
and protect it with an **Access application** (policy: your e-mail). Without Access, keep using an SSH tunnel:
`ssh -L 9090:127.0.0.1:9090 user@server`.

## 6. Checklist
- [ ] `getWebhookInfo` shows the tunnel URL and no `last_error_message`
- [ ] From any other IP, `curl -X POST https://bot.example.com/telegram/webhook` is blocked (403) and `/healthz` is 404/403
- [ ] `nmap <server-ip>` shows only SSH (or nothing)
- [ ] `TUNNEL_TOKEN`, `BOT_TOKEN`, `WEBHOOK_SECRET` exist only in `.env` (chmod 600) and in your password manager
