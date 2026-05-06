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

Декоратор `core.decorators.role_required('admin')` ограничивает вьюху по группам.

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

## Тесты

```bash
pytest
```

Покрывают FIFO-биллинг, Σ к оплате, отсутствие штрафа после закрытия.
