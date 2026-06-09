"""FIFO billing tests.

Each issue Movement is a chunk; returns consume oldest chunks first.
A same-day return counts as 1 day; otherwise integer date diff.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from config.billing import (
    compute_item_base,
    compute_item_unit_days,
    compute_rental_billing,
    compute_return_amount_for_qty,
    return_charge_map,
)
from config.models import (
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
        due_date=timezone.now() + timedelta(days=due_in_days),
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
        due_date=timezone.now() - timedelta(days=3),  # 3 days overdue
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


def test_item_base_uses_stored_return_amount(actors):
    """A return with an explicit amount overrides the auto FIFO rent for the
    returned units; still-outstanding units keep accruing automatically."""
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
        rental_item=item, kind=Movement.Kind.RETURN, qty=7,
        date=t0 + timedelta(days=12), amount=Decimal('5000.00'),
        created_by=actors['user'],
    )
    as_of = t0 + timedelta(days=12)
    # returned 7 → stored 5000 (not auto 7*12*100=8400);
    # outstanding 3 → 3*12*100 = 3600 → base 8600
    assert compute_item_base(item, as_of=as_of) == Decimal('8600.00')


def test_item_base_falls_back_to_auto_when_amount_null(actors):
    """A return left without a stored amount bills the auto FIFO rent — keeps
    old data and existing behaviour identical."""
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
        date=t0 + timedelta(days=5), created_by=actors['user'],  # amount None
    )
    as_of = t0 + timedelta(days=10)
    # returned 3*5*100 = 1500; outstanding 7*10*100 = 7000 → 8500
    assert compute_item_base(item, as_of=as_of) == Decimal('8500.00')


def test_rental_billing_base_uses_return_amounts(actors):
    """End-to-end: a manual return amount drives summary['base']."""
    rental = _make_rental(actors)  # due in 30d → no fine
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=10,
        price_per_day=Decimal('100.00'),
    )
    t0 = timezone.now() - timedelta(days=8)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        date=t0, created_by=actors['user'],
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=10,
        date=t0 + timedelta(days=3), amount=Decimal('1234.00'),
        created_by=actors['user'],
    )
    summary = compute_rental_billing(rental)
    # auto would be 10*3*100 = 3000; stored amount wins
    assert summary['base'] == Decimal('1234.00')


def test_compute_return_amount_for_qty_uses_current_outstanding(actors):
    """Default suggestion when the operator leaves the amount blank: FIFO rent
    for returning `qty` units right now."""
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=10,
        price_per_day=Decimal('100.00'),
    )
    t0 = timezone.now() - timedelta(days=6)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        date=t0, created_by=actors['user'],
    )
    as_of = t0 + timedelta(days=6)
    # returning 7 now: 7 * 6 days * 100 = 4200
    assert compute_return_amount_for_qty(item, 7, as_of=as_of) == Decimal('4200.00')


def test_return_charge_map_reports_stored_or_auto(actors):
    """Timeline map: stored amount when set, auto FIFO rent otherwise."""
    rental = _make_rental(actors)
    item = RentalItem.objects.create(
        rental=rental, product=actors['product'], qty=10,
        price_per_day=Decimal('100.00'),
    )
    t0 = timezone.now() - timedelta(days=10)
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        date=t0, created_by=actors['user'],
    )
    m_auto = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=2,
        date=t0 + timedelta(days=4), created_by=actors['user'],  # amount None
    )
    m_manual = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=3,
        date=t0 + timedelta(days=6), amount=Decimal('999.00'),
        created_by=actors['user'],
    )
    charges = return_charge_map(rental)
    assert charges[m_auto.id] == Decimal('800.00')    # 2 * 4 * 100
    assert charges[m_manual.id] == Decimal('999.00')   # stored


def test_rental_billing_no_fine_after_close(actors):
    today = timezone.localdate()
    rental = Rental.objects.create(
        customer=actors['customer'],
        due_date=timezone.now() - timedelta(days=5),
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
