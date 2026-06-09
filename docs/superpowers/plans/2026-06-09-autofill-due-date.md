# Auto-fill Rental Due Date Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При выборе товара на странице «Новая аренда» автоматически подставлять «Срок и время возврата» = время выдачи + кратчайшая «Норма (макс)» среди выбранных товаров, оставляя поле редактируемым.

**Architecture:** Серверная часть — один data-атрибут (`data-return-days`) в шаблоне выбранного товара, повторяющий приём с существующим `data-price`. Клиентская часть — функция `syncDueDate()` в `<script>` страницы создания, привязанная к htmx-событиям и изменению поля выдачи, с флагом «тронуто вручную».

**Tech Stack:** Django templates, htmx, vanilla JS, pytest (django).

Спека: `docs/superpowers/specs/2026-06-09-autofill-due-date-design.md`

---

### Task 1: Прокинуть срок товара в DOM выбранного товара (`data-return-days`)

**Files:**
- Test: `tests/test_product_picker.py` (добавить фикстуру + тесты)
- Modify: `config/templates/config/rentals/_item_product_picked.html`

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `tests/test_product_picker.py`:

```python
# ---------- срок возврата (data-return-days) ----------

@pytest.fixture
def kolonna_with_norm(cat):
    return Product.objects.create(
        name='Колонна с нормой', category=cat, unit='шт',
        stock_total=10, daily_price=Decimal('120.00'),
        deposit_per_unit=Decimal('0.00'),
        expected_min_days=2, expected_max_days=5,
    )


def test_pick_renders_return_days_when_norm_set(client_staff, kolonna_with_norm):
    """У товара с заданной нормой скрытый input несёт data-return-days=<макс>."""
    url = reverse('rental_item_product_pick',
                  args=[kolonna_with_norm.pk]) + '?row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 200
    assert 'data-return-days="5"' in r.content.decode()


def test_pick_renders_empty_return_days_without_norm(client_staff, kolonna):
    """У товара без нормы (expected_max_days=None) атрибут пустой —
    JS такую позицию пропустит."""
    url = reverse('rental_item_product_pick', args=[kolonna.pk]) + '?row_id=abc123'
    r = client_staff.get(url)
    assert 'data-return-days=""' in r.content.decode()
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `./venv/bin/python -m pytest tests/test_product_picker.py -k return_days -v`
Expected: FAIL — `data-return-days` не найден в выводе (атрибута ещё нет).

- [ ] **Step 3: Добавить атрибут в шаблон**

В `config/templates/config/rentals/_item_product_picked.html` заменить блок hidden input:

```html
    <input type="hidden" name="{{ field_name|default:'item_product' }}"
           value="{{ product.pk }}"
           data-price="{{ product.daily_price|unlocalize }}">
```

на:

```html
    <input type="hidden" name="{{ field_name|default:'item_product' }}"
           value="{{ product.pk }}"
           data-price="{{ product.daily_price|unlocalize }}"
           data-return-days="{{ product.expected_max_days|default:'' }}">
```

(`{{ ...|default:'' }}` даёт `data-return-days=""` для `None`.)

- [ ] **Step 4: Запустить тесты — убедиться, что проходят**

Run: `./venv/bin/python -m pytest tests/test_product_picker.py -k return_days -v`
Expected: PASS (2 теста).

- [ ] **Step 5: Прогнать весь файл пикера (регрессий нет)**

Run: `./venv/bin/python -m pytest tests/test_product_picker.py -v`
Expected: все тесты PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_product_picker.py config/templates/config/rentals/_item_product_picked.html
git commit -m "feat(rentals): expose product norm as data-return-days on picker"
```

---

### Task 2: Авто-подстановка срока возврата в JS страницы создания

**Files:**
- Modify: `config/templates/config/rentals/create.html` (блок `extra_js`, существующая IIFE)

JS-логика не покрывается автотестами (нет JS-харнесса в проекте) — проверяется вручную в Step 3. Это согласовано в спеке.

- [ ] **Step 1: Добавить логику авто-подстановки в существующую IIFE**

В `config/templates/config/rentals/create.html`, внутри `(function () { ... })();` блока `extra_js`, **перед** строкой `document.addEventListener('input', recalc);`, добавить:

```javascript
    // --- Авто-подстановка срока возврата по «Норме (макс)» товара ---
    const dueInput = document.querySelector('[name="due_date"]');
    // Если при загрузке поле уже заполнено (ре-рендер формы после ошибки
    // submit) — считаем значение ручным и не трогаем.
    let dueDateTouched = !!(dueInput && dueInput.value);

    // Ручной ввод оператора замораживает авто-подстановку. Программная
    // установка .value события не порождает, поэтому свои обновления сюда
    // не попадают.
    if (dueInput) {
        ['input', 'change'].forEach(evt =>
            dueInput.addEventListener(evt, () => { dueDateTouched = true; }));
    }

    function fmtLocal(d) {
        // datetime-local ждёт 'YYYY-MM-DDTHH:MM' в ЛОКАЛЬНОМ времени.
        // toISOString() уехал бы в UTC — собираем компоненты вручную.
        const p = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}` +
               `T${p(d.getHours())}:${p(d.getMinutes())}`;
    }

    function syncDueDate() {
        if (!dueInput || dueDateTouched) return;
        // Собрать сроки со всех выбранных товаров (целые >= 1).
        const days = [];
        document.querySelectorAll('input[name="item_product"]').forEach(inp => {
            const n = parseInt(inp.dataset.returnDays || '', 10);
            if (Number.isInteger(n) && n >= 1) days.push(n);
        });
        if (!days.length) return;          // нет норм — поле не трогаем
        const n = Math.min(...days);       // самый короткий срок
        const base = readDt('created_at') || new Date();
        const due = new Date(base.getTime() + n * 86400000);
        dueInput.value = fmtLocal(due);    // программно — флаг не взводится
        recalc();
    }
```

- [ ] **Step 2: Привязать `syncDueDate` к событиям**

В той же IIFE, рядом с существующими подписками, добавить вызовы. Заменить блок:

```javascript
    document.addEventListener('input', recalc);
    document.addEventListener('change', recalc);

    // Когда htmx добавляет новую строку — пересчитать заново.
    document.body.addEventListener('htmx:afterSwap', recalc);
    document.body.addEventListener('htmx:afterSettle', recalc);

    document.addEventListener('DOMContentLoaded', recalc);
```

на:

```javascript
    document.addEventListener('input', recalc);
    document.addEventListener('change', recalc);

    // Изменение времени выдачи сдвигает базу авто-срока (пока не тронуто вручную).
    const createdInput = document.querySelector('[name="created_at"]');
    if (createdInput) {
        ['input', 'change'].forEach(evt =>
            createdInput.addEventListener(evt, syncDueDate));
    }

    // Когда htmx подменяет строку/пикер (выбор, смена, очистка, удаление) —
    // пересчитать срок и итоги.
    document.body.addEventListener('htmx:afterSwap', recalc);
    document.body.addEventListener('htmx:afterSettle', () => {
        syncDueDate();
        recalc();
    });

    document.addEventListener('DOMContentLoaded', () => {
        syncDueDate();
        recalc();
    });
```

- [ ] **Step 3: Ручная проверка в браузере**

Запустить дев-сервер (framework python, не ./venv — см. CLAUDE.md memory):
Run: `python manage.py runserver`

Открыть «Новая аренда» и проверить сценарии (нужны товары с заданной «Нормой (макс)» — напр. созданные в Task 1 или существующие):
1. Выбрать товар с нормой 5 дней → «Срок и время возврата» = время выдачи + 5 дней, то же время суток.
2. Изменить «Дата и время выдачи» → срок пересчитывается от новой базы.
3. Вручную поправить срок → выбрать ещё товар → срок **не** перезаписывается.
4. Перезагрузить страницу, выбрать товар с нормой 5, затем второй товар с нормой 2 → срок укорачивается до выдача + 2 дня.
5. Выбрать товар **без** нормы → поле срока пустое/без изменений, ввести вручную → submit проходит.
6. Submit с авто-подставленным сроком → аренда создаётся, ошибок валидации нет.

Expected: все 6 сценариев ведут себя как описано.

- [ ] **Step 4: Прогнать весь тест-сьют (регрессий нет)**

Run: `./venv/bin/python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 5: Commit**

```bash
git add config/templates/config/rentals/create.html
git commit -m "feat(rentals): auto-fill due date from product norm on rental create"
```

---

## Self-Review

**Spec coverage:**
- Источник `expected_max_days` → Task 1 (data-атрибут) + Task 2 (чтение). ✓
- Минимум при нескольких товарах → Task 2, `Math.min(...days)`. ✓
- Ручная правка побеждает → Task 2, `dueDateTouched`. ✓
- Только страница создания → правки лишь в `create.html` и общем picked-партиале (безвреден в модалках). ✓
- Срабатывание на htmx/created_at → Task 2, Step 2. ✓
- Игнор товаров без нормы / пустой список → `data-return-days=""` пропускается. ✓
- Сохранение времени суток, локальный формат → `fmtLocal`. ✓
- Тест сервера по аналогии с test_product_picker → Task 1. ✓

**Placeholder scan:** плейсхолдеров нет; весь код приведён.

**Type consistency:** `syncDueDate`, `fmtLocal`, `dueInput`, `dueDateTouched`, `readDt` (существующая), `recalc` (существующая) — имена согласованы между шагами.
