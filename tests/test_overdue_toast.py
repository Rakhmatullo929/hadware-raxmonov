"""Тесты для тост-уведомления о просроченных арендах."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.context_processors import _count_overdue_rentals
from config.models import Movement, Rental, RentalItem


def _make_overdue_rental(customer, product, user, days_overdue=3):
    """Создать аренду с истёкшим сроком возврата и невыданным остатком."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() - timedelta(days=days_overdue),
        created_by=user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=2,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=2,
        created_by=user,
    )
    return r


def _make_fresh_rental(customer, product, user):
    """Создать активную аренду без просрочки (на будущее)."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=1,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=1,
        created_by=user,
    )
    return r


def test_count_overdue_rentals_counts_only_overdue(db, customer, product,
                                                   admin_user):
    assert _count_overdue_rentals() == 0
    _make_overdue_rental(customer, product, admin_user)
    _make_overdue_rental(customer, product, admin_user)
    _make_fresh_rental(customer, product, admin_user)
    assert _count_overdue_rentals() == 2


def test_count_ignores_returned_overdue(db, customer, product, admin_user):
    """Аренда с истёкшим сроком, но всё вернули — не просрочка."""
    r = _make_overdue_rental(customer, product, admin_user)
    item = r.items.first()
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=item.qty,
        created_by=admin_user,
    )
    assert _count_overdue_rentals() == 0


def test_toast_renders_for_admin_when_overdue(db, customer, product, admin_user):
    _make_overdue_rental(customer, product, admin_user)
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')

    resp = c.get(reverse('rental_list'))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="overdueToast"' in body
    assert 'overdueToastShown' in body
    # Бейдж в сайдбаре тоже отрисован.
    assert 'badge rounded-pill bg-danger' in body


def test_toast_absent_for_staff(db, customer, product, staff_user):
    """Staff видит бейдж, но «громкий» тост — только для админа."""
    _make_overdue_rental(customer, product, staff_user)
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')

    resp = c.get(reverse('rental_list'))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="overdueToast"' not in body
    # Но бейдж в сайдбаре всё равно есть — оператору тоже полезно.
    assert 'badge rounded-pill bg-danger' in body


def test_toast_absent_when_no_overdue(db, customer, product, admin_user):
    _make_fresh_rental(customer, product, admin_user)
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')

    resp = c.get(reverse('rental_list'))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'id="overdueToast"' not in body
    assert 'badge rounded-pill bg-danger' not in body


def test_context_skips_count_for_htmx_request(db, customer, product, admin_user):
    """HTMX-фрагменты не рендерят base.html, поэтому count не выполняется."""
    _make_overdue_rental(customer, product, admin_user)
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')

    # Запрос с HX-Request — overdue_count в контексте должен быть 0,
    # чтобы не платить за лишний COUNT на каждом hx-get.
    resp = c.get(reverse('rental_list'), HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    # base.html для htmx-запроса всё равно отрисуется (это полный list,
    # не partial), но тост-маркер должен отсутствовать, т.к. overdue_count=0.
    body = resp.content.decode()
    assert 'id="overdueToast"' not in body
