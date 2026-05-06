from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from core.models import Category, Customer, Product


@pytest.fixture
def staff_user(db):
    User = get_user_model()
    u = User.objects.create_user('alice', 'alice@x.local', 'pwpwpwpw')
    g, _ = Group.objects.get_or_create(name='staff')
    u.groups.add(g)
    return u


@pytest.fixture
def admin_user(db):
    User = get_user_model()
    u = User.objects.create_user('bob', 'bob@x.local', 'pwpwpwpw')
    g, _ = Group.objects.get_or_create(name='admin')
    u.groups.add(g)
    return u


@pytest.fixture
def superuser(db):
    User = get_user_model()
    return User.objects.create_superuser('root', 'root@x.local', 'pwpwpwpw')


@pytest.fixture
def category(db):
    return Category.objects.create(name='Test category')


@pytest.fixture
def product(category):
    return Product.objects.create(
        name='Test product',
        category=category,
        unit='шт',
        stock_total=100,
        daily_price=Decimal('100.00'),
        deposit_per_unit=Decimal('1000.00'),
    )


@pytest.fixture
def customer(db):
    return Customer.objects.create(
        full_name='Тестовый клиент',
        phone='+998 90 000 00 00',
    )
