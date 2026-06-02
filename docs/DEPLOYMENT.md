# Deployment & Operations Runbook — rental_track

Production runs on a single Ubuntu 24.04 server (`207.180.210.65`,
`rakhmonov-arenda.uz`) as a Docker Compose stack:

| Service | Image | Role |
|---------|-------|------|
| `db` | postgres:16-alpine | PostgreSQL (volume `pgdata`, not exposed) |
| `web` | built from `Dockerfile` | Django + gunicorn; entrypoint runs migrate + collectstatic |
| `cron` | same image | `supercronic` runs `mark_overdue`/`notify_debtors` |
| `nginx` | nginx:1.27-alpine | TLS reverse-proxy, serves `/static/`, 80→443 |
| `certbot` | certbot/certbot | Let's Encrypt issuance + renew loop |

All commands run from `~/hadware-raxmonov` on the server as user `rakhmonov`
(member of the `docker` group, so no `sudo` for docker). Compose project name
is pinned to `rental_track` (stable volume names like `rental_track_pgdata`).

`COMPOSE="docker compose -f docker-compose.prod.yml"`

---

## 1. One-time server provisioning (sudo)

```bash
cd ~/hadware-raxmonov
sudo bash deploy/provision.sh
```
Installs Docker CE + compose plugin, adds `rakhmonov` to the `docker` group,
enables `ufw` (22/80/443), and adds 2 GiB swap. **Log out and back in** so the
docker group applies, then verify: `docker run --rm hello-world`.

## 2. Server `.env` (secrets — never committed)

Create `~/hadware-raxmonov/.env` from `.env.prod.example` with generated
secrets (mode 600):
```bash
SK=$(python3 -c "import secrets;print(secrets.token_urlsafe(50))")
PW=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
umask 077
cat > .env <<EOF
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
```
To enable Telegram debtor reminders later, set `TELEGRAM_BOT_TOKEN` (a fresh
token from @BotFather — the old one is considered compromised) and
`TELEGRAM_ADMIN_CHAT_IDS`, then `docker compose -f docker-compose.prod.yml up -d cron`.

## 3. First deploy + TLS certificate

```bash
git checkout production && git reset --hard origin/production

# 3a. Bootstrap over HTTP (no cert yet) and verify the app responds.
./deploy/deploy.sh
curl -s -o /dev/null -w "%{http_code}\n" http://rakhmonov-arenda.uz/   # expect 302

# 3b. Issue the certificate (apex only). NOTE: --entrypoint certbot overrides
#     the renew-loop entrypoint of the certbot service.
COMPOSE_PROJECT_NAME=rental_track docker compose -f docker-compose.prod.yml run --rm \
  --entrypoint certbot certbot certonly --webroot -w /var/www/certbot \
  -d rakhmonov-arenda.uz --email YOUR_EMAIL --agree-tos --no-eff-email

# 3c. Re-deploy: deploy.sh now selects the SSL config and serves HTTPS.
./deploy/deploy.sh
curl -s -o /dev/null -w "%{http_code}\n" https://rakhmonov-arenda.uz/   # expect 302
```

## 4. Create the admin user

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

## 5. Routine deploys (CI/CD)

Day-to-day you never SSH in. The flow:

1. Merge feature work into `main` (CI runs pytest against Postgres).
2. Open a PR `main` → `production` and merge it (or push `main` to `production`).
3. The **Deploy** GitHub Action SSHes to the server and runs `deploy/deploy.sh`,
   which rebuilds and restarts the stack. Migrations run automatically in the
   `web` entrypoint.

Required GitHub Actions secrets (Settings → Secrets and variables → Actions):
`DEPLOY_HOST=207.180.210.65`, `DEPLOY_USER=rakhmonov`, `DEPLOY_PORT=22`,
`DEPLOY_SSH_KEY=<private key of the dedicated CI deploy keypair>`.

## 6. Common operations

```bash
$COMPOSE ps                        # status
$COMPOSE logs -f web               # app logs
$COMPOSE logs -f nginx             # proxy/TLS logs
$COMPOSE exec web python manage.py <cmd>
$COMPOSE restart web
$COMPOSE down                      # stop (keeps volumes/data)
```

## 7. Database backup & restore

```bash
# Backup
$COMPOSE exec -T db pg_dump -U rental rental_track > backup_$(date +%F).sql
# Restore (DANGER: overwrites)
cat backup.sql | $COMPOSE exec -T db psql -U rental -d rental_track
```
Take a backup before any risky migration. Off-site/automated backups are not
configured yet (future work).

## 8. Rollback

```bash
git checkout production
git reset --hard <previous-good-commit>
git push --force-with-lease origin production   # triggers redeploy
# or on the server directly:
./deploy/deploy.sh
```

## 9. Certificate renewal

The `certbot` service auto-renews every 12h; `nginx` reloads every 6h to pick
up renewed certs. Force a renew test:
`$COMPOSE run --rm --entrypoint certbot certbot renew --dry-run`.

## 10. Cron fallback

Scheduled tasks run in the `cron` service via supercronic (jobs inherit the
container env). If that service ever misbehaves, an equivalent host-cron line
works because the `web` container already has the env:
```cron
0 * * * * cd ~/hadware-raxmonov && docker compose -f docker-compose.prod.yml exec -T web python manage.py mark_overdue
```

## 11. Security notes

- Secrets live only in server `.env` (git-ignored); never in the repo or CI.
- PostgreSQL is not published to the host — internal docker network only.
- `ufw` allows only 22/80/443.
- Rotate the `rakhmonov`/root passwords if they were ever shared.
- Recommended hardening: SSH key-only auth (`PasswordAuthentication no`,
  `PermitRootLogin no`) once key login is confirmed working.
