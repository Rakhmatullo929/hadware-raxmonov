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
    # Контракт с JS: money-input.js цепляется по .money-input,
    # rental-create.js читает цену по .item-price.
    assert 'money-input item-price' in body


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


# ---------- применение цены ----------

def test_admin_sets_custom_price(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, '250.50'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('250.50')


def test_custom_price_does_not_touch_catalog(client_admin, customer, product):
    """Цена аренды — снимок: справочник товара остаётся прежним."""
    client_admin.post(_url(), data=_payload(customer, product, '250.50'))
    product.refresh_from_db()
    assert product.daily_price == Decimal('100.00')


def test_empty_price_falls_back_to_catalog(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, ''))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == product.daily_price


def test_price_accepts_ru_grouping_and_comma(client_admin, customer, product):
    resp = client_admin.post(_url(),
                             data=_payload(customer, product, '1 234,50'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('1234.50')


def test_zero_price_allowed(client_admin, customer, product):
    """Ноль — валидная цена: бесплатная выдача."""
    resp = client_admin.post(_url(), data=_payload(customer, product, '0'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == Decimal('0.00')


# ---------- ошибки ----------

def test_invalid_price_blocks_creation(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, 'abc'))
    assert resp.status_code == 200
    assert 'цена за сутки указана неверно' in resp.content.decode().lower()
    assert not Rental.objects.filter(customer=customer).exists()


def test_negative_price_blocks_creation(client_admin, customer, product):
    resp = client_admin.post(_url(), data=_payload(customer, product, '-5'))
    assert resp.status_code == 200
    assert 'отрицательной' in resp.content.decode().lower()
    assert not Rental.objects.filter(customer=customer).exists()


def test_entered_price_survives_validation_error(client_admin, customer, product):
    """Ошибка в количестве не должна стирать уже введённую цену."""
    resp = client_admin.post(
        _url(), data=_payload(customer, product, '777.00', qty='0'))
    assert resp.status_code == 200
    assert 'value="777.00"' in resp.content.decode()
    assert not Rental.objects.filter(customer=customer).exists()


# ---------- права ----------

def test_staff_price_is_ignored(client_staff, customer, product):
    """Подделанный POST от staff не должен менять цену."""
    resp = client_staff.post(_url(), data=_payload(customer, product, '1.00'))
    assert resp.status_code == 302, resp.content[:400]
    item = RentalItem.objects.get(rental__customer=customer)
    assert item.price_per_day == product.daily_price


# ---------- несколько строк ----------

def test_prices_are_not_mixed_between_rows(client_admin, customer, product,
                                           category):
    other = Product.objects.create(
        name='Второй товар', category=category, unit='шт',
        stock_total=100, daily_price=Decimal('300.00'),
    )
    resp = client_admin.post(_url(), data={
        'customer': str(customer.pk),
        'created_at': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
        'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(),
        'item_product': [str(product.pk), str(other.pk)],
        'item_qty': ['2', '3'],
        'item_price': ['11.00', '22.00'],
    })
    assert resp.status_code == 302, resp.content[:400]
    prices = {
        it.product_id: it.price_per_day
        for it in RentalItem.objects.filter(rental__customer=customer)
    }
    assert prices[product.pk] == Decimal('11.00')
    assert prices[other.pk] == Decimal('22.00')


# ---------- регресс-стражи по исходнику JS ----------
#
# Браузерного раннера в репозитории нет (см. requirements.txt), поэтому
# поведение rental-create.js проверяется вручную, а здесь стоят дешёвые
# стражи против случайного удаления ключевых кусков.

def _rental_create_js():
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent
            / 'static' / 'js' / 'rental-create.js').read_text(encoding='utf-8')


def test_js_reads_price_from_row_input():
    """Подытоги должны считаться от введённой цены, а не только от data-price."""
    js = _rental_create_js()
    assert 'input.item-price' in js


def test_js_autofills_price_and_respects_manual_edit():
    """Автоподстановка цены есть, и ручная правка её замораживает."""
    js = _rental_create_js()
    assert 'syncPrices' in js
    assert 'markPriceTouched' in js
    # Синтетическое событие из syncPrices не должно считаться ручной правкой.
    assert 'isTrusted' in js
