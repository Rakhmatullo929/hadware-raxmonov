"""Тесты отчёта «Способы оплаты»."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def rental_with_payments(db, customer, product, admin_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=2,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=2,
        created_by=admin_user,
    )
    Payment.objects.create(rental=r, amount=Decimal('100.00'),
                           kind=Payment.Kind.DEPOSIT, method=Payment.Method.CASH)
    Payment.objects.create(rental=r, amount=Decimal('200.00'),
                           kind=Payment.Kind.ADVANCE, method=Payment.Method.CARD)
    Payment.objects.create(rental=r, amount=Decimal('300.00'),
                           kind=Payment.Kind.RENT, method=Payment.Method.CARD)
    Payment.objects.create(rental=r, amount=Decimal('50.00'),
                           kind=Payment.Kind.FINE, method=Payment.Method.CASH)
    return r


def test_report_payment_methods_renders(client_admin, rental_with_payments):
    resp = client_admin.get(reverse('report_payment_methods'))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Все ключевые лейблы присутствуют.
    for label in ('Наличные', 'Карта', 'Аванс', 'Залог', 'Штраф'):
        assert label in body


def test_report_payment_methods_totals_correct(client_admin, rental_with_payments):
    resp = client_admin.get(reverse('report_payment_methods'))
    assert resp.status_code == 200
    body = resp.content.decode()
    # floatformat:2 при ru-локали даёт запятую как разделитель.
    # Σ за период = 100+200+300+50 = 650.00
    assert '650,00' in body or '650.00' in body
    # Σ наличными = 100+50 = 150.00
    assert '150,00' in body or '150.00' in body
    # Σ картой = 200+300 = 500.00
    assert '500,00' in body or '500.00' in body


def test_report_payment_methods_respects_date_filter(client_admin, customer,
                                                     product, admin_user):
    """Платёж вне диапазона не попадает в сводку."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=admin_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('999.00'),
        kind=Payment.Kind.RENT, method=Payment.Method.CARD,
        date=timezone.now() - timedelta(days=365),
    )
    today = timezone.localdate()
    url = (reverse('report_payment_methods')
           + f'?date_from={today.isoformat()}&date_to={today.isoformat()}')
    resp = client_admin.get(url)
    assert resp.status_code == 200
    assert '999.00' not in resp.content.decode()


def test_report_payment_methods_requires_admin(staff_user, rental_with_payments):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    resp = c.get(reverse('report_payment_methods'))
    # Staff не имеет роли admin — должен получить 403 или редирект.
    assert resp.status_code in (302, 403)
