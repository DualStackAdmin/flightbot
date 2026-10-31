# GitHub (qapalı repo) və Linux serverə quraşdırma

## 1. GitHub-da qapalı (private) repo
Layihə `git` repo kimi hazırdır (`main` branch, ilk commit). Öz kompüterinizdə:
```bash
unzip flightbot.zip && cd flightbot
git log --oneline            # ilk commit görünməlidir
# Variant A: GitHub CLI (tövsiyə olunan)
gh auth login
gh repo create flightbot --private --source=. --remote=origin --push
# Variant B: GitHub saytında BOŞ private repo yaradın (README/.gitignore əlavə ETMƏYİN), sonra:
git remote add origin git@github.com:<siz>/flightbot.git
git push -u origin main
```
İlk commit-in müəllifi ümumi addır; öz adınızla etmək üçün: `git commit --amend --reset-author --no-edit && git push -f` (yalnız ilk push-dan əvvəl/dərhal sonra, tək istifadəçi repo-sunda).
`.env` `.gitignore`-dadır, **tokenlər heç vaxt repo-ya düşmür**.

## 2. Linux serverə ilk quraşdırma
Server üçün repo-ya yalnız oxuma icazəsi olan **deploy key** yaradın:
```bash
ssh-keygen -t ed25519 -f ~/.ssh/flightbot_deploy -N "" -C "flightbot-server"
cat ~/.ssh/flightbot_deploy.pub     # GitHub repo -> Settings -> Deploy keys -> Add (Allow write access SEÇMƏYİN)
cat >> ~/.ssh/config <<'CFG'
Host github-flightbot
  HostName github.com
  User git
  IdentityFile ~/.ssh/flightbot_deploy
  IdentitiesOnly yes
CFG
sudo mkdir -p /opt/flightbot && sudo chown "$USER" /opt/flightbot
git clone git@github-flightbot:<siz>/flightbot.git /opt/flightbot
cd /opt/flightbot && ./scripts/install.sh
```
`install.sh`: Docker yoxdursa quraşdırır, `.env` yaradır (parol və webhook secret təsadüfi, `chmod 600`), `BOT_TOKEN` və (istəyə görə)
Travelpayouts token soruşur, `docker compose up -d --build` işlədir və sağlamlığı yoxlayır.
Qeyri-interaktiv: `BOT_TOKEN=... TRAVELPAYOUTS_TOKEN=... ./scripts/install.sh`.

Alternativ: serverdə `gh auth login` edib `gh repo clone <siz>/flightbot`.

## 3. Yeniləmə
```bash
cd /opt/flightbot && ./scripts/update.sh     # git pull --ff-only + yenidən qur + miqrasiya + köhnə image-ləri təmizlə
```
**Avtomatik deploy (könüllü):** `.github/workflows/deploy.yml` main-ə push və CI uğurlu olandan sonra serverdə `update.sh` işlədir.
Repo -> Settings -> Secrets and variables -> Actions: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (CI-nin serverə girişi üçün **ayrı** SSH açarı),
`DEPLOY_PATH` (`/opt/flightbot`). Secret-lər yoxdursa job səssizcə keçilir. Bu workflow hələ real serverdə sınanmayıb.

**Geri qayıtma:** `git checkout <əvvəlki-commit> && docker compose up -d --build`. Diqqət: miqrasiyalar irəli yönlüdür; sxem dəyişən
buraxılışı geri alanda `docker compose run --rm migrate alembic downgrade -1` lazım ola bilər (əvvəlcə backup).

## 4. Dəyişiklikləri GitHub-a necə çatdırmaq
Bu söhbətdə mən GitHub-a **push edə bilmirəm** (hesabınıza girişim yoxdur və tokeni söhbətə yazmağınız təhlükəsizdir deyil).
Seçimlər:
1. **Yeniləmə paketi:** hər dəyişiklikdən sonra sizə `.patch` fayl (və ya yeni zip) verirəm: `git apply update.patch && git commit -am "..." && git push`.
   Əvvəlcə GitHub-da öz əlinizlə dəyişiklik etsəniz, patch toqquşa bilər.
2. **Claude Code:** kompüterinizdə repo qovluğunda Claude Code işlədin: kodu birbaşa repo-da dəyişir, test edir və commit/push edə bilir,
   yəni yükləmə addımı olmur. Qurulum üçün Anthropic-in rəsmi sənədinə baxın.
