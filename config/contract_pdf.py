"""Серверная генерация PDF договора аренды через fpdf2.

Чистый Python, без системных зависимостей (в отличие от WeasyPrint).
Шрифт ищется по списку кандидатов, чтобы работало и на macOS (dev),
и на Linux (прод). На проде достаточно `apt install fonts-dejavu-core`.

Поддерживаются три формата:
* ``full``    — A4, полный договор со всеми разделами (по умолчанию).
* ``half``    — A5, средний: стороны, позиции, ключевые условия.
* ``quarter`` — A6, краткая выписка «для своих»: №, клиент, позиции, итог.

Важно: ``fpdf2`` импортируется лениво внутри :func:`build_contract_pdf`,
чтобы вызов HTML-печати договора и наличие констант формата работали даже
тогда, когда библиотека ещё не установлена (она нужна только для PDF).
"""
from decimal import Decimal

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
        'show_note': False,
        'item_columns': 'compact',     # без цены/залога — только позиция и кол-во
    },
}


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


def _draw_items_table(pdf, layout, items, total_cost):
    """Таблица позиций: №, Тип, Наименование, Кол-во, Ед., Цена/сут, Стоимость.

    Стоимость позиции = кол-во × цена/сут. Колонки одинаковы для всех форматов
    (для A6 шрифт мельче, см. layout)."""
    w = pdf.epw
    row_h = layout['row_h']
    base = layout['font_small']

    # frac: №, Тури, Номи, Сони, Бирл., Нарх/кун, Қиймат — сумма = 1.00
    headers = [
        ('№', 0.06, 'C'),
        (_('Тури'), 0.19, 'L'),
        (_('Номи'), 0.29, 'L'),
        (_('Сони'), 0.10, 'R'),
        (_('Бирл.'), 0.09, 'C'),
        (_('Нарх/кун'), 0.135, 'R'),
        (_('Қиймат'), 0.135, 'R'),
    ]

    pdf.set_font('Body', 'B', base)
    pdf.set_fill_color(238, 240, 242)
    for title, frac, _align in headers:
        pdf.cell(w * frac, row_h, str(title), border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font('Body', size=base)
    for idx, it in enumerate(items, start=1):
        line_cost = it.qty * it.price_per_day
        row = [
            (str(idx), 0.06, 'C'),
            (str(it.product.category), 0.19, 'L'),
            (it.product.name, 0.29, 'L'),
            (str(it.qty), 0.10, 'R'),
            (it.product.unit, 0.09, 'C'),
            (_money(it.price_per_day), 0.135, 'R'),
            (_money(line_cost), 0.135, 'R'),
        ]
        if pdf.will_page_break(row_h):
            pdf.add_page()
        for text, frac, align in row:
            pdf.cell(w * frac, row_h, str(text), border=1, align=align)
        pdf.ln()
        kit = (it.product.included_kit or '').strip()
        if kit:
            pdf.set_font('Body', '', max(base - 1, 6))
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(
                w, row_h - 1,
                _('тўпламда') + ': ' + kit,
                border='LR', align='L',
            )
            # multi_cell оставляет курсор справа — возвращаем к левому полю,
            # иначе последующие multi_cell(0, ...) получат нулевую ширину.
            pdf.set_x(pdf.l_margin)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Body', size=base)

    # Итог: суммарная стоимость аренды в сутки (Σ кол-во × цена/сут).
    pdf.set_font('Body', 'B', base)
    pdf.cell(w * 0.865, row_h, _('Жами (кунлик)'), border=1, align='R')
    pdf.cell(w * 0.135, row_h, _money(total_cost), border=1, align='R')
    pdf.ln(row_h + 3)


def build_contract_pdf(rental, size: str = SIZE_FULL) -> bytes:
    """Собрать PDF договора заданного формата.

    :param rental: ``Rental`` с подгруженными items/payments/customer.
    :param size:   ``full`` (A4), ``half`` (A5) или ``quarter`` (A6).
                   Любое неизвестное значение трактуется как ``full``.
    :returns:      Готовый PDF в ``bytes``.
    :raises ContractFontMissing: если не найден ни один TTF-шрифт.
    :raises ContractDependencyMissing: если не установлен ``fpdf2``.
    """
    fpdf_module = load_fpdf()

    from django.db.models import Sum

    from . import billing
    from .models import Movement, Payment

    layout = _LAYOUTS[normalize_size(size)]

    font_regular, font_bold = resolve_fonts()

    items = list(
        rental.items.select_related('product', 'product__category').all()
    )
    total_cost = sum(
        (it.qty * it.price_per_day for it in items), Decimal('0.00'),
    )
    deposit_paid = sum(
        (p.amount for p in rental.payments.filter(kind=Payment.Kind.DEPOSIT)),
        Decimal('0.00'),
    )
    total_deposit_due = sum(
        (it.product.deposit_per_unit * it.qty for it in items),
        Decimal('0.00'),
    )
    # «Сколько вернул и на какую сумму»: суммарный возврат по аренде.
    charges = billing.return_charge_map(rental)
    returned_amount = sum(charges.values(), Decimal('0.00'))
    returned_qty = (
        Movement.objects
        .filter(rental_item__rental=rental, kind=Movement.Kind.RETURN)
        .aggregate(q=Sum('qty'))['q'] or 0
    )
    fine_coef = getattr(settings, 'RENTAL_OVERDUE_FINE_COEF', Decimal('1.5'))

    pdf = _make_contract_pdf(fpdf_module, font_regular, font_bold, layout)
    pdf.add_page()
    w = pdf.epw

    # ---- Заголовок ----
    pdf.set_font('Body', 'B', layout['font_h1'])
    pdf.cell(0, layout['header_h'],
             _('ИЖАРА ШАРТНОМАСИ № %(n)s') % {'n': rental.pk},
             align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Body', size=layout['font_small'])
    pdf.set_text_color(110, 110, 110)
    pdf.cell(
        0, layout['subheader_h'],
        _('%(d)s, Тошкент ш.') % {'d': rental.created_at.strftime('%d.%m.%Y %H:%M')},
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
        pdf.multi_cell(col, layout['line_h'], _('Ижарага берувчи:'),
                       new_x='RIGHT', new_y='TOP')
        pdf.set_xy(pdf.l_margin + col + 4, y0)
        pdf.multi_cell(col, layout['line_h'], _('Ижарага олувчи:'),
                       new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('Body', size=layout['font_small'])
        y1 = pdf.get_y()
        landlord = '\n'.join([
            _('«Rakhmonov — ижара ҳисоби» МЧЖ'),
            _('Тел.: +998906364044'),
        ])
        pdf.multi_cell(col, layout['line_h'], landlord,
                       new_x='RIGHT', new_y='TOP')
        y_left_end = pdf.get_y()

        renter_lines = [cust.full_name]
        if cust.code:
            renter_lines.append(_('Ички рақам: № %(c)s') % {'c': cust.code})
        if cust.passport:
            renter_lines.append(_('Паспорт: %(p)s') % {'p': cust.passport})
        if cust.address:
            renter_lines.append(_('Манзил: %(a)s') % {'a': cust.address})
        if cust.phone:
            renter_lines.append(_('Тел.: %(t)s') % {'t': cust.phone})
        pdf.set_xy(pdf.l_margin + col + 4, y1)
        pdf.multi_cell(col, layout['line_h'], '\n'.join(renter_lines),
                       new_x='LMARGIN', new_y='NEXT')
        pdf.set_y(max(y_left_end, pdf.get_y()) + 4)
    else:
        # quarter: только клиент, в одну строку.
        pdf.set_font('Body', 'B', layout['font_base'])
        pdf.cell(0, layout['line_h'], _('Ижарага олувчи:'),
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
        pdf.cell(0, layout['header_h'], _('Ускуналар'),
                 new_x='LMARGIN', new_y='NEXT')
    else:
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('1. Шартнома предмети'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        pdf.multi_cell(0, layout['line_h'], _(
            'Ижарага берувчи топширади, Ижарага олувчи эса қуйида '
            'кўрсатилган ускуналарни вақтинча, ҳақ эвазига фойдаланишга '
            'қабул қилади:'
        ), new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

    _draw_items_table(pdf, layout, items, total_cost)

    # ---- Сроки и оплата ----
    if layout['show_terms']:
        pdf.set_font('Body', 'B', layout['font_h2'])
        pdf.cell(0, layout['header_h'], _('2. Муддат ва тўлов'),
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        bullets = [
            _('Бериш санаси: %(d)s') % {'d': rental.created_at.strftime('%d.%m.%Y %H:%M')},
            _('Қайтариш муддати: %(d)s') % {'d': rental.due_date.strftime('%d.%m.%Y %H:%M')},
            _('Беришда олинган гаров: %(s)s сўм') % {'s': _money(deposit_paid)},
            _('Ҳисобланган гаров (жами): %(s)s сўм') % {'s': _money(total_deposit_due)},
        ]
        if returned_qty:
            bullets.append(
                _('Қайтарилди: %(q)s дона · %(s)s сўм')
                % {'q': returned_qty, 's': _money(returned_amount)}
            )
        bullets += [
            _('Кечиктирилганлик жаримаси коэффициенти: %(c)s — ҳар бир '
              'кечиктирилган бирлик учун кунлик нархдан.') % {'c': fine_coef},
            _('Опалубка ёки товар қайтарилаётганда тоза ҳолатда '
              'топширилиши шарт.'),
        ]
        for b in bullets:
            pdf.multi_cell(0, layout['line_h'], '•  ' + b,
                           new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)
    else:
        # quarter: ужимаем до строк с ключевыми датами, залогом и возвратом.
        pdf.set_font('Body', size=layout['font_small'])
        compact = (
            _('Берилди: %(d1)s · Қайтариш: %(d2)s · Гаров: %(s)s сўм')
            % {
                'd1': rental.created_at.strftime('%d.%m.%Y %H:%M'),
                'd2': rental.due_date.strftime('%d.%m.%Y %H:%M'),
                's': _money(deposit_paid),
            }
        )
        pdf.multi_cell(0, layout['line_h'], compact,
                       new_x='LMARGIN', new_y='NEXT')
        if returned_qty:
            pdf.multi_cell(
                0, layout['line_h'],
                _('Қайтарилди: %(q)s дона · %(s)s сўм')
                % {'q': returned_qty, 's': _money(returned_amount)},
                new_x='LMARGIN', new_y='NEXT',
            )
        pdf.multi_cell(0, layout['line_h'],
                       _('Қайтаришда тоза ҳолатда топширилади.'),
                       new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

    if layout['show_note'] and rental.note:
        pdf.ln(2)
        pdf.set_font('Body', 'B', layout['font_h2'])
        title = _('Қўшимча') if layout['item_columns'] == 'compact' \
            else _('3. Қўшимча')
        pdf.cell(0, layout['header_h'], title,
                 new_x='LMARGIN', new_y='NEXT')
        pdf.set_font('Body', size=layout['font_small'])
        pdf.multi_cell(0, layout['line_h'], rental.note,
                       new_x='LMARGIN', new_y='NEXT')

    return bytes(pdf.output())
