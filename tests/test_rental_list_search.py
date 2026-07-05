"""Поиск аренд по клиенту (ФИО / телефон / код) на дашборде аренд."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Customer, Movement, Rental, RentalItem


def _make_rental(customer, product, user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=1, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=1, created_by=user,
    )
    return r


@pytest.fixture
def two_rentals(db, product, staff_user):
    ivanov = Customer.objects.create(full_name='Иванов Иван', phone='+998 90 111 11 11')
    petrov = Customer.objects.create(full_name='Петров Пётр', phone='+998 90 222 22 22')
    r_ivanov = _make_rental(ivanov, product, staff_user)
    r_petrov = _make_rental(petrov, product, staff_user)
    return {'ivanov': (ivanov, r_ivanov), 'petrov': (petrov, r_petrov)}


def test_search_by_name_filters_rentals(client_staff, two_rentals):
    """`?q=Иванов` показывает только аренду Иванова, Петров отфильтрован."""
    url = reverse('rental_list')
    resp = client_staff.get(url, {'q': 'Иванов'})
    assert resp.status_code == 200
    rentals = list(resp.context['rentals'])
    ids = {r.pk for r in rentals}
    assert two_rentals['ivanov'][1].pk in ids
    assert two_rentals['petrov'][1].pk not in ids


def test_search_is_case_insensitive_and_partial(client_staff, two_rentals):
    """Поиск нечувствителен к регистру и работает по подстроке."""
    resp = client_staff.get(reverse('rental_list'), {'q': 'петр'})
    ids = {r.pk for r in resp.context['rentals']}
    assert two_rentals['petrov'][1].pk in ids
    assert two_rentals['ivanov'][1].pk not in ids


def test_search_by_phone(client_staff, two_rentals):
    """Поиск по фрагменту телефона находит нужного клиента."""
    resp = client_staff.get(reverse('rental_list'), {'q': '222 22'})
    ids = {r.pk for r in resp.context['rentals']}
    assert two_rentals['petrov'][1].pk in ids
    assert two_rentals['ivanov'][1].pk not in ids


def test_search_by_code(client_staff, two_rentals):
    """Поиск по коду клиента (№ авто-присвоенный) находит его аренду."""
    ivanov = two_rentals['ivanov'][0]
    resp = client_staff.get(reverse('rental_list'), {'q': ivanov.code})
    ids = {r.pk for r in resp.context['rentals']}
    assert two_rentals['ivanov'][1].pk in ids


def test_empty_query_shows_all(client_staff, two_rentals):
    """Пустой `q` не фильтрует — видны обе аренды."""
    resp = client_staff.get(reverse('rental_list'), {'q': ''})
    ids = {r.pk for r in resp.context['rentals']}
    assert two_rentals['ivanov'][1].pk in ids
    assert two_rentals['petrov'][1].pk in ids
