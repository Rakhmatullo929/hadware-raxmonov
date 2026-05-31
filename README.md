# rental_track

Учётная система аренды строительных материалов и рамных лесов.

- Django 5.x · Python 3.12 · SQLite (dev)
- Bootstrap 5 + HTMX · Django templates
- TZ: Asia/Tashkent · LANG: ru

## Запуск (dev)

```bash
# 1. venv
python3.12 -m venv venv
source venv/bin/activate

# 2. зависимости
pip install -r requirements.txt

# 3. .env
cp .env.example .env

# 4. миграции и группы (staff/admin создаются автоматически)
python manage.py migrate

# 5. суперпользователь
python manage.py createsuperuser

# 6. (опционально) демо-данные для дашборда
python manage.py seed_demo --customers 30 --rentals 1000

# 7. запуск
python manage.py runserver
```

После запуска:

- `/` — редирект на `/dashboard/` (требует логин)
- `/login/` — вход
- `/logout/` — выход (POST)
- `/admin/` — Django admin
- `/dashboard/`, `/rentals/`, `/customers/`, `/products/` — для staff и admin
- `/reports/` — только для группы `admin` (или суперпользователя)

## Роли

После первой миграции автоматически создаются группы:

- `staff` — рядовые сотрудники
- `admin` — расширенный доступ (отчёты, цены, досрочное закрытие аренды)

Назначить пользователю группу можно в `/admin/` → Пользователи.

Декоратор `config.decorators.role_required('admin')` ограничивает вьюху по группам.

## Регулярная задача: mark_overdue

```bash
python manage.py mark_overdue
```

Переводит активные аренды с `due_date < сегодня` и невозвращёнными
позициями в статус `overdue`. Команда идемпотентна — можно запускать
повторно. Поддерживает `--dry-run`.

> Дашборд считает просрочку и без этой команды (на лету), поэтому если
> её ни разу не запустить, цифры на дашборде всё равно будут верными.
> Команда нужна, чтобы поле `Rental.status` не уходило в рассинхрон —
> по нему фильтруют список аренд и admin-страница.

### Расписание — cron

```cron
# /etc/crontab или crontab -e
0 * * * * cd /path/to/counter-track && /path/to/venv/bin/python manage.py mark_overdue >>/var/log/rental-track-overdue.log 2>&1
```

### Расписание — macOS (launchd)

Создайте `~/Library/LaunchAgents/local.rental-track.mark-overdue.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>local.rental-track.mark-overdue</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOU/Downloads/rakhmatullo/2026-May/counter-track/venv/bin/python</string>
        <string>/Users/YOU/Downloads/rakhmatullo/2026-May/counter-track/manage.py</string>
        <string>mark_overdue</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOU/Downloads/rakhmatullo/2026-May/counter-track</string>
    <key>StartInterval</key>
    <integer>3600</integer>
    <key>StandardOutPath</key>
    <string>/tmp/rental-track-overdue.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/rental-track-overdue.log</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```

Загрузить:

```bash
launchctl load ~/Library/LaunchAgents/local.rental-track.mark-overdue.plist
launchctl list | grep rental-track          # проверить, что висит
launchctl unload ~/Library/LaunchAgents/local.rental-track.mark-overdue.plist
```

## Telegram-напоминания арендодателю

Команда `notify_debtors` шлёт напоминания **только арендодателю**
(оператору/админу — тем, кто даёт в аренду). Клиентам бот ничего
не пишет.

* **За 1 день до возврата** — в указанный час (`TELEGRAM_REMINDER_HOUR`,
  по умолчанию 9 утра) один раз в день: сводка по арендам с
  `due_date == завтра`.
* **Каждый час по просроченным** — сводка по всем просрочкам, пока
  есть невозвращённые позиции.

Получатели — все chat_id из `TELEGRAM_ADMIN_CHAT_IDS`. Узнать свой
chat_id: написать `@userinfobot` из своего Telegram. Перед первым
запуском напишите боту `/start`, иначе он не сможет вам писать.

Дедуп через таблицу `DebtorNotification`: повторный запуск в том же
часе (для просрочек) / в тот же день (для «за день») ничего не
отправит.

### Настройка

В `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:AAA...        # из @BotFather
TELEGRAM_ADMIN_CHAT_IDS=12345,-100789   # через запятую; группы — отрицательные
TELEGRAM_REMINDER_HOUR=9                # 0-23
```

> **Безопасность.** Токен бота в публичном чате/коммите = скомпрометирован.
> Если такое случилось — `/revoke` в @BotFather и в `.env` положить новый.
> Файл `.env` уже в `.gitignore`.

### Команды

```bash
# Прогон без отправки и без записи в БД (посмотреть, что бы ушло):
python manage.py notify_debtors --dry-run

# Игнорировать TELEGRAM_REMINDER_HOUR (для разовых проверок «за день»):
python manage.py notify_debtors --force-daily
```

### Расписание — cron

Команда сама знает, что делать в каждый час, так что нужна **одна строка**:

```cron
# каждый час: dаy-before выстрелит только в TELEGRAM_REMINDER_HOUR,
# overdue — каждый час пока есть просрочки
5 * * * * cd /path/to/project && /path/to/venv/bin/python manage.py notify_debtors >>/var/log/rental-track-notify.log 2>&1
```

### Расписание — macOS (launchd)

`~/Library/LaunchAgents/local.rental-track.notify-debtors.plist` — аналог
`mark-overdue` плиста, только команда `notify_debtors` и `StartInterval = 3600`.

## PDF договора

На странице аренды две кнопки:

* **Печать договора** — HTML-версия (`/rentals/<id>/contract/`),
  печать через браузер (Ctrl+P).
* **Скачать PDF** — серверный PDF (`/rentals/<id>/contract.pdf`),
  генерируется через **fpdf2** (чистый Python, без системных
  библиотек — в отличие от WeasyPrint).

PDF собирается на языке текущего интерфейса (ru/uz).

### Шрифт

Нужен TTF с кириллицей и узбекской латиницей. Поиск по списку
кандидатов (`config/contract_pdf.py`):

1. `CONTRACT_PDF_FONT_PATH` из `.env` (если задан);
2. `static/fonts/DejaVuSans.ttf` (если положить в проект — самый
   переносимый вариант);
3. системный DejaVu на Linux;
4. `Arial Unicode.ttf` на macOS (есть из коробки).

**На Linux-проде** достаточно:

```bash
sudo apt install fonts-dejavu-core      # Debian/Ubuntu
# или положить static/fonts/DejaVuSans.ttf (+ -Bold.ttf) в репозиторий
```

Если шрифт не найден — кнопка покажет понятную ошибку, аренда не
ломается.

### Расписание — systemd timer (Linux)

```ini
# /etc/systemd/system/rental-track-overdue.service
[Unit]
Description=rental_track mark_overdue

[Service]
Type=oneshot
WorkingDirectory=/srv/counter-track
ExecStart=/srv/counter-track/venv/bin/python manage.py mark_overdue
User=rental
```

```ini
# /etc/systemd/system/rental-track-overdue.timer
[Unit]
Description=Run rental-track-overdue.service hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now rental-track-overdue.timer
```

## Демо-данные для дашборда

```bash
python manage.py seed_demo --rentals 1000 --customers 30
```

Создаст ~1000 аренд / ~10 000 движений с распределёнными датами. Все
демо-объекты помечены: клиенты — `notes='[seed_demo]'`, аренды и движения —
`note='[seed_demo]'`. Для очистки удалите `Customer.objects.filter(notes='[seed_demo]')`
(аренды и движения уйдут каскадно через PROTECT/CASCADE — не уйдут, нужно сначала
удалить аренды; см. comment ниже).

> Удаление демо-данных: `Rental.objects.filter(note='[seed_demo]').delete()` →
> `Customer.objects.filter(notes='[seed_demo]').delete()`. Делать в shell, не в проде.

## Тесты и покрытие

```bash
pytest                              # все тесты
coverage run -m pytest && coverage report
coverage html && open htmlcov/index.html  # детальный отчёт по строкам
```

Покрытие по состоянию на 2026-05-06 (65 тестов):

| Модуль | Stmts | Cover |
|---|---:|---:|
| `config/billing.py` | 60 | **95.3%** (line: 100%) |
| `config/models.py` | 152 | 93.7% |
| `config/decorators.py` | 16 | 100% |
| `config/forms.py` | 45 | 93.0% |
| `config/management/commands/mark_overdue.py` | 23 | 88.9% |
| `config/views.py` | 577 | 72.6% |
| **Итого** | 1070 | **78.6%** |

Тесты:

- `tests/test_billing.py` — FIFO-расчёт дней, пени, итог с залогом
- `tests/test_models.py` — outstanding_qty / available_stock / is_overdue / auto-close
- `tests/test_rental_flow.py` — e2e: создать → частичный возврат → доплата → полный возврат → closed; контракт печать; 404
- `tests/test_permissions.py` — staff/admin/anonymous матрица доступа (51 параметризованный кейс)
- `tests/test_management_commands.py` — `mark_overdue` (включая `--dry-run`) и `backup_db`

`seed_demo` исключён из coverage как dev-only fixture loader.

## Бэкап БД

```bash
python manage.py backup_db                    # снимок в backups/
python manage.py backup_db --keep 30          # хранить 30 последних
```

Для SQLite использует online-backup API (`sqlite3.Connection.backup`),
поэтому копировать можно даже на работающей БД. На Postgres/MySQL
переключается на `dumpdata`. Папка `backups/` исключена из git.

Расписание (cron, ежедневно в 03:00):

```cron
0 3 * * * cd /srv/counter-track && /srv/counter-track/venv/bin/python manage.py backup_db
```

## Деплой на VPS (Linux + systemd + nginx + gunicorn)

### 1. Подготовка

```bash
sudo adduser --system --group rental
sudo mkdir -p /srv/counter-track && sudo chown rental:rental /srv/counter-track
sudo -u rental git clone <repo> /srv/counter-track
cd /srv/counter-track
sudo -u rental python3.12 -m venv venv
sudo -u rental venv/bin/pip install -r requirements.txt
```

### 2. Переменные окружения

`/srv/counter-track/.env` (chmod 600, owner rental):

```ini
DJANGO_SECRET_KEY=<сгенерировать: python -c 'from secrets import token_urlsafe; print(token_urlsafe(64))'>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=rental.example.com
```

Команда первого деплоя:

```bash
sudo -u rental venv/bin/python manage.py migrate
sudo -u rental venv/bin/python manage.py collectstatic --noinput
sudo -u rental venv/bin/python manage.py createsuperuser
```

### 3. systemd unit для gunicorn

`/etc/systemd/system/rental-track.service`:

```ini
[Unit]
Description=rental_track gunicorn
After=network.target

[Service]
Type=notify
User=rental
Group=rental
WorkingDirectory=/srv/counter-track
EnvironmentFile=/srv/counter-track/.env
ExecStart=/srv/counter-track/venv/bin/gunicorn rental_track.wsgi:application \
    --workers 3 --bind unix:/run/rental-track.sock --access-logfile -
Restart=always
RuntimeDirectory=rental-track

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rental-track.service
```

### 4. nginx (front)

`/etc/nginx/sites-available/rental-track`:

```nginx
server {
    listen 80;
    server_name rental.example.com;

    client_max_body_size 10M;

    location /static/ { alias /srv/counter-track/staticfiles/; }
    location /media/  { alias /srv/counter-track/media/; }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://unix:/run/rental-track.sock;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/rental-track /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

После — выпустить TLS-сертификат через `certbot --nginx -d rental.example.com`.

### 5. Регулярные задачи

```cron
# /etc/cron.d/rental-track
0 *  * * * rental cd /srv/counter-track && venv/bin/python manage.py mark_overdue
5 *  * * * rental cd /srv/counter-track && venv/bin/python manage.py notify_debtors
0 3  * * * rental cd /srv/counter-track && venv/bin/python manage.py backup_db --keep 30
```

### 6. Чек-лист продакшена

- [ ] `DEBUG=False` в `.env`
- [ ] `DJANGO_SECRET_KEY` сгенерирован, не из `.env.example`
- [ ] `DJANGO_ALLOWED_HOSTS` указан
- [ ] HTTPS через nginx + certbot, `SECURE_SSL_REDIRECT`/`SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE` = True (добавьте в settings.py из `.env`)
- [ ] `python manage.py check --deploy` без warnings
- [ ] `collectstatic` отработал, статика отдаётся nginx (а не gunicorn)
- [ ] `mark_overdue` и `backup_db` крутятся в cron
- [ ] Создан суперпользователь, в группах `staff` / `admin` есть реальные люди
- [ ] Логи systemd доступны: `journalctl -u rental-track -f`
- [ ] Бэкапы тестово восстанавливаются: `cp backups/sqlite-... db.sqlite3 && manage.py runserver` на копии

> Под нагрузку выше 50 одновременных пользователей — мигрировать на Postgres
> (поменять `DATABASES`, прогнать `migrate`, восстановить данные через
> `dumpdata`/`loaddata`). HTMX и шаблоны не зависят от движка БД.
# hadware-raxmonov
# rakhmonov-rental
