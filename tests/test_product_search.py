"""Поиск товара при оформлении аренды должен находить позицию по размеру,
каким бы символом разделителя оператор его ни набрал: латинская x, знак
умножения ×, кириллическая х — и запятая вместо точки (как в прайс-листе)."""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from config.models import Product


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def korean_2x1(category):
    return Product.objects.create(
        name='Корейская опалубка 2х1',  # разделитель — кириллическая «х»
        category=category, unit='шт', stock_total=10,
        daily_price=Decimal('6000.00'), deposit_per_unit=Decimal('0.00'),
    )


@pytest.fixture
def finnish_sheet(category):
    return Product.objects.create(
        name='Финская опалубка 2.2х1.22',
        category=category, unit='шт', stock_total=10,
        daily_price=Decimal('6000.00'), deposit_per_unit=Decimal('0.00'),
    )


def _search(client, q):
    return client.get(
        reverse('rental_item_product_search'), {'item_product_q': q}
    ).content.decode()


@pytest.mark.parametrize('q', [
    '2x1',   # латинская x
    '2×1',   # знак умножения
    '2х1',   # кириллическая х
])
def test_search_finds_by_size_any_x_variant(client_admin, korean_2x1, q):
    body = _search(client_admin, q)
    assert 'Корейская опалубка 2х1' in body


def test_search_handles_comma_like_pricelist(client_admin, finnish_sheet):
    # В прайс-листе размеры писались через запятую и латинскую x: «2,2x1,22».
    body = _search(client_admin, '2,2x1,22')
    assert 'Финская опалубка 2.2х1.22' in body


def test_search_by_plain_digits(client_admin, korean_2x1, finnish_sheet):
    body = _search(client_admin, '2.2х1')
    assert 'Финская опалубка 2.2х1.22' in body
    assert 'Корейская опалубка 2х1' not in body
