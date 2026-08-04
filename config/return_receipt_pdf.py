"""Серверная генерация PDF-чека возврата через fpdf2.

Тот же вид, что печать аренды: подпись клиента + плоская таблица позиций
(общий хелпер :func:`config.pdf_common.draw_items_table`) — Код клиента ·
Товар(Наименование/Кол-во/Стоимость/Общая сумма) · Дата/Время Отправки и
Привозки. Альбомный A6, общий шрифт и водяной знак (см. config/pdf_common.py).
"""
from django.utils.translation import gettext as _

from .pdf_common import (
    draw_items_table,
    draw_watermark,
    load_fpdf,
    money,
    resolve_fonts,
)

_PAGE = (105, 148)  # A6 в мм (портретный кортеж; orientation='L' → альбом)
_ROW_H = 4.8
_BASE_FONT = 6.5


def build_return_receipt_pdf(ctx) -> bytes:
    """Собрать PDF-чек по контексту build_return_receipt_context.

    :param ctx: словарь с ключами rental, customer, rows, total_qty,
                total_amount, receipt_dt, note. В каждой строке rows —
                name, qty, price_per_day, amount, issue_dt, date (возврат).
    :returns:   готовый PDF в bytes.
    :raises PdfFontMissing / PdfDependencyMissing: см. pdf_common.
    """
    fpdf_module = load_fpdf()
    font_regular, font_bold = resolve_fonts()

    rental = ctx['rental']
    customer = ctx['customer']

    class _ReceiptPDF(fpdf_module.FPDF):
        def __init__(self):
            super().__init__(orientation='L', format=_PAGE)
            self.set_auto_page_break(auto=True, margin=7)
            self.set_margins(7, 7, 7)
            self.add_font('Body', '', font_regular)
            self.add_font('Body', 'B', font_bold or font_regular)
            self.set_font('Body', size=_BASE_FONT)

        def header(self):
            draw_watermark(self)

    pdf = _ReceiptPDF()
    pdf.add_page()

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
    bits = [customer.full_name]
    if customer.code:
        bits.append('№ ' + customer.code)
    if customer.phone:
        bits.append(customer.phone)
    pdf.multi_cell(0, 4, _('Клиент: ') + ' · '.join(bits),
                   new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)

    # ---- Таблица позиций (тот же вид, что печать аренды) ----
    rows = [{
        'name': row['name'],
        'qty': row['qty'],
        'price': row['price_per_day'],
        'total': row['amount'],
        'issue_dt': row.get('issue_dt'),
        'return_dt': row.get('date'),
    } for row in ctx['rows']]
    draw_items_table(
        pdf, rows, ctx['total_qty'], ctx['total_amount'],
        customer.code or '', row_h=_ROW_H, base_font=_BASE_FONT,
    )

    # ---- Итоговая фраза ----
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
