# Каталог опалубки + «Что входит в комплект» — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Завести детальные товары опалубки по размерам (сгруппированные в категории) и для каждого хранить справочное поле «В комплекте», показываемое на странице товара и в печати договора (HTML + PDF).

**Architecture:** Одно новое текстовое поле `included_kit` на модели `Product`. Наполнение каталога — идемпотентной миграцией данных (паттерн `0002_seed_catalog`/`0012_seed_norm_products`). Показ — в шаблоне списка товаров, HTML-договоре (`contract.html`) и PDF-договоре (`config/contract_pdf.py`). Старые обобщённые товары деактивируются той же миграцией.

**Tech Stack:** Django 5, SQLite (dev), pytest + pytest-django, fpdf2 (PDF), Bootstrap 5.

**Тесты запускаются так** (см. память проекта — `./venv/bin/pip` сломан, сервер на другом python; для тестов используем venv-python):
```
./venv/bin/python -m pytest <путь> -v
```

---

### Task 1: Поле `included_kit` на модели `Product`

**Files:**
- Modify: `config/models.py` (класс `Product`, после поля `is_active` ~ строка 53)
- Create (через makemigrations): `config/migrations/0015_product_included_kit.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Написать падающий тест**

В конец `tests/test_models.py` добавить:

```python
def test_product_included_kit_defaults_to_empty(category):
    from decimal import Decimal
    from config.models import Product
    p = Product.objects.create(
        name='Без комплекта',
        category=category,
        unit='шт',
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
    )
    assert p.included_kit == ''


def test_product_included_kit_stores_text(category):
    from decimal import Decimal
    from config.models import Product
    p = Product.objects.create(
        name='С комплектом',
        category=category,
        unit='шт',
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
        included_kit='Зажим ×3, Фиксатор ×3',
    )
    p.refresh_from_db()
    assert p.included_kit == 'Зажим ×3, Фиксатор ×3'
```

(Фикстура `category` определена в `tests/conftest.py`.)

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_models.py::test_product_included_kit_defaults_to_empty -v`
Expected: FAIL — `TypeError: ... unexpected keyword argument 'included_kit'` или `AttributeError`.

- [ ] **Step 3: Добавить поле на модель**

В `config/models.py`, в классе `Product`, сразу после строки
`is_active = models.BooleanField(_('Активен'), default=True)` добавить:

```python
    included_kit = models.TextField(
        _('В комплекте'),
        blank=True,
        default='',
        help_text=_('Что входит в комплект на 1 шт (справочно). '
                    'Напр.: Зажим ×3, Фиксатор ×3, Штир/шайба ×3'),
    )
```

- [ ] **Step 4: Создать миграцию схемы**

Run: `./venv/bin/python manage.py makemigrations config`
Expected: создан файл `config/migrations/0015_product_included_kit.py` с `AddField`.

- [ ] **Step 5: Применить миграцию и прогнать тесты**

Run: `./venv/bin/python manage.py migrate && ./venv/bin/python -m pytest tests/test_models.py -k included_kit -v`
Expected: PASS (оба теста).

- [ ] **Step 6: Commit**

```bash
git add config/models.py config/migrations/0015_product_included_kit.py tests/test_models.py
git commit -m "feat(catalog): add included_kit field to Product"
```

---

### Task 2: `included_kit` в форме товара

**Files:**
- Modify: `config/forms.py` (`ProductForm.Meta.fields`, ~строка 86)
- Test: `tests/test_models.py` (можно отдельный файл, но держим рядом с товаром)

`ProductForm` наследует `BootstrapFormMixin`, который сам навешивает класс
`form-control` и `rows=3` на `forms.Textarea` — отдельная правка виджета не нужна.
Шаблон `products/form.html` перебирает `{% for field in form %}`, поэтому новое
поле отрисуется автоматически.

- [ ] **Step 1: Написать падающий тест**

В `tests/test_models.py` добавить:

```python
def test_product_form_has_included_kit_and_saves(category):
    from config.forms import ProductForm
    assert 'included_kit' in ProductForm.base_fields
    form = ProductForm(data={
        'name': 'Корейская опалубка 2×1',
        'category': category.pk,
        'unit': 'шт',
        'stock_total': '0',
        'daily_price': '0',
        'deposit_per_unit': '0',
        'included_kit': 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3',
        'is_active': 'on',
    })
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.included_kit.startswith('Зажим ×3')
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_models.py::test_product_form_has_included_kit_and_saves -v`
Expected: FAIL — `assert 'included_kit' in ProductForm.base_fields` (KeyError/AssertionError).

- [ ] **Step 3: Добавить поле в форму**

В `config/forms.py`, в `ProductForm.Meta.fields`, добавить `'included_kit'` после
`'is_active'`:

```python
        fields = [
            'name',
            'category',
            'unit',
            'stock_total',
            'daily_price',
            'deposit_per_unit',
            'expected_min_days',
            'expected_max_days',
            'is_active',
            'included_kit',
        ]
```

- [ ] **Step 4: Запустить — PASS**

Run: `./venv/bin/python -m pytest tests/test_models.py::test_product_form_has_included_kit_and_saves -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/forms.py tests/test_models.py
git commit -m "feat(catalog): expose included_kit in ProductForm"
```

---

### Task 3: Показ комплекта в списке товаров и в админке

**Files:**
- Modify: `config/templates/config/products/_table.html` (ячейка названия, ~строка 18-24)
- Modify: `config/admin.py` (`ProductAdmin`, ~строка 22-40)
- Test: `tests/test_product_picker.py` или новый `tests/test_catalog_included_kit.py`

- [ ] **Step 1: Написать падающий тест (список товаров)**

Создать `tests/test_catalog_included_kit.py`:

```python
"""Тесты показа поля «В комплекте» в каталоге и договоре."""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from config.models import Product


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def kit_product(category):
    return Product.objects.create(
        name='Корейская опалубка 2×1',
        category=category,
        unit='шт',
        stock_total=0,
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
        included_kit='Зажим ×3, Фиксатор ×3',
    )


def test_product_list_shows_included_kit(client_admin, kit_product):
    resp = client_admin.get(reverse('product_list'))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'Зажим ×3, Фиксатор ×3' in body
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_product_list_shows_included_kit -v`
Expected: FAIL — текста комплекта нет в ответе.

- [ ] **Step 3: Показать комплект в `_table.html`**

В `config/templates/config/products/_table.html` заменить ячейку названия:

```html
                    <td>
                        {{ p.name }}
                        {% if not p.is_active %}
                            <span class="badge bg-secondary ms-1">{% trans "отключён" %}</span>
                        {% endif %}
                    </td>
```

на:

```html
                    <td>
                        {{ p.name }}
                        {% if not p.is_active %}
                            <span class="badge bg-secondary ms-1">{% trans "отключён" %}</span>
                        {% endif %}
                        {% if p.included_kit %}
                            <div class="small text-muted">
                                {% trans "в комплекте" %}: {{ p.included_kit }}
                            </div>
                        {% endif %}
                    </td>
```

- [ ] **Step 4: Запустить — PASS**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_product_list_shows_included_kit -v`
Expected: PASS.

- [ ] **Step 5: Добавить поле в админку**

В `config/admin.py`, в `ProductAdmin`, после строки `search_fields = ('name',)`
добавить:

```python
    fields = (
        'name', 'category', 'unit', 'stock_total',
        'daily_price', 'deposit_per_unit',
        'expected_min_days', 'expected_max_days',
        'is_active', 'included_kit',
    )
```

(Это гарантирует наличие поля в форме редактирования админки; `list_display`
менять не нужно.)

- [ ] **Step 6: Прогнать тесты файла**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config/templates/config/products/_table.html config/admin.py tests/test_catalog_included_kit.py
git commit -m "feat(catalog): show included_kit in product list and admin"
```

---

### Task 4: Комплект в HTML-договоре

**Files:**
- Modify: `config/templates/config/rentals/contract.html` (две таблицы позиций: ~строки 33-40 и ~94-103)
- Test: `tests/test_catalog_included_kit.py`

- [ ] **Step 1: Написать падающий тест**

В `tests/test_catalog_included_kit.py` добавить (использует фикстуры из
`tests/conftest.py`: `staff_user`, `customer`):

```python
def _make_rental_with(product, customer, staff_user):
    from datetime import timedelta
    from django.utils import timezone
    from config.models import Movement, Rental, RentalItem
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=2, created_by=staff_user,
    )
    return r


def test_html_contract_shows_included_kit(client_admin, kit_product, customer, admin_user):
    rental = _make_rental_with(kit_product, customer, admin_user)
    resp = client_admin.get(reverse('rental_contract', args=[rental.pk]))
    assert resp.status_code == 200
    assert 'Зажим ×3, Фиксатор ×3' in resp.content.decode()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_html_contract_shows_included_kit -v`
Expected: FAIL — комплекта нет в HTML договора.

- [ ] **Step 3: Добавить комплект в обе таблицы `contract.html`**

В первой таблице (накладная без цен) заменить:

```html
                    <td>{{ it.product.name }}</td>
                    <td class="text-end">{{ it.qty }}</td>
                    <td>{{ it.product.unit }}</td>
```

на:

```html
                    <td>
                        {{ it.product.name }}
                        {% if it.product.included_kit %}
                            <div class="small fst-italic">{% trans "в комплекте" %}: {{ it.product.included_kit }}</div>
                        {% endif %}
                    </td>
                    <td class="text-end">{{ it.qty }}</td>
                    <td>{{ it.product.unit }}</td>
```

Во второй таблице (с ценами) заменить:

```html
                    <td>{{ it.product.name }}</td>
                    <td class="text-end">{{ it.qty }}</td>
                    <td>{{ it.product.unit }}</td>
                    <td class="text-end">{{ it.price_per_day }}</td>
                    <td class="text-end">{{ it.product.deposit_per_unit }}</td>
```

на:

```html
                    <td>
                        {{ it.product.name }}
                        {% if it.product.included_kit %}
                            <div class="small fst-italic">{% trans "в комплекте" %}: {{ it.product.included_kit }}</div>
                        {% endif %}
                    </td>
                    <td class="text-end">{{ it.qty }}</td>
                    <td>{{ it.product.unit }}</td>
                    <td class="text-end">{{ it.price_per_day }}</td>
                    <td class="text-end">{{ it.product.deposit_per_unit }}</td>
```

- [ ] **Step 4: Запустить — PASS**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_html_contract_shows_included_kit -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/templates/config/rentals/contract.html tests/test_catalog_included_kit.py
git commit -m "feat(catalog): show included_kit on HTML contract"
```

---

### Task 5: Комплект в PDF-договоре

**Files:**
- Modify: `config/contract_pdf.py` (`_draw_items_table`, строки 250-310)
- Test: `tests/test_catalog_included_kit.py`

- [ ] **Step 1: Написать падающий тест**

В `tests/test_catalog_included_kit.py` добавить:

```python
@pytest.mark.parametrize('size', ['full', 'half', 'quarter'])
def test_pdf_contract_renders_with_included_kit(kit_product, customer, admin_user, size):
    from config.contract_pdf import build_contract_pdf
    rental = _make_rental_with(kit_product, customer, admin_user)
    pdf = build_contract_pdf(rental, size=size)
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 500
```

- [ ] **Step 2: Запустить — убедиться, что проходит уже сейчас (PDF не падает) — это страховка от регрессии**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_pdf_contract_renders_with_included_kit -v`
Expected: PASS (PDF и так строится). Этот тест фиксирует, что добавление под-строки комплекта не сломает генерацию. Если хочется «красного» сначала — пропустить шаг и сразу к Step 3, затем убедиться, что тест зелёный.

- [ ] **Step 3: Дорисовать строку комплекта после позиции**

В `config/contract_pdf.py`, в `_draw_items_table`, в цикле по позициям, заменить
завершение строки. Было:

```python
        if pdf.will_page_break(row_h):
            pdf.add_page()
        for text, frac, align in row:
            pdf.cell(w * frac, row_h, str(text), border=1, align=align)
        pdf.ln()
```

Стало:

```python
        if pdf.will_page_break(row_h):
            pdf.add_page()
        for text, frac, align in row:
            pdf.cell(w * frac, row_h, str(text), border=1, align=align)
        pdf.ln()
        kit = (it.product.included_kit or '').strip()
        if kit:
            pdf.set_font('Body', 'I', max(base - 1, 6))
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(
                w, row_h - 1,
                _('в комплекте') + ': ' + kit,
                border='LR', align='L',
            )
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Body', size=base)
```

Примечание: шрифт `Body` зарегистрирован с начертаниями обычный/`B`; начертание
`I` (курсив) поддерживается fpdf2 синтетически. Если на этапе прогона возникнет
ошибка про отсутствие стиля `I`, заменить `pdf.set_font('Body', 'I', ...)` на
`pdf.set_font('Body', '', ...)` (без курсива) — визуально достаточно серого цвета.

- [ ] **Step 4: Запустить тест PDF**

Run: `./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_pdf_contract_renders_with_included_kit -v`
Expected: PASS для всех трёх размеров. Если падает на стиле `I` — применить
примечание из Step 3 и повторить.

- [ ] **Step 5: Прогнать существующие PDF-тесты (регрессия)**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py -v`
Expected: PASS (все существующие).

- [ ] **Step 6: Commit**

```bash
git add config/contract_pdf.py tests/test_catalog_included_kit.py
git commit -m "feat(catalog): show included_kit on PDF contract"
```

---

### Task 6: Миграция данных — категории, товары, деактивация старых

**Files:**
- Create: `config/migrations/0016_seed_formwork_catalog.py`
- Test: `tests/test_management_commands.py` (или новый блок в `tests/test_catalog_included_kit.py`)

Зависит от `0015_product_included_kit` (поле уже есть). Миграция идемпотентная
(`get_or_create`), использует исторические модели через `apps.get_model`.

- [ ] **Step 1: Создать пустую миграцию**

Run: `./venv/bin/python manage.py makemigrations config --empty -n seed_formwork_catalog`
Expected: создан `config/migrations/0016_seed_formwork_catalog.py`.

- [ ] **Step 2: Заполнить миграцию**

Полностью заменить содержимое `config/migrations/0016_seed_formwork_catalog.py` на:

```python
from django.db import migrations

# (категория, [(размер, included_kit), ...])
KIT_KOR_3 = 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3'
KIT_KOR_2 = 'Зажим ×2, Фиксатор ×2, Тайрод р/калпокча ×2, Штир/шайба ×2'
KIT_KOR_ANGLE = 'Зажим ×2'

KOREAN = [
    ('2×1', KIT_KOR_3), ('2×80', KIT_KOR_3), ('2×70', KIT_KOR_3),
    ('2×60', KIT_KOR_3), ('2×50', KIT_KOR_3), ('2×40', KIT_KOR_3),
    ('2×20', KIT_KOR_3), ('2×10', KIT_KOR_3), ('2×30', KIT_KOR_3),
    ('1.5×1', KIT_KOR_3), ('1×1', KIT_KOR_3), ('1×80', KIT_KOR_3),
    ('1×70', KIT_KOR_3),
    ('1×60', KIT_KOR_2), ('1×50', KIT_KOR_2), ('1×40', KIT_KOR_2),
    ('1×30', KIT_KOR_2), ('1×20', KIT_KOR_2), ('1×10', KIT_KOR_2),
    ('1×05', KIT_KOR_2), ('50×50', KIT_KOR_2), ('50×40', KIT_KOR_2),
    ('50×30', KIT_KOR_2), ('50×20', KIT_KOR_2), ('50×10', KIT_KOR_2),
    ('вуг1м', KIT_KOR_ANGLE), ('вуг50', KIT_KOR_ANGLE),
    ('вуг2м', KIT_KOR_ANGLE), ('наруг2м', KIT_KOR_ANGLE),
    ('наруг1м', KIT_KOR_ANGLE), ('наруг50', KIT_KOR_ANGLE),
]

FINNISH = [
    ('2.2×60', 'Штир/шайба ×3'), ('2.2×50', 'Штир/шайба ×3'),
    ('2.2×40', 'Штир/шайба ×3'), ('2.2×30', 'Штир/шайба ×3'),
    ('2.2×20', 'Штир/шайба ×3'),
]

COLUMN = [
    ('3.11×40', 'Тайрод ×20'), ('3.11×60', 'Тайрод ×20'),
    ('3.11×80', 'Тайрод ×20'), ('3.11×1', 'Тайрод ×20'),
    ('3.7×40', 'Тайрод ×24'), ('3.72×60', 'Тайрод ×24'),
    ('1.22×040', 'Тайрод ×8'), ('1.22×0.60', 'Тайрод ×8'),
    ('3×50', 'Тайрод ×24'),
]

# категория -> (префикс названия товара, список (размер, kit))
GROUPS = [
    ('Корейская опалубка', 'Корейская опалубка', KOREAN),
    ('Финская опалубка', 'Финская опалубка', FINNISH),
    ('Колонна', 'Колонна', COLUMN),
]

# одиночные товары: (категория, имя товара, kit)
SINGLES = [
    ('Стойка телескопическая домкрат', 'Стойка телескопическая домкрат', 'Крючок ×1'),
    ('Леса строительные', 'Леса строительные', 'Крестик ×2'),
]

# старые обобщённые товары — деактивировать
DEACTIVATE_NAMES = [
    'Корейская опалубка',
    'Колонна',
    'Финская фанера',
    'Стойка телескопическая 3.0 м',
]


def seed(apps, schema_editor):
    Category = apps.get_model('config', 'Category')
    Product = apps.get_model('config', 'Product')

    # Деактивируем старые ДО создания новых, чтобы не задеть новые по имени.
    Product.objects.filter(name__in=DEACTIVATE_NAMES).update(is_active=False)

    for cat_name, prefix, rows in GROUPS:
        cat, _ = Category.objects.get_or_create(name=cat_name)
        for size, kit in rows:
            name = f'{prefix} {size}'
            Product.objects.get_or_create(
                name=name,
                defaults={
                    'category': cat,
                    'unit': 'шт',
                    'stock_total': 0,
                    'daily_price': 0,
                    'deposit_per_unit': 0,
                    'is_active': True,
                    'included_kit': kit,
                },
            )

    for cat_name, name, kit in SINGLES:
        cat, _ = Category.objects.get_or_create(name=cat_name)
        Product.objects.get_or_create(
            name=name,
            defaults={
                'category': cat,
                'unit': 'шт',
                'stock_total': 0,
                'daily_price': 0,
                'deposit_per_unit': 0,
                'is_active': True,
                'included_kit': kit,
            },
        )


def unseed(apps, schema_editor):
    # Мягкий откат: удаляем только созданные товары и пустые новые категории.
    # Старые деактивированные товары обратно НЕ включаем (состояние неизвестно).
    Category = apps.get_model('config', 'Category')
    Product = apps.get_model('config', 'Product')

    names = []
    for _cat, prefix, rows in GROUPS:
        names += [f'{prefix} {size}' for size, _kit in rows]
    names += [name for _cat, name, _kit in SINGLES]
    Product.objects.filter(name__in=names).delete()

    for cat_name in ['Корейская опалубка', 'Финская опалубка', 'Колонна',
                     'Стойка телескопическая домкрат', 'Леса строительные']:
        cat = Category.objects.filter(name=cat_name).first()
        if cat and not cat.products.exists():
            cat.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('config', '0015_product_included_kit'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
```

- [ ] **Step 3: Написать тест миграции/итогового состояния**

В `tests/test_catalog_included_kit.py` добавить (работает на уже мигрированной
тестовой БД — данные сидируются миграцией):

```python
def test_seed_created_catalog(db):
    from config.models import Category, Product
    # Категории созданы
    for name in ['Корейская опалубка', 'Финская опалубка', 'Колонна',
                 'Стойка телескопическая домкрат', 'Леса строительные']:
        assert Category.objects.filter(name=name).exists(), name
    # Конкретные товары с комплектом
    p = Product.objects.get(name='Корейская опалубка 2×1')
    assert p.included_kit == 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3'
    assert p.unit == 'шт' and p.daily_price == 0
    col = Product.objects.get(name='Колонна 3.7×40')
    assert col.included_kit == 'Тайрод ×24'
    # Кол-во новых товаров
    assert Product.objects.filter(category__name='Корейская опалубка').count() == 31
    assert Product.objects.filter(category__name='Финская опалубка').count() == 5
    assert Product.objects.filter(category__name='Колонна').count() == 9
    # Старые деактивированы
    old = Product.objects.filter(
        name__in=['Финская фанера', 'Стойка телескопическая 3.0 м'],
    )
    assert old.exists()
    assert all(not p.is_active for p in old)
```

- [ ] **Step 4: Применить миграцию и прогнать тест**

Run: `./venv/bin/python manage.py migrate config && ./venv/bin/python -m pytest tests/test_catalog_included_kit.py::test_seed_created_catalog -v`
Expected: PASS.

- [ ] **Step 5: Проверить идемпотентность (повторный прогон сидирования)**

Run:
```
./venv/bin/python manage.py shell -c "from config.migrations import __name__; import importlib; m=importlib.import_module('config.migrations.0016_seed_formwork_catalog'); from django.apps import apps; m.seed(apps, None); from config.models import Product; print('korean', Product.objects.filter(category__name='Корейская опалубка').count())"
```
Expected: `korean 31` (повторный вызов `seed` не создаёт дублей).

- [ ] **Step 6: Commit**

```bash
git add config/migrations/0016_seed_formwork_catalog.py tests/test_catalog_included_kit.py
git commit -m "feat(catalog): seed formwork products with included_kit, deactivate legacy items"
```

---

### Task 7: Финальная проверка всего набора тестов

**Files:** —

- [ ] **Step 1: Прогнать весь тестовый набор**

Run: `./venv/bin/python -m pytest -q`
Expected: все тесты зелёные (включая существующие salary/billing/contract тесты).

- [ ] **Step 2: Если есть падения — чинить по месту, затем повторить Step 1.**

- [ ] **Step 3: Финальный commit (если были правки)**

```bash
git add -A
git commit -m "test(catalog): full suite green for included_kit feature"
```

---

## Self-review (выполнено автором плана)

- **Покрытие спека:** поле `included_kit` (Task 1), форма (Task 2), список+админка
  (Task 3), HTML-договор (Task 4), PDF-договор (Task 5), миграция данных +
  деактивация старых (Task 6), регрессия (Task 7). Все разделы спека покрыты.
- **Плейсхолдеры:** отсутствуют — везде конкретный код и команды.
- **Согласованность имён:** поле `included_kit` единообразно во всех тасках;
  имена товаров строятся как `f'{prefix} {size}'`; категории совпадают между
  `seed`/`unseed` и тестом.
- **Данные:** Корейская 31, Финская 5, Колонна 9, + 2 одиночных = 47 товаров,
  5 категорий — совпадает со спеком.
