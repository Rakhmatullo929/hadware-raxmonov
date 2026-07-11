"""Модалка «Создать аренду» на карточке клиента (клиент зафиксирован)."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Rental


def _modal_url(customer):
    return reverse('rental_create') + f'?customer={customer.pk}'


# ---------- кнопка на карточке клиента ----------

def test_create_button_on_customer_detail(client_staff, customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    assert 'Создать аренду' in body
    assert 'create-modal-slot' in body
    assert f"?customer={customer.pk}" in body


def test_create_button_hidden_for_archived(client_staff, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert 'Создать аренду' not in resp.content.decode()


# ---------- GET модалки ----------

def test_modal_get_fixes_customer(client_staff, customer):
    resp = client_staff.get(_modal_url(customer), HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'modal-content' in body                     # это модалка
    assert customer.full_name in body
    # клиент зафиксирован скрытым полем, без поиска
    assert f'name="customer" value="{customer.pk}"' in body
    assert 'name="customer_q"' not in body


def test_modal_get_requires_htmx(client_staff, customer):
    """Без htmx ?customer= не включает модальный режим — обычная страница."""
    resp = client_staff.get(_modal_url(customer))
    assert resp.status_code == 200
    assert 'modal-content' not in resp.content.decode()


def test_archived_customer_not_served_in_modal(client_staff, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    resp = client_staff.get(_modal_url(customer), HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    assert 'modal-content' not in resp.content.decode()


# ---------- POST из модалки ----------

def test_modal_post_creates_rental_and_hx_redirects(client_staff, customer, product):
    created = timezone.localtime()
    resp = client_staff.post(_modal_url(customer), data={
        'customer': str(customer.pk),
        'created_at': created.strftime('%Y-%m-%dT%H:%M'),
        'due_date': (created + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
        'item_product': [str(product.pk)],
        'item_qty': ['4'],
    }, HTTP_HX_REQUEST='true')
    assert resp.status_code == 204
    rental = Rental.objects.get(customer=customer)
    assert resp['HX-Redirect'] == reverse('rental_detail', args=[rental.pk])
    assert rental.items.first().qty == 4


def test_modal_post_invalid_rerenders_modal(client_staff, customer):
    """Без позиций — модалка перерисовывается с ошибкой, аренда не создана."""
    created = timezone.localtime()
    resp = client_staff.post(_modal_url(customer), data={
        'customer': str(customer.pk),
        'created_at': created.strftime('%Y-%m-%dT%H:%M'),
        'due_date': (created + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
    }, HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'modal-content' in body
    assert 'хотя бы одну позицию' in body
    assert not Rental.objects.filter(customer=customer).exists()
