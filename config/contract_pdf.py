"""Серверная генерация PDF договора аренды через fpdf2.

Чистый Python, без системных зависимостей (в отличие от WeasyPrint).
Шрифт ищется по списку кандидатов, чтобы работало и на macOS (dev),
и на Linux (прод). На проде достаточно `apt install fonts-dejavu-core`.

Поддерживаются три формата:
* ``full``    — A4, полный договор со всеми разделами (по умолчанию).
* ``half``    — A5, средний: стороны, позиции, ключевые условия, подписи.
* ``quarter`` — A6, краткая выписка «для своих»: №, клиент, позиции, итог.

Важно: ``fpdf2`` импортируется лениво внутри :func:`build_contract_pdf`,
чтобы вызов HTML-печати договора и наличие констант формата работали даже
тогда, когда библиотека ещё не установлена (она нужна только для PDF).
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _

BASE_DIR = Path(settings.BASE_DIR)

SIZE_FULL = 'full'
SIZE_HALF = 'half'
SIZE_QUARTER = 'quarter'
ALLOWED_SIZES = (SIZE_FULL, SIZE_HALF, SIZE_QUARTER)


def normalize_size(value):
    """Привести значение к одному из ``ALLOWED_SIZES``; по умолчанию ``full``."""
    if value in ALLOWED_SIZES:
        return value
    return SIZE_FULL


# Параметры макета на каждый формат. Подобраны так, чтобы:
#  - A4 (full)    давал прежний результат;
#  - A5 (half)    помещался в "среднем" объёме с компактной таблицей;
#  - A6 (quarter) умещал «корешок» договора на четвертушке листа.
_LAYOUTS = {
    SIZE_FULL: {
        'page_format': 'A4',
        'margins': (18, 16, 18),         # left, top, right
        'auto_break_margin': 18,
        'font_base': 10,
        'font_small': 9,
        'font_tiny': 8,
        'font_h1': 16,
        'font_h2': 11,
        'row_h': 7,
        'line_h': 5,
        'header_h': 9,
        'subheader_h': 6,
        'show_parties': True,
        'show_terms': True,
        'show_duties': True,
        'show_note': True,
        'item_columns': 'wide',
    },
    SIZE_HALF: {
        'page_format': 'A5',
        'margins': (14, 12, 14),
        'auto_break_margin': 14,
        'font_base': 9,
        'font_small': 8,
        'font_tiny': 7,
        'font_h1': 13,
        'font_h2': 10,
        'row_h': 5.6,
        'line_h': 4.2,
        'header_h': 7,
        'subheader_h': 5,
        'show_parties': True,
        'show_terms': True,
        'show_duties': False,
        'show_note': True,
        'item_columns': 'wide',
    },
    SIZE_QUARTER: {
        # A6 не всегда есть в PAGE_FORMATS у fpdf2 — задаём в мм явно.
        'page_format': (105, 148),
        'margins': (8, 8, 8),
        'auto_break_margin': 8,
        'font_base': 8,
        'font_small': 7,
        'font_tiny': 6,
        'font_h1': 11,
        'font_h2': 9,
        'row_h': 4.6,
        'line_h': 3.6,
        'header_h': 6,
        'subheader_h': 4,
        'show_parties': False,         # только Арендатор кратко
        'show_terms': False,           # только дата возврата
        'show_duties': False,
        'show_note': False,
        'item_columns': 'compact',     # без цены/залога — только позиция и кол-во
    },
}


# Порядок поиска шрифта с поддержкой кириллицы и узбекской латиницы.
_FONT_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',          # Debian/Ubuntu
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',                    # RHEL/Fedora
    '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',     # macOS
    '/Library/Fonts/Arial Unicode.ttf',                         # macOS (alt)
]
_BOLD_CANDIDATES = [
    getattr(settings, 'CONTRACT_PDF_FONT_BOLD_PATH', None),
    BASE_DIR / 'static' / 'fonts' / 'DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
]


class ContractFontMissing(RuntimeError):
    pass


class ContractDependencyMissing(RuntimeError):
    """Бросается, когда не установлен `fpdf2` — PDF собрать нечем."""
    pass


def _first_existing(paths):
    for p in paths:
        if not p:
            continue
        p = Path(p)
        if p.is_file():
            return str(p)
    return None


def _money(value) -> str:
    q = Decimal(value or 0).quantize(Decimal('0.01'))
    # 12345.60 -> "12 345.60"
    intpart, _, frac = f'{q:.2f}'.partition('.')
    neg = intpart.startswith('-')
    intpart = intpart.lstrip('-')
    groups = []
    while intpart:
        groups.insert(0, intpart[-3:])
        intpart = intpart[:-3]
    return ('-' if neg else '') + ' '.join(groups) + '.' + frac


def _make_contract_pdf(fpdf_module, font_regular, font_bold, layout):
    """Создать инстанс FPDF, сконфигурированный под выбранный layout.

    Класс определяется внутри, чтобы FPDF (из лениво импортированного
    ``fpdf2``) не требовался на этапе загрузки модуля.
    """

    class _ContractPDF(fpdf_module.FPDF):
        def __init__(self):
            super().__init__(format=layout['page_format'])
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

        def footer(self):
            self.set_y(-12)
            self.set_font('Body', size=self._layout['font_tiny'])
            self.set_text_color(140, 140, 140)
            self.cell(
                0, 6,
                f'Rakhmonov · {timezone.now():%d.%m.%Y %H:%M}'
                f'  ·  {_("стр.")} {self.page_no()}',
                align='C',
            )
            self.set_text_color(0, 0, 0)

    return _ContractPDF()


def _draw_items_table(pdf, layout, items, total_deposit_due):
    """Таблица позиций. Колонки зависят от layout['item_columns']."""
    w = pdf.epw
    row_h = layout['row_h']
    base = layout['font_small']

    if layout['item_columns'] == 'compact':
        # quarter: только №, наименование, кол-во, ед.
        headers = [
            ('№', 0.10, 'C'),
            (_('Наименование'), 0.62, 'L'),
            (_('Кол-во'), 0.16, 'R'),
            (_('Ед.'), 0.12, 'C'),
        ]
    else:
        headers = [
            ('№', 0.07, 'C'),
            (_('Наименование'), 0.40, 'L'),
            (_('Кол-во'), 0.12, 'R'),
            (_('Ед.'), 0.10, 'C'),
            (_('Цена/сут.'), 0.16, 'R'),
            (_('Залог/ед.'), 0.15, 'R'),
        ]

    pdf.set_font('Body', 'B', base)
    pdf.set_fill_color(238, 240, 242)
    for title, frac, _align in headers:
        pdf.cell(w * frac, row_h, str(title), border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font('Body', size=base)
    for idx, it in enumerate(items, start=1):
        if layout['item_columns'] == 'compact':
            row = [
                (str(idx), 0.10, 'C'),
                (it.product.name, 0.62, 'L'),
                (str(it.qty), 0.16, 'R'),
                (it.product.unit, 0.12, 'C'),
            ]
        else:
            row = [
                (str(idx), 0.07, 'C'),
                (it.product.name, 0.40, 'L'),
                (str(it.qty), 0.12, 'R'),
                (it.product.unit, 0.10, 'C'),
                (_money(it.price_per_day), 0.16, 'R'),
                (_money(it.product.deposit_per_unit), 0.15, 'R'),
            ]
        if pdf.will_page_break(row_h):
            pdf.add_page()
        for text, frac, align in row:
            pdf.cell(w * frac, row_h, str(text), border=1, align=align)
        pdf.ln()

    # Итоговая строка с суммой залога — только когда есть колонка залога.
    if layout['item_columns'] != 'compact':
        pdf.set_font('Body', 'B', base)
        pdf.cell(w * 0.85, row_h, _('Залог суммарно'), border=1, align='R')
        pdf.cell(w * 0.15, row_h, _money(total_deposit_due),
                 border=1, align='R')
        pdf.ln(row_h + 3)


def _draw_signatures(pdf, layout):
    pdf.ln(layout['line_h'] * 2)
    if pdf.will_page_break(layout['line_h'] * 4):
        pdf.add_page()
    w = pdf.epw
    col = w / 2 - 6
    y = pdf.get_y()
    pdf.line(pdf.l_margin, y, pdf.l_margin + col, y)
    pdf.line(pdf.l_margin + col + 12, y,
             pdf.l_margin + 2 * col + 12, y)
    pdf.set_font('Body', size=layout['font_tiny'])
    pdf.set_text_color(110, 110, 110)
    pdf.set_xy(pdf.l_margin, y + 1)
    pdf.cell(col, layout['line_h'], _('Арендодатель / подпись · печать'),
             align='C')
    pdf.set_xy(pdf.l_margin + col + 12, y + 1)
    pdf.cell(col, layout['line_h'], _('Арендатор / подпись'), align='C')
    pdf.set_text_color(0, 0, 0)


def build_contract_pdf(rental, size: str = SIZE_FULL) -> bytes:
    """Собрать PDF договора заданного формата.

    :param rental: ``Rental`` с подгруженными items/payments/customer.
    :param size:   ``full`` (A4), ``half`` (A5) или ``quarter`` (A6).
                   Любое неизвестное значение трактуется как ``full``.
    :returns:      Готовый PDF в ``bytes``.
    :raises ContractFontMissing: если не найден ни один TTF-шрифт.
    :raises ContractDependencyMissing: если не установлен ``fpdf2``.
    """
    try:
        import fpdf as fpdf_module  # ленивый импорт: HTML-печать не зависит от него
    except ImportError as exc:
        raise ContractDependencyMissing(
            'Для генерации PDF договора требуется пакет fpdf2. '
            'Установите его в текущий Python-интерпретатор: '
            '`pip install fpdf2`.'
        ) from exc

    from .models import Payment

    layout = _LAYOUTS[normalize_size(size)]

    font_regular = _first_existing(_FONT_CANDIDATES)
    if not font_regular:
        raise ContractFontMissing(
            'Не найден TTF-шрифт для PDF. Положите static/fonts/DejaVuSans.ttf '
            'или установите системный (apt install fonts-dejavu-core), '
            'либо задайте CONTRACT_PDF_FONT_PATH.'
        )
    font_bold = _first_existing(_BOLD_CANDIDATES)

    items = list(rental.items.select_related('product').all())
    deposit_paid = sum(
        (p.amount for p in rental.payments.filter(kind=Payment.Kind.DEPOSIT)),
        Decimal('0.00'),
    )
    total_deposit_due = sum(
        (it.product.deposit_per_unit * it.qty for it in items),
        Decimal('0.00'),
    )
    fine_coef = getattr(settings, 'RENTAL_OVERDUE_FINE_COEF', Decimal('1.5'))

    pdf = _make_contract_pdf(fpdf_module, font_regular, font_bold, layout)
    pdf.add_page()
    w = pdf.epw

    # ---- Заголовок ----
    pdf.set_font('Body', 'B', layout['font_h1'])
    pdf.cell(0, layout['header_h'],
             _('ДОГОВОР АРЕНДЫ № %(n)s') % {'n': rental.pk},
             align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Body', size=layout['font_small'])
    pdf.set_text_color(110, 110, 110)
    pdf.cell(
        0, layout['subheader_h'],
        _('от %(d)s, г. Ташкент') % {'d': rental.created_at.strftime('%d.%m.%Y %H:%M')},
        align='C', new_x='LMARGIN', new_y='NEXT',
    )
    pdf.set_text_color(0, 0, 0)
    pdf.ln(layout['line_h'])

    cust = rental.customer

    if layout['show_parties']:
        # ---- Стороны (две колонки) ----
        col = w / 2 - 2
        y0 = pdf.get_y()
        pdf.set_font('Body', 'B', layout['font_base'])
        pdf.multi_cell(col, layout['line_h'], _('Арендодатель:'),
                       new_x='RIGHT', new_y='TOP')
        pdf.set_xy(pdf.l_margin + col + 4, y0)
        pdf.multi_cell(col, layout['line_h'], _('Арендатор:'),
                       new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('Body', size=layout['font_small'])
        y1 = pdf.get_y()
        landlord = '\n'.join([
            _('ООО «Rakhmonov — учёт аренды»'),
            _('ИНН ____________'),
            _('Тел.: ____________'),
        ])
        pdf.multi_cell(col, layout['line_h'], landlord,
                       new_x='RIGHT', new_y='TOP')
        y_left_end = pdf.get_y()

        renter_lines = [cust.full_name]
        if cust.code:
            renter_lines.append(_('Внутр. номер: № %(c)s') % {'c': cust.code})
        if cust.passport:
            renter_lines.append(_('Паспорт: %(p)s') % {'p': cust.passport})
        if cust.address:
            renter_lines.append(_('Адрес: %(a)s') % {'a': cust.address})
        if cust.phone:
            renter_lines.append(_('Тел.: %(t)s') % {'t': cust.phone})
        pdf.set_xy(pdf.l_margin + col + 4, y1)
        pdf.multi_cell(col, layout['line_h'], '\n'.join(renter_lines),
                       new_x='LMARGIN', new_y='NEXT')
        pdf.set_y(max(y_left_end, pdf.get_y()) + 4)
    else:
        # quarter: только клиент, в одну строку.
        pdf.set_font('Body', 'B', layout['font_base'])
        pdf.cell(0, layout['line_h'], _('Арендатор:'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        renter_bits = [cust.full_name]
        if cust.code:
            renter_bits.append('№ ' + cust.code)
        if cust.phone:
            renter_bits.append(cust.phone)
        pdf.multi_cell(0, layout['line_h'], ' · '.join(renter_bits),
                       new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

    # ---- Раздел «Предмет договора» ----
    if layout['item_columns'] == 'compact':
        # У quarter — без заголовка-номера, чтобы экономить место.
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('Предмет'),
                 new_x='LMARGIN', new_y='NEXT')
    else:
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('1. Предмет договора'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        pdf.multi_cell(0, layout['line_h'], _(
            'Арендодатель передаёт, а Арендатор принимает во временное '
            'возмездное пользование оборудование, перечисленное ниже:'
        ), new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

    _draw_items_table(pdf, layout, items, total_deposit_due)

    # ---- Сроки и оплата ----
    if layout['show_terms']:
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('2. Сроки и оплата'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        bullets = [
            _('Дата выдачи: %(d)s') % {'d': rental.created_at.strftime('%d.%m.%Y %H:%M')},
            _('Срок возврата: %(d)s') % {'d': rental.due_date.strftime('%d.%m.%Y %H:%M')},
            _('Внесённый залог при выдаче: %(s)s сум') % {'s': _money(deposit_paid)},
            _('Коэффициент штрафа за просрочку: %(c)s от стоимости суток '
              'за каждую просроченную единицу.') % {'c': fine_coef},
        ]
        for b in bullets:
            pdf.multi_cell(0, layout['line_h'], '•  ' + b,
                           new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)
    else:
        # quarter: ужимаем до одной строки с ключевыми датами и залогом.
        pdf.set_font('Body', size=layout['font_small'])
        compact = (
            _('Выдано: %(d1)s · Возврат: %(d2)s · Залог при выдаче: %(s)s сум')
            % {
                'd1': rental.created_at.strftime('%d.%m.%Y %H:%M'),
                'd2': rental.due_date.strftime('%d.%m.%Y %H:%M'),
                's': _money(deposit_paid),
            }
        )
        pdf.multi_cell(0, layout['line_h'], compact,
                       new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

    # ---- Обязанности арендатора ----
    if layout['show_duties']:
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('3. Обязанности арендатора'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        duties = [
            _('Использовать оборудование по назначению, не передавать третьим лицам.'),
            _('Вернуть оборудование в исправном состоянии в установленный срок.'),
            _('При повреждении / утрате возместить полную стоимость '
              '(удерживается из залога).'),
            _('При просрочке возврата уплатить штраф согласно п. 2.'),
        ]
        for i, d in enumerate(duties, start=1):
            pdf.multi_cell(0, layout['line_h'], f'{i}.  {d}',
                           new_x='LMARGIN', new_y='NEXT')

    if layout['show_note'] and rental.note:
        pdf.ln(2)
        pdf.set_font('Body', 'B', layout['font_h2'])
        title = _('Дополнительно') if layout['item_columns'] == 'compact' \
            else _('4. Дополнительно')
        pdf.cell(0, layout['header_h'], title,
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        pdf.multi_cell(0, layout['line_h'], rental.note,
                       new_x='LMARGIN', new_y='NEXT')

    _draw_signatures(pdf, layout)

    return bytes(pdf.output())
