"""Тесты отчёта «Возвраты товара» (приёмка возврата + начисленная аренда)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Rental, RentalItem


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


def _rental_with_issue(customer, product, admin_user, qty=5):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=qty,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=qty,
        created_by=admin_user,
    )
    return r, item


@pytest.fixture
def rental_with_returns(db, customer, product, admin_user):
    """Два возврата сегодня с явной суммой начисления: 180 + 270 = 450, 5 шт."""
    r, item = _rental_with_issue(customer, product, admin_user, qty=5)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=2,
        amount=Decimal('180.00'), created_by=admin_user,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=3,
        amount=Decimal('270.00'), created_by=admin_user,
    )
    return r


def test_report_returns_renders(client_admin, rental_with_returns):
    resp = client_admin.get(reverse('report_returns'))
    assert resp.status_code == 200
    body = resp.content.decode()
    for label in ('Возвраты', 'Начислено', 'Клиент', 'Тестовый клиент'):
        assert label in body


def test_report_returns_totals_correct(client_admin, rental_with_returns):
    resp = client_admin.get(reverse('report_returns'))
    assert resp.status_code == 200
    totals = resp.context['totals']
    assert totals['amount'] == Decimal('450.00')
    assert totals['qty'] == 5
    assert totals['count'] == 2
    body = resp.content.decode()
    assert '450,00' in body or '450.00' in body


def test_report_returns_auto_amount_when_blank(client_admin, customer, product,
                                               admin_user):
    """Возврат без сохранённого amount считается авто-расчётом (FIFO дни × цена).

    Выдача и возврат в один день → 1 день × 2 шт × 100 = 200.00.
    """
    r, item = _rental_with_issue(customer, product, admin_user, qty=2)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=2,
        amount=None, created_by=admin_user,
    )
    resp = client_admin.get(reverse('report_returns'))
    assert resp.status_code == 200
    assert resp.context['totals']['amount'] == Decimal('200.00')


def test_report_returns_respects_date_filter(client_admin, customer, product,
                                             admin_user):
    """Возврат вне диапазона дат не попадает в отчёт."""
    r, item = _rental_with_issue(customer, product, admin_user, qty=4)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=4,
        amount=Decimal('999.00'),
        date=timezone.now() - timedelta(days=365),
        created_by=admin_user,
    )
    today = timezone.localdate()
    url = (reverse('report_returns')
           + f'?date_from={today.isoformat()}&date_to={today.isoformat()}')
    resp = client_admin.get(url)
    assert resp.status_code == 200
    assert resp.context['totals']['amount'] == Decimal('0.00')
    assert resp.context['totals']['count'] == 0
    assert '999.00' not in resp.content.decode()


def test_report_returns_issue_not_counted(client_admin, customer, product,
                                          admin_user):
    """Движения ВЫДАЧИ не считаются возвратом."""
    _rental_with_issue(customer, product, admin_user, qty=5)  # only an ISSUE
    resp = client_admin.get(reverse('report_returns'))
    assert resp.status_code == 200
    assert resp.context['totals']['count'] == 0
    assert resp.context['totals']['qty'] == 0


def test_report_returns_csv(client_admin, rental_with_returns):
    resp = client_admin.get(reverse('report_returns_csv'))
    assert resp.status_code == 200
    assert 'text/csv' in resp['Content-Type']
    assert 'attachment' in resp['Content-Disposition']
    body = resp.content.decode('utf-8')
    assert 'Тестовый клиент' in body
    # Обе суммы возвратов присутствуют в выгрузке.
    assert '180.00' in body
    assert '270.00' in body


def test_report_returns_requires_admin(staff_user, rental_with_returns):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    resp = c.get(reverse('report_returns'))
    assert resp.status_code in (302, 403)
