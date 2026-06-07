"""Property-level model tests: outstanding_qty, available_stock, is_overdue."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from config.models import Movement, Rental, RentalItem


def _make_rental(customer, user, due_in_days=7, status=Rental.Status.ACTIVE):
    return Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=due_in_days),
        status=status,
        created_by=user,
    )


def _issue(item, qty, user, when=None):
    return Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=qty,
        date=when or timezone.now(), created_by=user,
    )


def _ret(item, qty, user, when=None):
    return Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=qty,
        date=when or timezone.now(), created_by=user,
    )


def test_outstanding_qty_initial_zero(admin_user, customer, product):
    rental = _make_rental(customer, admin_user)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=10,
        price_per_day=product.daily_price,
    )
    assert item.issued_qty == 0
    assert item.returned_qty == 0
    assert item.outstanding_qty == 0


def test_outstanding_qty_after_partial_returns(admin_user, customer, product):
    rental = _make_rental(customer, admin_user)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=10,
        price_per_day=product.daily_price,
    )
    _issue(item, 10, admin_user)
    _ret(item, 4, admin_user)
    _ret(item, 2, admin_user)
    assert item.issued_qty == 10
    assert item.returned_qty == 6
    assert item.outstanding_qty == 4


def test_available_stock_decreases_with_active_outstanding(admin_user, customer, product):
    assert product.available_stock == 100  # nothing rented yet

    rental = _make_rental(customer, admin_user)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=30,
        price_per_day=product.daily_price,
    )
    _issue(item, 30, admin_user)
    product.refresh_from_db()
    assert product.available_stock == 70

    _ret(item, 10, admin_user)
    product.refresh_from_db()
    assert product.available_stock == 80


def test_available_stock_ignores_closed_rentals(admin_user, customer, product):
    rental = _make_rental(
        customer, admin_user, status=Rental.Status.CLOSED,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=30,
        price_per_day=product.daily_price,
    )
    _issue(item, 30, admin_user)
    # closed rentals don't count against available_stock
    assert product.available_stock == 100


def test_is_overdue_true_when_past_due_with_outstanding(admin_user, customer, product):
    rental = _make_rental(customer, admin_user, due_in_days=-1)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5,
        price_per_day=product.daily_price,
    )
    _issue(item, 5, admin_user)
    assert rental.is_overdue is True


def test_is_overdue_false_when_due_in_future(admin_user, customer, product):
    """due_date теперь datetime — пока время возврата ещё не наступило,
    аренда не считается просроченной."""
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(minutes=30),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5,
        price_per_day=product.daily_price,
    )
    _issue(item, 5, admin_user)
    assert rental.is_overdue is False


def test_is_overdue_false_when_fully_returned(admin_user, customer, product):
    rental = _make_rental(customer, admin_user, due_in_days=-3)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5,
        price_per_day=product.daily_price,
    )
    _issue(item, 5, admin_user)
    _ret(item, 5, admin_user)
    assert rental.is_overdue is False


def test_is_overdue_false_when_closed(admin_user, customer, product):
    rental = _make_rental(
        customer, admin_user, due_in_days=-3, status=Rental.Status.CLOSED,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5,
        price_per_day=product.daily_price,
    )
    _issue(item, 5, admin_user)
    assert rental.is_overdue is False


def test_outstanding_items_lists_only_unsettled(admin_user, customer, product, category):
    from config.models import Product
    p2 = Product.objects.create(
        name='Other', category=category, unit='шт', stock_total=50,
        daily_price=Decimal('50.00'), deposit_per_unit=Decimal('0'),
    )
    rental = _make_rental(customer, admin_user)
    it1 = RentalItem.objects.create(rental=rental, product=product, qty=5,
                                    price_per_day=product.daily_price)
    it2 = RentalItem.objects.create(rental=rental, product=p2, qty=3,
                                    price_per_day=p2.daily_price)
    _issue(it1, 5, admin_user); _ret(it1, 5, admin_user)  # settled
    _issue(it2, 3, admin_user); _ret(it2, 1, admin_user)  # outstanding=2

    pks = list(rental.outstanding_items().values_list('pk', flat=True))
    assert pks == [it2.pk]


def test_maybe_auto_close_triggers_when_all_returned(admin_user, customer, product):
    rental = _make_rental(customer, admin_user)
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5,
        price_per_day=product.daily_price,
    )
    _issue(item, 5, admin_user)
    assert rental.maybe_auto_close() is False
    assert rental.status == Rental.Status.ACTIVE

    _ret(item, 5, admin_user)
    assert rental.maybe_auto_close() is True
    rental.refresh_from_db()
    assert rental.status == Rental.Status.CLOSED
    assert rental.closed_at is not None


def test_customer_code_auto_assigned_on_create(db):
    from config.models import Customer
    c = Customer.objects.create(full_name='Без кода')
    c.refresh_from_db()
    assert c.code is not None
    assert c.code == f'{c.pk:05d}'


def test_customer_code_manual_override_kept(db):
    from config.models import Customer
    c = Customer.objects.create(full_name='Свой код', code='VIP-001')
    c.refresh_from_db()
    assert c.code == 'VIP-001'


def test_customer_code_unique(db):
    from django.db import IntegrityError
    from config.models import Customer
    Customer.objects.create(full_name='A', code='SAME')
    with pytest.raises(IntegrityError):
        Customer.objects.create(full_name='B', code='SAME')


def test_customer_outstanding_qty_aggregates_active_rentals(
    admin_user, customer, product,
):
    r1 = _make_rental(customer, admin_user)
    r2 = _make_rental(customer, admin_user)
    closed = _make_rental(customer, admin_user, status=Rental.Status.CLOSED)
    for r, q in [(r1, 5), (r2, 7), (closed, 9)]:
        item = RentalItem.objects.create(rental=r, product=product, qty=q,
                                         price_per_day=product.daily_price)
        _issue(item, q, admin_user)

    # closed contributes 0; active rentals contribute 5 + 7 = 12
    assert customer.outstanding_qty == 12
    assert customer.active_rentals_count == 2


def test_product_included_kit_defaults_to_empty(category):
    from decimal import Decimal
    from config.models import Product
    p = Product.objects.create(
        name='Без комплекта',
        category=category,
        unit='шт',
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
    )
    assert p.included_kit == ''


def test_product_included_kit_stores_text(category):
    from decimal import Decimal
    from config.models import Product
    p = Product.objects.create(
        name='С комплектом',
        category=category,
        unit='шт',
        daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
        included_kit='Зажим ×3, Фиксатор ×3',
    )
    p.refresh_from_db()
    assert p.included_kit == 'Зажим ×3, Фиксатор ×3'


def test_product_form_has_included_kit_and_saves(category):
    from config.forms import ProductForm
    assert 'included_kit' in ProductForm.base_fields
    form = ProductForm(data={
        'name': 'Корейская опалубка 2×1',
        'category': category.pk,
        'unit': 'шт',
        'stock_total': '0',
        'daily_price': '0',
        'deposit_per_unit': '0',
        'included_kit': 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3',
        'is_active': 'on',
    })
    assert form.is_valid(), form.errors
    obj = form.save()
    assert obj.included_kit.startswith('Зажим ×3')
