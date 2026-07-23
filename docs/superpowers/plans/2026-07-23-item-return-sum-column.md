# Колонка «Сумма возврата» в позициях аренды — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в таблицу «Позиции» на карточке аренды колонку «Сумма возврата» — полную аренду по строке (кол-во × дни × цена, FIFO), сразу после «Возвращено».

**Architecture:** Значение — это существующий `billing.compute_item_base(item)` (возвращённое по сохранённым/авто суммам + набег по остатку до `now`). Считаем во вью `_rental_card_context` и вешаем атрибутом `it.line_base` на объект позиции — единственная точка сборки контекста для всех трёх мест рендера таблицы (страница аренды, HTMX-карточка клиента, OOB-обновление). Шаблон только выводит атрибут.

**Tech Stack:** Django 4/5, шаблоны Django + HTMX, pytest, ru-локаль (`USE_I18N=True`, `USE_THOUSAND_SEPARATOR` не задан → числа с запятой-разделителем дробной части, без разделителя тысяч: `9600,00`).

## Global Constraints

- Вся биллинг-логика живёт в `config/billing.py`; модели не импортируют `billing` (в моделях `@property` для этого не заводим).
- Денежные значения — `Decimal`, квантование `Decimal('0.01')`.
- Локаль вывода: ru, разделитель дробной — запятая, разделителя тысяч нет (`9600,00`).
- Заголовки/подписи — через `{% trans %}`.
- Не менять существующие колонки и блок «Итог»; их значения остаются прежними.
- Полный `pytest` должен оставаться зелёным.

---

### Task 1: Вью — построчная база аренды `it.line_base`

**Files:**
- Modify: `config/views.py` — функция `_rental_card_context` (сейчас строки 1196–1220)
- Test: `tests/test_rental_card.py`

**Interfaces:**
- Consumes: `billing.compute_item_base(item, as_of=None) -> Decimal`, `billing.compute_rental_billing(rental, as_of=None) -> dict` (ключ `'base'`) — уже существуют в `config/billing.py`.
- Produces: у каждого объекта в `context['items']` появляется атрибут `line_base: Decimal` (квантован до `0.01`). Свойство: `sum(it.line_base for it in items) == summary['base']`.

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `tests/test_rental_card.py`. Импорты вверху файла (после существующего блока импортов) — добавить:

```python
from config import billing
from config.views import _rental_card_context
```

Сам тест:

```python
def test_line_base_attached_and_sums_to_summary(rental_with_returns):
    """Каждая позиция получает line_base = свою базу аренды, и сумма по
    позициям сходится с базой в итоге (line_base — построчная расшифровка base).

    rental_with_returns: выдано 10, возвраты 4 (400) и 3 (300), 3 ещё на руках
    (issue сегодня → 1 день × 100 = 300) ⇒ база строки = 400+300+300 = 1000.
    """
    r, _item, _m1, _m2 = rental_with_returns
    ctx = _rental_card_context(r)

    for it in ctx['items']:
        assert it.line_base == billing.compute_item_base(it).quantize(Decimal('0.01'))

    assert sum(it.line_base for it in ctx['items']) == ctx['summary']['base']
    assert ctx['items'][0].line_base == Decimal('1000.00')
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/test_rental_card.py::test_line_base_attached_and_sums_to_summary -v`
Expected: FAIL — `AttributeError: 'RentalItem' object has no attribute 'line_base'`.

- [ ] **Step 3: Внести изменение во вью**

В `config/views.py`, функция `_rental_card_context`. Заменить начало функции и вызов `compute_rental_billing`, а также ключ `'now'`.

Было:

```python
def _rental_card_context(rental):
    """Shared context for the detail page and OOB refreshes after a return."""
    items = list(rental.items.select_related('product').all())
    movements = []
    for it in items:
        movements.extend(list(it.movements.select_related('created_by').all()))
    movements.sort(key=lambda m: m.date, reverse=True)
    # Сумма начисления по каждому возврату (сохранённая либо авто-расчёт) —
    # навешиваем прямо на объект движения, чтобы шаблон проверял `m.charge`.
    charges = billing.return_charge_map(rental)
    for m in movements:
        m.charge = charges.get(m.id)
    payments = list(rental.payments.all())
    summary = billing.compute_rental_billing(rental)
    has_outstanding = any(it.outstanding_qty > 0 for it in items)
    return {
        'rental': rental,
        'items': items,
        'movements': movements,
        'payments': payments,
        'summary': summary,
        'has_outstanding': has_outstanding,
        'today': timezone.localdate(),
        'now': timezone.now(),
    }
```

Стало:

```python
def _rental_card_context(rental):
    """Shared context for the detail page and OOB refreshes after a return."""
    now = timezone.now()
    items = list(rental.items.select_related('product').all())
    movements = []
    for it in items:
        # Полная аренда по строке (возвращённое + набег по остатку до `now`) —
        # построчная расшифровка базы аренды; вешаем на объект для шаблона.
        it.line_base = billing.compute_item_base(it, as_of=now).quantize(Decimal('0.01'))
        movements.extend(list(it.movements.select_related('created_by').all()))
    movements.sort(key=lambda m: m.date, reverse=True)
    # Сумма начисления по каждому возврату (сохранённая либо авто-расчёт) —
    # навешиваем прямо на объект движения, чтобы шаблон проверял `m.charge`.
    charges = billing.return_charge_map(rental)
    for m in movements:
        m.charge = charges.get(m.id)
    payments = list(rental.payments.all())
    summary = billing.compute_rental_billing(rental, as_of=now)
    has_outstanding = any(it.outstanding_qty > 0 for it in items)
    return {
        'rental': rental,
        'items': items,
        'movements': movements,
        'payments': payments,
        'summary': summary,
        'has_outstanding': has_outstanding,
        'today': timezone.localdate(),
        'now': now,
    }
```

Примечания: `Decimal`, `billing`, `timezone` уже импортированы в `config/views.py` (строки 5, 40, 27) — новые импорты не нужны. Один общий `now` передаётся и в построчный `compute_item_base`, и в `compute_rental_billing`, поэтому суммы строго сходятся (обе стороны на одну дату).

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `pytest tests/test_rental_card.py::test_line_base_attached_and_sums_to_summary -v`
Expected: PASS.

- [ ] **Step 5: Коммит**

```bash
git add config/views.py tests/test_rental_card.py
git commit -m "feat(rental): построчная база аренды it.line_base в контексте карточки"
```

---

### Task 2: Шаблон — колонка «Сумма возврата» после «Возвращено»

**Files:**
- Modify: `config/templates/config/rentals/_items_table.html` (шапка ~строка 21, тело ~строка 55)
- Test: `tests/test_rental_card.py`

**Interfaces:**
- Consumes: `it.line_base` из Task 1 (атрибут на объекте позиции в `context['items']`).

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_rental_card.py`:

```python
def test_items_table_shows_return_sum_column(client_staff, rental_with_multiday_return):
    """Колонка «Сумма возврата» показывает полную аренду строки.

    rental_with_multiday_return: 16 шт × 100/день × 6 дн = 9600 (полный возврат,
    сохранённая сумма). Значение 9600 отличается от Σ/сут.=1600, поэтому тест
    однозначный.
    """
    r, item, _m = rental_with_multiday_return
    resp = client_staff.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'Сумма возврата' in body          # заголовок колонки
    assert '9600,00' in body                  # полная аренда строки (ru-локаль)
    assert item.line_daily_cost == Decimal('1600.00')  # ≠ Σ/сут., значение не совпадает случайно
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `pytest tests/test_rental_card.py::test_items_table_shows_return_sum_column -v`
Expected: FAIL — `assert 'Сумма возврата' in body` (заголовка ещё нет).

- [ ] **Step 3: Добавить колонку в шаблон**

В `config/templates/config/rentals/_items_table.html`.

3a. Шапка. Было:

```html
                <th class="text-end">{% trans "Возвращено" %}</th>
                <th class="text-end">{% trans "Не возвращено" %}</th>
```

Стало:

```html
                <th class="text-end">{% trans "Возвращено" %}</th>
                <th class="text-end">{% trans "Сумма возврата" %}</th>
                <th class="text-end">{% trans "Не возвращено" %}</th>
```

3b. Тело строки. Было:

```html
                    <td class="text-end">{{ it.returned_qty }}</td>
                    <td class="text-end">
                        {% if it.outstanding_qty > 0 %}
```

Стало:

```html
                    <td class="text-end">{{ it.returned_qty }}</td>
                    <td class="text-end fw-semibold">{{ it.line_base }}</td>
                    <td class="text-end">
                        {% if it.outstanding_qty > 0 %}
```

Вставка идёт до admin-блока кнопок в конце строки, поэтому число ячеек согласовано и для staff, и для admin.

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `pytest tests/test_rental_card.py::test_items_table_shows_return_sum_column -v`
Expected: PASS.

- [ ] **Step 5: Прогнать весь файл тестов карточки + полный набор**

Run: `pytest tests/test_rental_card.py -v && pytest -q`
Expected: все зелёные. (Проверяем, что новая колонка не сломала существующие проверки таблицы/итога и остальной набор.)

- [ ] **Step 6: Коммит**

```bash
git add config/templates/config/rentals/_items_table.html tests/test_rental_card.py
git commit -m "feat(rental): колонка «Сумма возврата» в таблице позиций"
```

---

## Self-Review

**1. Spec coverage** (сверка со спецом `2026-07-23-item-return-sum-column-design.md`):
- Семантика «полная аренда строки» = `compute_item_base` → Task 1. ✓
- Считаем во вью, вешаем `it.line_base` → Task 1. ✓
- Один общий `now`, передан в `compute_rental_billing` (суммы сходятся) → Task 1. ✓
- Колонка после «Возвращено», формат как у денежных → Task 2. ✓
- Тест по образцу `test_items_table_shows_line_daily_cost_column`, выдача в прошлом → Task 2 (`rental_with_multiday_return`, база 9600 ≠ Σ/сут. 1600). ✓
- Свойство «сумма колонки == база итога» → Task 1 (assert). ✓
- Полный pytest зелёный → Task 2, Step 5. ✓
- Крайние случаи (нет движений → 0,00; частичный возврат; ручная сумма оператора; активная аренда) покрыты самим `compute_item_base` — отдельной логики не добавляем, доп. тесты не требуются (эти ветки уже покрыты `tests/test_billing.py`).

**2. Placeholder scan:** плейсхолдеров (TBD/TODO/«add error handling») нет; во всех code-шагах приведён реальный код. ✓

**3. Type consistency:** `line_base` — `Decimal`, квантован `0.01`; имя атрибута одинаково в Task 1 (запись во вью) и Task 2 (`{{ it.line_base }}` в шаблоне) и в тесте Task 1. `compute_item_base`/`compute_rental_billing` — сигнатуры совпадают с `config/billing.py`. ✓
