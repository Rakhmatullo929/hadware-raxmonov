"""Тесты чека возврата: контекст, HTML-страница, авто-триггер."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Rental, RentalItem
from config.views import _parse_movement_ids, build_return_receipt_context


def test_parse_movement_ids_drops_invalid():
    assert _parse_movement_ids('1,2,x,3,') == [1, 2, 3]
    assert _parse_movement_ids('') == []
    assert _parse_movement_ids(None) == []


def test_build_context_totals(rental_with_returns, product):
    r, item, m1, m2 = rental_with_returns
    ctx = build_return_receipt_context(r, [m1.id, m2.id])
    assert len(ctx['rows']) == 2
    assert ctx['total_qty'] == 7
    assert ctx['total_amount'] == Decimal('700.00')
    assert ctx['rows'][0]['name'] == product.name
    assert str(ctx['rows'][0]['category']) == str(product.category)
    assert ctx['customer'] == r.customer
    assert ctx['receipt_dt'] is not None


def test_build_context_ignores_foreign_movements(
    rental_with_returns, customer, product, staff_user,
):
    r, item, m1, m2 = rental_with_returns
    other = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    oitem = RentalItem.objects.create(
        rental=other, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.ISSUE, qty=2,
        created_by=staff_user,
    )
    om = Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.RETURN, qty=2,
        amount=Decimal('200.00'), created_by=staff_user,
    )
    # om принадлежит другой аренде — должен быть отброшен.
    ctx = build_return_receipt_context(r, [m1.id, om.id])
    assert len(ctx['rows']) == 1
    assert ctx['rows'][0]['qty'] == 4
