"""Админ задаёт цену позиции прямо в форме создания аренды (до создания).

Цена — снимок этой аренды (`RentalItem.price_per_day`); справочник товара
(`Product.daily_price`) не меняется. Оператору (staff) поле не показывается и
из его POST игнорируется.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Product, Rental, RentalItem


def _url():
    """Реверсим внутри теста, а не на импорте: проект под i18n_patterns,
    и адрес зависит от активного языка."""
    return reverse('rental_create')


def _payload(customer, product, price=None, qty='5'):
    """POST формы создания аренды с одной позицией.

    ``price=None`` — поля цены в запросе нет вовсе (как у staff).
    """
    data = {
        'customer': str(customer.pk),
        'created_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk)],
        'item_qty': [qty],
    }
    if price is not None:
        data['item_price'] = [price]
    return data


# ---------- рендер формы ----------

def test_price_field_visible_for_admin(client_admin):
    body = client_admin.get(_url()).content.decode()
    assert 'name="item_price"' in body


def test_price_field_hidden_for_staff(client_staff):
    body = client_staff.get(_url()).content.decode()
    assert 'name="item_price"' not in body


def test_new_row_fragment_has_price_field_for_admin(client_admin):
    """Строка, добавленная кнопкой «+ Позиция», тоже должна иметь поле цены."""
    body = client_admin.get(reverse('rental_item_row_new')).content.decode()
    assert 'name="item_price"' in body


def test_new_row_fragment_has_no_price_field_for_staff(client_staff):
    body = client_staff.get(reverse('rental_item_row_new')).content.decode()
    assert 'name="item_price"' not in body
