# Своя цена позиции при создании аренды — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Админ задаёт цену за сутки для конкретной позиции прямо в форме
создания аренды — до создания, при выборе товара; цена относится только к этой
аренде и не меняет справочник.

**Architecture:** Модель не меняется — `RentalItem.price_per_day` уже снимок,
независимый от `Product.daily_price`. В строку позиции добавляется денежное поле
`item_price` (видно только админу), `RentalCreateView` разбирает его по индексу
строки и применяет вместо `product.daily_price`. Разбор денежной строки
выносится в общий хелпер `parse_money` в `config/forms.py` поверх уже
существующего `_strip_money_spaces`, и на него же переводится
`RentalItemEditView`.

**Tech Stack:** Django 5 (шаблоны, `{% trans %}`, `gettext`), htmx, ванильный JS,
pytest + pytest-django, Bootstrap 5.

**Спека:** `docs/superpowers/specs/2026-07-31-rental-create-custom-price-design.md`

## Global Constraints

- Ветка `feat/rental-create-custom-price` уже создана от `main`, спека в неё
  закоммичена. Работаем в ней.
- Тесты гоняем из корня репо: `pytest`.
- Права: цену принимает **только админ** — `user_is_admin(request.user)`
  (`config/decorators.py`, уже импортирован в `config/views.py`). Для staff поле
  не рендерится и `item_price` в POST игнорируется.
- Валидация: любая цена ≥ 0, ноль допустим. Пустое поле — **не** ошибка, берётся
  `product.daily_price`.
- Тексты ошибок (копировать посимвольно, в `_()`):
  - `Строка %(i)d: цена за сутки указана неверно.`
  - `Строка %(i)d: цена за сутки не может быть отрицательной.`
- Метка поля (копировать посимвольно): `Цена/сут.` — со слешем и точкой после
  «сут». Следует конвенции репо («Цена/сут.», «Σ/сут.»).
- Денежное поле следует проектной конвенции: `type="text"` +
  `class="form-control money-input"` + `inputmode="decimal"`, как у
  `initial_deposit` (`_money_widget` в `config/forms.py`).
  `static/js/money-input.js` подключён глобально в `templates/base.html` и сам
  цепляется к таким полям, в том числе к строкам, вставленным через htmx.
- `locale/*.po` не пересобираем: `LANGUAGE_CODE = 'ru'`, для строки без перевода
  Django отдаёт msgid как есть — то есть русский оригинал.
- Не трогаем: модель `RentalItem` и миграции, `config/billing.py`, PDF/печать
  (`contract_pdf.py`, `return_receipt_pdf.py`), модалку «Добавить позицию»
  (`RentalItemAddView`).

---

## File Structure

- `config/forms.py` — **modify.** Добавляем публичный хелпер `parse_money(raw)`
  рядом с `_strip_money_spaces`. Единственное место, где живёт разбор денежной
  строки в `Decimal`.
- `config/views.py` — **modify.** `RentalCreateView`: разбор/валидация/применение
  `item_price`. `RentalItemEditView`: перевод на `parse_money`. `ItemRowNewView`:
  ключ `price` в заготовке строки.
- `config/templates/config/rentals/_item_row.html` — **modify.** Колонка
  «Цена/сут.» под `{% if is_admin %}` + перераскладка колонок.
- `static/js/rental-create.js` — **modify.** Автоподстановка цены из справочника
  и расчёт подытогов от введённой цены.
- `tests/test_money_input.py` — **modify.** Юнит-тесты `parse_money` (файл уже
  держит тесты `_strip_money_spaces` и `MoneyDecimalField`).
- `tests/test_rental_create_price.py` — **create.** Тесты фичи целиком.

---

## Task 1: Хелпер `parse_money` и перевод правки позиции на него

**Files:**
- Modify: `config/forms.py` (импорт `decimal`, новая функция после
  `_strip_money_spaces`)
- Modify: `config/views.py` (`RentalItemEditView.post`)
- Test: `tests/test_money_input.py`

**Interfaces:**
- Consumes: `_strip_money_spaces(raw)` из `config/forms.py` — снимает
  пробелы-разделители тысяч только при корректной группировке и нормализует
  запятую в точку.
- Produces: `parse_money(raw) -> Decimal | None` в `config/forms.py`. Возвращает
  `Decimal`, округлённый до двух знаков, либо `None`, если значение пустое,
  не число, `NaN` или бесконечность. Знак **не** проверяет — `'-5'` вернётся как
  `Decimal('-5.00')`, отвергать отрицательное — дело вызывающего.
  Используется в Task 3.

- [ ] **Step 1: Написать падающие тесты хелпера**

Дописать в конец `tests/test_money_input.py`:

```python
# ---------- parse_money ----------

def test_parse_money_plain_decimal():
    assert parse_money('250.50') == Decimal('250.50')


def test_parse_money_ru_grouping_and_comma():
    assert parse_money('1 234,50') == Decimal('1234.50')


def test_parse_money_nbsp_grouping():
    assert parse_money('40\xa0000') == Decimal('40000.00')


def test_parse_money_quantizes_to_kopecks():
    assert parse_money('10.006') == Decimal('10.01')


def test_parse_money_keeps_negative_sign():
    """Знак — не дело парсера; отвергает минус вызывающий код."""
    assert parse_money('-5') == Decimal('-5.00')


def test_parse_money_rejects_garbage():
    assert parse_money('abc') is None


def test_parse_money_rejects_empty():
    assert parse_money('') is None
    assert parse_money('   ') is None
    assert parse_money(None) is None


def test_parse_money_rejects_nan_and_infinity():
    """Decimal сам по себе принимает 'nan'/'Infinity' — их надо отсечь."""
    assert parse_money('nan') is None
    assert parse_money('Infinity') is None
```

И расширить импорт в шапке файла:

```python
from config.forms import (
    MoneyDecimalField, PaymentForm, _strip_money_spaces, parse_money,
)
```

- [ ] **Step 2: Прогнать тесты — убедиться, что падают**

Run: `pytest tests/test_money_input.py -q`
Expected: FAIL — `ImportError: cannot import name 'parse_money' from 'config.forms'`

- [ ] **Step 3: Реализовать `parse_money`**

В `config/forms.py` заменить строку импорта

```python
from decimal import Decimal
```

на

```python
from decimal import Decimal, InvalidOperation
```

и добавить функцию сразу после `_strip_money_spaces` (перед классом
`MoneyDecimalField`):

```python
def parse_money(raw):
    """Разобрать денежную строку в ``Decimal`` с округлением до копеек.

    Терпит ru-ввод: пробелы-разделители тысяч (обычный, неразрывный, тонкий)
    и запятую как разделитель дроби — нормализация ровно та же, что у
    ``MoneyDecimalField``. Возвращает ``None``, если значение пустое или не
    разбирается в конечное число (в том числе для 'nan'/'Infinity', которые
    ``Decimal`` принял бы молча).

    Знак не проверяется: решение, допустима ли отрицательная сумма, остаётся
    за вызывающим кодом.
    """
    if raw is None:
        return None
    s = _strip_money_spaces(str(raw).strip())
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
```

- [ ] **Step 4: Прогнать тесты — убедиться, что проходят**

Run: `pytest tests/test_money_input.py -q`
Expected: PASS (все, включая ранее существовавшие)

- [ ] **Step 5: Перевести `RentalItemEditView` на хелпер**

В `config/views.py` в импорте из `.forms` добавить `parse_money` (список
импортируемых имён отсортирован по алфавиту — вставить между `MoneyDecimalField`
и `PaymentForm`):

```python
from .forms import (
    CategoryForm,
    CustomerForm,
    MoneyDecimalField,
    parse_money,
    PaymentForm,
    ProductForm,
    RentalCreateForm,
    RentalEditForm,
    SalaryEntryForm,
    WorkerForm,
)
```

В `RentalItemEditView.post` заменить блок

```python
        new_price = None
        if 'price_per_day' in request.POST:
            price_raw = (request.POST.get('price_per_day') or '').strip()
            price_norm = (price_raw.replace(' ', '')
                          .replace('\xa0', '').replace(',', '.'))
            try:
                parsed = Decimal(price_norm)
            except (InvalidOperation, TypeError, ValueError):
                parsed = None
            if parsed is None:
                errors.append(_('Цена за сутки указана неверно.'))
            elif parsed < 0:
                errors.append(_('Цена за сутки не может быть отрицательной.'))
            else:
                new_price = parsed.quantize(Decimal('0.01'))
```

на

```python
        new_price = None
        if 'price_per_day' in request.POST:
            parsed = parse_money(request.POST.get('price_per_day'))
            if parsed is None:
                errors.append(_('Цена за сутки указана неверно.'))
            elif parsed < 0:
                errors.append(_('Цена за сутки не может быть отрицательной.'))
            else:
                new_price = parsed
```

Комментарий над блоком («Цена — снимок именно этой аренды…») оставить как есть.

- [ ] **Step 6: Прогнать тесты правки позиции — поведение не изменилось**

Run: `pytest tests/test_money_input.py tests/test_rental_item_price_edit.py -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add config/forms.py config/views.py tests/test_money_input.py
git commit -m "refactor(forms): общий parse_money для разбора денежных строк"
```

---

## Task 2: Поле «Цена/сут.» в строке позиции (только админу)

**Files:**
- Modify: `config/templates/config/rentals/_item_row.html`
- Modify: `config/views.py` (`RentalCreateView._initial_context`,
  `RentalCreateView._rows_for_template`, `ItemRowNewView.get`)
- Test: `tests/test_rental_create_price.py` (create)

**Interfaces:**
- Consumes: `is_admin` из контекст-процессора `config.context_processors.navigation`
  (зарегистрирован в `rental_track/settings.py`, доступен в любом
  `render(request, …)`, в том числе в htmx-фрагменте новой строки).
- Produces: поле `<input name="item_price" class="money-input item-price">` в
  каждой строке позиции при `is_admin`; ключ `price` в словаре строки
  (`row.price`), который заполняют `_initial_context`, `_rows_for_template` и
  `ItemRowNewView`. Разбор этого поля — Task 3.

- [ ] **Step 1: Написать падающие тесты видимости поля**

Создать `tests/test_rental_create_price.py`:

```python
"""Админ задаёт цену позиции прямо в форме создания аренды (до создания).

Цена — снимок этой аренды (`RentalItem.price_per_day`); справочник товара
(`Product.daily_price`) не меняется. Оператору (staff) поле не показывается и
из его POST игнорируется.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Product, Rental, RentalItem


def _url():
    """Реверсим внутри теста, а не на импорте: проект под i18n_patterns,
    и адрес зависит от активного языка."""
    return reverse('rental_create')


def _payload(customer, product, price=None, qty='5'):
    """POST формы создания аренды с одной позицией.

    ``price=None`` — поля цены в запросе нет вовсе (как у staff).
    """
    data = {
        'customer': str(customer.pk),
        'created_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk)],
        'item_qty': [qty],
    }
    if price is not None:
        data['item_price'] = [price]
    return data


# ---------- рендер формы ----------

def test_price_field_visible_for_admin(client_admin):
    body = client_admin.get(_url()).content.decode()
    assert 'name="item_price"' in body


def test_price_field_hidden_for_staff(client_staff):
    body = client_staff.get(_url()).content.decode()
    assert 'name="item_price"' not in body


def test_new_row_fragment_has_price_field_for_admin(client_admin):
    """Строка, добавленная кнопкой «+ Позиция», тоже должна иметь поле цены."""
    body = client_admin.get(reverse('rental_item_row_new')).content.decode()
    assert 'name="item_price"' in body


def test_new_row_fragment_has_no_price_field_for_staff(client_staff):
    body = client_staff.get(reverse('rental_item_row_new')).content.decode()
    assert 'name="item_price"' not in body
```

- [ ] **Step 2: Прогнать тесты — убедиться, что падают**

Run: `pytest tests/test_rental_create_price.py -q`
Expected: FAIL — 2 теста на наличие `name="item_price"` падают
(`assert 'name="item_price"' in body`); 2 теста на staff проходят,
потому что поля пока нет ни у кого.

- [ ] **Step 3: Добавить колонку цены в шаблон строки**

Заменить содержимое `config/templates/config/rentals/_item_row.html` целиком:

```html
{% load i18n %}
<div class="row g-2 align-items-end mb-2 item-row" id="row-{{ row.row_id }}">
    <div class="col-md-4">
        <label class="form-label small text-muted mb-1">{% trans "Товар" %}</label>
        {% if row.product %}
            {% include 'config/rentals/_item_product_picked.html' with product=row.product row_id=row.row_id %}
        {% else %}
            {% include 'config/rentals/_item_product_search.html' with row_id=row.row_id %}
        {% endif %}
    </div>
    <div class="col-md-2">
        <label class="form-label small text-muted mb-1">{% trans "Кол-во" %}</label>
        <input type="number" name="item_qty" min="1" class="form-control item-qty"
               value="{{ row.qty }}" placeholder="0">
    </div>
    {% if is_admin %}
        {% comment %}
          Цена — снимок именно этой аренды; справочник товара не меняется.
          Пусто = взять цену из справочника. Поле только для админа: у staff
          его нет в разметке, и сервер игнорирует item_price из его POST.
        {% endcomment %}
        <div class="col-md-2">
            <label class="form-label small text-muted mb-1">{% trans "Цена/сут." %}</label>
            <input type="text" name="item_price" inputmode="decimal"
                   autocomplete="off" placeholder="0"
                   class="form-control money-input item-price"
                   value="{{ row.price }}">
        </div>
    {% endif %}
    <div class="{% if is_admin %}col-md-3{% else %}col-md-4{% endif %}">
        <div class="small mt-1">
            {% trans "Подытог:" %}
            <strong class="row-subtotal text-primary">0.00</strong>
            <span class="text-muted">{% trans "сум" %}</span>
        </div>
    </div>
    <div class="col-md-1 text-end">
        <button type="button"
                class="btn btn-outline-danger btn-sm"
                title="{% trans 'Удалить позицию' %}"
                hx-post="{% url 'rental_item_row_remove' %}"
                hx-target="#row-{{ row.row_id }}"
                hx-swap="delete">×</button>
    </div>
</div>
```

- [ ] **Step 4: Добавить ключ `price` в заготовки строк**

В `config/views.py`, в `RentalCreateView._initial_context`:

```python
            'item_rows': [{'row_id': uuid.uuid4().hex[:8], 'product': None,
                           'qty': '', 'price': ''}],
```

В `RentalCreateView._rows_for_template` — в оба места, где создаётся словарь
строки:

```python
            out.append({
                'row_id': row_id,
                'product': product,
                'qty': r.get('qty', ''),
                'price': r.get('price_raw', ''),
            })
        if not out:
            out = [{'row_id': uuid.uuid4().hex[:8], 'product': None,
                    'qty': '', 'price': ''}]
        return out
```

(`price_raw` появится в строках в Task 3; до этого `.get` вернёт `''` — шаблон
отрендерит пустое поле, тесты этого шага на это не опираются.)

В `ItemRowNewView.get`:

```python
    def get(self, request):
        return render(request, 'config/rentals/_item_row.html', {
            'row': {'row_id': uuid.uuid4().hex[:8], 'product': None,
                    'qty': '', 'price': ''},
        })
```

- [ ] **Step 5: Прогнать тесты — убедиться, что проходят**

Run: `pytest tests/test_rental_create_price.py -q`
Expected: PASS (4 теста)

- [ ] **Step 6: Прогнать весь набор — раскладка колонок ничего не сломала**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add config/templates/config/rentals/_item_row.html config/views.py tests/test_rental_create_price.py
git commit -m "feat(rentals): поле «Цена/сут.» в строке позиции формы создания"
```

---

## Task 3: Разбор, валидация и применение цены на сервере

**Files:**
- Modify: `config/views.py` (`RentalCreateView.post`, `_parse_item_rows`,
  `_validate_items`, `_create_rental`)
- Test: `tests/test_rental_create_price.py`

**Interfaces:**
- Consumes: `parse_money(raw) -> Decimal | None` из `config/forms.py` (Task 1);
  `user_is_admin(user) -> bool` из `config/decorators.py` (уже импортирован в
  `config/views.py`); поле `item_price` из разметки строки (Task 2).
- Produces: ключи `price_raw` (сырая строка из POST, для возврата в форму) и
  `price` (`Decimal`, только если разобралась и неотрицательна) в словарях
  строк, которые ходят между `_parse_item_rows` → `_validate_items` →
  `_create_rental` / `_rows_for_template`.

- [ ] **Step 1: Написать падающие тесты поведения**

Дописать в конец `tests/test_rental_create_price.py`:

```python
# ---------- применение цены ----------

def test_admin_sets_custom_price(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, '250.50'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('250.50')


def test_custom_price_does_not_touch_catalog(client_admin, customer, product):
    """Цена аренды — снимок: справочник товара остаётся прежним."""
    client_admin.post(_url(), data=_payload(customer, product, '250.50'))
    product.refresh_from_db()
    assert product.daily_price == Decimal('100.00')


def test_empty_price_falls_back_to_catalog(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, ''))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == product.daily_price


def test_price_accepts_ru_grouping_and_comma(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, '1 234,50'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('1234.50')


def test_zero_price_allowed(client_admin, customer, product):
    """Ноль — валидная цена: бесплатная выдача."""
    resp = client_admin.post(_url(), data=_payload(customer, product, '0'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('0.00')


# ---------- ошибки ----------

def test_invalid_price_blocks_creation(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, 'abc'))
    assert resp.status_code == 200
    assert 'цена за сутки указана неверно' in resp.content.decode().lower()
    assert not Rental.objects.filter(customer=customer).exists()


def test_negative_price_blocks_creation(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, '-5'))
    assert resp.status_code == 200
    assert 'отрицательной' in resp.content.decode().lower()
    assert not Rental.objects.filter(customer=customer).exists()


def test_entered_price_survives_validation_error(client_admin, customer, product):
    """Ошибка в количестве не должна стирать уже введённую цену."""
    resp = client_admin.post(_url(),
                             data=_payload(customer, product, '777.00', qty='0'))
    assert resp.status_code == 200
    assert 'value="777.00"' in resp.content.decode()
    assert not Rental.objects.filter(customer=customer).exists()


# ---------- права ----------

def test_staff_price_is_ignored(client_staff, customer, product):
    """Подделанный POST от staff не должен менять цену."""
    resp = client_staff.post(_url(), data=_payload(customer, product, '1.00'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == product.daily_price


# ---------- несколько строк ----------

def test_prices_are_not_mixed_between_rows(client_admin, customer, product,
                                           category):
    other = Product.objects.create(
        name='Второй товар', category=category, unit='шт',
        stock_total=100, daily_price=Decimal('300.00'),
    )
    resp = client_admin.post(_url(), data={
        'customer': str(customer.pk),
        'created_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk), str(other.pk)],
        'item_qty': ['2', '3'],
        'item_price': ['11.00', '22.00'],
    })
    assert resp.status_code == 302, resp.content[:400]
    prices = {
        it.product_id: it.price_per_day
        for it in RentalItem.objects.filter(rental__customer=customer)
    }
    assert prices[product.pk] == Decimal('11.00')
    assert prices[other.pk] == Decimal('22.00')
```

- [ ] **Step 2: Прогнать тесты — убедиться, что падают**

Run: `pytest tests/test_rental_create_price.py -q`
Expected: FAIL — `item.price_per_day == Decimal('100.00')` вместо заданной цены;
тесты ошибок падают, потому что аренда создаётся (302 вместо 200).

- [ ] **Step 3: Передать признак админа в разбор строк**

В `config/views.py`, в `RentalCreateView.post`, заменить

```python
        rows = self._parse_item_rows(request.POST)
```

на

```python
        rows = self._parse_item_rows(
            request.POST, can_set_price=user_is_admin(request.user),
        )
```

- [ ] **Step 4: Читать `item_price` по индексу строки**

Заменить `RentalCreateView._parse_item_rows` целиком:

```python
    def _parse_item_rows(self, post, *, can_set_price=False):
        product_ids = post.getlist('item_product')
        qtys = post.getlist('item_qty')
        # Цену принимаем только от админа: у оператора поля в форме нет, и
        # подделанный POST не должен на неё влиять.
        #
        # Читаем по индексу строки, а НЕ через zip: у оператора список пустой,
        # и zip обнулил бы все строки разом. Скрытый item_product рендерится
        # даже пустым (см. _item_product_search.html), поэтому индексы строк
        # совпадают во всех трёх списках.
        prices = post.getlist('item_price') if can_set_price else []
        rows = []
        for i, (pid_raw, qty_raw) in enumerate(zip(product_ids, qtys)):
            pid_raw = (pid_raw or '').strip()
            qty_raw = (qty_raw or '').strip()
            price_raw = (prices[i] if i < len(prices) else '').strip()
            if not pid_raw and not qty_raw:
                continue
            try:
                pid = int(pid_raw)
                qty = int(qty_raw)
            except (TypeError, ValueError):
                rows.append({'product_id': pid_raw, 'qty': qty_raw,
                             'price_raw': price_raw, 'invalid': True})
                continue
            rows.append({'product_id': pid, 'qty': qty,
                         'price_raw': price_raw, 'invalid': False})
        return rows
```

- [ ] **Step 5: Валидировать цену**

В `RentalCreateView._validate_items`, внутри цикла `for i, r in enumerate(rows,
start=1):`, сразу после блока `if r.get('invalid'): … continue` и **до**
проверки `if r['qty'] <= 0:` вставить:

```python
            # Цена — снимок этой аренды. Пусто = взять из справочника.
            # Проверяем до проверок количества/товара: ошибки независимы и
            # оператор должен увидеть их все сразу.
            price_raw = (r.get('price_raw') or '').strip()
            if price_raw:
                price = parse_money(price_raw)
                if price is None:
                    errors.append(
                        _('Строка %(i)d: цена за сутки указана неверно.')
                        % {'i': i}
                    )
                elif price < 0:
                    errors.append(
                        _('Строка %(i)d: цена за сутки не может быть '
                          'отрицательной.') % {'i': i}
                    )
                else:
                    r['price'] = price
```

- [ ] **Step 6: Применить цену при создании позиции**

В `RentalCreateView._create_rental` заменить

```python
            item = RentalItem.objects.create(
                rental=rental,
                product=product,
                qty=r['qty'],
                price_per_day=product.daily_price,
            )
```

на

```python
            # Цена, заданная админом в форме, иначе — из справочника.
            price = r.get('price')
            if price is None:
                price = product.daily_price
            item = RentalItem.objects.create(
                rental=rental,
                product=product,
                qty=r['qty'],
                price_per_day=price,
            )
```

- [ ] **Step 7: Прогнать тесты фичи — убедиться, что проходят**

Run: `pytest tests/test_rental_create_price.py -q`
Expected: PASS (13 тестов)

- [ ] **Step 8: Прогнать весь набор**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 9: Коммит**

```bash
git add config/views.py tests/test_rental_create_price.py
git commit -m "feat(rentals): своя цена позиции при создании аренды (только админ)"
```

---

## Task 4: Автоподстановка цены и живой расчёт

**Files:**
- Modify: `static/js/rental-create.js`

**Interfaces:**
- Consumes: `data-price` на скрытом `input[name="item_product"]`
  (`_item_product_picked.html` уже отдаёт `{{ product.daily_price|unlocalize }}`,
  `_item_product_search.html` — `"0"` при пустом выборе); класс `item-price` на
  поле цены (Task 2); `static/js/money-input.js`, который форматирует значение по
  событию `input` и подключён в `templates/base.html` **до** `rental-create.js`.
- Produces: ничего для других задач — последний шаг.

Логики без покрытия автотестами тут нет только потому, что в репозитории нет
браузерного раннера (ни Playwright, ни jest — см. `requirements.txt` и
`pytest.ini`); заводить его ради одного файла — вне объёма. Проверяем вручную по
чеклисту в Step 5.

- [ ] **Step 1: Добавить разбор денежной строки в JS**

В `static/js/rental-create.js`, сразу после объявления `fmt` (перед `readDt`),
добавить:

```js
    // В поле цены лежит отформатированное значение вида «40 000.50»
    // (money-input.js), поэтому перед разбором снимаем пробелы и приводим
    // запятую к точке — той же нормализацией, что делает бэкенд.
    function parseMoney(raw) {
        var s = String(raw == null ? '' : raw).replace(/\s/g, '').replace(',', '.');
        var n = parseFloat(s);
        return isNaN(n) ? 0 : n;
    }
```

- [ ] **Step 2: Считать подытоги от введённой цены**

В `recalc()` заменить блок чтения цены

```js
            var price = 0;
            if (pidInp && pidInp.dataset.price) {
                price = parseFloat(pidInp.dataset.price) || 0;
            } else if (sel) {
                var opt = sel.options[sel.selectedIndex];
                price = parseFloat((opt && opt.dataset.price) || '0') || 0;
            }
```

на

```js
            // Приоритет — цена, введённая админом в строке. Пустое поле
            // (или его отсутствие у оператора) означает «цена из справочника».
            var priceInp = row.querySelector('input.item-price');
            var price = 0;
            if (priceInp && priceInp.value.trim() !== '') {
                price = parseMoney(priceInp.value);
            } else if (pidInp && pidInp.dataset.price) {
                price = parseFloat(pidInp.dataset.price) || 0;
            } else if (sel) {
                var opt = sel.options[sel.selectedIndex];
                price = parseFloat((opt && opt.dataset.price) || '0') || 0;
            }
```

- [ ] **Step 3: Подставлять цену справочника при выборе товара**

Добавить функцию сразу после `syncDueDate()`:

```js
    // Подставить цену товара в поле «Цена/сут.», пока админ не правил его сам.
    // «Тронутость» храним на самом input (data-touched), чтобы состояние не
    // протекало между экземплярами формы — так же, как для срока возврата.
    function syncPrices() {
        document.querySelectorAll('.item-row').forEach(function (row) {
            var priceInp = row.querySelector('input.item-price');
            var pidInp = row.querySelector('input[name="item_product"]');
            if (!priceInp || !pidInp) return;          // оператор: поля нет
            if (priceInp.dataset.touched === '1') return;
            if (!pidInp.value) return;                 // товар не выбран
            var price = pidInp.dataset.price || '';
            if (!price) return;
            if (parseMoney(priceInp.value) === parseFloat(price)) return;
            priceInp.value = price;
            // money-input.js форматирует значение по событию input; заодно
            // отрабатывает наш пересчёт подытогов.
            priceInp.dispatchEvent(new Event('input', {bubbles: true}));
        });
    }
```

- [ ] **Step 4: Помечать ручную правку и вызывать `syncPrices`**

Добавить функцию рядом с `markDueTouched`:

```js
    // Ручная правка цены замораживает автоподстановку для этой строки.
    // isTrusted отсекает наше же синтетическое событие из syncPrices().
    function markPriceTouched(e) {
        var el = e.target;
        if (!el || !el.classList || !el.classList.contains('item-price')) return;
        if (!e.isTrusted) return;
        el.dataset.touched = '1';
    }
```

Затем добавить её вызов в оба обработчика и вызвать `syncPrices()` там же, где
уже вызывается `syncDueDate()`:

```js
    document.addEventListener('input', function (e) {
        markDueTouched(e.target);
        markPriceTouched(e);
        if (e.target && e.target.name === 'created_at') syncDueDate();
        recalc();
    });
    document.addEventListener('change', function (e) {
        markDueTouched(e.target);
        markPriceTouched(e);
        recalc();
    });

    // htmx подменил строку/пикер/вставил модалку — пересчитать и подстроить.
    document.body.addEventListener('htmx:afterSettle', function () {
        syncDueDate();
        syncPrices();
        recalc();
    });

    document.addEventListener('DOMContentLoaded', function () {
        syncDueDate();
        syncPrices();
        recalc();
    });
```

- [ ] **Step 5: Ручная проверка в браузере**

Run: `python manage.py runserver`, зайти админом на `/rentals/new/`.

Проверить по пунктам:
1. Выбрать товар → поле «Цена/сут.» заполнилось ценой справочника и
   отформатировалось с пробелами (например `40 000.00`).
2. Подытог строки и «Σ к оплате» посчитаны от этой цены.
3. Изменить цену вручную → подытог и «Σ к оплате» пересчитались.
4. Нажать «сменить» и выбрать другой товар → введённая вручную цена **не**
   перетёрлась.
5. Кнопка «+ Позиция» → в новой строке есть поле цены, выбор товара его
   заполняет.
6. Отправить форму → создана аренда с введённой ценой; на странице аренды в
   таблице позиций видна она же.
7. Зайти оператором (staff) → поля цены нет, подытоги считаются по справочнику.

- [ ] **Step 6: Прогнать весь набор**

Run: `pytest -q`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add static/js/rental-create.js
git commit -m "feat(rentals): автоподстановка и живой расчёт цены позиции"
```

---

## Финальная проверка

- [ ] **Прогнать полный набор тестов**

Run: `pytest -q`
Expected: PASS, ни одного упавшего теста

- [ ] **Проверить, что модель и миграции не тронуты**

Run: `python manage.py makemigrations --check --dry-run`
Expected: `No changes detected`
