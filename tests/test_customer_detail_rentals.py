"""Детальная страница клиента: аренды — аккордеон с ленивой карточкой."""
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
    # Кнопка «Открыть» ведёт на полную страницу аренды.
    assert reverse('rental_detail', args=[r.pk]) in body
    assert f'#{r.id}' in body


def test_customer_detail_shows_rental_summary(client_staff, customer,
                                              rental_for_customer):
    r, item = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Свёрнутый заголовок показывает позицию и залог.
    assert item.product.name in body
    assert '×7' in body
    assert '/ 500' in body
    rentals = list(resp.context['rentals'])
    assert rentals[0].outstanding_total == 7
    assert rentals[0].deposit_total == Decimal('500.00')


def test_customer_detail_accordion_wiring(client_staff, customer,
                                          rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Строка-заголовок раскрывает карточку через rental_card в свой контейнер.
    assert f'data-card-url="{reverse("rental_card", args=[r.pk])}"' in body
    assert f'id="crow-{r.id}"' in body
    assert f'id="rbody-{r.id}"' in body
    assert 'rental-acc-header' in body


def test_customer_detail_no_rentals(client_staff, customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    assert 'Аренд пока нет' in resp.content.decode()


def test_customer_detail_includes_accordion_js(client_staff, customer,
                                                rental_for_customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert 'js/customer-rentals.js' in resp.content.decode()
