"""Дата выдачи новой аренды по умолчанию = текущая, но админ может изменить.

Контракт (по просьбе пользователя): при открытии формы новой аренды поле
«Дата и время выдачи» уже заполнено текущим числом/временем — оператору не
нужно ничего вводить. При этом значение остаётся редактируемым: админ может
поставить любую другую дату, и она сохраняется (не перетирается на now()).
"""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.forms import RentalCreateForm
from config.models import Rental


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


# ---------- форма ----------

def test_create_form_prefills_created_at_with_today(db):
    """Незаполненная форма отдаёт текущую дату как initial поля выдачи."""
    form = RentalCreateForm()
    value = form['created_at'].value()
    assert value is not None, 'поле выдачи должно быть предзаполнено'
    # value() отдаёт naive-local datetime для виджета — сравниваем дневную часть.
    local = value if timezone.is_naive(value) else timezone.localtime(value)
    assert local.date() == timezone.localdate()


# ---------- рендер страницы ----------

def test_create_page_renders_created_at_value(client_admin):
    """На странице новой аренды input выдачи имеет value с сегодняшним числом."""
    r = client_admin.get(reverse('rental_create'))
    body = r.content.decode()
    today = timezone.localdate().isoformat()
    assert 'name="created_at"' in body
    # datetime-local формат — 'YYYY-MM-DDTHH:MM'; ищем сегодняшнюю дату в value.
    assert f'value="{today}T' in body


# ---------- админ переопределяет ----------

def test_admin_can_override_created_at(client_admin, customer, product):
    """Своя дата выдачи сохраняется, а не заменяется текущим временем."""
    custom = timezone.localtime() - timedelta(days=3)
    custom_str = custom.strftime('%Y-%m-%dT%H:%M')
    due = (timezone.localdate() + timedelta(days=10)).isoformat()

    r = client_admin.post('/rentals/new/', data={
        'customer': str(customer.pk),
        'created_at': custom_str,
        'due_date': due,
        'item_product': [str(product.pk)],
        'item_qty': ['5'],
    })
    assert r.status_code == 302, r.content[:300]

    rental = Rental.objects.get(customer=customer)
    saved = timezone.localtime(rental.created_at).strftime('%Y-%m-%dT%H:%M')
    assert saved == custom_str
