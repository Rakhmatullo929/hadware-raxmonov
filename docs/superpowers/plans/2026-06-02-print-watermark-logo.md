# Print Watermark Logo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a faint, grayscale, diagonally-rotated logo watermark behind the rental contract on both print paths — the browser HTML print page and the server-side `fpdf2` PDF — always on.

> **Update after implementation:** the shipped mark is a diagonal **text** word mark «Raxmonov», not the circle + «R» below. `static/img/logo.svg` is a `<text>` SVG; the PDF draws the string `_WATERMARK_TEXT='Raxmonov'` (see `config/contract_pdf.py`, commit 22bfedd). Placement/diagonal/faintness are unchanged; only the glyph differs. The original circle+R architecture is kept below for history.

**Architecture:** One simple monochrome SVG mark (circle + «R») is committed as a static asset. The HTML path renders it as a faint, rotated foreground `<img>` in the shared print base template (so any future print page inherits it). The PDF path reproduces the same mark with native `fpdf2` primitives (ellipse outline + core-font «R») in light gray, drawn in `header()` so it lands under content on every page.

**Tech Stack:** Django 5.2 templates, `{% static %}`, CSS `@media print`; `fpdf2` 2.8 (`rotation()`, `ellipse()`, core font); pytest / pytest-django.

**Spec:** `docs/superpowers/specs/2026-06-02-print-watermark-logo-design.md`

**Run tests with:** `./venv/bin/python -m pytest` (this venv has pytest-django + fpdf2 and is confirmed green).

---

## File Structure

- `static/img/logo.svg` — **new** static asset. The single monochrome mark, reused by HTML and (conceptually) PDF.
- `templates/print_base.html` — **modify**. Shared base for all print pages. Add `{% load static %}`, the watermark `<img>`, and its CSS.
- `config/contract_pdf.py` — **modify**. Add module-level `draw_watermark(pdf)` and a `header()` method on `_ContractPDF` that calls it.
- `tests/test_contract_pdf.py` — **modify**. Add asset-existence, HTML-watermark, and PDF-watermark tests. (Reuses the existing `rental` and `client_staff` fixtures already in this file.)

---

## Task 1: Logo SVG asset

**Files:**
- Create: `static/img/logo.svg`
- Test: `tests/test_contract_pdf.py`

- [ ] **Step 1: Write the failing test**

Add these imports near the top of `tests/test_contract_pdf.py` (after the existing imports, around line 11):

```python
from pathlib import Path

from django.conf import settings
```

Then append this test to the end of `tests/test_contract_pdf.py`:

```python
def test_logo_svg_asset_exists():
    """Монохромный знак-логотип для водяного знака должен быть в static/img/."""
    p = Path(settings.BASE_DIR) / 'static' / 'img' / 'logo.svg'
    assert p.is_file(), 'static/img/logo.svg отсутствует'
    content = p.read_text(encoding='utf-8')
    assert '<svg' in content
    assert 'R</text>' in content  # буква-марка присутствует
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py::test_logo_svg_asset_exists -q`
Expected: FAIL — `AssertionError: static/img/logo.svg отсутствует`.

- [ ] **Step 3: Create the asset**

Create `static/img/logo.svg` with exactly this content:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="Rakhmonov">
  <circle cx="50" cy="50" r="46" fill="none" stroke="#000000" stroke-width="4"/>
  <text x="50" y="50" text-anchor="middle" dominant-baseline="central"
        font-family="Arial, Helvetica, sans-serif" font-weight="700" font-size="54" fill="#000000">R</text>
</svg>
```

(Monochrome black on purpose — faintness is applied at render time via CSS opacity/grayscale in HTML and via light-gray color in PDF, so the mark stays easy to retune.)

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py::test_logo_svg_asset_exists -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add static/img/logo.svg tests/test_contract_pdf.py
git commit -m "feat(print): add monochrome logo.svg asset for print watermark"
```

---

## Task 2: HTML print watermark (browser path)

**Files:**
- Modify: `templates/print_base.html`
- Test: `tests/test_contract_pdf.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_contract_pdf.py`:

```python
def test_contract_html_has_background_watermark(client_staff, rental):
    """HTML-страница печати договора содержит фоновый знак и ссылку на лого."""
    from django.urls import reverse
    url = reverse('rental_contract', args=[rental.pk])
    r = client_staff.get(url)
    assert r.status_code == 200
    assert b'print-watermark' in r.content
    assert b'img/logo.svg' in r.content
```

(`reverse` and `Client` are already imported at the top of the file; the local `reverse` import here is harmless and keeps the test self-contained.)

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py::test_contract_html_has_background_watermark -q`
Expected: FAIL — `assert b'print-watermark' in r.content` is False.

- [ ] **Step 3: Implement the template changes**

**3a.** In `templates/print_base.html`, change line 1 to load the `static` tag library:

Old:
```django
{% load i18n %}<!doctype html>
```
New:
```django
{% load i18n static %}<!doctype html>
```

**3b.** Add the watermark CSS inside the existing `<style>` block. Insert it right after the `.print-page { margin: 1rem auto; ... }` rule (currently around line 12):

```css
        /* Бледный диагональный водяной знак-лого на заднем фоне печати.
           Именно <img> (а не background-image): браузеры не печатают CSS-фон
           без включённой «Фоновой графики», а передний <img> печатается всегда. */
        .print-watermark {
            position: fixed;
            top: 50%; left: 50%;
            width: 60%; max-width: 16cm;
            transform: translate(-50%, -50%) rotate(-30deg);
            opacity: .08;
            filter: grayscale(1);
            z-index: 0;
            pointer-events: none;
        }
        .print-watermark--half,
        .print-watermark--quarter { width: 45%; max-width: 9cm; }
        .print-page { position: relative; z-index: 1; }
```

**3c.** Add the watermark `<img>` right after the closing `</div>` of `.print-toolbar` and before the `.print-page` div (currently around line 57, between line 56 and line 58):

```django
<img class="print-watermark print-watermark--{{ size }}"
     src="{% static 'img/logo.svg' %}" alt="" aria-hidden="true">
```

The `size` context variable is already provided to this template (the existing `{% block page_size_print %}` uses `{% if size == 'half' %}`), so the `print-watermark--{{ size }}` modifier sizes the mark per format. The base `z-index: 1` on `.print-page` keeps all contract content above the `z-index: 0` watermark.

- [ ] **Step 4: Run test to verify it passes**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py::test_contract_html_has_background_watermark -q`
Expected: PASS.

Also re-run the existing HTML render test to confirm no regression:
Run: `./venv/bin/python -m pytest "tests/test_contract_pdf.py::test_contract_html_renders_for_all_sizes" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/print_base.html tests/test_contract_pdf.py
git commit -m "feat(print): faint diagonal logo watermark on HTML contract print"
```

---

## Task 3: PDF watermark (server fpdf2 path)

**Files:**
- Modify: `config/contract_pdf.py`
- Test: `tests/test_contract_pdf.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_contract_pdf.py`:

```python
def test_draw_watermark_keeps_single_page_and_restores_cursor():
    """draw_watermark рисует знак, не добавляя страниц и не сдвигая курсор."""
    import fpdf

    from config.contract_pdf import draw_watermark

    pdf = fpdf.FPDF(format='A4')
    pdf.add_page()
    pdf.set_xy(25, 40)
    x0, y0 = pdf.get_x(), pdf.get_y()

    draw_watermark(pdf)

    assert pdf.page_no() == 1                      # страниц не прибавилось
    assert round(pdf.get_x(), 2) == round(x0, 2)   # курсор X восстановлен
    assert round(pdf.get_y(), 2) == round(y0, 2)   # курсор Y восстановлен


def test_pdf_multipage_with_watermark_is_valid(
    client_staff, customer, product, staff_user,
):
    """Многостраничный договор (много позиций) собирается валидно —
    header() рисует водяной знак на каждой странице, не ломая вёрстку."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    for _ in range(60):
        RentalItem.objects.create(
            rental=r, product=product, qty=1,
            price_per_day=product.daily_price,
        )
    pdf = build_contract_pdf(r, size='full')
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 1000
```

(`fpdf`, `Rental`, `RentalItem`, `timezone`, `timedelta`, `build_contract_pdf` are all already imported at the top of this test file or imported locally as shown.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py::test_draw_watermark_keeps_single_page_and_restores_cursor -q`
Expected: FAIL — `ImportError: cannot import name 'draw_watermark' from 'config.contract_pdf'`.

- [ ] **Step 3: Implement `draw_watermark` and wire up `header()`**

**3a.** Add this module-level function to `config/contract_pdf.py`, right before `def _make_contract_pdf(...)` (currently line 153):

```python
def draw_watermark(pdf):
    """Бледный диагональный водяной знак (окружность + «R») по центру
    текущей страницы PDF.

    Вызывается из ``header()`` — поэтому ложится ПОД контент. Цвет
    светло-серый (≈205), что даёт «малозаметность» без альфа-канала.
    Графическое состояние и позиция курсора восстанавливаются, чтобы
    вёрстка контента не сдвинулась.

    Знак рисуется встроенным core-шрифтом Helvetica (ASCII «R» рендерится
    без TTF), поэтому функция не зависит от загруженного шрифта договора и
    тестируется на «голом» ``fpdf.FPDF``.

    Направление наклона согласовано с HTML-печатью (там ``rotate(-30deg)``);
    в fpdf2 положительный угол вращает в обратную сторону, поэтому здесь −30.
    """
    gray = 205
    x0, y0 = pdf.get_x(), pdf.get_y()
    lw0 = pdf.line_width
    cx, cy = pdf.w / 2, pdf.h / 2
    r = min(pdf.w, pdf.h) * 0.33

    with pdf.rotation(-30, cx, cy):
        pdf.set_draw_color(gray, gray, gray)
        pdf.set_line_width(max(0.6, r * 0.03))
        pdf.ellipse(cx - r, cy - r, 2 * r, 2 * r, style='D')

        pdf.set_text_color(gray, gray, gray)
        pdf.set_font('Helvetica', 'B', int(r * 2.0))
        pdf.set_xy(cx - r, cy - r * 0.7)
        pdf.cell(2 * r, r * 1.4, 'R', align='C')

    # Восстановить графическое состояние и курсор.
    pdf.set_draw_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    pdf.set_line_width(lw0)
    pdf.set_xy(x0, y0)
```

**3b.** Add a `header()` method to the `_ContractPDF` class inside `_make_contract_pdf`. Insert it just before the existing `def footer(self):` (currently line 178):

```python
        def header(self):
            # Водяной знак рисуется первым на каждой странице → под контентом.
            draw_watermark(self)
```

- [ ] **Step 4: Run the full PDF test file to verify pass + no regression**

Run: `./venv/bin/python -m pytest tests/test_contract_pdf.py -q`
Expected: PASS — all previous 15 tests plus the 4 new ones (asset, HTML, cursor-restore, multipage). The `A5 dimensions were fixed` UserWarning is pre-existing and harmless.

- [ ] **Step 5: Commit**

```bash
git add config/contract_pdf.py tests/test_contract_pdf.py
git commit -m "feat(print): faint diagonal logo watermark on PDF contract (per page)"
```

---

## Task 4: Full-suite verification & manual smoke check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `./venv/bin/python -m pytest -q`
Expected: PASS (no new failures introduced).

- [ ] **Step 2: Manual smoke check (dev server)**

The running server uses the framework Python, which now has `fpdf2` installed. With the server running:

1. HTML: open `/rentals/<pk>/contract/?size=full` → a faint, grayscale, diagonally-tilted «R» logo is visible behind the contract; open the browser print preview (Cmd/Ctrl+P) and confirm the watermark appears in the preview without enabling «Background graphics».
2. Repeat for `?size=half` and `?size=quarter` — the watermark is proportionally smaller.
3. PDF: open `/rentals/<pk>/contract.pdf?size=full&inline=1` → the same faint diagonal mark sits behind the text on every page; repeat for `half` and `quarter`.

- [ ] **Step 3 (optional): tune appearance**

If the mark is too strong/weak or mis-sized, adjust in one place per path:
- HTML: `.print-watermark { opacity / width }` in `templates/print_base.html`.
- PDF: `gray` value and the `r` factor (`0.33`) / font factor (`2.0`) in `draw_watermark()`.

---

## Known limitation (in scope, documented)

`position: fixed` watermarks in **HTML multi-page** print are repeated per page only in some browsers; a long HTML contract printed from the browser may show the watermark on the first page only. The contract is typically one A4 page, and the **PDF** path draws the watermark on every page via `header()`, so this is acceptable for now. (Out of scope: per-page HTML watermarking via a running-element/paged-media approach.)

---

## Self-Review

- **Spec coverage:** logo.svg asset (§3.1 → Task 1); HTML `<img>` watermark + CSS, `<img>` not background, z-index layering, per-format sizing, `{% load static %}` (§3.2 → Task 2); PDF `header()` drawing circle+«R» light-gray rotated with cursor restore on every page (§3.3 → Task 3); rotation direction consistency (§5 → encoded as −30° in `draw_watermark` + comment); tests for PDF validity across sizes (pre-existing) + cursor restore + multipage and HTML watermark presence (§6 → Tasks 2–3); YAGNI items untouched (§7). All covered.
- **Deviations from spec (intentional, same outcome):** (a) per-format HTML sizing uses a `print-watermark--{{ size }}` modifier class on the `<img>` instead of a descendant selector, because the watermark is a sibling of `.print-page`, not a child; (b) PDF watermark is a module-level `draw_watermark()` using a core font, instead of inline code using the loaded `Body` font — this makes it unit-testable on a bare `FPDF` and removes the TTF dependency for the ASCII «R».
- **Placeholder scan:** none — every code/template/command step contains literal content.
- **Type/name consistency:** `draw_watermark(pdf)` is defined in Task 3 step 3a, imported in the Task 3 test, and called by `header()` in step 3b — names match. CSS class `print-watermark` matches between Task 2 template and test.
