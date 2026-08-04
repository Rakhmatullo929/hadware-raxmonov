"""Общие хелперы серверной генерации PDF (договор, чек возврата).

Вынесено из contract_pdf.py: поиск TTF-шрифта с кириллицей/латиницей,
форматирование денег, ленивый импорт fpdf2, диагональный водяной знак.
Чистый Python, без системных зависимостей.
"""
import math
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


# Параметры водяного знака.
_WATERMARK_GRAY = 205
_WATERMARK_TEXT = 'Raxmonov'
_WATERMARK_ANGLE = -30           # угол наклона, согласован с HTML-печатью
# Доля области печати, занимаемая знаком: <1 — компактно, с воздухом.
_WATERMARK_FILL = 0.6
# Вертикальный центр в долях области печати: чуть выше середины, чтобы знак
# лёг за таблицей (она во всех форматах в верхней половине листа), а не
# свисал в пустоту под ней.
_WATERMARK_VPOS = 0.42


def draw_watermark(pdf):
    """Бледный диагональный водяной знак, компактно вписанный за таблицу.

    Размер подбирается так, чтобы повёрнутый прямоугольник текста целиком
    помещался в область печати (поля учтены через ``epw``/``eph``) при любом
    формате и ориентации — A4 книжная, A5/A6 альбомная и т.д. Рисуется
    встроенным core-шрифтом Helvetica (ASCII), не зависит от загруженного TTF.
    ``pdf.rotation(...)`` восстанавливает цвет/шрифт сам; курсор возвращаем явно.
    """
    g = _WATERMARK_GRAY
    x0, y0 = pdf.get_x(), pdf.get_y()
    # Центр — по середине области печати (за вычетом полей), слегка приподнят.
    cx = pdf.l_margin + pdf.epw / 2
    cy = pdf.t_margin + pdf.eph * _WATERMARK_VPOS

    rad = math.radians(_WATERMARK_ANGLE)
    cos_a, sin_a = abs(math.cos(rad)), abs(math.sin(rad))

    pdf.set_font('Helvetica', 'B', 100)
    w_ref = pdf.get_string_width(_WATERMARK_TEXT) or 1
    ratio = (100 * 0.3528) / w_ref  # высота/ширина текста (pt → mm)

    # Ширина текста, при которой повёрнутый габарит вписан в область печати.
    fit_w = pdf.epw / (cos_a + ratio * sin_a)
    fit_h = pdf.eph / (sin_a + ratio * cos_a)
    target_w = min(fit_w, fit_h) * _WATERMARK_FILL

    with pdf.rotation(_WATERMARK_ANGLE, cx, cy):
        pdf.set_text_color(g, g, g)
        size = 100 * target_w / w_ref
        pdf.set_font('Helvetica', 'B', size)
        tw = pdf.get_string_width(_WATERMARK_TEXT)
        th = size * 0.3528  # pt → mm
        pdf.set_xy(cx - tw / 2, cy - th / 2)
        pdf.cell(tw, th, _WATERMARK_TEXT, align='C')

    pdf.set_xy(x0, y0)


# ---- Общая таблица позиций (печать аренды и чека возврата) ----------------
#
# И договор аренды, и чек возврата печатают одну и ту же плоскую таблицу
# (образец — бумажный лист клиента). Держим её здесь единым источником, чтобы
# оба вида не разъезжались.

def fit_text(pdf, text, cell_w, pad=1.2):
    """Обрезать text с многоточием, чтобы влез в ячейку шириной cell_w (мм).

    fpdf ``cell`` не обрезает текст — длинная строка вылезает в соседнюю
    колонку. Здесь укорачиваем по фактической ширине текущего шрифта.
    """
    s = str(text)
    avail = max(cell_w - pad, 1)
    if pdf.get_string_width(s) <= avail:
        return s
    ell = '…'
    while s and pdf.get_string_width(s + ell) > avail:
        s = s[:-1]
    return (s + ell) if s else ell


def fmt_date(dt):
    """tz-aware datetime → локальная дата ``дд.мм.гггг`` (или «—»)."""
    if not dt:
        return '—'
    from django.utils import timezone
    return timezone.localtime(dt).strftime('%d.%m.%Y')


def fmt_time(dt):
    """tz-aware datetime → локальное время ``чч:мм:сс`` (или «—»)."""
    if not dt:
        return '—'
    from django.utils import timezone
    return timezone.localtime(dt).strftime('%H:%M:%S')


# Доли ширины колонок (в сумме = 1.0). Порядок:
# Код клиента | Наименование | Кол-во | Стоимость | Общая сумма |
# Дата-Отправки | Дата-Привозки | Время-Отправки | Время-Привозки
_FR_CODE = 0.09
_FR_NAME = 0.22
_FR_QTY = 0.07
_FR_PRICE = 0.10
_FR_SUM = 0.12
_FR_DOUT = 0.105
_FR_DIN = 0.105
_FR_TOUT = 0.095
_FR_TIN = 0.095


def draw_items_table(pdf, rows, total_qty, grand_total, customer_code, *,
                     row_h, base_font):
    """Плоская таблица позиций с двухрядной «шапкой» — общая для двух печатей.

    Шапка: Код клиента │ Товар(Наименование│Кол-во│Стоимость│Общая сумма)
                       │ Дата(Отправки│Привозки) │ Время(Отправки│Привозки).
    ``rows`` — список словарей ``{name, qty, price, total, issue_dt, return_dt}``;
    ``issue_dt``/``return_dt`` — tz-aware datetime либо ``None`` (тогда «—»).
    «Код клиента» повторяется в каждой строке; итог — Σ кол-ва и Σ суммы.
    """
    from django.utils.translation import gettext as _
    w = pdf.epw
    h = row_h
    base = base_font
    hdr = max(base - 1, 6)
    x_left = pdf.l_margin

    subheaders = [
        (_('Наименование'), _FR_NAME),
        (_('Кол-во'), _FR_QTY),
        (_('Стоимость'), _FR_PRICE),
        (_('Общая сумма'), _FR_SUM),
        (_('Отправки'), _FR_DOUT),
        (_('Привозки'), _FR_DIN),
        (_('Отправки'), _FR_TOUT),
        (_('Привозки'), _FR_TIN),
    ]

    def draw_header():
        pdf.set_font('Body', 'B', hdr)
        pdf.set_fill_color(238, 240, 242)
        y0 = pdf.get_y()
        pdf.cell(w * _FR_CODE, h * 2,
                 fit_text(pdf, _('Код клиента'), w * _FR_CODE),
                 border=1, align='C', fill=True)
        pdf.cell(w * (_FR_NAME + _FR_QTY + _FR_PRICE + _FR_SUM), h,
                 _('Товар'), border=1, align='C', fill=True)
        pdf.cell(w * (_FR_DOUT + _FR_DIN), h,
                 _('Дата'), border=1, align='C', fill=True)
        pdf.cell(w * (_FR_TOUT + _FR_TIN), h,
                 _('Время'), border=1, align='C', fill=True)
        pdf.ln(h)
        pdf.set_xy(x_left + w * _FR_CODE, y0 + h)
        for title, frac in subheaders:
            pdf.cell(w * frac, h, fit_text(pdf, str(title), w * frac),
                     border=1, align='C', fill=True)
        pdf.ln(h)

    draw_header()

    pdf.set_font('Body', size=base)
    for r in rows:
        if pdf.will_page_break(h):
            pdf.add_page()
            draw_header()
            pdf.set_font('Body', size=base)
        cells = [
            (customer_code, _FR_CODE, 'C'),
            (fit_text(pdf, r['name'], w * _FR_NAME), _FR_NAME, 'L'),
            (str(r['qty']), _FR_QTY, 'R'),
            (money(r['price']), _FR_PRICE, 'R'),
            (money(r['total']), _FR_SUM, 'R'),
            (fmt_date(r.get('issue_dt')), _FR_DOUT, 'C'),
            (fmt_date(r.get('return_dt')), _FR_DIN, 'C'),
            (fmt_time(r.get('issue_dt')), _FR_TOUT, 'C'),
            (fmt_time(r.get('return_dt')), _FR_TIN, 'C'),
        ]
        for text, frac, align in cells:
            pdf.cell(w * frac, h, str(text), border=1, align=align)
        pdf.ln(h)

    # Итог: Σ кол-ва и Σ суммы.
    pdf.set_font('Body', 'B', base)
    pdf.cell(w * (_FR_CODE + _FR_NAME), h, _('Итого'), border=1, align='R')
    pdf.cell(w * _FR_QTY, h, str(total_qty), border=1, align='R')
    pdf.cell(w * _FR_PRICE, h, '', border=1)
    pdf.cell(w * _FR_SUM, h, money(grand_total), border=1, align='R')
    pdf.cell(w * (_FR_DOUT + _FR_DIN + _FR_TOUT + _FR_TIN), h, '', border=1)
    pdf.ln(h + 2)
