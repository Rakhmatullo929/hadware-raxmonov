"""Role gating: staff vs admin vs anonymous."""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from core.models import Customer, Movement, Rental, RentalItem


# Endpoints accessible to both staff and admin (login required only)
STAFF_OK = [
    '/dashboard/',
    '/products/',
    '/customers/',
    '/customers/new/',
    '/rentals/',
    '/rentals/new/',
]

# Endpoints requiring admin (or superuser)
ADMIN_ONLY = [
    '/products/new/',
    '/categories/new/',
    '/reports/',
    '/reports/revenue/',
    '/reports/top-products/',
    '/reports/debtors/',
    '/reports/debtors.csv',
    '/reports/stock/',
]


@pytest.mark.parametrize('path', ADMIN_ONLY)
def test_admin_only_endpoints_block_staff(staff_user, path):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    assert c.get(path).status_code == 403


@pytest.mark.parametrize('path', ADMIN_ONLY)
def test_admin_only_endpoints_allow_admin(admin_user, path):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    assert c.get(path).status_code == 200


@pytest.mark.parametrize('path', STAFF_OK + ADMIN_ONLY)
def test_anonymous_redirected_to_login(db, path):
    c = Client(SERVER_NAME='localhost')
    r = c.get(path)
    assert r.status_code == 302
    assert '/login/' in r.url


@pytest.mark.parametrize('path', STAFF_OK)
def test_staff_can_access_staff_endpoints(staff_user, path):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    assert c.get(path).status_code == 200


def test_staff_cannot_close_rental_early(
    staff_user, admin_user, customer, product,
):
    # build a rental with outstanding qty (issue done)
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.localdate() + timedelta(days=5),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=3,
        price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=3,
        created_by=admin_user,
    )

    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    assert c.get(f'/rentals/{rental.pk}/close/').status_code == 403
    assert c.post(
        f'/rentals/{rental.pk}/close/', data={'note': 'test'}
    ).status_code == 403


def test_staff_cannot_toggle_product_active(staff_user, product):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    assert c.post(f'/products/{product.pk}/toggle/').status_code == 403


def test_superuser_can_access_admin_only(superuser):
    c = Client(SERVER_NAME='localhost')
    c.login(username='root', password='pwpwpwpw')
    for path in ADMIN_ONLY[:3]:
        assert c.get(path).status_code == 200
