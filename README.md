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

# 6. запуск
python manage.py runserver
```

После запуска:

- `/` — редирект на `/dashboard/` (требует логин)
- `/login/` — вход
- `/logout/` — выход (POST)
- `/admin/` — Django admin
- `/dashboard/`, `/rentals/`, `/clients/`, `/products/` — для авторизованных
- `/reports/` — только для группы `admin` (или суперпользователя)

## Роли

После первой миграции автоматически создаются группы:

- `staff` — рядовые сотрудники
- `admin` — расширенный доступ (отчёты, цены)

Назначить пользователю группу можно в `/admin/` → Пользователи.

Декоратор `core.decorators.role_required('admin')` ограничивает вьюху по группам.

## Тесты

```bash
pytest
```
