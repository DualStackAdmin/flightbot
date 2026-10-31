# Private GitHub repo and Linux server setup

## 1. A private GitHub repo
The project is a ready-made `git` repository (`main` branch, tagged `v0.2.0`). On your own machine:
```bash
unzip flightbot.zip && cd flightbot
git log --oneline            # the first commits should be visible
# Option A: GitHub CLI (recommended). Creates the repo PRIVATE and refuses to continue if it is public:
gh auth login
./scripts/publish_to_github.sh          # or: gh repo create flightbot --private --source=. --remote=origin --push
# Option B: create an EMPTY private repo on github.com (do NOT add a README/.gitignore), then:
git remote add origin git@github.com:<you>/flightbot.git
git push -u origin main --tags
```
The commit author is a generic name; to use your own run `git commit --amend --reset-author --no-edit && git push -f`
(only right before/after the first push, and only on a single-user repo).
`.env` is in `.gitignore`, so **tokens never reach the repo**.

## 2. First install on a Linux server
Create a **read-only deploy key** for the server:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/flightbot_deploy -N "" -C "flightbot-server"
cat ~/.ssh/flightbot_deploy.pub     # GitHub repo -> Settings -> Deploy keys -> Add (do NOT tick "Allow write access")
cat >> ~/.ssh/config <<'CFG'
Host github-flightbot
  HostName github.com
  User git
  IdentityFile ~/.ssh/flightbot_deploy
  IdentitiesOnly yes
CFG
sudo mkdir -p /opt/flightbot && sudo chown "$USER" /opt/flightbot
git clone git@github-flightbot:<you>/flightbot.git /opt/flightbot
cd /opt/flightbot && ./scripts/install.sh
```
`install.sh` installs Docker if missing, creates `.env` (random password and webhook secret, `chmod 600`), asks for `BOT_TOKEN` and (optionally) the Travelpayouts token,
runs `docker compose up -d --build` and checks health. Non-interactive: `BOT_TOKEN=... TRAVELPAYOUTS_TOKEN=... ./scripts/install.sh`.

Alternative: run `gh auth login` on the server and `gh repo clone <you>/flightbot`.

## 3. Updating
```bash
cd /opt/flightbot && ./scripts/update.sh     # git pull --ff-only + rebuild + migrations + prune old images
```
**Automatic deploy (optional):** `.github/workflows/deploy.yml` runs `update.sh` on the server after a push to main and a green CI run.
Repo -> Settings -> Secrets and variables -> Actions: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (a **separate** SSH key for CI to log in to the server),
`DEPLOY_PATH` (`/opt/flightbot`). If the secrets are missing the job is skipped silently. This workflow has not been tested on a real server yet.

**Rolling back:** `git checkout <previous-commit> && docker compose up -d --build`. Caution: migrations are forward-only; when rolling back a release that changed the schema you may need
`docker compose run --rm migrate alembic downgrade -1` (take a backup first).

## 4. Getting changes into GitHub
The assistant that generated this project cannot push to your GitHub (it has no access to your account, and pasting a token into a chat is unsafe). Options:
1. **Update bundle:** after each change you receive a `.patch` file (or a new zip): `git apply update.patch && git commit -am "..." && git push`.
   If you edited the repo on GitHub in the meantime, the patch may conflict.
2. **Claude Code:** run Claude Code in the repo directory on your machine: it edits the code directly, tests it, and can commit/push, so there is no download step.
   See Anthropic's official documentation for setup.

## 5. Before making the repo public
- Pick a license (replace `LICENSE`) and update the README status note.
- Replace or empty the affiliate marker in `.env.example` and the `travelpayouts_marker` default in `config.py`, otherwise forks earn commissions for your partner ID.
- Re-scan the git history for tokens (`git log -p | grep -E '[0-9]{8,10}:[A-Za-z0-9_-]{35}'`) and rotate anything that ever leaked.
- Review the legal items in `docs/LAUNCH_CHECKLIST.md` (privacy policy, terms, partner-program terms).
