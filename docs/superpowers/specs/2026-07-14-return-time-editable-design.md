# Дизайн: редактируемое время возврата

Дата: 2026-07-14
Статус: утверждён (брейншторм)

## Цель

Сейчас время возврата жёстко ставится в момент подтверждения приёмки
(`Movement.date` = `timezone.now()`) и потом не редактируется. Нужно дать
оператору **выбирать время возврата при приёмке** и **менять его у уже
сохранённого возврата — в любой момент на любое время**.

«Время возврата» — это `Movement.date` у движения типа `RETURN`. Оно видно в
таймлайне («Движения»), в чеке возврата и в отчёте по возвратам (фильтр по дате).

## Принятые решения (из брейншторма)

1. **Управляем временем в двух местах:** при приёмке (модалка «Принять возврат»)
   и постфактум (кнопка у сохранённого возврата в таймлайне).
2. **Время не трогает сумму.** Время возврата — независимая отметка:
   - При приёмке: введённая вручную сумма используется как есть; **пустая**
     сумма считается авторасчётом **`as_of` выбранного времени**
     (`compute_return_amount_for_qty(it, qty, as_of=return_at)`).
   - Правка времени сохранённого возврата **никогда** не пересчитывает
     `Movement.amount` — сумма остаётся снимком.
3. **Права:**
   - Приёмка возврата с выбором времени — **staff + admin** (как сейчас).
   - Правка времени сохранённого возврата — **только admin** (как правка
     платежей/позиций).
4. **«Любое время» — без жёстких границ.** Ни верхней, ни нижней границы даты не
   ставим (явное требование). `_billable_days` клампит к минимуму 1 дню, поэтому
   отрицательных дней в авторасчёте не будет.
5. **Модель не меняем.** Поле `Movement.date` уже есть. Миграций нет.
6. **Только возвраты.** Правку постфактум добавляем к движениям `RETURN`;
   движения выдачи (`ISSUE`) не трогаем (вне рамок).

## Архитектура

Все правки — в приложении `config`. Идём по существующему паттерну проекта:
HTMX-модалка + OOB-перерисовка карточки аренды (`_oob_response` →
`_oob_refresh.html`), как у `RentalPaymentEditView` / `RentalItemEditView`.

### Хелпер парсинга времени (config/views.py)

Один общий парсер `datetime-local` → aware-datetime в текущем поясе:

```python
def _parse_local_dt(raw):
    """'2026-07-14T03:22' → aware datetime (Asia/Tashkent) | None при пустом/кривом."""
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        naive = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())
```

`USE_TZ = True`, `TIME_ZONE = 'Asia/Tashkent'`, per-request `activate()` в проекте
нет → текущий пояс = `Asia/Tashkent`.

Для предзаполнения полей — обратное преобразование `timezone.localtime(dt)` и
`strftime('%Y-%m-%dT%H:%M')`.

### Приёмка возврата: выбор времени

**`_return_modal_context` (config/views.py)** — добавить в контекст
`return_at_value`:
- по умолчанию — `localtime(now)` в формате `'%Y-%m-%dT%H:%M'`;
- при перерисовке после ошибки — введённое оператором сырое значение (чтобы не
  терялось).

**`_return_modal.html`** — добавить поле рядом с блоком «Период»:

```html
<label class="form-label">{% trans "Дата и время возврата" %}</label>
<input type="datetime-local" name="return_at" class="form-control"
       value="{{ return_at_value }}">
```

**`RentalReturnView.post`**:
- Прочитать `request.POST.get('return_at')`, распарсить через `_parse_local_dt`.
- Валидация: если значение **пришло непустым, но не распарсилось** → добавить
  ошибку в `errors` (модалка перерисовывается, сохранив введённое время); если
  пусто → `return_at = timezone.now()`.
- Пробросить `return_at` в сырое значение контекста при перерисовке ошибок.
- При создании движений использовать `return_at` как `date`, а для пустых сумм —
  как `as_of` авторасчёта:

```python
if amount is None:  # поле суммы оставили пустым → авторасчёт as_of выбранного времени
    amount = billing.compute_return_amount_for_qty(it, qty, as_of=return_at)
mv = Movement.objects.create(
    rental_item=it, kind=Movement.Kind.RETURN, qty=qty,
    amount=amount, date=return_at, note=note, created_by=request.user,
)
```

`compute_return_amount_for_qty(item, qty, as_of=None)` уже принимает `as_of`
(config/billing.py:117) — сигнатуру менять не нужно.

Все позиции одной приёмки получают одно и то же `return_at`.

**`return-amount.js`** — не меняем. Это UX-подсказка (сам файл это оговаривает:
«не источник истины»); сервер авторитетно пересчитывает пустые суммы `as_of`
выбранного времени. Известный нюанс: если оператор и время сильно сдвинул, и
сумму оставил пустой — живой предпросмотр в модалке покажет дни «от сейчас», а
сохранится сумма по выбранному времени. Приемлемо (сумму почти всегда
вводят/видят на карточке); клиентский пересчёт дней — вне рамок.

### Правка времени сохранённого возврата

**Новый `RentalMovementEditView(AdminRequiredMixin, View)` (config/views.py):**

```python
class RentalMovementEditView(AdminRequiredMixin, View):
    """Правка времени (Movement.date) у движения возврата. Только admin.
    Сумму не трогает; работает и на закрытой аренде («в любое время»)."""

    def _get_objs(self, pk, movement_pk):
        rental = get_object_or_404(Rental, pk=pk)
        movement = get_object_or_404(
            Movement.objects.select_related('rental_item__product'),
            pk=movement_pk, rental_item__rental=rental,
            kind=Movement.Kind.RETURN,
        )
        return rental, movement

    def get(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        return render(request, 'config/rentals/_movement_edit_modal.html', {
            'rental': rental, 'movement': movement,
            'date_value': timezone.localtime(movement.date).strftime('%Y-%m-%dT%H:%M'),
            'errors': [],
        })

    def post(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        new_dt = _parse_local_dt(request.POST.get('date'))
        if new_dt is None:
            return render(request, 'config/rentals/_movement_edit_modal.html', {
                'rental': rental, 'movement': movement,
                'date_value': (request.POST.get('date') or '').strip(),
                'errors': [_('Укажите корректные дату и время.')],
            })
        movement.date = new_dt
        movement.save(update_fields=['date'])
        messages.success(request, _('Время возврата обновлено.'))
        return _oob_response(request, _reload_rental(rental.pk))
```

Ограничение `kind=RETURN` в `_get_objs` защищает от правки выдач через прямой URL.

**URL (config/urls.py):**

```python
path('rentals/<int:pk>/movement/<int:movement_pk>/edit/',
     views.RentalMovementEditView.as_view(), name='rental_movement_edit'),
```

**`_movement_edit_modal.html` (новый)** — маленькая модалка по образцу
`_item_edit_modal.html`: заголовок «Изменить время возврата · <товар>», блок
ошибок, одно поле `datetime-local` (`name="date"`, `value="{{ date_value }}"`),
кнопки «Отмена» / «Сохранить», `hx-post` на `rental_movement_edit`,
`hx-target="#modal-slot"`.

**`_timeline.html`** — у строк возврата (`m.kind != 'issue'`) добавить, под
гейтом `{% if is_admin %}`, карандаш открытия модалки:

```html
{% if is_admin and m.kind != 'issue' %}
    <button type="button" class="btn btn-sm btn-link p-0 ms-2"
            title="{% trans 'Изменить время' %}"
            hx-get="{% url 'rental_movement_edit' rental.pk m.pk %}"
            hx-target="#modal-slot" hx-swap="innerHTML">
        <i class="bi bi-pencil"></i>
    </button>
{% endif %}
```

`rental` уже в области видимости таймлайна (`_timeline.html` включается без
`only` внутри `_card.html` / `_oob_refresh.html`), поэтому берём `rental.pk`, а не
идём через `m.rental_item.rental_id`.

`is_admin` доступен из контекст-процессора `navigation`
(config/context_processors.py:111) и на детальной странице, и в OOB-фрагментах;
`_rental_card_context` его не кладёт, но `_oob_response` дублирует явно —
дополнительно ничего заводить не нужно.

## Тестирование

`tests/` (рядом с `test_rental_flow` / соответствующим набором по возвратам):

Приёмка с выбором времени:
- POST возврата с `return_at` → `Movement.date` == выбранному моменту.
- Пустая сумма + более раннее `return_at` → сохранённый `amount` меньше, чем при
  `as_of=now` (авторасчёт считается по выбранному времени).
- Введённая вручную сумма + любое `return_at` → сумма сохранена как есть.
- Пустой `return_at` → `date` ≈ `now` (движение создаётся).
- Кривой `return_at` (непустой, не парсится) → ошибка в модалке, движение НЕ
  создано.

Правка времени постфактум:
- admin POST `rental_movement_edit` → `Movement.date` изменился; `amount`/`charge`
  НЕ изменились.
- Работает на **закрытой** аренде (status CLOSED) — время меняется, 200/OOB.
- staff (не admin) → **403** на GET и POST (`AdminRequiredMixin` → `role_required`
  → `PermissionDenied`).
- Правка через URL движения **выдачи** → 404 (гейт `kind=RETURN`).
- Таймлайн: карандаш виден админу у возвратов; не виден у выдач и не-админу.

Часовой пояс:
- `_parse_local_dt('2026-07-14T03:22')` → aware-datetime в `Asia/Tashkent`;
  round-trip через `localtime(...).strftime(...)` даёт исходную строку.

## Вне рамок (YAGNI)

- Правка времени у движений **выдачи** (`ISSUE`).
- Пересчёт сумм при изменении времени возврата.
- Клиентский пересчёт `days_avg`/живого предпросмотра при смене даты в модалке
  (сервер авторитетен для пустых сумм; предпросмотр остаётся оценкой «от сейчас»).
- Жёсткая валидация диапазона времени (нижняя/верхняя граница) — по требованию
  «любое время».
