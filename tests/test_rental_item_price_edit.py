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


def test_parse_price_per_day_helper():
    from config.views import _parse_price_per_day

    assert _parse_price_per_day('250')[0] == Decimal('250.00')
    assert _parse_price_per_day('1 234,50')[0] == Decimal('1234.50')
    assert _parse_price_per_day('2\xa0000,00')[0] == Decimal('2000.00')

    val, err = _parse_price_per_day('abc')
    assert val is None and err

    val, err = _parse_price_per_day('-5')
    assert val is None and err


def _inline_url(rental, item):
    return reverse('rental_item_price_edit', args=[rental.pk, item.pk])


def _cell_url(rental, item):
    return reverse('rental_item_price_cell', args=[rental.pk, item.pk])


def test_inline_get_returns_input_with_current_price(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns          # price 100.00
    resp = client_admin.get(_inline_url(r, item))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="price_per_day"' in body
    assert 'value="100.00"' in body            # текущая цена без локали
    assert _cell_url(r, item) in body          # ✗ ведёт на возврат ячейки


def test_inline_post_updates_price_and_reloads_card(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns          # qty 10
    resp = client_admin.post(_inline_url(r, item), {'price_per_day': '250'})
    assert resp.status_code == 200
    item.refresh_from_db()
    assert item.price_per_day == Decimal('250.00')
    assert resp['HX-Reswap'] == 'none'          # главный swap подавлен, только OOB
    assert '2500,00' in resp.content.decode()   # новая Σ/сут. = 250 × 10 (ru)


def test_inline_post_invalid_keeps_price(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    old = item.price_per_day
    resp = client_admin.post(_inline_url(r, item), {'price_per_day': '-5'})
    assert resp.status_code == 200
    assert 'is-invalid' in resp.content.decode()
    item.refresh_from_db()
    assert item.price_per_day == old


def test_inline_cancel_returns_plain_cell(client_admin, rental_with_returns):
    r, item, *_ = rental_with_returns
    resp = client_admin.get(_cell_url(r, item))
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="price_per_day"' not in body   # отображение, не форма
    assert '100,00' in body                       # цена как текст (ru)


def test_inline_forbidden_for_staff(client_staff, rental_with_returns):
    r, item, *_ = rental_with_returns
    assert client_staff.get(_inline_url(r, item)).status_code == 403
    assert client_staff.post(_inline_url(r, item),
                             {'price_per_day': '5'}).status_code == 403
    assert client_staff.get(_cell_url(r, item)).status_code == 403
