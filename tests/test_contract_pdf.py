"""Тесты PDF-договора (fpdf2, без системных зависимостей)."""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.contract_pdf import build_contract_pdf
from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


@pytest.fixture
def rental(db, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=staff_user,
        note='Особые условия: вернуть до обеда.',
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=4,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=4,
        created_by=staff_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('1500.00'), kind=Payment.Kind.DEPOSIT,
    )
    return r


def test_build_contract_pdf_returns_valid_pdf(rental):
    pdf = build_contract_pdf(rental)
    assert isinstance(pdf, (bytes, bytearray))
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 1000


@pytest.mark.parametrize('size', ['full', 'half', 'quarter'])
def test_build_contract_pdf_supports_all_sizes(rental, size):
    pdf = build_contract_pdf(rental, size=size)
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 500


def test_build_contract_pdf_unknown_size_falls_back_to_full(rental):
    # Неизвестное значение не должно падать — трактуется как 'full'.
    pdf_unknown = build_contract_pdf(rental, size='xxl')
    pdf_full = build_contract_pdf(rental, size='full')
    assert pdf_unknown[:5] == b'%PDF-'
    assert pdf_full[:5] == b'%PDF-'


def test_pdf_endpoint_attachment(client_staff, rental):
    url = reverse('rental_contract_pdf', args=[rental.pk])
    r = client_staff.get(url)
    assert r.status_code == 200
    assert r['Content-Type'] == 'application/pdf'
    assert 'attachment' in r['Content-Disposition']
    # По умолчанию — полный (A4) формат, имя файла отражает это.
    assert f'contract-{rental.pk}-full.pdf' in r['Content-Disposition']
    assert r.content[:5] == b'%PDF-'


@pytest.mark.parametrize('size', ['full', 'half', 'quarter'])
def test_pdf_endpoint_respects_size_query(client_staff, rental, size):
    url = reverse('rental_contract_pdf', args=[rental.pk]) + f'?size={size}'
    r = client_staff.get(url)
    assert r.status_code == 200
    assert r['Content-Type'] == 'application/pdf'
    assert f'contract-{rental.pk}-{size}.pdf' in r['Content-Disposition']
    assert r.content[:5] == b'%PDF-'


def test_pdf_endpoint_unknown_size_falls_back_to_full(client_staff, rental):
    url = reverse('rental_contract_pdf', args=[rental.pk]) + '?size=bogus'
    r = client_staff.get(url)
    assert r.status_code == 200
    assert f'contract-{rental.pk}-full.pdf' in r['Content-Disposition']


def test_contract_html_renders_for_all_sizes(client_staff, rental):
    for size in ('full', 'half', 'quarter'):
        url = reverse('rental_contract', args=[rental.pk]) + f'?size={size}'
        r = client_staff.get(url)
        assert r.status_code == 200
        assert f'print-page--{size}'.encode() in r.content


def test_pdf_endpoint_inline_mode(client_staff, rental):
    url = reverse('rental_contract_pdf', args=[rental.pk]) + '?inline=1'
    r = client_staff.get(url)
    assert r.status_code == 200
    assert 'inline' in r['Content-Disposition']


def test_pdf_endpoint_requires_auth(client, rental):
    url = reverse('rental_contract_pdf', args=[rental.pk])
    r = client.get(url)
    assert r.status_code in (302, 403)


def test_pdf_endpoint_404_for_unknown(client_staff):
    url = reverse('rental_contract_pdf', args=[999999])
    r = client_staff.get(url)
    assert r.status_code == 404


def test_pdf_handles_rental_without_note(client_staff, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=3),
        created_by=staff_user,
    )
    RentalItem.objects.create(
        rental=r, product=product, qty=1, price_per_day=product.daily_price,
    )
    resp = client_staff.get(reverse('rental_contract_pdf', args=[r.pk]))
    assert resp.status_code == 200
    assert resp.content[:5] == b'%PDF-'


def test_logo_svg_asset_exists():
    """Монохромный знак-логотип для водяного знака должен быть в static/img/."""
    p = Path(settings.BASE_DIR) / 'static' / 'img' / 'logo.svg'
    assert p.is_file(), 'static/img/logo.svg отсутствует'
    content = p.read_text(encoding='utf-8')
    assert '<svg' in content
    assert 'R</text>' in content  # буква-марка присутствует


def test_contract_html_has_background_watermark(client_staff, rental):
    """HTML-страница печати договора содержит фоновый знак и ссылку на лого."""
    url = reverse('rental_contract', args=[rental.pk])
    r = client_staff.get(url)
    assert r.status_code == 200
    assert b'print-watermark' in r.content
    assert b'img/logo.svg' in r.content
