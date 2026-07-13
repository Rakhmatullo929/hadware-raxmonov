# Редактируемое время возврата — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать оператору выбирать время возврата при приёмке и позволить админу менять время у уже сохранённого возврата — на любое значение, в любой момент.

**Architecture:** Время возврата — это `Movement.date` (поле уже есть, миграций нет). В модалке «Принять возврат» появляется поле `datetime-local`; сервер использует его как `date` создаваемых движений и как `as_of` авторасчёта пустых сумм. Правка постфактум — отдельный admin-only HTMX-view + маленькая модалка + карандаш у строк возврата в таймлайне; идём по существующему паттерну `RentalItemEditView`/`RentalPaymentEditView` (OOB-перерисовка карточки через `_oob_response`).

**Tech Stack:** Django, HTMX, Bootstrap 5 + Bootstrap Icons, pytest + pytest-django.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-07-14-return-time-editable-design.md`.
- **Время не трогает сумму.** Правка времени сохранённого возврата НИКОГДА не пересчитывает `Movement.amount`. При приёмке: введённую вручную сумму берём как есть; пустую — авторасчёт `as_of` выбранного времени.
- **Права:** приёмка возврата — staff+admin (как сейчас); правка времени сохранённого возврата — только admin (`AdminRequiredMixin` → `role_required('admin')` → `PermissionDenied`/403).
- **«Любое время»** — без верхней/нижней границы даты. `_billable_days` клампит к ≥1, отрицательных дней не будет.
- **Только возвраты.** Правку постфактум добавляем движениям `kind='return'`; движения выдачи не трогаем.
- Часовой пояс: `USE_TZ=True`, `TIME_ZONE='Asia/Tashkent'`. `datetime-local` наивный → `timezone.make_aware(..., timezone.get_current_timezone())`; показ существующего — `timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M')`.
- Запуск тестов из корня репозитория (venv активна): `pytest <path>::<test> -v`. Настройки Django берутся из `pytest.ini` (`DJANGO_SETTINGS_MODULE=rental_track.settings`).
- В `config/views.py` уже импортированы: `datetime` (`from datetime import date, datetime, timedelta`), `timezone`, `messages`, `get_object_or_404`, `billing`, `Movement`, `Rental`, `_` (gettext), а также хелперы `_reload_rental`, `_oob_response`. Новых импортов не требуется.

## File Structure

- `config/views.py` — новый хелпер `_parse_local_dt`; правки `_return_modal_context` и `RentalReturnView.post`; новый класс `RentalMovementEditView`.
- `config/urls.py` — новый маршрут `rental_movement_edit`.
- `config/templates/config/rentals/_return_modal.html` — поле «Дата и время возврата».
- `config/templates/config/rentals/_movement_edit_modal.html` — **новый** шаблон модалки правки времени.
- `config/templates/config/rentals/_timeline.html` — карандаш «изменить время» у строк возврата (только admin).
- `tests/test_rental_flow.py` — тесты приёмки с выбором времени (Task 1).
- `tests/test_rental_admin_edit.py` — тесты правки постфактум + таймлайн (Tasks 2, 3).

---

## Task 1: Приёмка возврата с выбором времени

**Files:**
- Modify: `config/views.py` (добавить `_parse_local_dt`; править `_return_modal_context` и `RentalReturnView.post`)
- Modify: `config/templates/config/rentals/_return_modal.html`
- Test: `tests/test_rental_flow.py`

**Interfaces:**
- Produces: `_parse_local_dt(raw) -> datetime | None` — парсер `datetime-local` в aware-datetime текущего пояса (используется и в Task 2).
- Produces: у POST `/rentals/<pk>/return/` появляется необязательное поле `return_at` (формат `%Y-%m-%dT%H:%M`); пустое → «сейчас»; непустое-но-кривое → ошибка, движения не создаются.
- Consumes: `billing.compute_return_amount_for_qty(item, qty, as_of=None)` — сигнатура уже поддерживает `as_of` (config/billing.py:117).

- [ ] **Step 1: Написать падающие тесты приёмки с временем**

Добавить в конец `tests/test_rental_flow.py` (модульный хелпер `_make_rental_with_issue` и импорты `timedelta`, `Decimal`, `timezone`, `Movement` уже есть в файле):

```python
def test_return_modal_shows_return_at_field(client_admin, customer, product):
    rental, item = _make_rental_with_issue(client_admin, customer, product, qty=5)
    r = client_admin.get(f'/rentals/{rental.pk}/return/')
    assert r.status_code == 200
    assert 'name="return_at"' in r.content.decode()


def test_return_at_saved_and_drives_blank_amount(client_admin, customer, product):
    rental, item = _make_rental_with_issue(client_admin, customer, product, qty=10)
    # возврат датируем на 5 дней позже выдачи → авто-аренда за 5 дней, не за 1
    return_at = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
        second=0, microsecond=0,
    )
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '4',
        f'amount_{item.pk}': '',           # пусто → авторасчёт
        'return_at': return_at.strftime('%Y-%m-%dT%H:%M'),
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    ret = Movement.objects.get(rental_item=item, kind=Movement.Kind.RETURN)
    # время сохранено ровно как отдали (сверяем в локальном поясе)
    assert timezone.localtime(ret.date).strftime('%Y-%m-%dT%H:%M') == \
        return_at.strftime('%Y-%m-%dT%H:%M')
    # авто-сумма за 5-дневный интервал строго больше, чем «тот же день» (4×1×100=400)
    assert ret.amount > Decimal('400.00')


def test_return_without_return_at_defaults_to_now(client_admin, customer, product):
    rental, item = _make_rental_with_issue(client_admin, customer, product, qty=5)
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '2',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    ret = Movement.objects.get(rental_item=item, kind=Movement.Kind.RETURN)
    assert abs((timezone.now() - ret.date).total_seconds()) < 60


def test_return_rejects_invalid_return_at(client_admin, customer, product):
    rental, item = _make_rental_with_issue(client_admin, customer, product, qty=5)
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '2',
        'return_at': 'not-a-date',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert 'корректные дату и время' in r.content.decode()
    assert not Movement.objects.filter(
        rental_item=item, kind=Movement.Kind.RETURN,
    ).exists()
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `pytest tests/test_rental_flow.py -k return_at -v`
Expected: FAIL — поля `name="return_at"` нет; `return_at` игнорируется, авто-сумма = 400 (не > 400); кривой `return_at` не даёт ошибки.

- [ ] **Step 3: Добавить хелпер `_parse_local_dt`**

В `config/views.py` вставить функцию непосредственно перед `def _return_modal_context(` (≈ строка 1194):

```python
def _parse_local_dt(raw):
    """'2026-07-14T03:22' (datetime-local) → aware-datetime в текущем поясе.

    Пусто или неразбираемо → None (вызывающий решает: дефолт «сейчас» или ошибка).
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        naive = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())
```

- [ ] **Step 4: Добавить `return_at_value` в `_return_modal_context`**

В `config/views.py` изменить сигнатуру и возвращаемый словарь `_return_modal_context`.

Сигнатуру (было):
```python
def _return_modal_context(rental, outstanding_items, *, inputs, errors, note,
                          amount_inputs=None):
```
стало:
```python
def _return_modal_context(rental, outstanding_items, *, inputs, errors, note,
                          amount_inputs=None, return_at_value=None):
```

В `return {...}` добавить ключ (рядом с `period_to`):
```python
        'period_from': rental.created_at,
        'period_to': timezone.now(),
        'return_at_value': return_at_value or timezone.localtime(
            timezone.now()).strftime('%Y-%m-%dT%H:%M'),
    }
```

- [ ] **Step 5: Разобрать и применить `return_at` в `RentalReturnView.post`**

В `config/views.py`, в методе `RentalReturnView.post`, сразу после строки `errors = []` (≈1314) вставить блок:

```python
        return_at_raw = (request.POST.get('return_at') or '').strip()
        return_at = _parse_local_dt(return_at_raw)
        if return_at is None:
            if return_at_raw:
                errors.append(_('Укажите корректные дату и время возврата.'))
            return_at = timezone.now()
```

В блоке ошибок (`if errors: return render(...)`, ≈1374) добавить `return_at_value=return_at_raw` в вызов `_return_modal_context`:

```python
        if errors:
            return render(request, 'config/rentals/_return_modal.html',
                          _return_modal_context(rental, outstanding_items,
                                                inputs=inputs, errors=errors,
                                                note=note,
                                                amount_inputs=amount_inputs,
                                                return_at_value=return_at_raw))
```

В цикле создания движений (≈1383-1393) добавить `as_of=return_at` в авторасчёт и `date=return_at` в create:

```python
            for it, qty, amount in plan:
                if amount is None:
                    amount = billing.compute_return_amount_for_qty(
                        it, qty, as_of=return_at)
                mv = Movement.objects.create(
                    rental_item=it,
                    kind=Movement.Kind.RETURN,
                    qty=qty,
                    amount=amount,
                    date=return_at,
                    note=note,
                    created_by=request.user,
                )
                created_ids.append(mv.pk)
```

- [ ] **Step 6: Добавить поле в шаблон модалки возврата**

В `config/templates/config/rentals/_return_modal.html` вставить блок сразу ПОСЛЕ закрывающего `</div>` инфо-алерта «Период» (после строки 33, перед `<div class="table-responsive">`):

```html
                    <div class="mb-3">
                        <label class="form-label">{% trans "Дата и время возврата" %}</label>
                        <input type="datetime-local" name="return_at"
                               class="form-control" value="{{ return_at_value }}">
                    </div>
```

- [ ] **Step 7: Запустить тесты Task 1 — убедиться, что проходят**

Run: `pytest tests/test_rental_flow.py -k return_at -v`
Expected: PASS (4 теста).

- [ ] **Step 8: Прогнать смежные тесты возврата — регрессий нет**

Run: `pytest tests/test_rental_flow.py tests/test_billing.py tests/test_return_receipt.py -v`
Expected: PASS (существующие тесты приёмки/биллинга/чека зелёные — POST без `return_at` по-прежнему создаёт возврат «сейчас»).

- [ ] **Step 9: Commit**

```bash
git add config/views.py config/templates/config/rentals/_return_modal.html tests/test_rental_flow.py
git commit -m "feat(returns): выбор времени возврата при приёмке

Поле datetime-local в модалке возврата; сервер ставит его как
Movement.date и считает пустую сумму as_of выбранного времени.
Пусто → «сейчас»; кривое значение → ошибка.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Правка времени сохранённого возврата (admin)

**Files:**
- Modify: `config/views.py` (новый класс `RentalMovementEditView` рядом с `RentalItemEditView`)
- Modify: `config/urls.py` (маршрут `rental_movement_edit`)
- Create: `config/templates/config/rentals/_movement_edit_modal.html`
- Test: `tests/test_rental_admin_edit.py`

**Interfaces:**
- Consumes: `_parse_local_dt` (Task 1), `_reload_rental(pk)`, `_oob_response(request, rental)` (существуют в views.py).
- Produces: URL-name `rental_movement_edit` (аргументы `pk`, `movement_pk`) → путь `/rentals/<pk>/movement/<movement_pk>/edit/`. GET отдаёт модалку `_movement_edit_modal.html`; POST меняет только `Movement.date`. Доступ только admin; движение обязано быть `kind='return'` этой аренды, иначе 404. Потребляется карандашом таймлайна в Task 3.

- [ ] **Step 1: Написать падающие тесты правки времени**

Добавить в конец `tests/test_rental_admin_edit.py` (импорты `timedelta`, `Decimal`, `timezone`, `Movement`, `Rental` в файле уже есть; фикстуры `client_admin`, `client_staff` — в этом файле; `rental_with_returns` — в conftest.py):

```python
# ---------- return-movement time edit ----------

def test_movement_time_edit_changes_date_keeps_amount(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    new_local = timezone.localtime(timezone.now() - timedelta(days=3)).replace(
        second=0, microsecond=0,
    )
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': new_local.strftime('%Y-%m-%dT%H:%M')},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    m1.refresh_from_db()
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') == \
        new_local.strftime('%Y-%m-%dT%H:%M')
    assert m1.amount == Decimal('400.00')  # сумма не тронута


def test_movement_time_edit_modal_prefills_current_time(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    resp = client_admin.get(f'/rentals/{r.pk}/movement/{m1.pk}/edit/')
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="date"' in body
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') in body


def test_movement_time_edit_works_on_closed_rental(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    r.status = Rental.Status.CLOSED
    r.closed_at = timezone.now()
    r.save(update_fields=['status', 'closed_at'])
    new_local = timezone.localtime(timezone.now() - timedelta(days=1)).replace(
        second=0, microsecond=0,
    )
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': new_local.strftime('%Y-%m-%dT%H:%M')},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    m1.refresh_from_db()
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') == \
        new_local.strftime('%Y-%m-%dT%H:%M')


def test_movement_time_edit_rejects_invalid_date(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    original = m1.date
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': 'garbage'},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    assert 'корректные дату и время' in resp.content.decode()
    m1.refresh_from_db()
    assert m1.date == original


def test_movement_time_edit_forbidden_for_staff(
    client_staff, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/movement/{m1.pk}/edit/')
    assert resp.status_code in (302, 403)


def test_movement_time_edit_rejects_issue_movement(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    issue = Movement.objects.get(rental_item=item, kind=Movement.Kind.ISSUE)
    resp = client_admin.get(f'/rentals/{r.pk}/movement/{issue.pk}/edit/')
    assert resp.status_code == 404
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `pytest tests/test_rental_admin_edit.py -k movement_time -v`
Expected: FAIL — маршрута `/rentals/<pk>/movement/<mpk>/edit/` нет (404 на всё).

- [ ] **Step 3: Добавить view `RentalMovementEditView`**

В `config/views.py` вставить класс сразу после `class RentalItemEditView` (перед `class RentalItemRemoveView`, ≈ строка 2226):

```python
class RentalMovementEditView(AdminRequiredMixin, View):
    """Правка времени (Movement.date) у движения ВОЗВРАТА. Только admin.

    Сумму не трогает; работает и на закрытой аренде («в любое время»).
    Движение обязано быть возвратом этой аренды — иначе 404.
    """

    def _get_objs(self, pk, movement_pk):
        rental = get_object_or_404(Rental, pk=pk)
        movement = get_object_or_404(
            Movement.objects.select_related('rental_item__product'),
            pk=movement_pk, rental_item__rental=rental,
            kind=Movement.Kind.RETURN,
        )
        return rental, movement

    def _render_modal(self, request, rental, movement, date_value, errors):
        return render(request, 'config/rentals/_movement_edit_modal.html', {
            'rental': rental, 'movement': movement,
            'date_value': date_value, 'errors': errors,
        })

    def get(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        date_value = timezone.localtime(movement.date).strftime('%Y-%m-%dT%H:%M')
        return self._render_modal(request, rental, movement, date_value, [])

    def post(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        raw = (request.POST.get('date') or '').strip()
        new_dt = _parse_local_dt(raw)
        if new_dt is None:
            return self._render_modal(
                request, rental, movement, raw,
                [_('Укажите корректные дату и время.')],
            )
        movement.date = new_dt
        movement.save(update_fields=['date'])
        messages.success(request, _('Время возврата обновлено.'))
        return _oob_response(request, _reload_rental(rental.pk))
```

- [ ] **Step 4: Добавить маршрут**

В `config/urls.py` добавить рядом с `rental_item_edit` (≈ строка 127):

```python
    path(
        'rentals/<int:pk>/movement/<int:movement_pk>/edit/',
        views.RentalMovementEditView.as_view(), name='rental_movement_edit',
    ),
```

- [ ] **Step 5: Создать шаблон модалки**

Создать `config/templates/config/rentals/_movement_edit_modal.html`:

```html
{% load i18n %}
<div class="modal show d-block" tabindex="-1"
     style="background-color: rgba(0,0,0,0.5);">
    <div class="modal-dialog">
        <form class="modal-content"
              hx-post="{% url 'rental_movement_edit' rental.pk movement.pk %}"
              hx-target="#modal-slot"
              hx-swap="innerHTML">
            {% csrf_token %}
            <div class="modal-header">
                <h5 class="modal-title">
                    {% blocktrans with name=movement.rental_item.product.name %}Изменить время возврата · {{ name }}{% endblocktrans %}
                </h5>
                <button type="button" class="btn-close"
                        aria-label="{% trans 'Закрыть' %}"
                        hx-get="{% url 'rental_modal_close' %}"
                        hx-target="#modal-slot" hx-swap="innerHTML"></button>
            </div>
            <div class="modal-body">
                {% if errors %}
                    <div class="alert alert-danger">
                        <ul class="mb-0">
                            {% for e in errors %}<li>{{ e }}</li>{% endfor %}
                        </ul>
                    </div>
                {% endif %}
                <label class="form-label">{% trans "Дата и время возврата" %}</label>
                <input type="datetime-local" name="date" class="form-control"
                       value="{{ date_value }}">
                <div class="form-text">
                    {% trans "Сумма начисления не изменится — меняется только время." %}
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn btn-link"
                        hx-get="{% url 'rental_modal_close' %}"
                        hx-target="#modal-slot" hx-swap="innerHTML">
                    {% trans "Отмена" %}
                </button>
                <button type="submit" class="btn btn-primary">
                    {% trans "Сохранить" %}
                </button>
            </div>
        </form>
    </div>
</div>
```

- [ ] **Step 6: Запустить тесты Task 2 — убедиться, что проходят**

Run: `pytest tests/test_rental_admin_edit.py -k movement_time -v`
Expected: PASS (6 тестов).

- [ ] **Step 7: Commit**

```bash
git add config/views.py config/urls.py config/templates/config/rentals/_movement_edit_modal.html tests/test_rental_admin_edit.py
git commit -m "feat(returns): правка времени сохранённого возврата (admin)

RentalMovementEditView + маршрут + модалка. Меняет только
Movement.date, сумму не трогает; работает и на закрытой аренде;
только для движений возврата (иначе 404).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Карандаш «изменить время» в таймлайне

**Files:**
- Modify: `config/templates/config/rentals/_timeline.html`
- Test: `tests/test_rental_admin_edit.py`

**Interfaces:**
- Consumes: URL-name `rental_movement_edit` (Task 2); `rental` и `is_admin` в контексте таймлайна (`rental` приходит из `_rental_card_context`; `is_admin` — из контекст-процессора `navigation`, config/context_processors.py:111).
- Produces: у строк возврата в «Движениях» появляется кнопка-карандаш (hx-get модалки в `#modal-slot`), видимая только админу.

- [ ] **Step 1: Написать падающие тесты видимости карандаша**

Добавить в конец `tests/test_rental_admin_edit.py`:

```python
# ---------- timeline edit affordance ----------

def test_timeline_shows_edit_pencil_for_admin(client_admin, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_admin.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{m1.pk}/edit/' in resp.content.decode()


def test_timeline_hides_edit_pencil_for_staff(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{m1.pk}/edit/' not in resp.content.decode()


def test_timeline_no_edit_pencil_on_issue_row(client_admin, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    issue = Movement.objects.get(rental_item=item, kind=Movement.Kind.ISSUE)
    resp = client_admin.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{issue.pk}/edit/' \
        not in resp.content.decode()
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `pytest tests/test_rental_admin_edit.py -k timeline -v`
Expected: FAIL для `test_timeline_shows_edit_pencil_for_admin` (карандаша/ссылки ещё нет). Два «отрицательных» теста пока проходят вхолостую — это нормально; их защита включится после Step 3.

- [ ] **Step 3: Добавить карандаш в таймлайн**

В `config/templates/config/rentals/_timeline.html` заменить правый блок с датой/автором (строки 22-24):

```html
                <span class="text-muted small text-nowrap ms-2">
                    {{ m.date|date:"d.m.Y H:i" }} · {{ m.created_by.username }}
                </span>
```

на:

```html
                <span class="text-muted small text-nowrap ms-2">
                    {{ m.date|date:"d.m.Y H:i" }} · {{ m.created_by.username }}
                    {% if is_admin and m.kind != 'issue' %}
                        <button type="button"
                                class="btn btn-sm btn-link p-0 ms-1 align-baseline"
                                title="{% trans 'Изменить время' %}"
                                hx-get="{% url 'rental_movement_edit' rental.pk m.pk %}"
                                hx-target="#modal-slot" hx-swap="innerHTML">
                            <i class="bi bi-pencil"></i>
                        </button>
                    {% endif %}
                </span>
```

- [ ] **Step 4: Запустить тесты Task 3 — убедиться, что проходят**

Run: `pytest tests/test_rental_admin_edit.py -k timeline -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Полный прогон затронутых наборов — регрессий нет**

Run: `pytest tests/test_rental_flow.py tests/test_rental_admin_edit.py tests/test_rental_card.py tests/test_return_receipt.py tests/test_billing.py -v`
Expected: PASS (все).

- [ ] **Step 6: Ручная проверка end-to-end (skill `verify`)**

Открыть аренду с возвратом в браузере: (1) при приёмке возврата видно поле «Дата и время возврата», значение по умолчанию — сейчас; смена времени сохраняется в `Movement.date`; (2) у строки возврата в «Движениях» админу виден карандаш → модалка с текущим временем → сохранение меняет время в таймлайне, сумма не меняется; (3) под staff карандаша нет.

- [ ] **Step 7: Commit**

```bash
git add config/templates/config/rentals/_timeline.html tests/test_rental_admin_edit.py
git commit -m "feat(returns): карандаш «изменить время» у возвратов в таймлайне

Только для admin и только у движений возврата; открывает модалку
правки времени.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Спека §«Приёмка возврата: выбор времени» → Task 1 (поле, `_return_modal_context`, `RentalReturnView.post`, `_parse_local_dt`). ✓
- Спека §«Правка времени сохранённого возврата» → Task 2 (view + URL + модалка) и Task 3 (карандаш). ✓
- «Время не трогает сумму»: Task 1 — пустая сумма as_of выбранного времени, введённая как есть; Task 2 — `save(update_fields=['date'])`, тест `..._keeps_amount`. ✓
- Права: приёмка staff+admin (маршрут `rental_return` не менялся); правка admin-only (`AdminRequiredMixin`, тест `..._forbidden_for_staff`). ✓
- Только возвраты: гейт `kind=RETURN` в `_get_objs` (тест `..._rejects_issue_movement`) и `m.kind != 'issue'` в шаблоне (тест `..._no_edit_pencil_on_issue_row`). ✓
- Часовой пояс: `_parse_local_dt` + `localtime(...)`; тесты сверяют локальный round-trip. ✓
- «Любое время», закрытая аренда: тест `..._works_on_closed_rental`; границ даты нет. ✓
- Раздел спеки «Тестирование» — все пункты покрыты тестами Tasks 1–3. ✓

**2. Placeholder scan:** плейсхолдеров нет — во всех шагах с кодом приведён полный код и точные команды/ожидания.

**3. Type consistency:** `_parse_local_dt(raw) -> datetime|None` объявлен в Task 1, используется в Task 1 (`RentalReturnView.post`) и Task 2 (`RentalMovementEditView`). URL-name `rental_movement_edit(pk, movement_pk)` создан в Task 2, потребляется шаблонами модалки (Task 2) и таймлайна (Task 3) с теми же аргументами. Поля форм: `return_at` (Task 1), `date` (Task 2) — согласованы между шаблоном, view и тестами. `_oob_response`/`_reload_rental` — существующие, сигнатуры не меняются.
