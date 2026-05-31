"""End-to-end rental flow exercised via Django test client.

Full path: create rental → partial return → payment → final return → status closed.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


def test_full_rental_lifecycle(client_admin, admin_user, customer, product):
    # 1) Create rental via /rentals/new/ POST
    due = (timezone.localdate() + timedelta(days=10)).isoformat()
    r = client_admin.post('/rentals/new/', data={
        'customer': str(customer.pk),
        'due_date': due,
        'note': 'lifecycle test',
        'initial_deposit': '1000.00',
        'item_product': [str(product.pk)],
        'item_qty': ['10'],
    })
    assert r.status_code == 302, r.content[:300]
    rental = Rental.objects.get(note='lifecycle test')
    assert rental.items.count() == 1
    item = rental.items.first()
    assert item.qty == 10
    assert item.issued_qty == 10
    assert rental.payments.filter(kind='deposit').first().amount == Decimal('1000.00')

    # 2) Partial return: 4 of 10
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '4',
        'note': 'partial #1',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    item.refresh_from_db()
    assert item.outstanding_qty == 6
    rental.refresh_from_db()
    assert rental.status == Rental.Status.ACTIVE  # not yet closed

    # 3) Record an extra rent payment manually (admin-side simulation)
    Payment.objects.create(
        rental=rental, amount=Decimal('500.00'),
        kind=Payment.Kind.RENT, note='partial payment',
    )

    # 4) Final return: remaining 6
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '6',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    item.refresh_from_db()
    assert item.outstanding_qty == 0

    # 5) Auto-close kicked in
    rental.refresh_from_db()
    assert rental.status == Rental.Status.CLOSED
    assert rental.closed_at is not None

    # Movements timeline: 1 issue + 2 returns
    movs = Movement.objects.filter(rental_item=item).order_by('date', 'id')
    kinds = [m.kind for m in movs]
    qtys = [m.qty for m in movs]
    assert kinds == ['issue', 'return', 'return']
    assert qtys == [10, 4, 6]


def test_return_validations(client_admin, admin_user, customer, product):
    # Set up a rental with 5 issued
    r = client_admin.post('/rentals/new/', data={
        'customer': str(customer.pk),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk)],
        'item_qty': ['5'],
    })
    assert r.status_code == 302
    rental = Rental.objects.get(customer=customer)
    item = rental.items.first()

    # qty > outstanding → error
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '99',
    }, HTTP_HX_REQUEST='true')
    assert 'к возврату только 5' in r.content.decode()
    item.refresh_from_db()
    assert item.outstanding_qty == 5  # nothing happened

    # negative → error
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '-2',
    }, HTTP_HX_REQUEST='true')
    assert 'не может быть отрицательным' in r.content.decode()

    # all empty → error
    r = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '',
    }, HTTP_HX_REQUEST='true')
    assert 'Укажите количество' in r.content.decode()


def test_create_rental_rejects_qty_above_available_stock(
    client_admin, admin_user, customer, product,
):
    too_much = product.available_stock + 1
    r = client_admin.post('/rentals/new/', data={
        'customer': str(customer.pk),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk)],
        'item_qty': [str(too_much)],
    })
    assert r.status_code == 200  # form re-rendered with error
    assert 'доступно' in r.content.decode()
    assert not Rental.objects.filter(customer=customer).exists()


def test_contract_print_page_renders(client_admin, admin_user, customer, product):
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
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
    Payment.objects.create(
        rental=rental, amount=Decimal('500.00'), kind=Payment.Kind.DEPOSIT,
    )

    r = client_admin.get(f'/rentals/{rental.pk}/contract/')
    assert r.status_code == 200
    body = r.content.decode()
    assert 'ДОГОВОР АРЕНДЫ' in body
    assert customer.full_name in body
    assert product.name in body
    assert '@media print' in body  # print layout is wired
    assert 'navbar' not in body    # contract uses print_base, no nav


def test_404_template_used_for_unknown_rental(client_admin):
    r = client_admin.get('/rentals/99999/')
    assert r.status_code == 404
