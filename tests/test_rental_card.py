"""HTMX-фрагмент карточки аренды (rental_card) для аккордеона клиента."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def rental(db, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=7, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=7, created_by=staff_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('500.00'), kind=Payment.Kind.DEPOSIT,
    )
    return r, item


def test_rental_card_renders_all_blocks(client_staff, rental):
    r, item = rental
    resp = client_staff.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Все четыре обёртки-цели OOB + модал-слот присутствуют.
    for anchor in ('id="rental-summary"', 'id="rental-items"',
                   'id="rental-timeline"', 'id="rental-payments"',
                   'id="modal-slot"'):
        assert anchor in body, anchor
    # Это фрагмент, а не полная страница — без <html>/навигации base.html.
    assert '<html' not in body.lower()
    # Реальные данные аренды видны (позиция товара).
    assert item.product.name in body


def test_rental_card_404_for_missing(client_staff):
    resp = client_staff.get(reverse('rental_card', args=[999999]))
    assert resp.status_code == 404


def test_rental_card_requires_login(db, rental):
    r, _ = rental
    c = Client(SERVER_NAME='localhost')
    resp = c.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 302
    assert '/login/' in resp.url


def test_rental_card_allows_admin(client_admin, rental):
    r, _ = rental
    resp = client_admin.get(reverse('rental_card', args=[r.pk]))
    assert resp.status_code == 200


def test_line_daily_cost_property(rental):
    """Сумма позиции за сутки = цена/сут × кол-во."""
    _, item = rental          # price 100.00 × qty 7
    assert item.line_daily_cost == Decimal('700.00')


def test_items_table_shows_line_daily_cost_column(client_staff, rental):
    r, item = rental
    resp = client_staff.get(reverse('rental_card', args=[r.pk]))
    body = resp.content.decode()
    # Новый столбец «Σ/сут.» с суммой строки (цена × кол-во).
    assert 'Σ/сут.' in body
    assert item.line_daily_cost == Decimal('700.00')
    assert '700,00' in body        # 100.00 × 7 → '700,00' (ru-локаль)
