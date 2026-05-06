"""FIFO billing tests.

Each issue Movement is a chunk; returns consume oldest chunks first.
A same-day return counts as 1 day; otherwise integer date diff.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.billing import compute_item_unit_days, compute_rental_billing
from core.models import (
    Category,
    Customer,
    Movement,
    Payment,
    Product,
    Rental,
    RentalItem,
)


@pytest.fixture
def actors(db):
    User = get_user_model()
    user = User.objects.create_user('billing_tester', password='x')
    cat = Category.objects.create(name='Тест-категория')
    product = Product.objects.create(
        name='Test Product',
        category=cat,
        unit='шт',
        stock_total=1000,
        daily_price=Decimal('100.00'),
        deposit_per_unit=Decimal('0'),
    )
    customer = Customer.objects.create(full_name='Test Cust')
    return {'user': user, 'product': product, 'customer': customer}


def _make_rental(actors, due_in_days=30):
    today = timezone.localdate()
    return Rental.objects.create(
        customer=actors['customer'],
        due_date=today + timedelta(days=due_in_days),
        created_by=actors['user'],
    )


def test_fifo_two_returns_different_dates(actors):
    """Spec acceptance test: one position, two returns.

    Issue 10 at t0; return 3 at t0+5d; return 7 at t0+12d.
    Unit-days = 3*5 + 7*12 = 99. At 100 / day → base = 9900.
    """
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=10,
        price_per_day=Decimal('100.00'),
    )
    t0 = timezone.now() - timedelta(days=20)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        date=t0, created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=3,
        date=t0 + timedelta(days=5), created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=7,
        date=t0 + timedelta(days=12), created_by=actors['user'],
    )

    assert compute_item_unit_days(item) == 3 * 5 + 7 * 12  # 99


def test_outstanding_accrues_until_as_of(actors):
    """Issue 5; one return of 2 after 4d; remaining 3 still out at as_of=10d."""
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=5,
        price_per_day=Decimal('50.00'),
    )
    t0 = timezone.now() - timedelta(days=10)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=5,
        date=t0, created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=2,
        date=t0 + timedelta(days=4), created_by=actors['user'],
    )

    as_of = t0 + timedelta(days=10)
    # FIFO: 2 returned * 4 days + 3 still-out * 10 days = 8 + 30 = 38
    assert compute_item_unit_days(item, as_of=as_of) == 2 * 4 + 3 * 10


def test_same_day_return_billed_as_one_day(actors):
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=4,
        price_per_day=Decimal('50.00'),
    )
    t0 = timezone.now() - timedelta(hours=3)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=4,
        date=t0, created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=4,
        date=t0 + timedelta(hours=2), created_by=actors['user'],
    )
    # Same calendar day → 1 day, 4 units → 4 unit-days
    assert compute_item_unit_days(item) == 4


def test_two_issues_one_return_consumes_oldest_first(actors):
    """Issue 4 at t0, issue 6 at t0+2d, return 5 at t0+10d.
    FIFO: first chunk 4 fully consumed (10 days), second chunk 1 of 6
    consumed (8 days), 5 outstanding from second chunk (8 days from t0+2d
    to as_of=t0+10d).
    """
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=10,
        price_per_day=Decimal('100.00'),
    )
    t0 = timezone.now() - timedelta(days=15)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=4,
        date=t0, created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=6,
        date=t0 + timedelta(days=2), created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=5,
        date=t0 + timedelta(days=10), created_by=actors['user'],
    )
    as_of = t0 + timedelta(days=10)
    # consumed: 4 * 10 + 1 * 8 = 48; outstanding: 5 * 8 = 40 → 88
    assert compute_item_unit_days(item, as_of=as_of) == 4 * 10 + 1 * 8 + 5 * 8


def test_rental_billing_includes_overdue_fine_and_subtracts_payments(actors):
    """End-to-end totals: base + fine - deposit_held - paid."""
    today = timezone.localdate()
    rental = Rental.objects.create(
        customer=actors['customer'],
        due_date=today - timedelta(days=3),  # 3 days overdue
        created_by=actors['user'],
    )
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=2,
        price_per_day=Decimal('100.00'),
    )
    issue_dt = timezone.now() - timedelta(days=10)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=2,
        date=issue_dt, created_by=actors['user'],
    )
    Payment.objects.create(rental=rental, amount=Decimal('500.00'),
                           kind=Payment.Kind.DEPOSIT)

    summary = compute_rental_billing(rental)
    # 2 units * (~10 days) = 20 unit-days × 100 = 2000 base
    # fine: 2 outstanding × 100 × 1.5 × 3 = 900
    # deposit held: 500
    # total: 2000 + 900 - 500 - 0 = 2400
    assert summary['base'] == Decimal('2000.00')
    assert summary['fine'] == Decimal('900.00')
    assert summary['deposit_held'] == Decimal('500.00')
    assert summary['paid'] == Decimal('0.00')
    assert summary['total_due'] == Decimal('2400.00')


def test_rental_billing_no_fine_after_close(actors):
    today = timezone.localdate()
    rental = Rental.objects.create(
        customer=actors['customer'],
        due_date=today - timedelta(days=5),
        created_by=actors['user'],
        status=Rental.Status.CLOSED,
    )
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=1,
        price_per_day=Decimal('100.00'),
    )
    issue_dt = timezone.now() - timedelta(days=7)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=1,
        date=issue_dt, created_by=actors['user'],
    )
    summary = compute_rental_billing(rental)
    # base accrues but fine should be 0 because rental is closed
    assert summary['fine'] == Decimal('0.00')
