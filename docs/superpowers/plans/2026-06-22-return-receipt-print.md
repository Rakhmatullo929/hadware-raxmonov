# Печать чека при оформлении возврата — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При каждом оформлении возврата автоматически открывать печатный чек (HTML + PDF) с ФИО клиента, типом товара, наименованием, кол-вом, ценой за день, начисленной стоимостью и датой/временем — по позициям именно этой партии возврата.

**Architecture:** Чек привязывается к ID движений `Movement(kind=return)`, созданных в одной отправке формы возврата (`?m=1,2,3`). Возврат-POST добавляет HTTP-заголовок `HX-Trigger: openReturnReceipt{url}`, фронтовый JS открывает чек в новой вкладке (с fallback-ссылкой при блокировке попапа). HTML-чек рендерится на базе `print_base.html` (размер A6), PDF — через fpdf2. Общие PDF-хелперы (шрифты, деньги, водяной знак, ленивый импорт fpdf) выносятся в новый `config/pdf_common.py`, который переиспользуют и договор, и чек. Новых полей/миграций БД нет.

**Tech Stack:** Django, HTMX (HX-Trigger), fpdf2, pytest, Django i18n (ru/uz).

## Global Constraints

- Запуск тестов: `./venv/bin/python -m pytest` (НЕ `./venv/bin/pip`; интерпретатор сервера отличается, но тесты гонять этим).
- Новых полей моделей и миграций БД **не создавать**.
- Метки интерфейса — через `{% trans %}` / `gettext` с **русскими** msgid (доминирующий паттерн проекта); узбекские переводы добавляются в `locale/uz/LC_MESSAGES/django.po`.
- Денежные значения — `DecimalField(max_digits=12, decimal_places=2)`; форматирование тысяч — функция `money()` из `config/pdf_common.py` (PDF) / сырой Decimal (HTML, как в договоре).
- Доступ к печати — декоратор `@role_required('staff', 'admin')` (как у договора).
- Имя HTMX-события строго `openReturnReceipt`; `detail = {"url": "..."}`.
- Размер чека по умолчанию — `quarter` (A6); допустимы значения из `ALLOWED_SIZES` (`full|half|quarter`).
- Суммы возврата брать ТОЛЬКО через `billing.return_charge_map(rental)` (один источник с таймлайном/отчётом).
- Каждый коммит завершать строкой:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Вынести общие PDF-хелперы в `config/pdf_common.py` (рефактор без смены поведения)

**Files:**
- Create: `config/pdf_common.py`
- Modify: `config/contract_pdf.py` (импорты + удаление перенесённого кода + использование `resolve_fonts()`/`load_fpdf()`)
- Test: `tests/test_pdf_common.py` (новый), `tests/test_contract_pdf.py` (существующий — страховочная сеть)

**Interfaces:**
- Produces:
  - `config/pdf_common.py`:
    - `class PdfFontMissing(RuntimeError)`
    - `class PdfDependencyMissing(RuntimeError)`
    - `money(value) -> str` — `Decimal → "12 345.60"`
    - `resolve_fonts() -> tuple[str, str | None]` — `(regular_path, bold_path|None)`; бросает `PdfFontMissing`
    - `load_fpdf() -> module` — ленивый импорт `fpdf`; бросает `PdfDependencyMissing`
    - `draw_watermark(pdf) -> None`
  - `config/contract_pdf.py` сохраняет публичные имена (алиасы): `ContractFontMissing is PdfFontMissing`, `ContractDependencyMissing is PdfDependencyMissing`, `draw_watermark` (реэкспорт), `ALLOWED_SIZES`, `normalize_size`, `build_contract_pdf`.

- [ ] **Step 1: Написать падающие юнит-тесты для нового модуля**

Создать `tests/test_pdf_common.py`:

```python
"""Юнит-тесты общих PDF-хелперов (вынесены из contract_pdf)."""
from decimal import Decimal

from config import contract_pdf
from config.pdf_common import (
    PdfDependencyMissing,
    PdfFontMissing,
    money,
    resolve_fonts,
)


def test_money_groups_thousands():
    assert money(Decimal('12345.6')) == '12 345.60'
    assert money(0) == '0.00'
    assert money(Decimal('-1500')) == '-1 500.00'


def test_resolve_fonts_returns_regular_path():
    regular, bold = resolve_fonts()
    assert regular and isinstance(regular, str)
    assert bold is None or isinstance(bold, str)


def test_contract_aliases_point_to_common_exceptions():
    assert contract_pdf.ContractFontMissing is PdfFontMissing
    assert contract_pdf.ContractDependencyMissing is PdfDependencyMissing
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_pdf_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.pdf_common'`.

- [ ] **Step 3: Создать `config/pdf_common.py`**

```python
"""Общие хелперы серверной генерации PDF (договор, чек возврата).

Вынесено из contract_pdf.py: поиск TTF-шрифта с кириллицей/латиницей,
форматирование денег, ленивый импорт fpdf2, диагональный водяной знак.
Чистый Python, без системных зависимостей.
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)


class PdfFontMissing(RuntimeError):
    """Не найден ни один TTF-шрифт для PDF."""
    pass


class PdfDependencyMissing(RuntimeError):
    """Не установлен пакет fpdf2 — PDF собрать нечем."""
    pass


# Порядок поиска шрифта с поддержкой кириллицы и узбекской латиницы.
_FONT_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
    '/Library/Fonts/Arial Unicode.ttf',
]
_BOLD_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_BOLD_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
]


def _first_existing(paths):
    for p in paths:
        if not p:
            continue
        p = Path(p)
        if p.is_file():
            return str(p)
    return None


def resolve_fonts():
    """Вернуть (regular_path, bold_path|None). Бросить PdfFontMissing, если
    не найден ни один обычный шрифт."""
    regular = _first_existing(_FONT_CANDIDATES)
    if not regular:
        raise PdfFontMissing(
            'Не найден TTF-шрифт для PDF. Положите static/fonts/DejaVuSans.ttf '
            'или установите системный (apt install fonts-dejavu-core), '
            'либо задайте CONTRACT_PDF_FONT_PATH.'
        )
    bold = _first_existing(_BOLD_CANDIDATES)
    return regular, bold


def load_fpdf():
    """Ленивый импорт fpdf2; PdfDependencyMissing, если пакет не установлен."""
    try:
        import fpdf as fpdf_module
    except ImportError as exc:
        raise PdfDependencyMissing(
            'Для генерации PDF требуется пакет fpdf2. '
            'Установите его в текущий Python-интерпретатор: '
            '`pip install fpdf2`.'
        ) from exc
    return fpdf_module


def money(value) -> str:
    """12345.60 -> "12 345.60" (пробел-разделитель тысяч, 2 знака)."""
    q = Decimal(value or 0).quantize(Decimal('0.01'))
    intpart, _, frac = f'{q:.2f}'.partition('.')
    neg = intpart.startswith('-')
    intpart = intpart.lstrip('-')
    groups = []
    while intpart:
        groups.insert(0, intpart[-3:])
        intpart = intpart[:-3]
    return ('-' if neg else '') + ' '.join(groups) + '.' + frac


# Параметры водяного знака (перенесены из contract_pdf без изменений).
_WATERMARK_GRAY = 205
_WATERMARK_TEXT = 'Raxmonov'
_WATERMARK_WIDTH_FACTOR = 0.9


def draw_watermark(pdf):
    """Бледный диагональный текстовый водяной знак по центру текущей страницы.

    Рисуется встроенным core-шрифтом Helvetica (ASCII), не зависит от
    загруженного TTF. ``pdf.rotation(...)`` восстанавливает цвет/шрифт сам;
    курсор возвращаем явно. Угол −30° согласован с HTML-печатью.
    """
    g = _WATERMARK_GRAY
    x0, y0 = pdf.get_x(), pdf.get_y()
    cx, cy = pdf.w / 2, pdf.h / 2
    target_w = min(pdf.w, pdf.h) * _WATERMARK_WIDTH_FACTOR

    with pdf.rotation(-30, cx, cy):
        pdf.set_text_color(g, g, g)
        pdf.set_font('Helvetica', 'B', 100)
        w100 = pdf.get_string_width(_WATERMARK_TEXT) or 1
        size = 100 * target_w / w100
        pdf.set_font('Helvetica', 'B', size)
        tw = pdf.get_string_width(_WATERMARK_TEXT)
        th = size * 0.3528  # pt → mm
        pdf.set_xy(cx - tw / 2, cy - th / 2)
        pdf.cell(tw, th, _WATERMARK_TEXT, align='C')

    pdf.set_xy(x0, y0)
```

- [ ] **Step 4: Переключить `config/contract_pdf.py` на общий модуль**

В шапке файла `config/contract_pdf.py` заменить блок импортов (строки 16–21):

```python
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
```

на:

```python
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

from .pdf_common import (
    PdfDependencyMissing as ContractDependencyMissing,
    PdfFontMissing as ContractFontMissing,
    draw_watermark,
    load_fpdf,
    money as _money,
    resolve_fonts,
)
```

Удалить из `config/contract_pdf.py` перенесённый код (теперь живёт в `pdf_common`):
- строку `BASE_DIR = Path(settings.BASE_DIR)`;
- блоки `_FONT_CANDIDATES = [...]` и `_BOLD_CANDIDATES = [...]`;
- классы `class ContractFontMissing(RuntimeError): pass` и `class ContractDependencyMissing(RuntimeError): ...`;
- функцию `def _first_existing(paths): ...`;
- функцию `def _money(value) -> str: ...`;
- константы `_WATERMARK_GRAY`, `_WATERMARK_TEXT`, `_WATERMARK_WIDTH_FACTOR` и функцию `def draw_watermark(pdf): ...`.

Оставить без изменений: `SIZE_*`, `ALLOWED_SIZES`, `normalize_size`, `_LAYOUTS`, `_make_contract_pdf`, `_draw_items_table`, `build_contract_pdf`.

Внутри `build_contract_pdf` заменить ленивый импорт fpdf (строки ~334–341):

```python
    try:
        import fpdf as fpdf_module  # ленивый импорт: HTML-печать не зависит от него
    except ImportError as exc:
        raise ContractDependencyMissing(
            'Для генерации PDF договора требуется пакет fpdf2. '
            'Установите его в текущий Python-интерпретатор: '
            '`pip install fpdf2`.'
        ) from exc
```

на:

```python
    fpdf_module = load_fpdf()
```

и заменить блок поиска шрифта (строки ~347–354):

```python
    font_regular = _first_existing(_FONT_CANDIDATES)
    if not font_regular:
        raise ContractFontMissing(
            'Не найден TTF-шрифт для PDF. Положите static/fonts/DejaVuSans.ttf '
            'или установите системный (apt install fonts-dejavu-core), '
            'либо задайте CONTRACT_PDF_FONT_PATH.'
        )
    font_bold = _first_existing(_BOLD_CANDIDATES)
```

на:

```python
    font_regular, font_bold = resolve_fonts()
```

- [ ] **Step 5: Запустить тесты — новый модуль и весь PDF-договор**

Run: `./venv/bin/python -m pytest tests/test_pdf_common.py tests/test_contract_pdf.py -v`
Expected: PASS — все тесты зелёные (рефактор не изменил поведение договора; `draw_watermark` по-прежнему импортируется из `config.contract_pdf`).

- [ ] **Step 6: Commit**

```bash
git add config/pdf_common.py config/contract_pdf.py tests/test_pdf_common.py
git commit -m "refactor(pdf): вынести шрифты/деньги/водяной знак в pdf_common

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Хелперы контекста чека + общие тест-фикстуры

**Files:**
- Modify: `config/views.py` (добавить `_parse_movement_ids`, `build_return_receipt_context`)
- Modify: `tests/conftest.py` (добавить фикстуры `client_staff`, `client_admin`, `rental_with_returns`)
- Test: `tests/test_return_receipt.py` (новый)

**Interfaces:**
- Produces (в `config/views.py`):
  - `_parse_movement_ids(raw: str | None) -> list[int]` — `"1,2,x,3" → [1,2,3]`
  - `build_return_receipt_context(rental, movement_ids) -> dict` со ключами:
    `rental`, `customer`, `rows` (список dict: `category, name, qty, unit, price_per_day, amount, date`), `total_qty: int`, `total_amount: Decimal`, `receipt_dt: datetime|None`, `note: str`
- Produces (в `tests/conftest.py`): фикстуры `client_staff`, `client_admin`, `rental_with_returns` (возвращает кортеж `(rental, item, m1, m2)`, где m1 qty=4/amount=400, m2 qty=3/amount=300).
- Consumes: `billing.return_charge_map` (config/billing.py:135), `Movement`, `Rental`, `RentalItem` (config/models.py).

- [ ] **Step 1: Добавить общие фикстуры в `tests/conftest.py`**

В начало `tests/conftest.py` дополнить импорты:

```python
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from config.models import (
    Category,
    Customer,
    Movement,
    Product,
    Rental,
    RentalItem,
)
```

В конец файла добавить фикстуры:

```python
@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def rental_with_returns(db, customer, product, staff_user):
    """Аренда: выдано 10, два возврата (4 и 3) с явными суммами 400 и 300."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=10, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        created_by=staff_user,
    )
    m1 = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=4,
        amount=Decimal('400.00'), note='партия возврата', created_by=staff_user,
    )
    m2 = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=3,
        amount=Decimal('300.00'), created_by=staff_user,
    )
    return r, item, m1, m2
```

- [ ] **Step 2: Написать падающие тесты хелперов**

Создать `tests/test_return_receipt.py`:

```python
"""Тесты чека возврата: контекст, HTML-страница, авто-триггер."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Rental, RentalItem
from config.views import _parse_movement_ids, build_return_receipt_context


def test_parse_movement_ids_drops_invalid():
    assert _parse_movement_ids('1,2,x,3,') == [1, 2, 3]
    assert _parse_movement_ids('') == []
    assert _parse_movement_ids(None) == []


def test_build_context_totals(rental_with_returns, product):
    r, item, m1, m2 = rental_with_returns
    ctx = build_return_receipt_context(r, [m1.id, m2.id])
    assert len(ctx['rows']) == 2
    assert ctx['total_qty'] == 7
    assert ctx['total_amount'] == Decimal('700.00')
    assert ctx['rows'][0]['name'] == product.name
    assert str(ctx['rows'][0]['category']) == str(product.category)
    assert ctx['customer'] == r.customer
    assert ctx['receipt_dt'] is not None


def test_build_context_ignores_foreign_movements(
    rental_with_returns, customer, product, staff_user,
):
    r, item, m1, m2 = rental_with_returns
    other = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    oitem = RentalItem.objects.create(
        rental=other, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.ISSUE, qty=2,
        created_by=staff_user,
    )
    om = Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.RETURN, qty=2,
        amount=Decimal('200.00'), created_by=staff_user,
    )
    # om принадлежит другой аренде — должен быть отброшен.
    ctx = build_return_receipt_context(r, [m1.id, om.id])
    assert len(ctx['rows']) == 1
    assert ctx['rows'][0]['qty'] == 4
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -v`
Expected: FAIL — `ImportError: cannot import name '_parse_movement_ids' from 'config.views'`.

- [ ] **Step 4: Реализовать хелперы в `config/views.py`**

Добавить рядом с `_return_modal_context` (после строки 1112, перед `class RentalReturnView`):

```python
def _parse_movement_ids(raw):
    """'1,2,x,3' → [1, 2, 3]. Невалидные токены отбрасываются."""
    ids = []
    for tok in (raw or '').split(','):
        tok = tok.strip()
        if tok.isdigit():
            ids.append(int(tok))
    return ids


def build_return_receipt_context(rental, movement_ids):
    """Контекст чека возврата по партии движений (см. ?m=...).

    Берём только движения ВОЗВРАТА этой аренды с указанными id (чужие/
    несуществующие отбрасываются). Суммы — через billing.return_charge_map
    (тот же источник, что таймлайн/отчёт). Строки отсортированы по дате;
    receipt_dt — момент самого раннего движения партии.
    """
    charges = billing.return_charge_map(rental)
    movements = (
        Movement.objects
        .filter(
            rental_item__rental=rental,
            kind=Movement.Kind.RETURN,
            id__in=movement_ids,
        )
        .select_related('rental_item__product__category')
        .order_by('date', 'id')
    )
    rows = []
    total_qty = 0
    total_amount = Decimal('0.00')
    note = ''
    for m in movements:
        it = m.rental_item
        amount = charges.get(m.id) or Decimal('0.00')
        rows.append({
            'category': it.product.category,
            'name': it.product.name,
            'qty': m.qty,
            'unit': it.product.unit,
            'price_per_day': it.price_per_day,
            'amount': amount,
            'date': m.date,
        })
        total_qty += m.qty
        total_amount += amount
        if not note and m.note:
            note = m.note
    return {
        'rental': rental,
        'customer': rental.customer,
        'rows': rows,
        'total_qty': total_qty,
        'total_amount': total_amount,
        'receipt_dt': rows[0]['date'] if rows else None,
        'note': note,
    }
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -v`
Expected: PASS (3 теста).

- [ ] **Step 6: Commit**

```bash
git add config/views.py tests/conftest.py tests/test_return_receipt.py
git commit -m "feat(receipt): контекст чека возврата + тест-фикстуры

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: PDF-чек — модуль `return_receipt_pdf.py`, view и роут

**Files:**
- Create: `config/return_receipt_pdf.py`
- Modify: `config/views.py` (view `rental_return_receipt_pdf` + импорт `Http404`)
- Modify: `config/urls.py` (роут `rental_return_receipt_pdf`)
- Test: `tests/test_return_receipt_pdf.py` (новый)

**Interfaces:**
- Consumes: `build_return_receipt_context` (Task 2), `pdf_common.{load_fpdf, resolve_fonts, money, draw_watermark, PdfFontMissing, PdfDependencyMissing}` (Task 1).
- Produces:
  - `config/return_receipt_pdf.py`: `build_return_receipt_pdf(ctx) -> bytes` (ctx — словарь из `build_return_receipt_context`).
  - `config/views.py`: view-функция `rental_return_receipt_pdf(request, pk)`.
  - URL name `rental_return_receipt_pdf` → `rentals/<int:pk>/return-receipt.pdf`.

- [ ] **Step 1: Написать падающие тесты PDF**

Создать `tests/test_return_receipt_pdf.py`:

```python
"""Тесты PDF-чека возврата (fpdf2)."""
from django.urls import reverse

from config.return_receipt_pdf import build_return_receipt_pdf
from config.views import build_return_receipt_context


def test_build_return_receipt_pdf_valid(rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    ctx = build_return_receipt_context(r, [m1.id, m2.id])
    pdf = build_return_receipt_pdf(ctx)
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 500


def test_pdf_endpoint_attachment(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt_pdf', args=[r.pk]) + f'?m={m1.id},{m2.id}'
    resp = client_staff.get(url)
    assert resp.status_code == 200
    assert resp['Content-Type'] == 'application/pdf'
    assert 'attachment' in resp['Content-Disposition']
    assert f'return-receipt-{r.pk}.pdf' in resp['Content-Disposition']
    assert resp.content[:5] == b'%PDF-'


def test_pdf_endpoint_404_when_no_valid_ids(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt_pdf', args=[r.pk]) + '?m=999999'
    assert client_staff.get(url).status_code == 404


def test_pdf_endpoint_requires_auth(client, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt_pdf', args=[r.pk]) + f'?m={m1.id}'
    assert client.get(url).status_code in (302, 403)


def test_pdf_endpoint_font_missing_redirects(
    client_staff, rental_with_returns, monkeypatch,
):
    r, item, m1, m2 = rental_with_returns
    from config import return_receipt_pdf
    from config.pdf_common import PdfFontMissing

    def boom():
        raise PdfFontMissing('no font')

    monkeypatch.setattr(return_receipt_pdf, 'resolve_fonts', boom)
    url = reverse('rental_return_receipt_pdf', args=[r.pk]) + f'?m={m1.id}'
    resp = client_staff.get(url)
    assert resp.status_code == 302
    assert reverse('rental_detail', args=[r.pk]) in resp['Location']
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt_pdf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'config.return_receipt_pdf'`.

- [ ] **Step 3: Создать `config/return_receipt_pdf.py`**

```python
"""Серверная генерация PDF-чека возврата через fpdf2.

Компактный формат A6 (105×148 мм), общий стиль с договором: тот же шрифт,
форматирование денег и водяной знак (см. config/pdf_common.py).
"""
from django.utils.translation import gettext as _

from .pdf_common import draw_watermark, load_fpdf, money, resolve_fonts

_PAGE = (105, 148)  # A6 в мм
_ROW_H = 4.6


def build_return_receipt_pdf(ctx) -> bytes:
    """Собрать PDF-чек по контексту build_return_receipt_context.

    :param ctx: словарь с ключами rental, customer, rows, total_qty,
                total_amount, receipt_dt, note.
    :returns:   готовый PDF в bytes.
    :raises PdfFontMissing / PdfDependencyMissing: см. pdf_common.
    """
    fpdf_module = load_fpdf()
    font_regular, font_bold = resolve_fonts()

    rental = ctx['rental']
    customer = ctx['customer']
    rows = ctx['rows']

    class _ReceiptPDF(fpdf_module.FPDF):
        def __init__(self):
            super().__init__(format=_PAGE)
            self.set_auto_page_break(auto=True, margin=8)
            self.set_margins(8, 8, 8)
            self.add_font('Body', '', font_regular)
            self.add_font('Body', 'B', font_bold or font_regular)
            self.set_font('Body', size=8)

        def header(self):
            draw_watermark(self)

    pdf = _ReceiptPDF()
    pdf.add_page()
    w = pdf.epw

    # ---- Заголовок ----
    pdf.set_font('Body', 'B', 11)
    pdf.cell(0, 6, _('ЧЕК ВОЗВРАТА'), align='C',
             new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Body', size=7)
    pdf.set_text_color(110, 110, 110)
    when = ctx['receipt_dt'].strftime('%d.%m.%Y %H:%M') if ctx['receipt_dt'] else ''
    pdf.cell(0, 4, _('Аренда №%(n)s') % {'n': rental.pk} + ' · ' + when,
             align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    # ---- Клиент ----
    pdf.set_font('Body', 'B', 8)
    pdf.cell(0, 4, _('Клиент:'), new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Body', size=8)
    bits = [customer.full_name]
    if customer.code:
        bits.append('№ ' + customer.code)
    if customer.phone:
        bits.append(customer.phone)
    pdf.multi_cell(0, 4, ' · '.join(bits), new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)

    # ---- Таблица позиций ----
    headers = [
        ('№', 0.08, 'C'),
        (_('Тип'), 0.22, 'L'),
        (_('Наименование'), 0.34, 'L'),
        (_('Кол-во'), 0.12, 'R'),
        (_('За день'), 0.12, 'R'),
        (_('Стоимость'), 0.12, 'R'),
    ]
    pdf.set_font('Body', 'B', 7)
    pdf.set_fill_color(238, 240, 242)
    for title, frac, _a in headers:
        pdf.cell(w * frac, _ROW_H, str(title), border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font('Body', size=7)
    for idx, row in enumerate(rows, start=1):
        cells = [
            (str(idx), 0.08, 'C'),
            (str(row['category']), 0.22, 'L'),
            (row['name'], 0.34, 'L'),
            (f"{row['qty']} {row['unit']}", 0.12, 'R'),
            (money(row['price_per_day']), 0.12, 'R'),
            (money(row['amount']), 0.12, 'R'),
        ]
        if pdf.will_page_break(_ROW_H):
            pdf.add_page()
        for text, frac, align in cells:
            pdf.cell(w * frac, _ROW_H, str(text), border=1, align=align)
        pdf.ln()

    # ---- Итог ----
    pdf.set_font('Body', 'B', 7)
    pdf.cell(w * 0.64, _ROW_H, _('Итого'), border=1, align='R')
    pdf.cell(w * 0.12, _ROW_H, str(ctx['total_qty']), border=1, align='R')
    pdf.cell(w * 0.12, _ROW_H, '', border=1)
    pdf.cell(w * 0.12, _ROW_H, money(ctx['total_amount']), border=1, align='R')
    pdf.ln(_ROW_H + 2)

    pdf.set_font('Body', 'B', 8)
    pdf.multi_cell(
        0, 4,
        _('Возврат: %(q)s ед. на сумму %(s)s сум')
        % {'q': ctx['total_qty'], 's': money(ctx['total_amount'])},
        new_x='LMARGIN', new_y='NEXT',
    )

    if ctx.get('note'):
        pdf.ln(1)
        pdf.set_font('Body', size=7)
        pdf.set_text_color(110, 110, 110)
        pdf.multi_cell(0, 4, _('Примечание: ') + ctx['note'],
                       new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(0, 0, 0)

    return bytes(pdf.output())
```

- [ ] **Step 4: Добавить view в `config/views.py`**

Сначала добавить `Http404` в импорт `django.http` (строка 22):

```python
from django.http import Http404, HttpResponse, HttpResponseRedirect
```

Добавить view рядом с `rental_contract_pdf` (после строки 1363):

```python
@role_required('staff', 'admin')
def rental_return_receipt_pdf(request, pk):
    """Скачать чек возврата как PDF (fpdf2). Параметр ?m=ids — партия движений."""
    from .pdf_common import PdfDependencyMissing, PdfFontMissing
    from .return_receipt_pdf import build_return_receipt_pdf

    rental = get_object_or_404(
        Rental.objects.select_related('customer'), pk=pk,
    )
    ids = _parse_movement_ids(request.GET.get('m'))
    ctx = build_return_receipt_context(rental, ids)
    if not ctx['rows']:
        raise Http404('Нет движений возврата для чека.')
    try:
        pdf_bytes = build_return_receipt_pdf(ctx)
    except (PdfFontMissing, PdfDependencyMissing) as e:
        messages.error(request, str(e))
        return HttpResponseRedirect(reverse('rental_detail', args=[rental.pk]))

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = (
        f'{disposition}; filename="return-receipt-{rental.pk}.pdf"'
    )
    return response
```

- [ ] **Step 5: Добавить роут в `config/urls.py`**

После строки 92 (роут `rental_contract_pdf`) добавить:

```python
    path(
        'rentals/<int:pk>/return-receipt.pdf',
        views.rental_return_receipt_pdf,
        name='rental_return_receipt_pdf',
    ),
```

- [ ] **Step 6: Запустить — убедиться, что проходит**

Run: `./venv/bin/python -m pytest tests/test_return_receipt_pdf.py -v`
Expected: PASS (5 тестов).

- [ ] **Step 7: Commit**

```bash
git add config/return_receipt_pdf.py config/views.py config/urls.py tests/test_return_receipt_pdf.py
git commit -m "feat(receipt): PDF-чек возврата (A6) + роут

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: HTML-чек — view, шаблон, роут

**Files:**
- Create: `config/templates/config/rentals/return_receipt.html`
- Modify: `config/views.py` (view `rental_return_receipt`)
- Modify: `config/urls.py` (роут `rental_return_receipt`)
- Test: `tests/test_return_receipt.py` (дополнить)

**Interfaces:**
- Consumes: `build_return_receipt_context`, `_parse_movement_ids` (Task 2), `ALLOWED_SIZES` (config/contract_pdf.py), URL name `rental_return_receipt_pdf` (Task 3).
- Produces: view `rental_return_receipt(request, pk)`; URL name `rental_return_receipt` → `rentals/<int:pk>/return-receipt/`; шаблон, рендерящий чек на `print_base.html` (по умолчанию `print-page--quarter`), с `data-autoprint`-скриптом при `?autoprint=1`.

- [ ] **Step 1: Дописать падающие тесты HTML-страницы**

Добавить в конец `tests/test_return_receipt.py`:

```python
def test_receipt_html_renders(client_staff, rental_with_returns, product):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id},{m2.id}'
    resp = client_staff.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'ЧЕК ВОЗВРАТА' in body
    assert r.customer.full_name in body
    assert product.name in body
    assert 'Тип товара' in body
    assert '700.00' in body            # итоговая сумма
    assert 'print-page--quarter' in body  # размер по умолчанию
    assert 'return-receipt.pdf' in body   # ссылка «Скачать PDF»


def test_receipt_html_autoprint_flag(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    base = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
    assert 'data-autoprint' in client_staff.get(base + '&autoprint=1').content.decode()
    assert 'data-autoprint' not in client_staff.get(base).content.decode()


def test_receipt_html_404_when_no_valid_ids(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + '?m=999999'
    assert client_staff.get(url).status_code == 404


def test_receipt_html_requires_auth(client, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
    assert client.get(url).status_code in (302, 403)
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -k html -v`
Expected: FAIL — `NoReverseMatch: Reverse for 'rental_return_receipt' not found`.

- [ ] **Step 3: Создать шаблон `config/templates/config/rentals/return_receipt.html`**

```django
{% extends 'print_base.html' %}
{% load i18n %}

{% block title %}{% trans "Чек возврата" %}{% endblock %}
{% block page_class %}print-page--{{ size }}{% endblock %}

{% block content %}
<div class="d-print-none mb-3">
    <a href="{{ pdf_url }}" class="btn btn-sm btn-outline-secondary">
        <i class="bi bi-file-earmark-pdf"></i> {% trans "Скачать PDF" %}
    </a>
</div>

<div class="text-center mb-2">
    <div class="contract-h1">{% trans "ЧЕК ВОЗВРАТА" %}</div>
    <div class="text-muted small">
        {% blocktrans with rid=rental.pk %}Аренда №{{ rid }}{% endblocktrans %}
        · {{ receipt_dt|date:"d.m.Y H:i" }}
    </div>
</div>

<table class="table table-sm mb-2">
    <tbody>
        <tr>
            <th class="text-muted" style="width:32%">{% trans "Клиент" %}</th>
            <td>
                {{ customer.full_name }}
                {% if customer.code %}<span class="text-muted">· №{{ customer.code }}</span>{% endif %}
                {% if customer.phone %}<br><span class="text-muted small">{{ customer.phone }}</span>{% endif %}
            </td>
        </tr>
    </tbody>
</table>

<table class="table table-sm align-middle">
    <thead>
        <tr>
            <th>#</th>
            <th>{% trans "Тип товара" %}</th>
            <th>{% trans "Наименование" %}</th>
            <th class="text-end">{% trans "Кол-во" %}</th>
            <th class="text-end">{% trans "За день" %}</th>
            <th class="text-end">{% trans "Стоимость" %}</th>
        </tr>
    </thead>
    <tbody>
        {% for row in rows %}
        <tr>
            <td>{{ forloop.counter }}</td>
            <td>{{ row.category }}</td>
            <td>{{ row.name }}</td>
            <td class="text-end">{{ row.qty }} {{ row.unit }}</td>
            <td class="text-end font-monospace">{{ row.price_per_day }}</td>
            <td class="text-end font-monospace">{{ row.amount }}</td>
        </tr>
        {% endfor %}
    </tbody>
    <tfoot>
        <tr class="table-light fw-bold">
            <td colspan="3" class="text-end">{% trans "Итого" %}</td>
            <td class="text-end">{{ total_qty }}</td>
            <td></td>
            <td class="text-end font-monospace">{{ total_amount }}</td>
        </tr>
    </tfoot>
</table>

<div class="alert alert-light border fw-semibold">
    {% blocktrans with q=total_qty s=total_amount %}Возврат: {{ q }} ед. на сумму {{ s }} сум{% endblocktrans %}
</div>

{% if note %}
<div class="text-muted small">{% trans "Примечание" %}: {{ note }}</div>
{% endif %}

{% if autoprint %}
<script data-autoprint>
    window.addEventListener('load', function () { window.print(); });
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 4: Добавить view в `config/views.py`**

Добавить рядом с `rental_contract` (после строки 1329):

```python
@role_required('staff', 'admin')
def rental_return_receipt(request, pk):
    """HTML-чек возврата (печать из браузера). ?m=ids — партия движений,
    ?size=full|half|quarter (по умолчанию quarter), ?autoprint=1 — печать сразу."""
    from .contract_pdf import ALLOWED_SIZES

    rental = get_object_or_404(
        Rental.objects.select_related('customer'), pk=pk,
    )
    ids = _parse_movement_ids(request.GET.get('m'))
    ctx = build_return_receipt_context(rental, ids)
    if not ctx['rows']:
        raise Http404('Нет движений возврата для чека.')

    size = request.GET.get('size')
    if size not in ALLOWED_SIZES:
        size = 'quarter'
    ids_q = ','.join(str(i) for i in ids)
    ctx.update({
        'size': size,
        'autoprint': request.GET.get('autoprint') == '1',
        'pdf_url': reverse('rental_return_receipt_pdf', args=[rental.pk]) + f'?m={ids_q}',
        'back_url': reverse('rental_detail', args=[rental.pk]),
    })
    return render(request, 'config/rentals/return_receipt.html', ctx)
```

- [ ] **Step 5: Добавить роут в `config/urls.py`**

После роута `rental_return` (строка 86) добавить:

```python
    path(
        'rentals/<int:pk>/return-receipt/',
        views.rental_return_receipt,
        name='rental_return_receipt',
    ),
```

- [ ] **Step 6: Запустить — убедиться, что проходит**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 7: Commit**

```bash
git add config/templates/config/rentals/return_receipt.html config/views.py config/urls.py tests/test_return_receipt.py
git commit -m "feat(receipt): HTML-чек возврата (печать A6) + роут

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Авто-открытие — HX-Trigger в `RentalReturnView.post`

**Files:**
- Modify: `config/views.py` (импорт `json`; сбор `created_ids`; заголовок `HX-Trigger`)
- Test: `tests/test_return_receipt.py` (дополнить)

**Interfaces:**
- Consumes: URL name `rental_return_receipt` (Task 4).
- Produces: на успешном POST возврата ответ получает заголовок `HX-Trigger` = `{"openReturnReceipt": {"url": "/rentals/<pk>/return-receipt/?m=<ids>&autoprint=1"}}`.

- [ ] **Step 1: Дописать падающий тест триггера**

Добавить в конец `tests/test_return_receipt.py`:

```python
def test_return_post_emits_open_receipt_trigger(
    client_admin, customer, product, admin_user,
):
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=5, created_by=admin_user,
    )

    resp = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '2',
    }, HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    assert 'HX-Trigger' in resp

    payload = json.loads(resp['HX-Trigger'])
    assert 'openReturnReceipt' in payload
    url = payload['openReturnReceipt']['url']
    ret = Movement.objects.get(rental_item=item, kind=Movement.Kind.RETURN)
    assert f'm={ret.id}' in url
    assert 'autoprint=1' in url
    assert str(rental.pk) in url
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py::test_return_post_emits_open_receipt_trigger -v`
Expected: FAIL — `assert 'HX-Trigger' in resp` (заголовка ещё нет).

- [ ] **Step 3: Добавить `import json` в `config/views.py`**

В шапке файла (строка 1) заменить `import re` на:

```python
import json
import re
```

- [ ] **Step 4: Собирать ID движений и ставить заголовок в `RentalReturnView.post`**

В `RentalReturnView.post` заменить блок создания движений и возврата ответа (строки 1204–1231):

```python
        with transaction.atomic():
            for it, qty, amount in plan:
                if amount is None:
                    amount = billing.compute_return_amount_for_qty(it, qty)
                Movement.objects.create(
                    rental_item=it,
                    kind=Movement.Kind.RETURN,
                    qty=qty,
                    amount=amount,
                    note=note,
                    created_by=request.user,
                )
            rental.refresh_from_db()
            rental.maybe_auto_close()

        rental = (
            Rental.objects
            .select_related('customer', 'created_by', 'closed_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
            .get(pk=rental.pk)
        )
        ctx = _rental_card_context(rental)
        ctx['is_admin'] = user_is_admin(request.user)
        return render(request, 'config/rentals/_oob_refresh.html', ctx)
```

на:

```python
        created_ids = []
        with transaction.atomic():
            for it, qty, amount in plan:
                if amount is None:
                    amount = billing.compute_return_amount_for_qty(it, qty)
                mv = Movement.objects.create(
                    rental_item=it,
                    kind=Movement.Kind.RETURN,
                    qty=qty,
                    amount=amount,
                    note=note,
                    created_by=request.user,
                )
                created_ids.append(mv.pk)
            rental.refresh_from_db()
            rental.maybe_auto_close()

        rental = (
            Rental.objects
            .select_related('customer', 'created_by', 'closed_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
            .get(pk=rental.pk)
        )
        ctx = _rental_card_context(rental)
        ctx['is_admin'] = user_is_admin(request.user)
        response = render(request, 'config/rentals/_oob_refresh.html', ctx)
        if created_ids:
            ids_q = ','.join(str(i) for i in created_ids)
            receipt_url = (
                reverse('rental_return_receipt', args=[rental.pk])
                + f'?m={ids_q}&autoprint=1'
            )
            response['HX-Trigger'] = json.dumps(
                {'openReturnReceipt': {'url': receipt_url}}
            )
        return response
```

- [ ] **Step 5: Запустить — триггер + регрессия по возврату**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py tests/test_rental_flow.py -v`
Expected: PASS — новый тест триггера зелёный, существующий flow возврата не сломан.

- [ ] **Step 6: Commit**

```bash
git add config/views.py tests/test_return_receipt.py
git commit -m "feat(receipt): авто-открытие чека после возврата (HX-Trigger)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Фронтовый JS авто-открытия + подключение в base.html

**Files:**
- Create: `static/js/return-receipt.js`
- Modify: `templates/base.html` (подключить скрипт)
- Test: `tests/test_return_receipt.py` (дополнить)

**Interfaces:**
- Consumes: HTMX-событие `openReturnReceipt` с `detail.url` (Task 5).
- Produces: статик `static/js/return-receipt.js`; подключение `<script src=".../return-receipt.js">` в base.html (грузится на всех авторизованных страницах).

- [ ] **Step 1: Дописать падающие тесты подключения**

Добавить в конец `tests/test_return_receipt.py`:

```python
def test_return_receipt_js_asset_exists():
    from pathlib import Path

    from django.conf import settings

    p = Path(settings.BASE_DIR) / 'static' / 'js' / 'return-receipt.js'
    assert p.is_file(), 'static/js/return-receipt.js отсутствует'
    content = p.read_text(encoding='utf-8')
    assert 'openReturnReceipt' in content
    assert 'window.open' in content


def test_base_includes_return_receipt_js(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert 'js/return-receipt.js' in resp.content.decode()
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -k return_receipt_js -v`
Expected: FAIL — файла нет / base.html не подключает скрипт.

- [ ] **Step 3: Создать `static/js/return-receipt.js`**

```javascript
/*
 * Авто-открытие чека возврата.
 *
 * После оформления возврата сервер шлёт HTMX-событие `openReturnReceipt`
 * с {url} чека (заголовок HX-Trigger). Открываем чек в новой вкладке.
 * Если попап заблокирован (window.open вернул null — обработчик ответа htmx
 * не всегда считается «прямым» жестом пользователя), показываем заметный
 * fallback-баннер со ссылкой.
 */
(function () {
    function showFallback(url) {
        var old = document.getElementById('return-receipt-fallback');
        if (old) old.remove();

        var box = document.createElement('div');
        box.id = 'return-receipt-fallback';
        box.style.cssText =
            'position:fixed;top:1rem;left:50%;transform:translateX(-50%);' +
            'z-index:1090;background:#0d6efd;color:#fff;padding:.6rem 1rem;' +
            'border-radius:.5rem;box-shadow:0 .25rem .75rem rgba(0,0,0,.3);' +
            'font-size:.95rem;';

        var a = document.createElement('a');
        a.href = url;
        a.target = '_blank';
        a.rel = 'noopener';
        a.style.cssText = 'color:#fff;font-weight:600;text-decoration:underline;';
        a.textContent = '🧾 Открыть чек возврата';

        box.appendChild(a);
        document.body.appendChild(box);

        setTimeout(function () {
            var el = document.getElementById('return-receipt-fallback');
            if (el) el.remove();
        }, 15000);
    }

    document.body && document.body.addEventListener(
        'openReturnReceipt', function (e) {
            var url = (e.detail && e.detail.url) || '';
            if (!url) return;
            var win = window.open(url, '_blank');
            if (!win) showFallback(url);
        }
    );
})();
```

- [ ] **Step 4: Подключить скрипт в `templates/base.html`**

После строки 193 (`<script src="{% static 'js/return-amount.js' %}"></script>`) добавить:

```django
<script src="{% static 'js/return-receipt.js' %}"></script>
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -k return_receipt_js -v`
Expected: PASS (2 теста).

- [ ] **Step 6: Commit**

```bash
git add static/js/return-receipt.js templates/base.html tests/test_return_receipt.py
git commit -m "feat(receipt): JS авто-открытия чека с fallback при блокировке попапа

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Узбекские переводы (locale/uz) + компиляция

**Files:**
- Modify: `locale/uz/LC_MESSAGES/django.po` (msgstr для новых строк) + `django.mo` (компиляция)
- Test: `tests/test_return_receipt.py` (дополнить)

**Interfaces:**
- Consumes: msgid из шаблона/PDF (Tasks 3–4).
- Produces: переключение языка на `uz` показывает узбекские метки чека.

- [ ] **Step 1: Дописать падающий тест узбекской локали**

Добавить в конец `tests/test_return_receipt.py`:

```python
def test_receipt_uz_translation(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    client_staff.cookies['django_language'] = 'uz'
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
    body = client_staff.get(url).content.decode()
    assert 'Tovar turi' in body   # узбекский заголовок «Тип товара»
    assert 'Qaytarish' in body    # узбекский «возврат»
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py::test_receipt_uz_translation -v`
Expected: FAIL — `'Tovar turi'` нет (по-узбекски пока не переведено, рендерится русский msgid).

- [ ] **Step 3: Извлечь новые строки в .po**

Run: `./venv/bin/python manage.py makemessages -l uz -l ru`
Это добавит новые `msgid` (из шаблона и PDF) в `locale/uz/LC_MESSAGES/django.po` и `locale/ru/...`. Русский (`ru`) оставляем с пустыми `msgstr` — Django покажет сам msgid (русский).

- [ ] **Step 4: Заполнить узбекские переводы**

В `locale/uz/LC_MESSAGES/django.po` проставить `msgstr` для новых строк (узбекская латиница):

```
msgid "Чек возврата"
msgstr "Qaytarish cheki"

msgid "Скачать PDF"
msgstr "PDF yuklab olish"

msgid "ЧЕК ВОЗВРАТА"
msgstr "QAYTARISH CHEKI"

msgid "Клиент"
msgstr "Mijoz"

msgid "Клиент:"
msgstr "Mijoz:"

msgid "Тип товара"
msgstr "Tovar turi"

msgid "Тип"
msgstr "Turi"

msgid "Наименование"
msgstr "Nomi"

msgid "Кол-во"
msgstr "Soni"

msgid "За день"
msgstr "Kuniga"

msgid "Стоимость"
msgstr "Narxi"

msgid "Итого"
msgstr "Jami"

msgid "Примечание"
msgstr "Izoh"

msgid "Аренда №%(n)s"
msgstr "Ijara №%(n)s"

msgid "Возврат: %(q)s ед. на сумму %(s)s сум"
msgstr "Qaytarildi: %(q)s dona, %(s)s so'm"

msgid "Примечание: "
msgstr "Izoh: "
```

Для blocktrans-строк (в `.po` они выглядят так же по msgid) проставить:

```
msgid "Аренда №%(rid)s"
msgstr "Ijara №%(rid)s"

msgid "Возврат: %(q)s ед. на сумму %(s)s сум"
msgstr "Qaytarildi: %(q)s dona, %(s)s so'm"
```

(Если `makemessages` свёл одинаковые msgid в один — заполнить один раз. Если строки «Аренда №…» в шаблоне и PDF дали разные плейсхолдеры `%(rid)s` vs `%(n)s` — заполнить обе.)

- [ ] **Step 5: Скомпилировать переводы**

Run: `./venv/bin/python manage.py compilemessages -l uz -l ru`
Expected: создаёт/обновляет `locale/uz/LC_MESSAGES/django.mo` без ошибок.

- [ ] **Step 6: Запустить — узбекская локаль + полный прогон**

Run: `./venv/bin/python -m pytest tests/test_return_receipt.py -v`
Expected: PASS, включая `test_receipt_uz_translation`.

- [ ] **Step 7: Commit**

```bash
git add locale/uz/LC_MESSAGES/django.po locale/uz/LC_MESSAGES/django.mo locale/ru/LC_MESSAGES/django.po tests/test_return_receipt.py
git commit -m "i18n(uz): перевод строк чека возврата

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Финальная проверка всего пакета

**Files:** —

- [ ] **Step 1: Прогнать весь набор тестов**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS — вся существующая и новая функциональность зелёная (особое внимание: `test_contract_pdf.py`, `test_rental_flow.py`, `test_returns_report.py`).

- [ ] **Step 2: Проверка отсутствия незакоммиченных хвостов**

Run: `git status`
Expected: рабочее дерево чистое; все изменения в коммитах Task 1–7.

---

## Self-Review (выполнено автором плана)

**1. Покрытие спеки:**
- §1 привязка к партии → Task 5 (`created_ids` + `?m=`), Task 2 (`build_return_receipt_context` фильтрует по id и аренде). ✅
- §2 авто-открытие + fallback → Task 5 (HX-Trigger), Task 6 (JS + fallback). ✅
- §3 HTML-чек (A6, поля, итог, кнопка PDF, autoprint) → Task 4 (view+шаблон), Task 3 (PDF-ссылка существует). ✅
- §4 PDF-чек → Task 3. ✅
- §5 общий `pdf_common` → Task 1. ✅
- §6 i18n → Task 7. ✅
- Состав полей (ФИО, тип, наименование, кол-во, стоимость, за день, дата/время, итог «Возврат: N на сумму S») → Task 4 шаблон + Task 3 PDF. ✅
- Обработка ошибок (404 при пустом m, чужие id, отсутствие fpdf/шрифта, права) → Task 3 (PDF 404/redirect/auth), Task 4 (HTML 404/auth). ✅
- Тесты → каждый Task завершается тестами; Task 8 — общий прогон. ✅

**2. Плейсхолдеры:** в плане нет «TBD/TODO/handle errors»; каждый шаг содержит реальный код/команды. ✅

**3. Согласованность типов/имён:** `build_return_receipt_context(rental, movement_ids) -> dict` используется одинаково в Tasks 3/4; `build_return_receipt_pdf(ctx)` принимает этот же dict; имена `resolve_fonts`/`load_fpdf`/`money`/`draw_watermark`/`PdfFontMissing`/`PdfDependencyMissing` совпадают между Task 1 (определение) и Task 3 (использование); событие `openReturnReceipt` одинаково в Task 5 (сервер) и Task 6 (клиент); URL name `rental_return_receipt`/`rental_return_receipt_pdf` согласованы между Tasks 3/4/5. ✅

## Вне рамок (YAGNI) — из спеки

- Кнопка ручной повторной печати в таймлайне (URL чека стабилен по `m`, добавится позже при необходимости).
- Возврат залога (`Payment refund`) на чеке.
- Чек по всей истории аренды / по одному движению.
- Тепловой формат 58/80 мм (пока A6; параметр `size` оставляет задел).
- i18n текста fallback-баннера в JS (остаётся на русском — вне домена gettext).
