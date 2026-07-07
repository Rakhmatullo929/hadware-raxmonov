"""Админ может менять цену позиции аренды (снимок price_per_day)."""
from decimal import Decimal

import pytest
from django.urls import reverse


def _url(rental, item):
    return reverse('rental_item_edit', args=[rental.pk, item.pk])


def test_admin_can_edit_item_price(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    resp = client_admin.post(_url(r, item),
                             {'qty': item.qty, 'price_per_day': '250.50'})
    assert resp.status_code == 200
    item.refresh_from_db()
    assert item.price_per_day == Decimal('250.50')


def test_price_accepts_comma_and_spaces(client_admin, rental_with_returns):
    """Ввод «1 234,50» (ru, пробелы-разделители) принимается."""
    r, item, *_ = rental_with_returns
    client_admin.post(_url(r, item), {'qty': item.qty, 'price_per_day': '1 234,50'})
    item.refresh_from_db()
    assert item.price_per_day == Decimal('1234.50')


def test_invalid_price_rejected(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    old = item.price_per_day
    resp = client_admin.post(_url(r, item),
                             {'qty': item.qty, 'price_per_day': 'abc'})
    assert resp.status_code == 200
    assert 'неверно' in resp.content.decode().lower()
    item.refresh_from_db()
    assert item.price_per_day == old


def test_negative_price_rejected(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    old = item.price_per_day
    client_admin.post(_url(r, item), {'qty': item.qty, 'price_per_day': '-5'})
    item.refresh_from_db()
    assert item.price_per_day == old


def test_qty_and_price_updated_together(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns  # issued=10, qty=10
    client_admin.post(_url(r, item), {'qty': '15', 'price_per_day': '99.00'})
    item.refresh_from_db()
    assert item.qty == 15
    assert item.price_per_day == Decimal('99.00')


def test_staff_cannot_edit_item_price(client_staff, rental_with_returns):
    """Правка позиции — только для админа (AdminRequiredMixin)."""
    r, item, *_ = rental_with_returns
    old = item.price_per_day
    resp = client_staff.post(_url(r, item),
                             {'qty': item.qty, 'price_per_day': '1.00'})
    assert resp.status_code == 403
    item.refresh_from_db()
    assert item.price_per_day == old
