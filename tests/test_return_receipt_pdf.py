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
