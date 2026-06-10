"""Тесты показа поля «В комплекте» в каталоге и договоре."""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from config.models import Product


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def kit_product(category):
    return Product.objects.create(
        name='Корейская опалубка 2×1',
        category=category,
        unit='шт',
        stock_total=0,
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
        included_kit='Зажим ×3, Фиксатор ×3',
    )


def _make_rental_with(product, customer, staff_user):
    from datetime import timedelta
    from django.utils import timezone
    from config.models import Movement, Rental, RentalItem
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=2, created_by=staff_user,
    )
    return r


def test_product_list_shows_included_kit(client_admin, kit_product):
    # Каталог большой и постраничный — ищем конкретный товар, чтобы тест не
    # зависел от того, на какую страницу он попал.
    resp = client_admin.get(reverse('product_list'), {'q': 'Корейская опалубка 2×1'})
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'Зажим ×3, Фиксатор ×3' in body


def test_html_contract_shows_included_kit(client_admin, kit_product, customer, admin_user):
    rental = _make_rental_with(kit_product, customer, admin_user)
    resp = client_admin.get(reverse('rental_contract', args=[rental.pk]))
    assert resp.status_code == 200
    assert 'Зажим ×3, Фиксатор ×3' in resp.content.decode()


@pytest.mark.parametrize('size', ['full', 'half', 'quarter'])
def test_pdf_contract_renders_with_included_kit(kit_product, customer, admin_user, size):
    from config.contract_pdf import build_contract_pdf
    rental = _make_rental_with(kit_product, customer, admin_user)
    pdf = build_contract_pdf(rental, size=size)
    assert pdf[:5] == b'%PDF-'
    assert len(pdf) > 500


def test_seed_created_catalog(db):
    from config.models import Category, Product
    for name in ['Корейская опалубка', 'Финская опалубка', 'Колонна',
                 'Стойка телескопическая домкрат', 'Леса строительные']:
        assert Category.objects.filter(name=name).exists(), name
    p = Product.objects.get(name='Корейская опалубка 2×1')
    assert p.included_kit == 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3'
    # Цена проставлена прайс-листом 0018_seed_pricelist.
    assert p.unit == 'шт' and p.daily_price == 6000
    col = Product.objects.get(name='Колонна 3.7×40')
    assert col.included_kit == 'Тайрод ×24'
    # Счётчики после 0018 (добавлены позиции прайс-листа):
    # Корейская 31+2, Финская 5+14, Колонна 9+4.
    assert Product.objects.filter(category__name='Корейская опалубка').count() == 33
    assert Product.objects.filter(category__name='Финская опалубка').count() == 19
    assert Product.objects.filter(category__name='Колонна').count() == 13
    old = Product.objects.filter(
        name__in=['Финская фанера', 'Стойка телескопическая 3.0 м'],
    )
    assert old.exists()
    assert all(not p.is_active for p in old)
