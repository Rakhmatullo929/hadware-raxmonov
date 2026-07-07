"""Детальная страница клиента: аренды кликабельны и показаны с деталями."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def rental_for_customer(db, customer, product, staff_user):
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


def test_customer_detail_links_to_rental(client_staff, customer, rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Ссылка на страницу самой аренды присутствует (можно перейти).
    assert reverse('rental_detail', args=[r.pk]) in body
    assert f'#{r.id}' in body


def test_customer_detail_shows_rental_details(client_staff, customer,
                                              rental_for_customer):
    r, item = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Детали аренды: название товара с количеством, залог, остаток на руках.
    assert item.product.name in body
    assert '×7' in body                 # позиция товара
    assert '/ 500' in body              # залог в ячейке «оплачено / залог»
    # Аннотация работает — остаток на руках доступен в контексте.
    rentals = list(resp.context['rentals'])
    assert rentals[0].outstanding_total == 7
    assert rentals[0].deposit_total == Decimal('500.00')


def test_customer_detail_no_rentals(client_staff, customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    assert 'Аренд пока нет' in resp.content.decode()
