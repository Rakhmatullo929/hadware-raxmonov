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


def test_pdf_renders_kit_totals(rental_with_kit_return):
    """PDF-чек выводит домноженные допы комплекта («Зажим 36» и т.д.).

    Текст PDF не извлечь без доп. зависимостей, поэтому перехватываем строки,
    которые билдер отправляет в cell/multi_cell.
    """
    r, item, m = rental_with_kit_return
    ctx = build_return_receipt_context(r, [m.id])

    from config.return_receipt_pdf import load_fpdf
    fpdf_module = load_fpdf()
    captured = []
    orig_cell = fpdf_module.FPDF.cell
    orig_multi = fpdf_module.FPDF.multi_cell

    def _grab(args):
        if len(args) > 2 and isinstance(args[2], str):
            captured.append(args[2])

    def rec_cell(self, *a, **k):
        _grab(a)
        return orig_cell(self, *a, **k)

    def rec_multi(self, *a, **k):
        _grab(a)
        return orig_multi(self, *a, **k)

    fpdf_module.FPDF.cell = rec_cell
    fpdf_module.FPDF.multi_cell = rec_multi
    try:
        build_return_receipt_pdf(ctx)
    finally:
        fpdf_module.FPDF.cell = orig_cell
        fpdf_module.FPDF.multi_cell = orig_multi

    blob = ' '.join(captured)
    assert 'Зажим 36' in blob
    assert 'Фиксатор 36' in blob
    assert 'Штир/шайба 36' in blob
