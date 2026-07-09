# Детализация аренд в карточке клиента (аккордеон) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** На детальной странице клиента каждую аренду можно раскрыть прямо в списке и увидеть её полную карточку (сводка/позиции/движения/платежи) с полным редактированием — не заходя в отдельную страницу аренды.

**Architecture:** Тело страницы аренды выносится в переиспользуемый партиал `rentals/_card.html`. Новый лёгкий view `rental_card` отдаёт этот партиал HTMX-запросом. История аренд в карточке клиента превращается в аккордеон: клик по строке лениво грузит карточку под неё. В каждый момент раскрыта максимум одна аренда (JS single-open), поэтому фиксированные ID (`#modal-slot`, `#rental-summary`, …) уникальны и вся модалко/OOB-механика редактирования работает без изменений.

**Tech Stack:** Django (шаблоны/CBV/FBV), htmx 1.9.12 (глобально в base.html), Bootstrap 5.3, pytest.

## Global Constraints

- Язык интерфейса — русский; все новые строки шаблонов через `{% trans %}`/`{% blocktrans %}` с русскими msgid (доминирующий паттерн проекта).
- Доступ к новому view — `@role_required('staff', 'admin')` (как у `rental_contract`, config/views.py:1472). Аноним → 302 на `/login/`, чужая роль → 403.
- Новых полей/миграций БД **нет**.
- Общие партиалы аренды (`_summary.html`, `_items_table.html`, `_timeline.html`, `_payments.html`, `_oob_refresh.html`) и view-действия (возврат/платёж/позиции/закрытие) **не меняются**.
- Запуск тестов: `./venv/bin/python -m pytest` (из корня репозитория).
- Коммит-сообщения заканчиваются строкой:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

- **Create** `config/templates/config/rentals/_card.html` — тело карточки аренды (4 блока-обёртки с ID + `#modal-slot`), переиспользуется страницей аренды и аккордеоном.
- **Modify** `config/templates/config/rentals/detail.html` — начинает `{% include 'config/rentals/_card.html' %}`.
- **Modify** `config/views.py` — новый FBV `rental_card`.
- **Modify** `config/urls.py` — маршрут `rentals/<int:pk>/card/`.
- **Create** `config/templates/config/customers/_rental_history_row.html` — строка-заголовок аренды (кликабельная, с data-атрибутами, `id="crow-<id>"`).
- **Modify** `config/templates/config/customers/detail.html` — блок «История аренд» → аккордеон (список карточек + пустые контейнеры `#rbody-<id>`).
- **Create** `static/js/customer-rentals.js` — поведение single-open аккордеона.
- **Modify** `templates/base.html` — подключить `customer-rentals.js`.
- **Create** `tests/test_rental_card.py` — тесты view `rental_card`.
- **Modify** `tests/test_customer_detail_rentals.py` — тесты аккордеона.

---

### Task 1: Вынести тело страницы аренды в `_card.html` (рефактор без изменения поведения)

**Files:**
- Create: `config/templates/config/rentals/_card.html`
- Modify: `config/templates/config/rentals/detail.html`
- Test: `tests/test_rental_flow.py` (существующие — как регресс)

**Interfaces:**
- Produces: партиал `config/rentals/_card.html`, содержащий обёртки с ID `rental-summary`, `rental-items`, `rental-timeline`, `rental-payments` и `modal-slot`. Ожидает те же контекстные переменные, что и `_rental_card_context` (config/views.py:1127): `rental`, `items`, `movements`, `payments`, `summary`, `has_outstanding`, `today`, `now`, плюс `is_admin` из контекст-процессора.

- [ ] **Step 1: Прогнать существующие тесты страницы аренды — зафиксировать зелёную базу**

Run: `./venv/bin/python -m pytest tests/test_rental_flow.py -q`
Expected: PASS (все существующие тесты проходят до рефактора).

- [ ] **Step 2: Создать партиал `_card.html`**

Create `config/templates/config/rentals/_card.html` с содержимым (дословно перенесённое тело `detail.html`):

```django
{% load i18n %}
<div id="rental-summary">
    {% include 'config/rentals/_summary.html' %}
</div>

<div id="rental-items">
    {% include 'config/rentals/_items_table.html' %}
</div>

<div class="row g-4">
    <div class="col-lg-6">
        <div id="rental-timeline">
            {% include 'config/rentals/_timeline.html' %}
        </div>
    </div>
    <div class="col-lg-6">
        <div id="rental-payments">
            {% include 'config/rentals/_payments.html' %}
        </div>
    </div>
</div>

<div id="modal-slot"></div>
```

- [ ] **Step 3: Переключить `detail.html` на include**

Replace the body block of `config/templates/config/rentals/detail.html` so the file reads:

```django
{% extends 'base.html' %}
{% load i18n %}

{% block title %}{% blocktrans with rid=rental.id %}Аренда #{{ rid }}{% endblocktrans %} — {% trans "Учёт аренды" %}{% endblock %}

{% block content %}
{% include 'config/rentals/_card.html' %}
{% endblock %}
```

- [ ] **Step 4: Прогнать тесты страницы аренды — поведение не изменилось**

Run: `./venv/bin/python -m pytest tests/test_rental_flow.py tests/test_rental_admin_edit.py tests/test_rental_item_price_edit.py -q`
Expected: PASS (тот же HTML, регресс зелёный).

- [ ] **Step 5: Commit**

```bash
git add config/templates/config/rentals/_card.html config/templates/config/rentals/detail.html
git commit -m "$(cat <<'EOF'
refactor(rentals): вынести тело страницы аренды в _card.html

Партиал переиспользуется страницей аренды и будущим аккордеоном в
карточке клиента; поведение rental_detail не меняется.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: View-фрагмент `rental_card`

**Files:**
- Modify: `config/views.py` (добавить FBV после класса `RentalDetailView`, ~config/views.py:1174)
- Modify: `config/urls.py` (маршрут рядом с `rental_detail`, config/urls.py:87)
- Test: `tests/test_rental_card.py` (создать)

**Interfaces:**
- Consumes: `_rental_card_context(rental)` (config/views.py:1127) — возвращает dict с `rental/items/movements/payments/summary/has_outstanding/today/now`. Партиал `config/rentals/_card.html` (Task 1).
- Produces: view `rental_card(request, pk)` и URL name `rental_card` (`rentals/<int:pk>/card/`). Отдаёт HTML-фрагмент `_card.html` (без `base.html`).

- [ ] **Step 1: Написать падающие тесты**

Create `tests/test_rental_card.py`:

```python
"""HTMX-фрагмент карточки аренды (rental_card) для аккордеона клиента."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def rental(db, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=7, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=7, created_by=staff_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('500.00'), kind=Payment.Kind.DEPOSIT,
    )
    return r, item


def test_rental_card_renders_all_blocks(client_staff, rental):
    r, item = rental
    resp = client_staff.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Все четыре обёртки-цели OOB + модал-слот присутствуют.
    for anchor in ('id="rental-summary"', 'id="rental-items"',
                   'id="rental-timeline"', 'id="rental-payments"',
                   'id="modal-slot"'):
        assert anchor in body, anchor
    # Это фрагмент, а не полная страница — без <html>/навигации base.html.
    assert '<html' not in body.lower()
    # Реальные данные аренды видны (позиция товара).
    assert item.product.name in body


def test_rental_card_404_for_missing(client_staff):
    resp = client_staff.get(reverse('rental_card', args=[999999]))
    assert resp.status_code == 404


def test_rental_card_requires_login(db, rental):
    r, _ = rental
    c = Client(SERVER_NAME='localhost')
    resp = c.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 302
    assert '/login/' in resp.url


def test_rental_card_allows_admin(client_admin, rental):
    r, _ = rental
    resp = client_admin.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 200
```

- [ ] **Step 2: Прогнать — тесты падают (нет URL/view)**

Run: `./venv/bin/python -m pytest tests/test_rental_card.py -q`
Expected: FAIL (`NoReverseMatch: 'rental_card'`).

- [ ] **Step 3: Добавить view `rental_card`**

In `config/views.py`, добавить функцию сразу после класса `RentalDetailView` (после строки ~1173, перед `def _return_modal_context`):

```python
@role_required('staff', 'admin')
def rental_card(request, pk):
    """HTML-фрагмент полной карточки аренды для встраивания в аккордеон
    карточки клиента. Тот же контент, что на странице аренды (_card.html),
    но без base.html — грузится HTMX-запросом при раскрытии строки."""
    rental = get_object_or_404(
        Rental.objects
        .select_related('customer', 'created_by', 'closed_by')
        .prefetch_related(
            'items__product',
            'items__movements__created_by',
            'payments',
        ),
        pk=pk,
    )
    return render(request, 'config/rentals/_card.html', _rental_card_context(rental))
```

(`role_required`, `get_object_or_404`, `render`, `Rental`, `_rental_card_context` уже импортированы/определены в файле.)

- [ ] **Step 4: Добавить маршрут**

In `config/urls.py`, сразу после строки `path('rentals/<int:pk>/', views.RentalDetailView.as_view(), name='rental_detail'),` (config/urls.py:87) добавить:

```python
    path('rentals/<int:pk>/card/', views.rental_card, name='rental_card'),
```

- [ ] **Step 5: Прогнать тесты — проходят**

Run: `./venv/bin/python -m pytest tests/test_rental_card.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add config/views.py config/urls.py tests/test_rental_card.py
git commit -m "$(cat <<'EOF'
feat(rentals): view-фрагмент rental_card для аккордеона клиента

Отдаёт _card.html без base.html; доступ staff/admin, 404 на чужой pk.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Аккордеон в карточке клиента (шаблоны)

**Files:**
- Create: `config/templates/config/customers/_rental_history_row.html`
- Modify: `config/templates/config/customers/detail.html` (блок «История аренд», detail.html:89-157)
- Modify: `static/css/theme.css` (мелкие стили аккордеона)
- Test: `tests/test_customer_detail_rentals.py`

**Interfaces:**
- Consumes: URL name `rental_card` (Task 2); переменные строки — `r` (аннотированная аренда из `CustomerDetailView`: `id`, `created_at`, `due_date`, `status`, `items_count`, `outstanding_total`, `paid_total`, `deposit_total`, `created_by`, `items`) и `now` (context).
- Produces: партиал `_rental_history_row.html` c корневым `id="crow-{{ r.id }}"`, классом `rental-acc-header`, атрибутами `data-rental-id="{{ r.id }}"`, `data-card-url="{% url 'rental_card' r.id %}"`, `role="button"`, `aria-controls="rbody-{{ r.id }}"`, `aria-expanded="false"`. Каждой аренде соответствует пустой контейнер `<div id="rbody-{{ r.id }}" class="rental-acc-body">`. Эти id/атрибуты — контракт для `customer-rentals.js` (Task 4).

- [ ] **Step 1: Написать/дополнить падающие тесты аккордеона**

Заменить содержимое `tests/test_customer_detail_rentals.py` на (сохраняет прежние проверки данных + добавляет проверки аккордеона):

```python
"""Детальная страница клиента: аренды — аккордеон с ленивой карточкой."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def rental_for_customer(db, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=7, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=7, created_by=staff_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('500.00'), kind=Payment.Kind.DEPOSIT,
    )
    return r, item


def test_customer_detail_links_to_rental(client_staff, customer, rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Кнопка «Открыть» ведёт на полную страницу аренды.
    assert reverse('rental_detail', args=[r.pk]) in body
    assert f'#{r.id}' in body


def test_customer_detail_shows_rental_summary(client_staff, customer,
                                              rental_for_customer):
    r, item = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Свёрнутый заголовок показывает позицию и залог.
    assert item.product.name in body
    assert '×7' in body
    assert '/ 500' in body
    rentals = list(resp.context['rentals'])
    assert rentals[0].outstanding_total == 7
    assert rentals[0].deposit_total == Decimal('500.00')


def test_customer_detail_accordion_wiring(client_staff, customer,
                                          rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Строка-заголовок раскрывает карточку через rental_card в свой контейнер.
    assert f'data-card-url="{reverse("rental_card", args=[r.pk])}"' in body
    assert f'id="crow-{r.id}"' in body
    assert f'id="rbody-{r.id}"' in body
    assert 'rental-acc-header' in body


def test_customer_detail_no_rentals(client_staff, customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    assert 'Аренд пока нет' in resp.content.decode()
```

- [ ] **Step 2: Прогнать — новые проверки падают**

Run: `./venv/bin/python -m pytest tests/test_customer_detail_rentals.py -q`
Expected: FAIL (`data-card-url`/`crow-`/`rbody-`/`rental-acc-header` ещё нет).

- [ ] **Step 3: Создать партиал строки-заголовка**

Create `config/templates/config/customers/_rental_history_row.html`:

Django `{% with %}` не поддерживает булевы выражения, поэтому условие
просрочки (как в исходном `customers/detail.html`) повторяется инлайн в
`{% if %}`:

```django
{% load i18n %}
<div id="crow-{{ r.id }}"
     class="rental-acc-header card-body py-2 d-flex align-items-center gap-3"
     role="button" tabindex="0"
     aria-expanded="false" aria-controls="rbody-{{ r.id }}"
     data-rental-id="{{ r.id }}"
     data-card-url="{% url 'rental_card' r.id %}">
    <i class="bi bi-chevron-right acc-chevron flex-shrink-0"></i>

    <div class="flex-grow-1 min-w-0">
        <div class="d-flex align-items-center flex-wrap gap-2">
            <span class="fw-semibold{% if r.status == 'active' and r.due_date < now and r.outstanding_total > 0 %} text-danger{% endif %}">#{{ r.id }}</span>
            {% if r.status == 'active' and r.due_date < now and r.outstanding_total > 0 %}
                <span class="badge bg-danger">{% trans "Просрочена" %}</span>
            {% elif r.status == 'active' %}
                <span class="badge bg-primary">{% trans "Активна" %}</span>
            {% else %}
                <span class="badge bg-secondary">{% trans "Закрыта" %}</span>
            {% endif %}
            {% if r.outstanding_total > 0 %}
                <span class="badge bg-warning text-dark" title="{% trans 'На руках' %}">
                    {% trans "на руках" %}: {{ r.outstanding_total }}
                </span>
            {% endif %}
        </div>
        {% if r.items.all %}
            <div class="small text-muted text-truncate">
                {% for it in r.items.all %}{{ it.product.name }} ×{{ it.qty }}{% if not forloop.last %} · {% endif %}{% endfor %}
            </div>
        {% endif %}
    </div>

    <div class="text-nowrap small text-muted d-none d-md-block">
        <div>{% trans "Создана" %}: {{ r.created_at|date:"d.m.Y H:i" }}</div>
        <div class="{% if r.status == 'active' and r.due_date < now and r.outstanding_total > 0 %}text-danger fw-semibold{% endif %}">
            {% trans "Срок" %}: {{ r.due_date|date:"d.m.Y H:i" }}
        </div>
    </div>

    <div class="text-nowrap small text-end d-none d-sm-block">
        <div class="font-monospace">{{ r.paid_total }} <span class="text-muted">/ {{ r.deposit_total }}</span></div>
        <div class="text-muted">{{ r.created_by.username }}</div>
    </div>

    <a href="{% url 'rental_detail' r.id %}"
       class="btn btn-sm btn-outline-primary text-nowrap flex-shrink-0"
       onclick="event.stopPropagation()">
        {% trans "Открыть" %}<i class="bi bi-box-arrow-up-right ms-1"></i>
    </a>
</div>
```

- [ ] **Step 4: Переделать блок «История аренд» в `detail.html`**

In `config/templates/config/customers/detail.html`, заменить весь блок от `<h2 class="h5 mt-4 mb-2">{% trans "История аренд" %}</h2>` (detail.html:89) до закрывающего `{% endif %}` перед `{% endblock %}` (detail.html:157) на:

```django
<h2 class="h5 mt-4 mb-2">{% trans "История аренд" %}</h2>
{% if rentals %}
    <div id="customer-rentals" class="rental-acc">
        {% for r in rentals %}
            <div class="rental-acc-item card mb-2">
                {% include 'config/customers/_rental_history_row.html' %}
                <div id="rbody-{{ r.id }}" class="rental-acc-body"></div>
            </div>
        {% endfor %}
    </div>
{% else %}
    <p class="text-muted">{% trans "Аренд пока нет." %}</p>
{% endif %}
```

- [ ] **Step 5: Добавить стили аккордеона**

Append to `static/css/theme.css`:

```css
/* Аккордеон истории аренд в карточке клиента */
.rental-acc-header { cursor: pointer; }
.rental-acc-header .acc-chevron { transition: transform .15s ease; }
.rental-acc-header[aria-expanded="true"] .acc-chevron { transform: rotate(90deg); }
.rental-acc-header[aria-expanded="true"] { background-color: var(--bs-tertiary-bg); }
.rental-acc-body:not(:empty) { padding: 1rem; border-top: 1px solid var(--bs-border-color); }
.min-w-0 { min-width: 0; }
```

- [ ] **Step 6: Прогнать тесты карточки клиента — проходят**

Run: `./venv/bin/python -m pytest tests/test_customer_detail_rentals.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add config/templates/config/customers/_rental_history_row.html config/templates/config/customers/detail.html static/css/theme.css tests/test_customer_detail_rentals.py
git commit -m "$(cat <<'EOF'
feat(customers): история аренд как аккордеон (строки-заголовки)

Строка аренды раскрывает карточку через rental_card в свой #rbody;
кнопка «Открыть» ведёт на полную страницу. Данные заголовка сохранены.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: JS single-open + подключение

**Files:**
- Create: `static/js/customer-rentals.js`
- Modify: `templates/base.html` (подключить скрипт рядом с прочими, base.html:194)
- Test: `tests/test_customer_detail_rentals.py` (добавить проверку подключения)

**Interfaces:**
- Consumes: DOM-контракт из Task 3 — `#customer-rentals`, `.rental-acc-header[data-rental-id][data-card-url]`, `#rbody-<id>`, `#crow-<id>`; глобальный `htmx` (base.html:188) и его `htmx.ajax(method, url, {target, swap})`.
- Produces: файл `static/js/customer-rentals.js` и его подключение в base.html.

- [ ] **Step 1: Добавить падающий тест подключения**

В `tests/test_customer_detail_rentals.py` добавить в конец:

```python
def test_customer_detail_includes_accordion_js(client_staff, customer,
                                                rental_for_customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert 'js/customer-rentals.js' in resp.content.decode()
```

- [ ] **Step 2: Прогнать — падает (скрипт не подключён)**

Run: `./venv/bin/python -m pytest tests/test_customer_detail_rentals.py::test_customer_detail_includes_accordion_js -q`
Expected: FAIL (`assert 'js/customer-rentals.js' in ...`).

- [ ] **Step 3: Создать `customer-rentals.js`**

Create `static/js/customer-rentals.js`:

```javascript
// Аккордеон истории аренд в карточке клиента.
// Раскрыта максимум одна аренда за раз — тогда фиксированные id карточки
// (#rental-summary, #modal-slot, ...) уникальны и модалко/OOB-механика
// редактирования работает как на странице аренды. Очистка #rbody убирает
// дубли id и любую открытую модалку (модалки — инлайн, без Bootstrap-подложки).
(function () {
    'use strict';

    function init() {
        var root = document.getElementById('customer-rentals');
        if (!root || typeof htmx === 'undefined') return;

        function bodyFor(id) { return document.getElementById('rbody-' + id); }
        function headerFor(id) { return document.getElementById('crow-' + id); }

        function collapse(id) {
            var body = bodyFor(id);
            var header = headerFor(id);
            if (body) body.innerHTML = '';
            if (header) header.setAttribute('aria-expanded', 'false');
        }

        function isOpen(id) {
            var body = bodyFor(id);
            return !!body && body.innerHTML.trim() !== '';
        }

        function expand(id) {
            // Закрыть все прочие открытые строки (single-open).
            root.querySelectorAll('.rental-acc-body').forEach(function (b) {
                var otherId = b.id.replace('rbody-', '');
                if (otherId !== id && b.innerHTML.trim() !== '') collapse(otherId);
            });
            var header = headerFor(id);
            var url = header.getAttribute('data-card-url');
            htmx.ajax('GET', url, {
                target: '#rbody-' + id, swap: 'innerHTML'
            }).then(function () {
                header.setAttribute('aria-expanded', 'true');
            });
        }

        function toggleFromHeader(header) {
            var id = header.getAttribute('data-rental-id');
            if (isOpen(id)) collapse(id); else expand(id);
        }

        root.addEventListener('click', function (evt) {
            // Клики по ссылкам/кнопкам и внутри уже открытой карточки — мимо.
            if (evt.target.closest('a, button, .rental-acc-body')) return;
            var header = evt.target.closest('.rental-acc-header');
            if (header && root.contains(header)) toggleFromHeader(header);
        });

        root.addEventListener('keydown', function (evt) {
            if (evt.key !== 'Enter' && evt.key !== ' ') return;
            var header = evt.target.closest('.rental-acc-header');
            if (!header || !root.contains(header)) return;
            evt.preventDefault();
            toggleFromHeader(header);
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
```

- [ ] **Step 4: Подключить скрипт в base.html**

In `templates/base.html`, после строки `<script src="{% static 'js/return-receipt.js' %}"></script>` (base.html:194) добавить:

```django
<script src="{% static 'js/customer-rentals.js' %}"></script>
```

- [ ] **Step 5: Прогнать тесты карточки клиента — проходят**

Run: `./venv/bin/python -m pytest tests/test_customer_detail_rentals.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add static/js/customer-rentals.js templates/base.html tests/test_customer_detail_rentals.py
git commit -m "$(cat <<'EOF'
feat(customers): single-open аккордеон аренд (JS)

Раскрыта максимум одна аренда за раз (htmx.ajax + очистка #rbody), чтобы
id карточки были уникальны и редактирование работало как на странице аренды.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Ручная проверка сценария редактирования и полный прогон

**Files:** нет изменений кода — верификация.

- [ ] **Step 1: Полный прогон тестов**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS (вся сюита зелёная, включая регресс страницы аренды и биллинга).

- [ ] **Step 2: Ручная проверка в браузере (dev-сервер)**

Run: `./venv/bin/python manage.py runserver`

Проверить на странице клиента с ≥2 арендами:
1. Клик по строке аренды — под ней раскрывается полная карточка (сводка/позиции/движения/платежи).
2. Клик по другой аренде — первая **сворачивается**, раскрывается вторая (single-open).
3. Повторный клик по раскрытой — сворачивает.
4. Внутри раскрытой аренды: «Принять возврат»/«Платёж»/«Позиция» открывают модалку, submit обновляет блоки карточки на месте (OOB), модалка закрывается.
5. Кнопка «Открыть» ведёт на полную страницу аренды (клик по ней не раскрывает/не сворачивает строку).
6. Клавиатура: Tab до заголовка, Enter/Space раскрывает.

Expected: все пункты работают; в консоли браузера нет ошибок.

- [ ] **Step 3: Финальный коммит (если были правки по итогам проверки)**

```bash
git add -A
git commit -m "$(cat <<'EOF'
test(customers): проверка аккордеона аренд end-to-end

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

(Если правок не было — шаг пропустить.)

---

## Self-Review

**Spec coverage:**
- Аккордеон / клик раскрывает под строкой → Task 3 + Task 4. ✅
- Полная детализация + редактирование → Task 1 (`_card.html` со всеми блоками и кнопками) + Task 2 (отдаёт карточку) + редактирование без изменений (Global Constraints, Task 5 §2.4). ✅
- Одна открытая за раз (уникальность id) → Task 4 JS. ✅
- Ленивая подгрузка → `htmx.ajax` при раскрытии (Task 4). ✅
- Рефактор страницы аренды без изменения поведения → Task 1 + регресс-тесты. ✅
- Компромисс v1 (свёрнутый заголовок может устареть) → строка вынесена в партиал с `id="crow-<id>"` (Task 3) как задел; авто-обновление явно вне рамок v1. ✅
- Тесты (view 200/404/доступ, регресс, карточка клиента) → Task 2 + Task 3 + Task 5. ✅

**Placeholder scan:** нет TBD/TODO/«обработать ошибки» — весь код и команды приведены дословно. ✅

**Type/имя-консистентность:** id/классы/data-атрибуты совпадают между Task 3 (шаблоны) и Task 4 (JS): `#customer-rentals`, `.rental-acc-header`, `.rental-acc-body`, `#rbody-<id>`, `#crow-<id>`, `data-rental-id`, `data-card-url`. URL name `rental_card` совпадает в Task 2/3/тестах. Контекст `_rental_card_context` используется в Task 2 так же, как в `RentalDetailView`. ✅
