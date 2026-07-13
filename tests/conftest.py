from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

from config.models import (
    Category,
    Customer,
    Movement,
    Product,
    Rental,
    RentalItem,
)


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


@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def rental_with_kit_return(db, customer, category, staff_user):
    """Аренда корейской опалубки 2×80, 12 шт, полный возврат.

    Комплект на 1 шт: Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3,
    Штир/шайба ×3 — значит на 12 шт каждого допа по 36.
    """
    product = Product.objects.create(
        name='Корейская опалубка 2×80', category=category, unit='шт',
        daily_price=Decimal('100.00'),
        included_kit='Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3',
    )
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=12, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=12, created_by=staff_user,
    )
    m = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=12,
        amount=Decimal('1200.00'), created_by=staff_user,
    )
    return r, item, m


@pytest.fixture
def rental_with_multiday_return(db, customer, product, staff_user):
    """Аренда: выдано 16 шт 6 дней назад, полный возврат сейчас, авто-сумма.

    unit_days = 16 × 6 = 96, сумма = 96 × 100 = 9600. На чеке это должно
    читаться как «16 шт × 100/день × 6 дн = 9600», а не как разовое начисление.
    """
    now = timezone.now()
    r = Rental.objects.create(
        customer=customer,
        due_date=now + timedelta(days=1),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=16, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=16,
        date=now - timedelta(days=6), created_by=staff_user,
    )
    m = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=16,
        amount=Decimal('9600.00'), date=now, created_by=staff_user,
    )
    return r, item, m


@pytest.fixture
def rental_with_returns(db, customer, product, staff_user):
    """Аренда: выдано 10, два возврата (4 и 3) с явными суммами 400 и 300."""
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=10, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=10,
        created_by=staff_user,
    )
    m1 = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=4,
        amount=Decimal('400.00'), note='партия возврата', created_by=staff_user,
    )
    m2 = Movement.objects.create(
        rental_item=item, kind=Movement.Kind.RETURN, qty=3,
        amount=Decimal('300.00'), created_by=staff_user,
    )
    return r, item, m1, m2
