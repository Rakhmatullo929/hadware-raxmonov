# Инлайн-редактирование «Цена/сут.» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать админу менять цену за сутки прямо в ячейке «Цена/сут.» таблицы позиций (клик → поле + ✓/✗), без модалки; кнопка-карандаш остаётся для количества.

**Architecture:** HTMX «click-to-edit». Ячейка цены (для админа) — кликабельный span; клик грузит инлайн-форму в ту же ячейку; ✓ шлёт POST, который сохраняет цену и перезагружает карточку через существующий OOB-механизм (пересчёт Σ/сут., Сумма возврата, Итог); ✗ возвращает отображение. Разбор цены — общий хелпер с модалкой (DRY).

**Tech Stack:** Django 5, HTMX, Bootstrap 5, pytest (ru-локаль: `USE_I18N=True`, разделителя тысяч нет → `2500,00`).

## Global Constraints

- Правка цены — только `admin` (миксин `AdminRequiredMixin` = `role_required('admin')` → 403 для staff).
- Денежные значения — `Decimal`, квантование `Decimal('0.01')`; ввод терпит пробелы/`\xa0`/запятую-дробь.
- Ячейка цены живёт внутри OOB-региона `#rental-items`; на успешном POST главный swap подавляем (`HX-Reswap: none`), карточку обновляет только OOB.
- Заголовки/подписи — через `{% trans %}`. Формат вывода цены в ячейке — как у соседних колонок (ru, `2000,00`); формат ввода — без разделителей (`2000.00`).
- Не менять поведение модалки `rental_item_edit` и кнопки-карандаша. Полный `pytest` зелёный.

---

### Task 1: Общий хелпер разбора цены `_parse_price_per_day`

**Files:**
- Modify: `config/views.py` (добавить хелпер; переиспользовать в `RentalItemEditView.post`, строки 2313–2327)
- Test: `tests/test_rental_item_price_edit.py`

**Interfaces:**
- Produces: `_parse_price_per_day(raw) -> tuple[Decimal | None, str | None]` — `(цена, None)` при успехе; `(None, текст_ошибки)` при ошибке. Используют `RentalItemEditView` и (Task 2) `RentalItemPriceEditView`.

- [ ] **Step 1: Написать падающий тест**

Добавить в конец `tests/test_rental_item_price_edit.py`:

```python
def test_parse_price_per_day_helper():
    from config.views import _parse_price_per_day

    assert _parse_price_per_day('250')[0] == Decimal('250.00')
    assert _parse_price_per_day('1 234,50')[0] == Decimal('1234.50')
    assert _parse_price_per_day('2\xa0000,00')[0] == Decimal('2000.00')

    val, err = _parse_price_per_day('abc')
    assert val is None and err

    val, err = _parse_price_per_day('-5')
    assert val is None and err
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py::test_parse_price_per_day_helper -v`
Expected: FAIL — `ImportError: cannot import name '_parse_price_per_day'`.

- [ ] **Step 3: Добавить хелпер и переиспользовать в модалке**

В `config/views.py` добавить хелпер (рядом с прочими модульными хелперами, напр. перед `class RentalItemAddView`):

```python
def _parse_price_per_day(raw):
    """Разобрать цену за сутки из строки формы.

    Терпит пробелы-разделители, неразрывный пробел и запятую-дробь.
    Возвращает (Decimal | None, error | None): при ошибке (None, текст).
    """
    price_norm = (str(raw or '').strip()
                  .replace(' ', '').replace('\xa0', '').replace(',', '.'))
    try:
        parsed = Decimal(price_norm)
    except (InvalidOperation, TypeError, ValueError):
        return None, _('Цена за сутки указана неверно.')
    if parsed < 0:
        return None, _('Цена за сутки не может быть отрицательной.')
    return parsed.quantize(Decimal('0.01')), None
```

Заменить в `RentalItemEditView.post` блок разбора цены (строки 2313–2327). Было:

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

Стало:

```python
        new_price = None
        if 'price_per_day' in request.POST:
            new_price, price_err = _parse_price_per_day(request.POST.get('price_per_day'))
            if price_err:
                errors.append(price_err)
```

- [ ] **Step 4: Запустить тест хелпера + регрессия модалки**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py -v`
Expected: PASS — новый тест и все существующие тесты правки цены (модалка) зелёные.

- [ ] **Step 5: Коммит**

```bash
git add config/views.py tests/test_rental_item_price_edit.py
git commit -m "refactor(rental): вынести разбор цены в _parse_price_per_day"
```

---

### Task 2: Инлайн-эндпоинты и фрагменты правки цены

**Files:**
- Modify: `config/views.py` (новые вью `RentalItemPriceEditView`, `RentalItemPriceCellView`)
- Modify: `config/urls.py` (2 маршрута)
- Create: `config/templates/config/rentals/_price_cell.html`
- Create: `config/templates/config/rentals/_price_cell_edit.html`
- Test: `tests/test_rental_item_price_edit.py`

**Interfaces:**
- Consumes: `_parse_price_per_day` (Task 1); `_oob_response`, `_reload_rental`, `AdminRequiredMixin` (существуют в `config/views.py`).
- Produces: URL-имена `rental_item_price_edit` (GET/POST), `rental_item_price_cell` (GET); фрагменты `_price_cell.html`, `_price_cell_edit.html`.

- [ ] **Step 1: Написать падающие тесты**

Добавить в `tests/test_rental_item_price_edit.py`:

```python
def _inline_url(rental, item):
    return reverse('rental_item_price_edit', args=[rental.pk, item.pk])


def _cell_url(rental, item):
    return reverse('rental_item_price_cell', args=[rental.pk, item.pk])


def test_inline_get_returns_input_with_current_price(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns          # price 100.00
    resp = client_admin.get(_inline_url(r, item))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="price_per_day"' in body
    assert 'value="100.00"' in body            # текущая цена без локали
    assert _cell_url(r, item) in body          # ✗ ведёт на возврат ячейки


def test_inline_post_updates_price_and_reloads_card(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns          # qty 10
    resp = client_admin.post(_inline_url(r, item), {'price_per_day': '250'})
    assert resp.status_code == 200
    item.refresh_from_db()
    assert item.price_per_day == Decimal('250.00')
    assert resp['HX-Reswap'] == 'none'          # главный swap подавлен, только OOB
    assert '2500,00' in resp.content.decode()   # новая Σ/сут. = 250 × 10 (ru)


def test_inline_post_invalid_keeps_price(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    old = item.price_per_day
    resp = client_admin.post(_inline_url(r, item), {'price_per_day': '-5'})
    assert resp.status_code == 200
    assert 'is-invalid' in resp.content.decode()
    item.refresh_from_db()
    assert item.price_per_day == old


def test_inline_cancel_returns_plain_cell(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    resp = client_admin.get(_cell_url(r, item))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="price_per_day"' not in body   # отображение, не форма
    assert '100,00' in body                       # цена как текст (ru)


def test_inline_forbidden_for_staff(client_staff, rental_with_returns):
    r, item, *_ = rental_with_returns
    assert client_staff.get(_inline_url(r, item)).status_code == 403
    assert client_staff.post(_inline_url(r, item),
                             {'price_per_day': '5'}).status_code == 403
    assert client_staff.get(_cell_url(r, item)).status_code == 403
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py -k inline -v`
Expected: FAIL — `NoReverseMatch: 'rental_item_price_edit'` (маршрутов ещё нет).

- [ ] **Step 3: Создать фрагмент отображения ячейки**

Create `config/templates/config/rentals/_price_cell.html`:

```html
{% load i18n %}
{% if is_admin %}
    <span role="button" style="cursor: pointer;"
          title="{% trans 'Изменить цену' %}"
          hx-get="{% url 'rental_item_price_edit' rental.pk item.pk %}"
          hx-target="#price-cell-{{ item.pk }}" hx-swap="innerHTML">
        {{ item.price_per_day }}
    </span>
{% else %}
    {{ item.price_per_day }}
{% endif %}
```

- [ ] **Step 4: Создать фрагмент инлайн-формы**

Create `config/templates/config/rentals/_price_cell_edit.html`:

```html
{% load i18n %}
<form class="d-inline-flex align-items-center gap-1 justify-content-end"
      hx-post="{% url 'rental_item_price_edit' rental.pk item.pk %}"
      hx-target="#price-cell-{{ item.pk }}" hx-swap="innerHTML">
    {% csrf_token %}
    <input type="number" name="price_per_day" min="0" step="0.01"
           id="price-input-{{ item.pk }}" value="{{ value }}"
           class="form-control form-control-sm text-end{% if error %} is-invalid{% endif %}"
           style="max-width: 8rem;"
           {% if error %}title="{{ error }}"{% endif %}>
    <button type="submit" class="btn btn-sm btn-success"
            title="{% trans 'Сохранить' %}"><i class="bi bi-check-lg"></i></button>
    <button type="button" class="btn btn-sm btn-outline-secondary"
            title="{% trans 'Отмена' %}"
            hx-get="{% url 'rental_item_price_cell' rental.pk item.pk %}"
            hx-target="#price-cell-{{ item.pk }}" hx-swap="innerHTML">
        <i class="bi bi-x-lg"></i>
    </button>
</form>
{% if error %}<div class="text-danger small mt-1">{{ error }}</div>{% endif %}
<script>
  (function () {
    var i = document.getElementById('price-input-{{ item.pk }}');
    if (i) { i.focus(); i.select(); }
  })();
</script>
```

- [ ] **Step 5: Добавить вью**

В `config/views.py` рядом с `RentalItemEditView` добавить:

```python
class RentalItemPriceEditView(AdminRequiredMixin, View):
    """Инлайн-правка цены за сутки прямо в ячейке таблицы позиций.

    GET  → форма (поле + ✓/✗) в ячейку.
    POST → сохранить цену и перезагрузить карточку (OOB), либо форма с ошибкой.
    Количество не трогаем — для него остаётся модалка (rental_item_edit).
    """

    def _get_objs(self, pk, item_pk):
        rental = get_object_or_404(Rental, pk=pk)
        item = get_object_or_404(
            RentalItem.objects.select_related('product'),
            pk=item_pk, rental=rental,
        )
        return rental, item

    def get(self, request, pk, item_pk):
        rental, item = self._get_objs(pk, item_pk)
        return render(request, 'config/rentals/_price_cell_edit.html', {
            'rental': rental, 'item': item,
            'value': f'{item.price_per_day:.2f}', 'error': '',
        })

    def post(self, request, pk, item_pk):
        rental, item = self._get_objs(pk, item_pk)
        raw = request.POST.get('price_per_day')
        new_price, error = _parse_price_per_day(raw)
        if error:
            return render(request, 'config/rentals/_price_cell_edit.html', {
                'rental': rental, 'item': item,
                'value': (raw or ''), 'error': error,
            })
        item.price_per_day = new_price
        item.save(update_fields=['price_per_day'])
        messages.success(request, _('Цена обновлена.'))
        # Ячейка внутри OOB-региона #rental-items: главный swap не нужен,
        # карточку целиком обновляют OOB-блоки из _oob_refresh.html.
        response = _oob_response(request, _reload_rental(rental.pk))
        response['HX-Reswap'] = 'none'
        return response


class RentalItemPriceCellView(AdminRequiredMixin, View):
    """Вернуть обычную ячейку цены (для кнопки ✗ — отмена без сохранения)."""

    def get(self, request, pk, item_pk):
        rental = get_object_or_404(Rental, pk=pk)
        item = get_object_or_404(
            RentalItem.objects.select_related('product'),
            pk=item_pk, rental=rental,
        )
        return render(request, 'config/rentals/_price_cell.html', {
            'rental': rental, 'item': item,
        })
```

- [ ] **Step 6: Добавить маршруты**

В `config/urls.py` после блока `rental_item_edit` (строка ~137) добавить:

```python
    path(
        'rentals/<int:pk>/item/<int:item_pk>/price/',
        views.RentalItemPriceEditView.as_view(), name='rental_item_price_edit',
    ),
    path(
        'rentals/<int:pk>/item/<int:item_pk>/price/cell/',
        views.RentalItemPriceCellView.as_view(), name='rental_item_price_cell',
    ),
```

- [ ] **Step 7: Запустить инлайн-тесты**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py -k inline -v`
Expected: PASS (5 инлайн-тестов).

- [ ] **Step 8: Коммит**

```bash
git add config/views.py config/urls.py \
        config/templates/config/rentals/_price_cell.html \
        config/templates/config/rentals/_price_cell_edit.html \
        tests/test_rental_item_price_edit.py
git commit -m "feat(rental): инлайн-правка цены за сутки в ячейке (эндпоинты+фрагменты)"
```

---

### Task 3: Встроить кликабельную ячейку в таблицу позиций

**Files:**
- Modify: `config/templates/config/rentals/_items_table.html` (строка 52)
- Test: `tests/test_rental_item_price_edit.py`

**Interfaces:**
- Consumes: `_price_cell.html` (Task 2); `is_admin` (из контекст-процессора, уже доступен в шаблоне таблицы).

- [ ] **Step 1: Написать падающий тест**

Добавить в `tests/test_rental_item_price_edit.py`:

```python
def test_price_cell_clickable_for_admin_not_staff(client_admin, client_staff,
                                                   rental_with_returns):
    r, item, *_ = rental_with_returns
    edit_url = reverse('rental_item_price_edit', args=[r.pk, item.pk])
    admin_body = client_admin.get(reverse('rental_card', args=[r.pk])).content.decode()
    staff_body = client_staff.get(reverse('rental_card', args=[r.pk])).content.decode()
    assert edit_url in admin_body       # у админа ячейка кликабельна
    assert edit_url not in staff_body   # у оператора — обычный текст
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py::test_price_cell_clickable_for_admin_not_staff -v`
Expected: FAIL — `edit_url not in admin_body` (ячейка ещё не подключена).

- [ ] **Step 3: Подключить фрагмент в таблицу**

В `config/templates/config/rentals/_items_table.html` заменить строку 52. Было:

```html
                    <td class="text-end">{{ it.price_per_day }}</td>
```

Стало:

```html
                    <td class="text-end" id="price-cell-{{ it.pk }}">{% include 'config/rentals/_price_cell.html' with item=it rental=rental %}</td>
```

(`{% include %}` без `only` — `is_admin` остаётся в контексте.)

- [ ] **Step 4: Запустить тест**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py::test_price_cell_clickable_for_admin_not_staff -v`
Expected: PASS.

- [ ] **Step 5: Прогнать файл тестов + полный набор**

Run: `venv/bin/python3 -m pytest tests/test_rental_item_price_edit.py -v && venv/bin/python3 -m pytest -q`
Expected: всё зелёное (инлайн, модалка, и весь набор — существующее отображение цены и Σ/сут. не сломано).

- [ ] **Step 6: Коммит**

```bash
git add config/templates/config/rentals/_items_table.html tests/test_rental_item_price_edit.py
git commit -m "feat(rental): кликабельная ячейка цены в таблице позиций"
```

---

## Self-Review

**1. Spec coverage** (сверка со спецом `2026-07-31-rental-item-inline-price-edit-design.md`):
- Клик по ячейке → форма поле+✓/✗ → Task 2 (`_price_cell.html`, `_price_cell_edit.html`) + Task 3 (встраивание). ✓
- ✓/Enter → POST → сохранение + OOB-перезагрузка (пересчёт Σ/сут., Сумма возврата) → Task 2 (`HX-Reswap: none` + `_oob_response`). ✓
- ✗ → возврат отображения → Task 2 (`RentalItemPriceCellView`). ✓
- Ошибка → форма с красной рамкой, цена не меняется → Task 2 (`is-invalid` + тест). ✓
- Только админ; у оператора текст → Task 2 (`AdminRequiredMixin`, 403-тест) + Task 3 (тест clickable-only-admin). ✓
- DRY-хелпер разбора цены → Task 1. ✓
- Карандаш/модалка не тронуты → Task 1 сохраняет поведение (регрессия зелёная), Task 2/3 не трогают модалку. ✓
- Аудит через `item.save()` — обеспечен `save(update_fields=['price_per_day'])` в Task 2. ✓
- Полный pytest зелёный → Task 3, Step 5. ✓

**2. Placeholder scan:** плейсхолдеров нет; во всех code-шагах реальный код. ✓

**3. Type consistency:** `_parse_price_per_day` возвращает `(Decimal|None, str|None)` — так и используется в модалке (Task 1) и в `RentalItemPriceEditView` (Task 2). URL-имена `rental_item_price_edit` / `rental_item_price_cell` совпадают в шаблонах, вью-тестах и `urls.py`. `id="price-cell-{{ it.pk }}"` (таблица) == `hx-target` во фрагментах == `id` в тесте. `value` формата `f'{price:.2f}'` (GET) совпадает с ассертом `value="100.00"`. ✓
