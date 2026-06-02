# Деплой rental_track: Docker + PostgreSQL + CI/CD — дизайн

- **Дата:** 2026-06-03
- **Статус:** утверждён пользователем (вариант A), ожидает финального ревью спеки
- **Автор:** Claude (по запросу владельца проекта)
- **Рабочая ветка инфраструктуры:** `worktree-deploy-infra` (worktree от `origin/main` @ `5092ac1`)

## 1. Цель

Развернуть Django-приложение `rental_track` на «голом» Ubuntu-сервере:
PostgreSQL вместо SQLite, всё через Docker Compose, домен с HTTPS, и
CI/CD на GitHub Actions, при котором мердж `main` → `production`
автоматически выкатывает изменения на сервер.

## 2. Исходное состояние (обнаруженные факты)

### Приложение
- Django 5.x (`>=5.0,<5.3`), Python 3.12; пакет проекта `rental_track`,
  приложения `config`, `core`.
- Зависимости (`requirements.txt`): Django, django-htmx, python-dotenv,
  fpdf2, pytest-django, coverage, gunicorn.
- Конфигурация через env (`python-dotenv`, `load_dotenv(BASE_DIR/.env)`):
  `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`,
  `TELEGRAM_*`, `CONTRACT_PDF_FONT_*`.
- БД сейчас: SQLite (`db.sqlite3`).
- Статика: `STATIC_URL='static/'`, `STATIC_ROOT=BASE_DIR/'staticfiles'`,
  `STATICFILES_DIRS=[BASE_DIR/'static']`.
- Медиа-загрузок нет (в `config`/`core` нет `FileField`/`ImageField`) —
  том для media не нужен.
- i18n: `LANGUAGE_CODE='ru'`, языки ru/uz, `LocaleMiddleware` активен,
  есть `locale/*/LC_MESSAGES/*.po` → нужен `compilemessages` (gettext).
- PDF договоров (`fpdf2`) требует TTF с кириллицей → в образ ставится
  `fonts-dejavu-core` (settings уже умеют искать DejaVu на Linux).
- Management-команды по расписанию: `mark_overdue` (ежечасно),
  `notify_debtors` (ежечасно; внутренне срабатывает в заданный час;
  без `TELEGRAM_BOT_TOKEN` — no-op).
- `LOGIN_URL='login'`, корень редиректит на `/dashboard/` (требует логин).

### Сервер
- Ubuntu 24.04.4 LTS, x86_64; 6 vCPU, 11 GiB RAM, 96 GB диск (исп. ~2.4 GB),
  swap отсутствует.
- Публичный IP `207.180.210.65`; домен `rakhmonov-arenda.uz` (A-запись уже
  направлена на этот IP). `www` — уточнить, есть ли A-запись.
- Пользователь `rakhmonov`, группы `sudo users` — sudo есть, **с паролем**.
- Docker **не установлен**; git 2.43 установлен; наружу слушает только `:22`.
- Проект уже склонирован в `/home/rakhmonov/hadware-raxmonov`, ветка `main`
  @ `5092ac1`, remote `git@github.com:Rakhmatullo929/hadware-raxmonov.git`,
  доступ по ключу `~/.ssh/id_rsa` (read-доступ к GitHub).

### Git
- GitHub `origin/main` = `5092ac1` (= то, что на сервере).
- Локальный `main` опережает на 5 коммитов (watermark/print) + 23
  несохранённых файла (salary, customer modal, docs, static/js).
- `gh` CLI локально **не установлен**.

## 3. Решения (утверждено)

1. **Доступ:** домен `rakhmonov-arenda.uz` + HTTPS (Let's Encrypt).
2. **БД при старте:** чистая, прогон миграций + создание нового
   суперпользователя. Локальные dev/демо-данные не переносятся.
3. **Привилегии:** пользователь передаёт sudo-пароль; серверную настройку
   Claude выполняет сам (пароль — только в рамках сессии, для setup-команд,
   нигде не сохраняется).
4. **Код в прод:** только текущий `origin/main` (5092ac1) + инфра-коммит.
   Локальная незакоммиченная работа и 5 print-коммитов не выкатываются.
5. **Слой прокси/TLS:** вариант **A** — nginx + certbot (webroot).
6. **Сборка образа:** на сервере (`docker compose up --build`), без внешнего
   registry. GHCR — вне scope (можно добавить позже).
7. **Изоляция работы:** все файлы инфраструктуры и спека готовятся в worktree
   `worktree-deploy-infra` от `origin/main`, затем вливаются в `main`.

## 4. Целевая архитектура (docker-compose на сервере)

```
                Internet (rakhmonov-arenda.uz → 207.180.210.65)
                              │  :80 / :443
                    ┌─────────▼──────────┐
                    │   nginx (alpine)   │  TLS termination, 80→443 redirect,
                    │  reverse-proxy     │  отдаёт /static/ из тома
                    └─────────┬──────────┘
                              │ proxy → web:8000 (внутренняя сеть)
        ┌─────────────────────┼──────────────────────────┐
   ┌────▼─────┐        ┌───────▼────────┐         ┌────────▼────────┐
   │ certbot  │        │ web: Django +  │         │ cron: тот же    │
   │ renew    │        │ gunicorn       │         │ web-образ +     │
   │ loop     │        │ entrypoint:    │         │ supercronic     │
   └──────────┘        │ migrate +      │         │ mark_overdue,   │
                       │ collectstatic  │         │ notify_debtors  │
                       └───────┬────────┘         └─────────────────┘
                               │ psycopg
                       ┌───────▼────────┐
                       │ db: postgres16 │ том pgdata, healthcheck,
                       │ (не торчит      │ наружу НЕ публикуется
                       │  наружу)       │
                       └────────────────┘

Тома: pgdata (БД), staticfiles (collectstatic→nginx),
      certbot-etc (сертификаты), certbot-www (ACME webroot)
Порты наружу: 80, 443 (+ 22 ssh). PostgreSQL только во внутренней сети.
```

### Сервисы

| Сервис | Образ/сборка | Назначение | Порты |
|--------|--------------|------------|-------|
| `db` | `postgres:16-alpine` | PostgreSQL, том `pgdata`, healthcheck `pg_isready` | внутр. |
| `web` | сборка из `Dockerfile` | Django + gunicorn; entrypoint: migrate → collectstatic → gunicorn | `expose 8000` |
| `cron` | тот же образ | `supercronic /app/deploy/crontab`; entrypoint переопределён (миграции НЕ запускает) | — |
| `nginx` | `nginx:1.27-alpine` | reverse-proxy, TLS, отдача `/static/`, reload-loop | `80:80`, `443:443` |
| `certbot` | `certbot/certbot` | `certbot renew` в цикле каждые 12 ч | — |

`restart: unless-stopped` на всех. `web` и `cron` зависят от `db`
(`condition: service_healthy`). Только `web` выполняет миграции — `cron`
переопределяет entrypoint, чтобы избежать гонки миграций.

## 5. Изменения в коде (инфра-коммит поверх 5092ac1)

### 5.1 `rental_track/settings.py` (обратносовместимо)

`DATABASES` выбирается по наличию `POSTGRES_DB`:

```python
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
    DATABASES = {  # локальная разработка — без изменений
        'default': {'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': BASE_DIR / 'db.sqlite3'}
    }
```

Прод-безопасность при `DEBUG=False`:

```python
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    X_FRAME_OPTIONS = 'DENY'
    CSRF_TRUSTED_ORIGINS = [
        o.strip() for o in os.getenv(
            'DJANGO_CSRF_TRUSTED_ORIGINS',
            'https://rakhmonov-arenda.uz').split(',') if o.strip()
    ]
```

> nginx сам делает 80→443, поэтому `SECURE_SSL_REDIRECT` не включаем (иначе
> риск редирект-петли за прокси). `SECURE_PROXY_SSL_HEADER` обязателен, иначе
> Django за прокси считает запросы http и ломает CSRF/secure-cookie.

### 5.2 `requirements.txt`
Добавить `psycopg[binary]>=3.1` (драйвер PostgreSQL для Django 4.2+/5.x).

### 5.3 Новые файлы

```
Dockerfile
.dockerignore
docker-compose.prod.yml
.env.prod.example
deploy/entrypoint.sh
deploy/deploy.sh
deploy/provision.sh
deploy/crontab
deploy/nginx/templates/app.http.conf  # bootstrap: 80 + ACME + proxy (до выпуска cert)
deploy/nginx/templates/app.ssl.conf   # рабочий: 80→443 redirect + 443 TLS
deploy/nginx/conf.d/.gitkeep          # сюда deploy.sh кладёт активный default.conf (генерируемый, в .gitignore)
.github/workflows/ci.yml
.github/workflows/deploy.yml
docs/DEPLOYMENT.md              # рунбук эксплуатации
```

## 6. Спецификация ключевых артефактов

### 6.1 `Dockerfile`
- База `python:3.12-slim`; `PYTHONUNBUFFERED=1`, `PYTHONDONTWRITEBYTECODE=1`.
- apt: `fonts-dejavu-core` (PDF), `gettext` (compilemessages), `curl`
  (загрузка supercronic), затем очистка списков.
- `supercronic` — pin версии `v0.2.33`, бинарь linux-amd64, проверка sha256
  (точный хэш берётся со страницы релиза на этапе реализации) → `/usr/local/bin`.
- `pip install -r requirements.txt` (включает `psycopg[binary]`).
- `COPY . .`, затем `python manage.py compilemessages` (компиляция ru/uz .mo).
- `ENTRYPOINT ["deploy/entrypoint.sh"]`,
  `CMD ["gunicorn","rental_track.wsgi:application","--bind","0.0.0.0:8000","--workers","3","--timeout","60"]`.

### 6.2 `deploy/entrypoint.sh`
```sh
#!/usr/bin/env sh
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
exec "$@"
```
БД к этому моменту healthy (через `depends_on`). `collectstatic` пишет в
том `staticfiles`, который nginx отдаёт как `/static/`. **Миграции
выполняет только `web`** (через этот entrypoint) — `deploy.sh` их не
дублирует, чтобы избежать гонки.

### 6.3 `docker-compose.prod.yml` (структура)
- `db`: `postgres:16-alpine`, env `POSTGRES_DB/USER/PASSWORD` из `.env`,
  том `pgdata:/var/lib/postgresql/data`, healthcheck
  `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB`.
- `web`: `build: .`, `env_file: .env`, `depends_on: db (service_healthy)`,
  том `staticfiles:/app/staticfiles`, `expose: 8000`.
- `cron`: `build: .`, `env_file: .env`, `entrypoint: ["supercronic"]`,
  `command: ["/app/deploy/crontab"]` (и entrypoint, и command переопределены,
  иначе Dockerfile CMD `gunicorn` попадёт аргументом в supercronic).
- `nginx`: `nginx:1.27-alpine`, порты `80/443`, тома:
  `./deploy/nginx/conf.d:/etc/nginx/conf.d:ro` (только активный
  `default.conf`), `staticfiles` (ro), `certbot-etc` (ro),
  `certbot-www` (ro); команда с reload-циклом каждые 6 ч (подхват
  обновлённых сертификатов).
- `certbot`: `certbot/certbot`, тома `certbot-etc`, `certbot-www`,
  entrypoint с циклом `certbot renew` каждые 12 ч.
- Тома: `pgdata`, `staticfiles`, `certbot-etc`, `certbot-www`.

### 6.4 nginx-конфиги
Исходники лежат в `deploy/nginx/templates/`, наружу (в `conf.d`) монтируется
только активный `default.conf`, который `deploy.sh` копирует из нужного
шаблона. Так nginx грузит ровно один server-конфиг (нет конфликта
`listen 80`/`server_name`).
- `templates/app.http.conf` (bootstrap, до первого сертификата): `listen 80`,
  `location /.well-known/acme-challenge/ { root /var/www/certbot; }`,
  `location / { proxy_pass http://web:8000; ... }` — чтобы проверить, что
  приложение живо ещё до TLS.
- `templates/app.ssl.conf` (рабочий):
  - server :80 — ACME-challenge + `return 301 https://$host$request_uri`.
  - server :443 ssl (http2), `ssl_certificate*` из
    `/etc/letsencrypt/live/rakhmonov-arenda.uz/`,
    `location /static/ { alias /app/staticfiles/; expires 30d; }`,
    `location / { proxy_pass http://web:8000; }` с заголовками
    `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Real-IP`,
    `client_max_body_size 25m`.
- `deploy/nginx/conf.d/default.conf` — генерируемый (в `.gitignore`);
  `deploy.sh` выбирает шаблон по наличию
  `live/rakhmonov-arenda.uz/fullchain.pem` (см. 6.6).

### 6.5 `deploy/crontab` (supercronic, 5 полей)
```
0 * * * * python manage.py mark_overdue
5 * * * * python manage.py notify_debtors
```

### 6.6 `deploy/deploy.sh` (идемпотентный деплой; вызывается CI и вручную)
```sh
#!/usr/bin/env sh
set -e
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=rental_track   # стабильные имена томов/сети
COMPOSE="docker compose -f docker-compose.prod.yml"
mkdir -p deploy/nginx/conf.d
# выбрать nginx-конфиг по наличию сертификата
if $COMPOSE run --rm --no-deps --entrypoint sh certbot -c \
     'test -f /etc/letsencrypt/live/rakhmonov-arenda.uz/fullchain.pem'; then
  cp deploy/nginx/templates/app.ssl.conf  deploy/nginx/conf.d/default.conf
else
  cp deploy/nginx/templates/app.http.conf deploy/nginx/conf.d/default.conf
fi
$COMPOSE up -d --build          # web сам прогонит migrate+collectstatic (entrypoint)
$COMPOSE ps                     # статусы для логов деплоя
echo "Deploy OK"
```
> `COMPOSE_PROJECT_NAME=rental_track` фиксирует имена томов/сети независимо
> от имени каталога. Проверка сертификата идёт через сам certbot-сервис
> (у него уже примонтирован том `certbot-etc`), без угадывания имени тома.
> Миграции выполняет entrypoint `web` (см. 6.2) — здесь не дублируются.

### 6.7 `.dockerignore`
Исключить из build-контекста: `.git`, `venv`/`.venv`, `.env*`,
`db.sqlite3*`, `__pycache__`/`*.pyc`, `.pytest_cache`, `.coverage`,
`htmlcov`, `backups`, `staticfiles`, `docs`, `.claude`. Образ собирается
без секретов и dev-артефактов.

### 6.8 `.env.prod.example`
```
DJANGO_SECRET_KEY=GENERATE_ME
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=rakhmonov-arenda.uz,www.rakhmonov-arenda.uz,207.180.210.65
DJANGO_CSRF_TRUSTED_ORIGINS=https://rakhmonov-arenda.uz,https://www.rakhmonov-arenda.uz
POSTGRES_DB=rental_track
POSTGRES_USER=rental
POSTGRES_PASSWORD=GENERATE_ME
POSTGRES_HOST=db
POSTGRES_PORT=5432
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_CHAT_IDS=
TELEGRAM_REMINDER_HOUR=9
```
Реальный `.env` создаётся на сервере (в `.gitignore`), с
сгенерированными секретами. В репозиторий не попадает.

## 7. Провижининг сервера (разово, с sudo)

`deploy/provision.sh` (запускается через sudo; идемпотентный):
1. `apt-get update`; установка Docker CE + `docker-compose-plugin` из
   официального репозитория Docker.
2. `usermod -aG docker rakhmonov` → дальше docker без sudo (CI деплоит
   без sudo). Требуется новый вход в сессию для применения группы.
3. `ufw`: `allow OpenSSH` (или 22) → `allow 80` → `allow 443` →
   `--force enable`. **22 разрешается до enable**, чтобы не потерять ssh.
4. Swap 2 GiB: `fallocate /swapfile` → `mkswap` → `swapon` → запись в
   `/etc/fstab` (страховка на пик сборки образа).

## 8. Первый деплой (ручной runbook)

Выполняется после провижининга, на ветке `production`:
1. На сервере: `cd ~/hadware-raxmonov && git fetch origin &&
   git checkout production && git reset --hard origin/production`.
2. Создать `.env` из `.env.prod.example`, сгенерировать `DJANGO_SECRET_KEY`
   и `POSTGRES_PASSWORD` (например `python -c "import secrets;print(...)"`).
3. `./deploy/deploy.sh` — поднимет db/web/cron/nginx (nginx в bootstrap-HTTP,
   т.к. сертификата ещё нет), прогонит миграции.
4. Проверить, что приложение живо по `http://rakhmonov-arenda.uz`.
5. Выпустить сертификат:
   `docker compose -f docker-compose.prod.yml run --rm certbot certonly \
   --webroot -w /var/www/certbot -d rakhmonov-arenda.uz [-d www....] \
   --email <email> --agree-tos --no-eff-email`.
   (`www` добавляется только если для него есть A-запись.)
6. Повторно `./deploy/deploy.sh` — теперь подхватит ssl-конфиг → HTTPS.
7. Создать суперпользователя:
   `docker compose -f docker-compose.prod.yml exec web python manage.py
   createsuperuser` (логин/почта/пароль — от пользователя).
8. Смоук-проверка (раздел 11).

## 9. CI/CD (GitHub Actions)

### 9.1 `ci.yml` — на `pull_request` и `push: main`
- `services.postgres: postgres:16` с healthcheck.
- Python 3.12, `pip install -r requirements.txt psycopg[binary]`.
- env: `DJANGO_DEBUG=True` (security-блок отключён в тестах),
  `POSTGRES_*` на сервис postgres, `DJANGO_SECRET_KEY=ci-secret`.
- `python manage.py migrate --noinput` → `pytest`.

### 9.2 `deploy.yml` — на `push: production`
- `concurrency: production-deploy` (без отмены — деплои не накладываются).
- Шаг через `appleboy/ssh-action`: ssh на сервер →
  `cd ~/hadware-raxmonov && git fetch origin && git checkout production &&
  git reset --hard origin/production && ./deploy/deploy.sh`.

### 9.3 Секреты GitHub (Actions → Secrets)
| Имя | Значение |
|-----|----------|
| `DEPLOY_HOST` | `207.180.210.65` |
| `DEPLOY_USER` | `rakhmonov` |
| `DEPLOY_PORT` | `22` |
| `DEPLOY_SSH_KEY` | приватный ключ выделенной пары CI→сервер |

- Генерируется **отдельная** пара ключей (ed25519, `ci_deploy`), публичный
  добавляется в `~/.ssh/authorized_keys` сервера; приватный — в
  `DEPLOY_SSH_KEY`. Существующий `id_rsa` (доступ сервера к GitHub) не
  трогается.
- **Секреты приложения в GitHub не кладутся** — они только в `.env` на
  сервере. CI нужен лишь ssh-доступ.
- Способ добавления секретов уточняется на исполнении: либо `gh auth login`
  (device-flow) и Claude добавляет через CLI, либо пользователь вставляет
  4 значения в UI (Claude даёт точные значения).

## 10. Git-стратегия и поток

1. В worktree `worktree-deploy-infra` (от `origin/main`) добавляются все
   файлы инфраструктуры + правки settings/requirements → коммит.
2. Влить в `main` (PR или fast-forward), запушить `origin/main`.
3. Создать ветку `production` из `main`, запушить `origin/production`.
4. Сервер переключить на `production` (первый деплой — вручную, см. §8).
5. Далее: PR `main` → `production`; мердж триггерит `deploy.yml` →
   сервер обновляется автоматически.

> Последствие выбора «только текущий main»: локальный `main` пользователя
> (5 print-коммитов) разойдётся с `origin/main`. После деплоя показать, как
> свести (rebase локальных коммитов поверх обновлённого `origin/main`).

## 11. Тестирование и проверка

- **CI:** `pytest` против PostgreSQL до мерджа.
- **Healthchecks:** `db` (pg_isready) и статусы контейнеров `docker compose ps`.
- **Смоук после деплоя:**
  - `curl -I http://rakhmonov-arenda.uz` → 301 на https;
  - `curl -I https://rakhmonov-arenda.uz/` → 302 на `/login/`;
  - `/admin/` открывается; вход работает (CSRF поверх https);
  - сертификат валиден (срок, issuer Let's Encrypt);
  - `docker compose logs` без ошибок; `mark_overdue` отрабатывает по cron.

## 12. Откат (rollback)

- Код: в ветке `production` `git revert`/`reset --hard <prev>` + повторный
  деплой (сборка на сервере), либо мердж фикс-коммита.
- БД: перед рискованной миграцией снять дамп
  `docker compose exec db pg_dump -U $POSTGRES_USER $POSTGRES_DB > backup.sql`.
  Автоматические офсайт-бэкапы — вне scope (см. §13), описываются в рунбуке.

## 13. Безопасность

- Секреты только в `.env` на сервере (`.gitignore`); генерируются сильные
  `DJANGO_SECRET_KEY` и `POSTGRES_PASSWORD`.
- PostgreSQL не публикуется наружу (только внутренняя docker-сеть).
- `ufw`: открыты только 22/80/443.
- TLS Let's Encrypt + HSTS; `DEBUG=False`, заданы `ALLOWED_HOSTS` и
  `CSRF_TRUSTED_ORIGINS`.
- Отдельный CI-ключ деплоя, изолированный от GitHub-ключа сервера.
- Telegram-токен по умолчанию пуст (функция выключена). Если включать —
  только новый токен в `.env` (старый, по примечанию в `.env.example`,
  считать скомпрометированным).
- sudo-пароль используется только в setup-командах текущей сессии, нигде
  не сохраняется и не логируется.

## 14. Вне scope (YAGNI)

- Внешний registry/GHCR (выбрана сборка на сервере).
- Несколько реплик / балансировка.
- Управляемый PostgreSQL, объектное хранилище/медиа (загрузок нет).
- Caddy (выбран nginx).
- Автоматические офсайт-бэкапы БД (документируется ручной `pg_dump`).
- Перенос локальных dev-данных (выбрана чистая БД).

## 15. Что потребуется от пользователя на исполнении

1. sudo-пароль (шаг провижининга).
2. Подтвердить наличие A-записи для `www.rakhmonov-arenda.uz` (иначе
   сертификат только на apex).
3. Способ добавления GitHub-секретов (`gh` device-login или вручную).
4. Данные суперпользователя (логин/email/пароль) для `createsuperuser`.
