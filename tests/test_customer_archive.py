"""Архивация клиента: скрытие из списка/поиска, обратимость, гейт по активным."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Customer, Movement, Rental, RentalItem


def _make_active_rental(customer, product, user):
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


# ---------- модель ----------

def test_can_archive_when_no_active_rentals(db, customer):
    assert customer.can_archive is True
    assert customer.is_archived is False


def test_cannot_archive_flag_with_active_rental(db, customer, product, staff_user):
    _make_active_rental(customer, product, staff_user)
    assert customer.can_archive is False


# ---------- view: архив / разархив ----------

def test_archive_customer(client_admin, customer):
    resp = client_admin.post(reverse('customer_archive', args=[customer.pk]))
    assert resp.status_code == 302
    customer.refresh_from_db()
    assert customer.is_archived


def test_archive_blocked_with_active_rental(client_admin, customer, product,
                                            staff_user):
    _make_active_rental(customer, product, staff_user)
    client_admin.post(reverse('customer_archive', args=[customer.pk]))
    customer.refresh_from_db()
    assert not customer.is_archived


def test_unarchive_customer(client_admin, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    client_admin.post(reverse('customer_unarchive', args=[customer.pk]))
    customer.refresh_from_db()
    assert not customer.is_archived


# ---------- список: скрытие архива ----------

def test_archived_hidden_from_list_by_default(client_staff, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    resp = client_staff.get(reverse('customer_list'))
    assert customer.full_name not in resp.content.decode()


def test_archived_shown_with_toggle(client_staff, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    resp = client_staff.get(reverse('customer_list'), {'archived': '1'})
    assert customer.full_name in resp.content.decode()


# ---------- поиск в аренде: архивных не предлагаем ----------

def test_archived_excluded_from_rental_search(client_staff, customer):
    customer.archived_at = timezone.now()
    customer.save(update_fields=['archived_at'])
    resp = client_staff.get(reverse('rental_customer_search'),
                            {'customer_q': customer.full_name})
    assert customer.full_name not in resp.content.decode()


# ---------- форма клиента: компактное поле заметок (задача 2) ----------

def test_customer_notes_field_is_compact(db):
    from config.forms import CustomerForm
    form = CustomerForm()
    assert form.fields['notes'].widget.attrs.get('rows') == 2
