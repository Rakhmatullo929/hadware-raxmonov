"""Тесты inline-создания клиента со страницы создания аренды."""
import pytest
from django.test import Client
from django.urls import reverse

from config.models import Customer


@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


# ---------- GET (открыть модалку) ----------

def test_get_opens_modal(client_staff):
    r = client_staff.get(reverse('rental_customer_create'),
                         HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    body = r.content.decode()
    assert 'Новый клиент' in body
    # Поля формы.
    assert 'name="full_name"' in body
    assert 'name="phone"' in body


def test_get_prefills_full_name_from_search_query(client_staff):
    """Если пользователь начал вводить ФИО в поиске и нажал «Новый» —
    введённое попадёт в поле ФИО модалки."""
    r = client_staff.get(
        reverse('rental_customer_create') + '?customer_q=Алишер Каримов',
        HTTP_HX_REQUEST='true',
    )
    body = r.content.decode()
    assert 'value="Алишер Каримов"' in body


def test_get_requires_auth(client):
    r = client.get(reverse('rental_customer_create'))
    assert r.status_code in (302, 403)


# ---------- POST (создание) ----------

def test_post_creates_customer_and_returns_oob(client_staff):
    r = client_staff.post(reverse('rental_customer_create'), {
        'code': '',
        'full_name': 'Новый Клиент Иванович',
        'phone': '+998 90 000 00 00',
        'passport': '',
        'address': '',
        'notes': '',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    # Клиент создан.
    c = Customer.objects.get(full_name='Новый Клиент Иванович')
    assert c.phone == '+998 90 000 00 00'
    # Ответ содержит OOB-swap по customer-section с picked-state.
    body = r.content.decode()
    assert 'id="customer-section"' in body
    assert 'hx-swap-oob' in body
    # Скрытое поле с pk клиента в picked-партиале.
    assert f'value="{c.pk}"' in body


def test_post_oob_has_single_customer_section_id(client_staff):
    """OOB-ответ должен содержать ровно ОДИН id="customer-section" —
    раньше обёртка дублировала id вложенного _customer_picked (невалидный DOM)."""
    r = client_staff.post(reverse('rental_customer_create'), {
        'code': '', 'full_name': 'Уникальный Клиент', 'phone': '+998 90 111 22 33',
        'passport': '', 'address': '', 'notes': '',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    body = r.content.decode()
    assert body.count('id="customer-section"') == 1
    assert 'hx-swap-oob' in body


def test_post_invalid_returns_modal_with_errors(client_staff):
    """ФИО обязательное — пустое поле должно вернуть модалку с ошибкой,
    не создавать клиента."""
    before = Customer.objects.count()
    r = client_staff.post(reverse('rental_customer_create'), {
        'code': '',
        'full_name': '',  # пусто
        'phone': '',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert Customer.objects.count() == before
    body = r.content.decode()
    # Модалка перерендерилась — заголовок «Новый клиент» снова в DOM.
    assert 'Новый клиент' in body
    # И НЕ должно быть OOB-блока (создания не было).
    assert 'hx-swap-oob' not in body


def test_post_requires_auth(db, client):
    r = client.post(reverse('rental_customer_create'), {
        'full_name': 'X',
    })
    assert r.status_code in (302, 403)
    # И не должен был быть создан.
    assert not Customer.objects.filter(full_name='X').exists()


# ---------- интеграция со страницей создания аренды ----------

def test_create_page_has_modal_slot_and_new_button(client_staff):
    """На странице новой аренды должны быть и slot, и кнопка «Новый»."""
    r = client_staff.get(reverse('rental_create'))
    body = r.content.decode()
    assert 'id="modal-slot"' in body
    # Кнопка «Новый» в группе с поиском.
    assert 'rental_customer_create' in body or '/customer-create/' in body


def test_create_page_search_input_includes_new_button(client_staff):
    """Кнопка должна быть рядом с поисковой строкой клиента —
    регресс-тест на её случайное удаление."""
    r = client_staff.get(reverse('rental_create'))
    body = r.content.decode()
    # bootstrap-иконка person-plus используется только в этой кнопке.
    assert 'bi-person-plus' in body
