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
    pdf.cell(0, 4, _('Тел.: +998906364044'), align='C',
             new_x='LMARGIN', new_y='NEXT')
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
        ('№', 0.06, 'C'),
        (_('Тип'), 0.20, 'L'),
        (_('Наименование'), 0.30, 'L'),
        (_('Кол-во'), 0.12, 'R'),
        (_('За день'), 0.11, 'R'),
        (_('Дней'), 0.09, 'R'),
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
            (str(idx), 0.06, 'C'),
            (str(row['category']), 0.20, 'L'),
            (row['name'], 0.30, 'L'),
            (f"{row['qty']} {row['unit']}", 0.12, 'R'),
            (money(row['price_per_day']), 0.11, 'R'),
            (str(row['days']), 0.09, 'R'),
            (money(row['amount']), 0.12, 'R'),
        ]
        if pdf.will_page_break(_ROW_H):
            pdf.add_page()
        for text, frac, align in cells:
            pdf.cell(w * frac, _ROW_H, str(text), border=1, align=align)
        pdf.ln()

        # Допы комплекта (домножены на кол-во) — отдельной строкой под позицией.
        kit = row.get('kit') or []
        if kit:
            kit_txt = _('Доп.: ') + ' · '.join(
                f"{k['name']} {k['qty']}" for k in kit)
            pdf.set_font('Body', size=6)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(w, _ROW_H, kit_txt, border='LR',
                           new_x='LMARGIN', new_y='NEXT')
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Body', size=7)

    # ---- Итог ----
    pdf.set_font('Body', 'B', 7)
    pdf.cell(w * 0.56, _ROW_H, _('Итого'), border=1, align='R')
    pdf.cell(w * 0.12, _ROW_H, str(ctx['total_qty']), border=1, align='R')
    pdf.cell(w * 0.11, _ROW_H, '', border=1)
    pdf.cell(w * 0.09, _ROW_H, '', border=1)
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
