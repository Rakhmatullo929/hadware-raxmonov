"""Серверная генерация PDF аренды через fpdf2.

Печатает подпись клиента и плоскую таблицу позиций (образец — бумажный лист
клиента): Код клиента · Товар(Наименование/Кол-во/Стоимость/Общая сумма) ·
Дата(Отправки/Привозки) · Время(Отправки/Привозки).

Чистый Python, без системных зависимостей (в отличие от WeasyPrint).
Шрифт ищется по списку кандидатов, чтобы работало и на macOS (dev),
и на Linux (прод). На проде достаточно `apt install fonts-dejavu-core`.

Поддерживаются три формата (все — альбомная ориентация, таблица широкая):
* ``full``    — A4 (по умолчанию).
* ``half``    — A5.
* ``quarter`` — A6.

Важно: ``fpdf2`` импортируется лениво внутри :func:`build_contract_pdf`,
чтобы вызов HTML-печати и наличие констант формата работали даже тогда,
когда библиотека ещё не установлена (она нужна только для PDF).
"""
from decimal import Decimal

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

SIZE_FULL = 'full'
SIZE_HALF = 'half'
SIZE_QUARTER = 'quarter'
ALLOWED_SIZES = (SIZE_FULL, SIZE_HALF, SIZE_QUARTER)


def normalize_size(value):
    """Привести значение к одному из ``ALLOWED_SIZES``; по умолчанию ``full``."""
    if value in ALLOWED_SIZES:
        return value
    return SIZE_FULL


# Параметры макета на каждый формат. Все — альбомная ориентация, потому что
# таблица позиций широкая (9 колонок). Отличаются лишь бумагой и кеглем.
_LAYOUTS = {
    SIZE_FULL: {
        'page_format': 'A4',
        'orientation': 'L',              # альбом — под широкую таблицу
        'margins': (12, 12, 12),         # left, top, right
        'auto_break_margin': 12,
        'font_base': 10,
        'font_small': 9,
        'font_tiny': 8,
        'font_h1': 16,
        'font_h2': 11,
        'row_h': 7,
        'line_h': 5,
        'header_h': 9,
        'subheader_h': 6,
    },
    SIZE_HALF: {
        'page_format': 'A5',
        'orientation': 'L',
        'margins': (10, 10, 10),
        'auto_break_margin': 10,
        'font_base': 8,
        'font_small': 7.5,
        'font_tiny': 7,
        'font_h1': 13,
        'font_h2': 10,
        'row_h': 5.6,
        'line_h': 4.2,
        'header_h': 7,
        'subheader_h': 5,
    },
    SIZE_QUARTER: {
        # A6 не всегда есть в PAGE_FORMATS у fpdf2 — задаём в мм явно
        # (портретный кортеж; orientation='L' развернёт в 148×105 альбом).
        'page_format': (105, 148),
        'orientation': 'L',
        'margins': (7, 7, 7),
        'auto_break_margin': 7,
        'font_base': 7,
        'font_small': 6.5,
        'font_tiny': 6,
        'font_h1': 11,
        'font_h2': 9,
        'row_h': 4.6,
        'line_h': 3.6,
        'header_h': 6,
        'subheader_h': 4,
    },
}


def _make_contract_pdf(fpdf_module, font_regular, font_bold, layout):
    """Создать инстанс FPDF, сконфигурированный под выбранный layout.

    Класс определяется внутри, чтобы FPDF (из лениво импортированного
    ``fpdf2``) не требовался на этапе загрузки модуля.
    """

    class _ContractPDF(fpdf_module.FPDF):
        def __init__(self):
            super().__init__(
                orientation=layout.get('orientation', 'P'),
                format=layout['page_format'],
            )
            ml, mt, mr = layout['margins']
            self.set_auto_page_break(
                auto=True, margin=layout['auto_break_margin'],
            )
            self.set_margins(ml, mt, mr)
            self.add_font('Body', '', font_regular)
            if font_bold:
                self.add_font('Body', 'B', font_bold)
            else:
                # Нет отдельного bold-файла — используем тот же, fpdf2
                # синтезирует "fake bold".
                self.add_font('Body', 'B', font_regular)
            self.set_font('Body', size=layout['font_base'])
            self._layout = layout

        def header(self):
            # Водяной знак рисуется первым на каждой странице → под контентом.
            draw_watermark(self)

        def footer(self):
            self.set_y(-12)
            self.set_font('Body', size=self._layout['font_tiny'])
            self.set_text_color(140, 140, 140)
            self.cell(
                0, 6,
                f'Rakhmonov · {timezone.now():%d.%m.%Y %H:%M}'
                f'  ·  {_("бет")} {self.page_no()}',
                align='C',
            )
            self.set_text_color(0, 0, 0)

    return _ContractPDF()


def _fit_text(pdf, text, cell_w, pad=1.2):
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


def _fmt_date(dt):
    """tz-aware datetime → локальная дата ``дд.мм.гггг`` (или «—»)."""
    if not dt:
        return '—'
    return timezone.localtime(dt).strftime('%d.%m.%Y')


def _fmt_time(dt):
    """tz-aware datetime → локальное время ``чч:мм:сс`` (или «—»)."""
    if not dt:
        return '—'
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


def _draw_items_table(pdf, layout, rows, total_qty, grand_total, customer_code):
    """Плоская таблица позиций с двухрядной «шапкой».

    Шапка: Код клиента │ Товар(Наименование│Кол-во│Стоимость│Общая сумма)
                       │ Дата(Отправки│Привозки) │ Время(Отправки│Привозки).
    «Код клиента» повторяется в каждой строке; итог — Σ кол-ва и Σ суммы.
    Длинные наименования обрезаются по ширине ячейки, чтобы не налезать."""
    w = pdf.epw
    h = layout['row_h']
    base = layout['font_small']
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
        # Верхний ряд: «Код клиента» на всю высоту (2 строки), затем группы.
        pdf.cell(w * _FR_CODE, h * 2,
                 _fit_text(pdf, _('Код клиента'), w * _FR_CODE),
                 border=1, align='C', fill=True)
        pdf.cell(w * (_FR_NAME + _FR_QTY + _FR_PRICE + _FR_SUM), h,
                 _('Товар'), border=1, align='C', fill=True)
        pdf.cell(w * (_FR_DOUT + _FR_DIN), h,
                 _('Дата'), border=1, align='C', fill=True)
        pdf.cell(w * (_FR_TOUT + _FR_TIN), h,
                 _('Время'), border=1, align='C', fill=True)
        pdf.ln(h)
        # Нижний ряд под-заголовков — правее колонки «Код клиента».
        pdf.set_xy(x_left + w * _FR_CODE, y0 + h)
        for title, frac in subheaders:
            pdf.cell(w * frac, h,
                     _fit_text(pdf, str(title), w * frac),
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
            (_fit_text(pdf, r['name'], w * _FR_NAME), _FR_NAME, 'L'),
            (str(r['qty']), _FR_QTY, 'R'),
            (_money(r['price']), _FR_PRICE, 'R'),
            (_money(r['total']), _FR_SUM, 'R'),
            (r['issue_date'], _FR_DOUT, 'C'),
            (r['return_date'], _FR_DIN, 'C'),
            (r['issue_time'], _FR_TOUT, 'C'),
            (r['return_time'], _FR_TIN, 'C'),
        ]
        for text, frac, align in cells:
            pdf.cell(w * frac, h, str(text), border=1, align=align)
        pdf.ln(h)

    # Итог: Σ кол-ва и Σ суммы.
    pdf.set_font('Body', 'B', base)
    pdf.cell(w * (_FR_CODE + _FR_NAME), h, _('Итого'), border=1, align='R')
    pdf.cell(w * _FR_QTY, h, str(total_qty), border=1, align='R')
    pdf.cell(w * _FR_PRICE, h, '', border=1)
    pdf.cell(w * _FR_SUM, h, _money(grand_total), border=1, align='R')
    pdf.cell(w * (_FR_DOUT + _FR_DIN + _FR_TOUT + _FR_TIN), h, '', border=1)
    pdf.ln(h + 2)


def build_contract_pdf(rental, size: str = SIZE_FULL) -> bytes:
    """Собрать PDF аренды: подпись клиента + плоская таблица позиций.

    :param rental: ``Rental`` с подгруженными items/movements/customer.
    :param size:   ``full`` (A4), ``half`` (A5) или ``quarter`` (A6), все — альбом.
                   Любое неизвестное значение трактуется как ``full``.
    :returns:      Готовый PDF в ``bytes``.
    :raises ContractFontMissing: если не найден ни один TTF-шрифт.
    :raises ContractDependencyMissing: если не установлен ``fpdf2``.
    """
    fpdf_module = load_fpdf()

    from . import billing

    layout = _LAYOUTS[normalize_size(size)]

    font_regular, font_bold = resolve_fonts()

    items = list(
        rental.items
        .select_related('product')
        .prefetch_related('movements')
        .all()
    )
    rows = []
    total_qty = 0
    grand_total = Decimal('0.00')
    for it in items:
        # Общая сумма = кол-во × цена × дни (billing: FIFO, ручные правки).
        total = billing.compute_item_base(it)
        issue_dt = it.first_issue_at
        return_dt = it.last_return_at
        rows.append({
            'name': it.product.name,
            'qty': it.qty,
            'price': it.price_per_day,
            'total': total,
            'issue_date': _fmt_date(issue_dt),
            'issue_time': _fmt_time(issue_dt),
            'return_date': _fmt_date(return_dt),
            'return_time': _fmt_time(return_dt),
        })
        total_qty += it.qty
        grand_total += total

    cust = rental.customer
    pdf = _make_contract_pdf(fpdf_module, font_regular, font_bold, layout)
    pdf.add_page()

    # ---- Заголовок ----
    pdf.set_font('Body', 'B', layout['font_h1'])
    pdf.cell(0, layout['header_h'],
             _('Аренда № %(n)s') % {'n': rental.pk},
             align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Body', size=layout['font_small'])
    pdf.set_text_color(110, 110, 110)
    pdf.cell(
        0, layout['subheader_h'],
        rental.created_at.strftime('%d.%m.%Y %H:%M'),
        align='C', new_x='LMARGIN', new_y='NEXT',
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(layout['line_h'])

    # ---- Подпись клиента ----
    bits = []
    if cust.code:
        bits.append('№ ' + cust.code)
    if cust.full_name:
        bits.append(cust.full_name)
    if cust.phone:
        bits.append(cust.phone)
    pdf.set_font('Body', 'B', layout['font_small'])
    pdf.multi_cell(0, layout['line_h'],
                   _('Клиент: ') + ' · '.join(bits),
                   new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)

    _draw_items_table(
        pdf, layout, rows, total_qty, grand_total, cust.code or '',
    )

    return bytes(pdf.output())
