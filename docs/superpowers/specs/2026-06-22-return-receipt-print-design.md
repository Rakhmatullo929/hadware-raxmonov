# Дизайн: печать чека при оформлении возврата

Дата: 2026-06-22
Статус: утверждён (брейншторм)

## Цель

При **каждом оформлении возврата** оператор должен получать печатный **чек**
с информацией о том, что и сколько вернул клиент и **на какую сумму** начислена
аренда за возвращённые единицы. Чек открывается автоматически сразу после
подтверждения возврата, печатается из браузера и доступен как PDF.

Состав чека (из ТЗ):

- **Клиент — ФИО**
- **Тип товара** (категория)
- **Наименование**
- **Кол-во**
- **Стоимость** (начислено за позицию)
- **За день** (цена/сутки)
- **Дата и время**

## Принятые решения (из брейншторма)

1. **Триггер — авто после возврата.** Окно чека открывается автоматически
   сразу после подтверждения возврата (новая вкладка/окно браузера).
2. **Охват — текущая партия.** Один чек = все позиции, возвращённые в этом
   оформлении (одна отправка формы возврата = пачка `Movement(kind=return)`,
   созданных в одной транзакции). Не вся история аренды и не отдельное движение.
3. **Формат — HTML-печать + PDF.** HTML-чек на базе `print_base.html`
   (компактный размер A6 по умолчанию) + кнопка «Скачать PDF» (fpdf2), как у
   договора.
4. **Суммы — начислено за аренду.** «Стоимость» = начисление за возвращённые
   единицы (`Movement.amount`, тот же источник, что таймлайн/отчёт). Возврат
   залога (`Payment kind=refund`) на чек **не** выводим.
5. **Переиспользование PDF-кода через общий модуль.** Загрузка шрифтов,
   `_money`, исключения и водяной знак выносятся из `contract_pdf.py` в новый
   `config/pdf_common.py`; оба PDF-модуля импортируют оттуда.

## Архитектура

Новых полей/миграций БД **не требуется**: чек привязывается к ID уже
существующих движений возврата.

### 1. Привязка чека к партии возврата (config/views.py)

`RentalReturnView.post` (config/views.py:1204) — в транзакции при создании
движений собрать их ID:

```python
created_ids = []
with transaction.atomic():
    for it, qty, amount in plan:
        if amount is None:
            amount = billing.compute_return_amount_for_qty(it, qty)
        mv = Movement.objects.create(
            rental_item=it, kind=Movement.Kind.RETURN,
            qty=qty, amount=amount, note=note, created_by=request.user,
        )
        created_ids.append(mv.pk)
    rental.refresh_from_db()
    rental.maybe_auto_close()
```

После рендера `_oob_refresh.html` навесить заголовок `HX-Trigger`, который
скажет фронту открыть чек по этим ID:

```python
import json
...
response = render(request, 'config/rentals/_oob_refresh.html', ctx)
receipt_url = (
    reverse('rental_return_receipt', args=[rental.pk])
    + '?m=' + ','.join(str(i) for i in created_ids)
    + '&autoprint=1'
)
response['HX-Trigger'] = json.dumps(
    {'openReturnReceipt': {'url': receipt_url}}
)
return response
```

Заголовок ставится **только на успешном пути** (движения созданы). На пути
ошибок (перерисовка модалки) и при списании (`RentalCloseView`) чек не
триггерится.

### 2. Авто-открытие на фронте (static/js/return-receipt.js)

Новый JS, подключённый в `templates/base.html` рядом с `money-input.js` и
`return-amount.js`:

```javascript
document.body.addEventListener('openReturnReceipt', function (e) {
    var url = (e.detail && e.detail.url) || '';
    if (!url) return;
    var win = window.open(url, '_blank');
    if (!win) {
        // Попап заблокирован — показываем fallback-ссылку (toast/баннер).
        showReceiptFallback(url);
    }
});
```

`showReceiptFallback(url)` создаёт фиксированный поверх-страницы баннер/тост с
крупной ссылкой «🧾 Открыть чек возврата» (`target="_blank"`), авто-скрывается
через ~15 с или по клику.

**Честно про блокировку попапов:** `window.open` из обработчика ответа htmx не
всегда считается «прямым» жестом пользователя и может блокироваться браузером.
Поэтому fallback-ссылка обязательна — она гарантирует доступ к чеку, даже если
авто-открытие не сработало. Шаблон `_oob_refresh.html` при этом не меняется
(весь fallback — в JS).

### 3. HTML-чек

**Роут (config/urls.py):**

```python
path('rentals/<int:pk>/return-receipt/', views.rental_return_receipt,
     name='rental_return_receipt'),
path('rentals/<int:pk>/return-receipt.pdf', views.rental_return_receipt_pdf,
     name='rental_return_receipt_pdf'),
```

**View `rental_return_receipt(request, pk)`** (по образцу `rental_contract`,
config/views.py:1302; декоратор `@role_required('staff', 'admin')`):

1. Получить `Rental` (`select_related('customer')`, prefetch items/product/
   category, movements).
2. Распарсить `?m=` → список int ID. Выбрать движения этой аренды с
   `kind=Movement.Kind.RETURN` и `id in m_ids`. Чужие/несуществующие ID
   отбрасываются. Если валидных движений нет → `Http404`.
3. Суммы — через `billing.return_charge_map(rental)` (config/billing.py:135):
   `{movement_id: charge}`. Это **тот же** источник, что таймлайн/отчёт, цифры
   совпадут.
4. Собрать строки чека (по каждому выбранному движению):

   ```python
   row = {
       'category': it.product.category,        # Тип товара
       'name': it.product.name,                # Наименование
       'qty': m.qty,                           # Кол-во
       'unit': it.product.unit,
       'price_per_day': it.price_per_day,      # За день
       'amount': charges.get(m.id),            # Стоимость (начислено)
       'date': m.date,                         # Дата и время
   }
   ```

   `total_qty = Σ qty`, `total_amount = Σ amount`. Время чека (шапка) — дата
   первого движения партии (`min(m.date)`); все движения партии разделяют ~один
   момент.
5. `size = normalize_size(request.GET.get('size'))` с дефолтом `quarter`
   (компактный чек A6). `autoprint = request.GET.get('autoprint') == '1'`.
6. Контекст: `rental`, `customer`, `rows`, `total_qty`, `total_amount`,
   `receipt_dt`, `size`, `autoprint`, `back_url`, ссылка на PDF (тот же `m`).

**Шаблон `config/templates/config/rentals/return_receipt.html`** на
`{% extends 'print_base.html' %}`:

- Шапка: «ЧЕК ВОЗВРАТА · Аренда №{id}», **дата и время** возврата,
  **Клиент — ФИО** (+ код/телефон).
- Таблица позиций: `№ · Тип товара · Наименование · Кол-во (+ед.) · За день ·
  Стоимость`. Денежные значения — моноширинно, через тот же стиль, что договор.
- Итог: выделенная строка **«Возврат: {total_qty} ед. на сумму {total_amount}
  сум»** (прямой ответ на «сколько вернул и на какую сумму») + строка ИТОГО
  под таблицей. Примечание (`note`), если задано.
- В тулбар `print_base` добавить кнопку **«Скачать PDF»** (ссылка на
  `rental_return_receipt_pdf` с тем же `m`). Кнопка «Печать» и «← Назад» уже
  есть в `print_base`.
- Авто-печать: при `autoprint=1` — один `window.print()` на `window.onload`
  (через небольшой `<script>` в шаблоне, под флагом контекста). При ручном
  открытии (без флага) сам не печатает.

### 4. PDF-чек

**View `rental_return_receipt_pdf(request, pk)`** (по образцу
`rental_contract_pdf`, config/views.py:1332): тот же разбор `?m=`, сборка
движений и сумм, затем:

```python
from .return_receipt_pdf import build_return_receipt_pdf
from .pdf_common import PdfFontMissing, PdfDependencyMissing
try:
    pdf_bytes = build_return_receipt_pdf(rental, rows, total_qty, total_amount, receipt_dt)
except (PdfFontMissing, PdfDependencyMissing) as e:
    messages.error(request, str(e))
    return HttpResponseRedirect(reverse('rental_detail', args=[rental.pk]))
response = HttpResponse(pdf_bytes, content_type='application/pdf')
disposition = 'inline' if request.GET.get('inline') else 'attachment'
response['Content-Disposition'] = f'{disposition}; filename="return-receipt-{rental.pk}.pdf"'
return response
```

**Новый модуль `config/return_receipt_pdf.py`** с
`build_return_receipt_pdf(rental, rows, total_qty, total_amount, receipt_dt)`:
компактный A6-чек (формат `(105, 148)` мм, как `quarter` договора). Шапка
(№ аренды, дата/время, клиент), таблица `Тип · Наименование · Кол-во · За день
· Стоимость`, итоговая строка «Возврат: N ед. на сумму S сум». Использует общие
хелперы из `pdf_common`.

### 5. Общий PDF-модуль (config/pdf_common.py)

Вынести из `contract_pdf.py` в новый `config/pdf_common.py`:

- `BASE_DIR`, `_FONT_CANDIDATES`, `_BOLD_CANDIDATES`, `_first_existing`,
  `resolve_fonts()` (вернуть `(regular, bold)` или бросить исключение);
- `_money` → публичный `money(value)`;
- исключения: `PdfFontMissing`, `PdfDependencyMissing`;
- `draw_watermark(pdf)` и константы водяного знака.

`contract_pdf.py` после рефакторинга:

- импортирует эти имена из `pdf_common`;
- для обратной совместимости (другие импортируют `ContractFontMissing` /
  `ContractDependencyMissing` из `contract_pdf`, см. config/views.py:1339-1344)
  оставить алиасы: `ContractFontMissing = PdfFontMissing`,
  `ContractDependencyMissing = PdfDependencyMissing` — либо обновить импорты в
  `views.py`. Решение: **оставить алиасы** в `contract_pdf`, чтобы не трогать
  лишний код; новый код использует имена из `pdf_common`.

Договорный PDF прикрыт тестами — рефакторинг проверяется ими (тот же результат).

### 6. Язык (i18n)

Метки чека — через `{% trans %}` с **русскими** msgid (доминирующий паттерн
проекта), поэтому по умолчанию чек на русском (как в ТЗ). Добавить узбекские
переводы новых строк в `locale/uz/LC_MESSAGES/django.po`
(`makemessages` → перевод → `compilemessages`), чтобы переключатель языка
работал и для чека. PDF использует `gettext` так же, как `contract_pdf`.

## Поток данных

```
[Оператор: «Подтвердить возврат»]
        │ hx-post rentals/<pk>/return/
        ▼
RentalReturnView.post → создаёт Movement(return)×N (created_ids)
        │ ответ: _oob_refresh.html  +  HX-Trigger: openReturnReceipt{url ?m=ids&autoprint=1}
        ▼
return-receipt.js: window.open(url)  ──(если заблокировано)──▶ fallback-баннер со ссылкой
        ▼
GET rentals/<pk>/return-receipt/?m=ids&autoprint=1
        │ return_charge_map → суммы; сборка строк
        ▼
return_receipt.html (A6, печать) ── «Скачать PDF» ──▶ rentals/<pk>/return-receipt.pdf?m=ids
                                                              │ build_return_receipt_pdf (fpdf2)
                                                              ▼ application/pdf
```

## Обработка ошибок и крайние случаи

- **`?m=` пустой/нет валидных движений** → `Http404` (чек печатать нечего).
- **ID чужой аренды** в `m` → отбрасывается (выборка строго по `rental.pk`).
- **fpdf2 не установлен / шрифт не найден** → как у договора: `messages.error`
  + редирект на `rental_detail` (HTML-чек при этом работает без fpdf2).
- **Попап заблокирован** → fallback-баннер со ссылкой (см. §2).
- **Закрытие аренды списанием** (`RentalCloseView`) — это тоже `Movement(return)`
  с `amount=null`, но чек оттуда **не** триггерится (нет `HX-Trigger`). При
  ручном заходе с такими ID `return_charge_map` отдаст авторасчёт — корректно.
- **Права** — `@role_required('staff', 'admin')` на обоих view, как у договора.

## Тестирование

Тесты в каталоге `tests/` (запуск: `./venv/bin/python -m pytest`).

`tests/test_rental_flow.py` (или новый `tests/test_return_receipt.py`):

- POST возврата → ответ содержит заголовок `HX-Trigger` с `openReturnReceipt`,
  URL включает ID именно созданных движений и `autoprint=1`.
- `rental_return_receipt` GET с валидным `m`: 200; строки чека содержат верные
  категорию, наименование, кол-во, цену/день и сумму; `total_qty`/`total_amount`
  равны сумме по движениям.
- Фильтрация: `m` с ID чужой аренды/несуществующими → они отброшены; если не
  осталось валидных → 404.
- Доступ: аноним/без роли → редирект/403 (как у `rental_contract`).

`tests/test_return_receipt_pdf.py`:

- `rental_return_receipt_pdf` GET с валидным `m` → 200, `application/pdf`,
  корректный `Content-Disposition`, непустое тело, сигнатура `%PDF`.
- При отсутствии fpdf2/шрифта (monkeypatch) → редирект на `rental_detail` с
  сообщением (как у договора).

`tests/test_contract_pdf.py` (существующие) — должны остаться зелёными после
выноса хелперов в `pdf_common` (страховка рефакторинга).

## Вне рамок (YAGNI)

- Кнопка ручной повторной печати чека в таймлайне (выбран триггер «только авто»;
  URL чека стабилен по `m`, при необходимости добавится позже).
- Вывод возврата залога (`Payment refund`) на чек.
- Чек по всей истории аренды или по отдельному движению (охват = текущая партия).
- Тепловой/узкий формат принтера (58/80 мм) — пока A6; параметр `size`
  оставляет задел.
- Новые поля/миграции БД.
