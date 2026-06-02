# Docker + PostgreSQL + CI/CD Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the `rental_track` Django app to the Ubuntu server (207.180.210.65 / rakhmonov-arenda.uz) on PostgreSQL via Docker Compose with HTTPS, then wire GitHub Actions so merging `main` → `production` auto-deploys.

**Architecture:** Single-VPS Docker Compose stack — `db` (postgres:16), `web` (Django+gunicorn), `cron` (supercronic), `nginx` (TLS reverse-proxy + static), `certbot` (Let's Encrypt renew). Build-on-server, no registry. Secrets live only in server `.env`. CI runs pytest against Postgres; CD deploys over SSH.

**Tech Stack:** Django 5.x / Python 3.12, PostgreSQL 16, Docker Compose, nginx + certbot, gunicorn, supercronic, GitHub Actions.

**Working branch:** `worktree-deploy-infra` (worktree off `origin/main` @ 5092ac1). Reference spec: [docs/superpowers/specs/2026-06-03-docker-postgres-deploy-cicd-design.md](../specs/2026-06-03-docker-postgres-deploy-cicd-design.md).

**Server facts:** user `rakhmonov` (sudo w/ password), Docker not installed, project at `~/hadware-raxmonov`, only :22 open. Cert: apex `rakhmonov-arenda.uz` only (no www). DB: fresh + new superuser.

---

## Phase 1 — Author infrastructure files (in worktree)

### Task 1: Settings — Postgres + production security

**Files:**
- Modify: `rental_track/settings.py` (DATABASES block + new security block)

- [ ] **Step 1: Replace the DATABASES block**

Replace:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```
with:
```python
# PostgreSQL in production (POSTGRES_DB set via env); SQLite for local dev.
if os.getenv('POSTGRES_DB'):
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB'),
            'USER': os.getenv('POSTGRES_USER', 'rental'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', ''),
            'HOST': os.getenv('POSTGRES_HOST', 'db'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
            'CONN_MAX_AGE': int(os.getenv('DB_CONN_MAX_AGE', '60')),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }
```

- [ ] **Step 2: Add production security block right after the `ALLOWED_HOSTS = [...]` list**

```python
# --- Production hardening (active only when DEBUG is off) ---
if not DEBUG:
    # nginx terminates TLS and forwards X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_TRUSTED_ORIGINS = [
        o.strip()
        for o in os.getenv(
            'DJANGO_CSRF_TRUSTED_ORIGINS', 'https://rakhmonov-arenda.uz'
        ).split(',')
        if o.strip()
    ]
```
> Do NOT set `SECURE_SSL_REDIRECT` — nginx already redirects 80→443; enabling it behind the proxy risks a redirect loop.

- [ ] **Step 3: Verify Python parses**

Run: `python -m py_compile rental_track/settings.py && echo OK`
Expected: `OK`

### Task 2: requirements.txt — add psycopg

**Files:** Modify: `requirements.txt`

- [ ] **Step 1: Append driver**

Add line: `psycopg[binary]>=3.1`

### Task 3: Dockerfile

**Files:** Create: `Dockerfile`

- [ ] **Step 1: Resolve the supercronic checksum**

Run: `curl -fsSL https://github.com/aptible/supercronic/releases/download/v0.2.33/supercronic-linux-amd64 | sha1sum`
Record the hash → use as `SUPERCRONIC_SHA1` below. (Cross-check against the checksum on the supercronic release page.)

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# DejaVu fonts (PDF Cyrillic), gettext (compilemessages), curl (supercronic)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-dejavu-core gettext curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# supercronic — container-friendly cron with full env inheritance
ARG SUPERCRONIC_VERSION=v0.2.33
ARG SUPERCRONIC_SHA1=PASTE_FROM_STEP_1
RUN curl -fsSL --retry 3 -o /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
    && echo "${SUPERCRONIC_SHA1}  /usr/local/bin/supercronic" | sha1sum -c - \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Compile ru/uz translations to .mo
RUN python manage.py compilemessages

RUN chmod +x deploy/entrypoint.sh deploy/deploy.sh

EXPOSE 8000
ENTRYPOINT ["deploy/entrypoint.sh"]
CMD ["gunicorn", "rental_track.wsgi:application", \
     "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", \
     "--access-logfile", "-", "--error-logfile", "-"]
```
> `SUPERCRONIC_SHA1` must be the real value from Step 1 — not the placeholder.

### Task 4: .dockerignore

**Files:** Create: `.dockerignore`

```
.git
.gitignore
venv/
.venv/
env/
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
.coveragerc
htmlcov/
db.sqlite3
db.sqlite3-journal
.env
.env.*
backups/
staticfiles/
media/
docs/
.claude/
.vscode/
.idea/
*.log
.DS_Store
```

### Task 5: docker-compose.prod.yml

**Files:** Create: `docker-compose.prod.yml`

```yaml
name: rental_track

services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  web:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - staticfiles:/app/staticfiles
    expose:
      - "8000"

  cron:
    build: .
    restart: unless-stopped
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    entrypoint: ["supercronic"]
    command: ["/app/deploy/crontab"]

  nginx:
    image: nginx:1.27-alpine
    restart: unless-stopped
    depends_on:
      - web
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./deploy/nginx/conf.d:/etc/nginx/conf.d:ro
      - staticfiles:/app/staticfiles:ro
      - certbot-etc:/etc/letsencrypt:ro
      - certbot-www:/var/www/certbot:ro
    command: ["/bin/sh", "-c", "while :; do sleep 6h & wait $${!}; nginx -s reload; done & nginx -g 'daemon off;'"]

  certbot:
    image: certbot/certbot
    restart: unless-stopped
    volumes:
      - certbot-etc:/etc/letsencrypt
      - certbot-www:/var/www/certbot
    entrypoint: ["/bin/sh", "-c", "trap exit TERM; while :; do certbot renew --webroot -w /var/www/certbot; sleep 12h & wait $${!}; done"]

volumes:
  pgdata:
  staticfiles:
  certbot-etc:
  certbot-www:
```
> `name: rental_track` fixes volume/network names. Service `certbot`'s custom entrypoint runs the renew loop; the one-off **issuance** must override entrypoint (see Phase 5). `cron` overrides BOTH entrypoint and command so the image CMD (gunicorn) is not appended to supercronic.

### Task 6: deploy/entrypoint.sh

**Files:** Create: `deploy/entrypoint.sh`

```sh
#!/usr/bin/env sh
set -e

echo "[entrypoint] migrate..."
python manage.py migrate --noinput

echo "[entrypoint] collectstatic..."
python manage.py collectstatic --noinput

echo "[entrypoint] exec: $*"
exec "$@"
```

### Task 7: deploy/deploy.sh

**Files:** Create: `deploy/deploy.sh`

```sh
#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=rental_track
COMPOSE="docker compose -f docker-compose.prod.yml"

mkdir -p deploy/nginx/conf.d

# Pick nginx config by whether a real cert exists (checked via certbot's mounted volume).
if $COMPOSE run --rm --no-deps --entrypoint sh certbot \
     -c 'test -f /etc/letsencrypt/live/rakhmonov-arenda.uz/fullchain.pem' >/dev/null 2>&1; then
  echo "[deploy] cert present -> SSL config"
  cp deploy/nginx/templates/app.ssl.conf deploy/nginx/conf.d/default.conf
else
  echo "[deploy] no cert -> bootstrap HTTP config"
  cp deploy/nginx/templates/app.http.conf deploy/nginx/conf.d/default.conf
fi

echo "[deploy] build & up..."
$COMPOSE up -d --build

# Pick up swapped default.conf without recreating nginx.
$COMPOSE exec -T nginx nginx -s reload >/dev/null 2>&1 || true

$COMPOSE ps
echo "[deploy] done."
```

### Task 8: deploy/provision.sh

**Files:** Create: `deploy/provision.sh`

```sh
#!/usr/bin/env bash
set -euo pipefail

DEPLOY_USER="${SUDO_USER:-rakhmonov}"

echo "==> [1/4] Docker CE + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
else
  echo "docker present: $(docker --version)"
fi

echo "==> [2/4] add ${DEPLOY_USER} to docker group"
usermod -aG docker "${DEPLOY_USER}"

echo "==> [3/4] ufw 22/80/443"
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH || ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status verbose
else
  echo "ufw absent; rely on provider firewall"
fi

echo "==> [4/4] 2GiB swap"
if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
else
  echo "swap present"
fi

echo "==> done. ${DEPLOY_USER} must re-login for docker group."
```

### Task 9: deploy/crontab

**Files:** Create: `deploy/crontab`

```
# rental_track scheduled tasks (supercronic; 5-field cron). Jobs inherit container env.
0 * * * * cd /app && python manage.py mark_overdue
5 * * * * cd /app && python manage.py notify_debtors
```

### Task 10: nginx config templates

**Files:**
- Create: `deploy/nginx/templates/app.http.conf`
- Create: `deploy/nginx/templates/app.ssl.conf`
- Create: `deploy/nginx/conf.d/.gitkeep` (empty)

- [ ] **Step 1: `app.http.conf` (bootstrap, pre-cert)**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name rakhmonov-arenda.uz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location /static/ {
        alias /app/staticfiles/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- [ ] **Step 2: `app.ssl.conf` (production)**

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name rakhmonov-arenda.uz;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name rakhmonov-arenda.uz;

    ssl_certificate     /etc/letsencrypt/live/rakhmonov-arenda.uz/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/rakhmonov-arenda.uz/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;

    client_max_body_size 25m;

    location /static/ {
        alias /app/staticfiles/;
        access_log off;
        expires 30d;
    }

    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Task 11: .gitignore + .env.prod.example

**Files:**
- Modify: `.gitignore`
- Create: `.env.prod.example`

- [ ] **Step 1: Append to `.gitignore`**

```
# Generated nginx active config
deploy/nginx/conf.d/default.conf
```

- [ ] **Step 2: Create `.env.prod.example`**

```
DJANGO_SECRET_KEY=GENERATE_ME
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=rakhmonov-arenda.uz,207.180.210.65
DJANGO_CSRF_TRUSTED_ORIGINS=https://rakhmonov-arenda.uz
POSTGRES_DB=rental_track
POSTGRES_USER=rental
POSTGRES_PASSWORD=GENERATE_ME
POSTGRES_HOST=db
POSTGRES_PORT=5432
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_IDS=
TELEGRAM_REMINDER_HOUR=9
```

### Task 12: GitHub Actions — CI

**Files:** Create: `.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DJANGO_SECRET_KEY: ci-secret-key
      DJANGO_DEBUG: "True"
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_HOST: localhost
      POSTGRES_PORT: "5432"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: python -m pip install --upgrade pip && pip install -r requirements.txt
      - run: python manage.py migrate --noinput
      - run: pytest
```
> Verify `pytest.ini` sets `DJANGO_SETTINGS_MODULE = rental_track.settings`. If not, add `--ds=rental_track.settings` to the pytest step.

### Task 13: GitHub Actions — Deploy

**Files:** Create: `.github/workflows/deploy.yml`

```yaml
name: Deploy

on:
  push:
    branches: [production]

concurrency:
  group: production-deploy
  cancel-in-progress: false

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy over SSH
        uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.DEPLOY_HOST }}
          username: ${{ secrets.DEPLOY_USER }}
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          port: ${{ secrets.DEPLOY_PORT }}
          script_stop: true
          script: |
            set -e
            cd ~/hadware-raxmonov
            git fetch origin
            git checkout production
            git reset --hard origin/production
            ./deploy/deploy.sh
```

### Task 14: docs/DEPLOYMENT.md (operations runbook)

**Files:** Create: `docs/DEPLOYMENT.md`

Write a runbook covering: provisioning (`sudo bash deploy/provision.sh`), creating server `.env`, first deploy sequence (Phase 5), cert issuance command, `createsuperuser`, GitHub secrets setup (Phase 6 steps), routine deploy (merge `main`→`production`), rollback (`git reset` + redeploy), DB backup (`docker compose exec db pg_dump`), supercronic→host-cron fallback, and the credential-rotation reminder.

### Task 15: Commit Phase 1

- [ ] Run from worktree:
```bash
git add -A
git commit -m "feat(deploy): Docker + PostgreSQL + nginx/TLS + CI/CD infrastructure"
```

---

## Phase 2 — Local pre-flight (if Docker available locally)

### Task 16: Validate the image before pushing

- [ ] **Step 1: Check local Docker**

Run: `docker version >/dev/null 2>&1 && echo HAVE_DOCKER || echo NO_DOCKER`
If `NO_DOCKER`, skip Phase 2 — CI + server build will validate instead.

- [ ] **Step 2: Build the image**

Run: `docker build -t rental_track:preflight .`
Expected: build succeeds (apt, pip, supercronic checksum OK, compilemessages OK).

- [ ] **Step 3: Django check with prod-like env (no DB needed)**

Run:
```bash
docker run --rm -e DJANGO_DEBUG=False -e DJANGO_SECRET_KEY=x \
  -e DJANGO_ALLOWED_HOSTS=rakhmonov-arenda.uz \
  -e POSTGRES_DB=rental_track --entrypoint python rental_track:preflight \
  manage.py check --deploy
```
Expected: no blocking errors (security warnings about SSL_REDIRECT are acceptable/expected).

---

## Phase 3 — Publish code to GitHub

### Task 17: Push infra branch and update main

- [ ] **Step 1: Push the worktree branch**

Run: `git push -u origin worktree-deploy-infra`

- [ ] **Step 2: Fast-forward `origin/main` with the infra commit**

The infra branch is `origin/main` + one commit, so this is a clean fast-forward (no local-main commits, no WIP included):
```bash
git push origin worktree-deploy-infra:main
```
Expected: `origin/main` advances by exactly the infra commit. Verify:
`git log --oneline origin/main -2`

- [ ] **Step 3: Create and push `production` from the new main**

```bash
git push origin worktree-deploy-infra:production
```
Expected: `origin/production` created at the same commit as `origin/main`.

> After this, the user's local `main` (5 print commits) diverges from `origin/main`. Reconciliation shown in Phase 7.

---

## Phase 4 — Provision the server (sudo)

### Task 18: Copy and run provisioning

- [ ] **Step 1: Update the server checkout to production**

Run:
```bash
ssh rakhmonov 'cd ~/hadware-raxmonov && git fetch origin && git checkout production && git reset --hard origin/production && ls deploy/'
```
Expected: `deploy/` lists provision.sh, deploy.sh, entrypoint.sh, crontab, nginx/.

- [ ] **Step 2: Run provisioning with sudo (password via stdin, once)**

Run (password supplied by user; appears once):
```bash
ssh rakhmonov 'cd ~/hadware-raxmonov && echo "<SUDO_PASS>" | sudo -S -p "" bash deploy/provision.sh'
```
Expected: Docker installed, user added to docker group, ufw enabled (22/80/443), swap on.

- [ ] **Step 3: Re-login so docker group applies; verify docker works without sudo**

Run: `ssh rakhmonov 'docker run --rm hello-world && docker compose version'`
Expected: hello-world runs; compose version prints. (A fresh SSH session picks up the new group.)

---

## Phase 5 — First deploy + certificate + superuser

### Task 19: Create server `.env`

- [ ] **Step 1: Generate secrets and write `.env`** (values never committed)

Run:
```bash
ssh rakhmonov 'cd ~/hadware-raxmonov && \
  SK=$(python3 -c "import secrets;print(secrets.token_urlsafe(50))") && \
  PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))") && \
  umask 077 && cat > .env <<EOF
DJANGO_SECRET_KEY=$SK
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=rakhmonov-arenda.uz,207.180.210.65
DJANGO_CSRF_TRUSTED_ORIGINS=https://rakhmonov-arenda.uz
POSTGRES_DB=rental_track
POSTGRES_USER=rental
POSTGRES_PASSWORD=$PW
POSTGRES_HOST=db
POSTGRES_PORT=5432
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_IDS=
TELEGRAM_REMINDER_HOUR=9
EOF
echo "wrote .env (mode $(stat -c %a .env))"'
```
Expected: `wrote .env (mode 600)`.

### Task 20: Bootstrap deploy (HTTP) and verify app

- [ ] **Step 1: First deploy (no cert yet → HTTP config)**

Run: `ssh rakhmonov 'cd ~/hadware-raxmonov && ./deploy/deploy.sh'`
Expected: images build; `db`/`web`/`cron`/`nginx`/`certbot` up; `web` ran migrate+collectstatic.

- [ ] **Step 2: Verify app over HTTP**

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://rakhmonov-arenda.uz/`
Expected: `302` (redirect to /login/). If 502 → check `ssh rakhmonov 'cd ~/hadware-raxmonov && docker compose -f docker-compose.prod.yml logs web | tail'`.

### Task 21: Issue Let's Encrypt certificate

- [ ] **Step 1: Issue cert (webroot, apex only)**

Run (email = user's email):
```bash
ssh rakhmonov 'cd ~/hadware-raxmonov && \
  COMPOSE_PROJECT_NAME=rental_track docker compose -f docker-compose.prod.yml run --rm \
  --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d rakhmonov-arenda.uz --email <EMAIL> --agree-tos --no-eff-email'
```
Expected: "Successfully received certificate" at `/etc/letsencrypt/live/rakhmonov-arenda.uz/`.

- [ ] **Step 2: Re-deploy to switch to SSL config**

Run: `ssh rakhmonov 'cd ~/hadware-raxmonov && ./deploy/deploy.sh'`
Expected: `[deploy] cert present -> SSL config`; nginx serves 443.

- [ ] **Step 3: Verify HTTPS + redirect**

Run:
```bash
curl -s -o /dev/null -w "http=%{http_code}\n" http://rakhmonov-arenda.uz/      # expect 301
curl -s -o /dev/null -w "https=%{http_code}\n" https://rakhmonov-arenda.uz/    # expect 302
```

### Task 22: Create superuser

- [ ] **Step 1: Create the admin** (credentials from user)

Run:
```bash
ssh -t rakhmonov 'cd ~/hadware-raxmonov && \
  docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser'
```
Expected: interactive prompt; account created.

- [ ] **Step 2: Smoke test login + admin**

Verify in browser: `https://rakhmonov-arenda.uz/login/` loads over HTTPS and login succeeds (CSRF works behind proxy); `https://rakhmonov-arenda.uz/admin/` loads with valid Let's Encrypt cert.

---

## Phase 6 — CI/CD wiring

### Task 23: Dedicated CI→server deploy key

- [ ] **Step 1: Generate keypair locally (no passphrase)**

Run: `ssh-keygen -t ed25519 -f /tmp/ci_deploy -N "" -C "github-actions-deploy"`

- [ ] **Step 2: Install public key on server**

Run: `cat /tmp/ci_deploy.pub | ssh rakhmonov 'cat >> ~/.ssh/authorized_keys && echo added'`
Expected: `added`.

- [ ] **Step 3: Test the key**

Run: `ssh -i /tmp/ci_deploy -o IdentitiesOnly=yes rakhmonov 'echo ci-key-ok'`
Expected: `ci-key-ok`.

### Task 24: User adds GitHub secrets (provide exact values)

Print the four secret values for the user, then they add them at
`https://github.com/Rakhmatullo929/hadware-raxmonov/settings/secrets/actions`:

| Secret | Value |
|--------|-------|
| `DEPLOY_HOST` | `207.180.210.65` |
| `DEPLOY_USER` | `rakhmonov` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_SSH_KEY` | full contents of `/tmp/ci_deploy` (private key, incl. BEGIN/END lines) |

- [ ] Confirm with user that all four secrets are saved. Then `rm -f /tmp/ci_deploy /tmp/ci_deploy.pub` locally.

### Task 25: End-to-end CD test

- [ ] **Step 1: Trigger a no-op deploy** (push a trivial commit to production, or re-run via empty change)

```bash
git commit --allow-empty -m "ci: verify production auto-deploy"
git push origin worktree-deploy-infra:production
```

- [ ] **Step 2: Watch the Deploy workflow**

In GitHub → Actions → "Deploy" run completes green. Server re-pulled production and re-ran `deploy.sh`.

- [ ] **Step 3: Confirm CI runs on main**

The "CI" workflow ran for the push to main (Phase 3) — confirm it is green; if red, read logs and fix tests against Postgres.

---

## Phase 7 — Hardening & handoff

### Task 26: Reconcile the user's local main divergence

- [ ] Show the user (do not run without consent) how to rebase their 5 local print commits + WIP onto the new origin/main:
```bash
git stash -u                  # park the 23 WIP files
git fetch origin
git rebase origin/main        # replay the 5 print commits on top of infra
git stash pop                 # restore WIP
```

### Task 27: Security follow-ups

- [ ] Remind user to **rotate** the root and `rakhmonov` passwords (shared in chat).
- [ ] Offer to set SSH key-only auth and disable password/root login (`PasswordAuthentication no`, `PermitRootLogin no`), only after confirming key login works.
- [ ] Note: provider firewall (Contabo) — ensure 80/443 allowed there too if any external firewall exists.

### Task 28: Finish the branch

- [ ] Invoke superpowers:finishing-a-development-branch to merge the infra branch cleanly (PR vs direct), since origin/main already advanced this is mostly cleanup + worktree removal.

---

## Self-Review

**Spec coverage:** §4 architecture → Tasks 5–10; §5.1 settings → Task 1; §5.2 psycopg → Task 2; §5.3 files → Tasks 3–14; §6 artifacts → Tasks 3,5–11; §7 provisioning → Task 8/18; §8 first-deploy runbook → Phase 5; §9 CI/CD → Tasks 12,13,23–25; §10 git strategy → Phase 3 + Task 26; §11 testing → Tasks 16,20,21,22,25; §12 rollback → Task 14 (runbook) + Task 28; §13 security → Tasks 1,19,27; §15 user items → Tasks 18 (sudo), 21 (apex-only), 24 (secrets), 22 (superuser). No gaps.

**Placeholder scan:** `<SUDO_PASS>`, `<EMAIL>`, `PASTE_FROM_STEP_1`, `GENERATE_ME` are intentional runtime/secret inputs with explicit resolution steps — not unresolved TODOs. No vague "add error handling"/"write tests" placeholders.

**Type/name consistency:** `COMPOSE_PROJECT_NAME=rental_track` and compose `name: rental_track` match; volume `certbot-etc`/`certbot-www`/`staticfiles`/`pgdata` names consistent across compose, deploy.sh, nginx, cert issuance; cert path `/etc/letsencrypt/live/rakhmonov-arenda.uz/fullchain.pem` identical in deploy.sh, app.ssl.conf, and Task 21 check; `deploy/nginx/templates/*` → `deploy/nginx/conf.d/default.conf` consistent between Task 10, compose mount, and deploy.sh.
