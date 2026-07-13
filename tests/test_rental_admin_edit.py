"""Админ-редактирование аренды на странице деталей:
правка срока/примечания, платежи (add/edit/delete), позиции."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


@pytest.fixture
def rental(db, customer, product, admin_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=7),
        created_by=admin_user,
        note='старое примечание',
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=5, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=5,
        created_by=admin_user,
    )
    return r


# ---------- rental edit ----------

def test_rental_edit_changes_due_date_and_note(client_admin, rental):
    # datetime-local в форме отдаётся в локальной таймзоне, поэтому
    # формируем строку из локального представления и сверяем тоже локально.
    new_local = timezone.localtime(timezone.now() + timedelta(days=20)).replace(
        second=0, microsecond=0,
    )
    created_local = timezone.localtime(rental.created_at).replace(
        second=0, microsecond=0,
    )
    r = client_admin.post(f'/rentals/{rental.pk}/edit/', {
        'created_at': created_local.strftime('%Y-%m-%dT%H:%M'),
        'due_date': new_local.strftime('%Y-%m-%dT%H:%M'),
        'note': 'новое примечание',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    rental.refresh_from_db()
    assert timezone.localtime(rental.due_date).strftime('%Y-%m-%dT%H:%M') == \
        new_local.strftime('%Y-%m-%dT%H:%M')
    assert rental.note == 'новое примечание'


def test_rental_edit_forbidden_for_staff(client_staff, rental):
    r = client_staff.get(f'/rentals/{rental.pk}/edit/')
    assert r.status_code in (302, 403)


# ---------- payments ----------

def test_payment_add(client_admin, rental):
    r = client_admin.post(f'/rentals/{rental.pk}/payment/add/', {
        'kind': Payment.Kind.RENT, 'method': Payment.Method.CASH,
        'amount': '500.00', 'note': 'нал',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    p = rental.payments.get()
    assert p.amount == Decimal('500.00')
    assert p.kind == Payment.Kind.RENT
    assert p.method == Payment.Method.CASH


def test_payment_add_rejects_zero(client_admin, rental):
    r = client_admin.post(f'/rentals/{rental.pk}/payment/add/', {
        'kind': Payment.Kind.RENT, 'method': Payment.Method.CASH,
        'amount': '0',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert rental.payments.count() == 0
    assert 'больше нуля' in r.content.decode()


def test_payment_edit(client_admin, rental):
    p = Payment.objects.create(
        rental=rental, amount=Decimal('100.00'), kind=Payment.Kind.RENT,
    )
    r = client_admin.post(
        f'/rentals/{rental.pk}/payment/{p.pk}/edit/',
        {
            'kind': Payment.Kind.FINE,
            'method': Payment.Method.CARD,
            'amount': '250.00',
            'note': 'штраф',
        },
        HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    p.refresh_from_db()
    assert p.amount == Decimal('250.00')
    assert p.kind == Payment.Kind.FINE
    assert p.method == Payment.Method.CARD


def test_payment_advance_kind_is_accepted(client_admin, rental):
    """Новый тип «Аванс» можно сохранить, и он попадает в paid в billing."""
    r = client_admin.post(f'/rentals/{rental.pk}/payment/add/', {
        'kind': Payment.Kind.ADVANCE, 'method': Payment.Method.CARD,
        'amount': '777.00',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    p = rental.payments.get()
    assert p.kind == Payment.Kind.ADVANCE
    assert p.method == Payment.Method.CARD

    # billing: аванс должен учитываться в paid
    from config import billing
    summary = billing.compute_rental_billing(rental)
    assert summary['paid'] >= Decimal('777.00')


def test_payment_delete(client_admin, rental):
    p = Payment.objects.create(
        rental=rental, amount=Decimal('100.00'), kind=Payment.Kind.RENT,
    )
    r = client_admin.post(
        f'/rentals/{rental.pk}/payment/{p.pk}/delete/',
        HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    assert not Payment.objects.filter(pk=p.pk).exists()


def test_payment_add_forbidden_for_staff(client_staff, rental):
    r = client_staff.post(f'/rentals/{rental.pk}/payment/add/', {
        'kind': Payment.Kind.RENT, 'amount': '500',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code in (302, 403)
    assert rental.payments.count() == 0


# ---------- items ----------

def test_item_add_creates_item_and_issue(client_admin, rental, product):
    before = rental.items.count()
    r = client_admin.post(f'/rentals/{rental.pk}/item/add/', {
        'product': str(product.pk), 'qty': '3',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert rental.items.count() == before + 1
    new_item = rental.items.order_by('-pk').first()
    assert new_item.qty == 3
    assert new_item.issued_qty == 3  # ISSUE movement created


def test_item_add_rejects_over_stock(client_admin, rental, product):
    r = client_admin.post(f'/rentals/{rental.pk}/item/add/', {
        'product': str(product.pk),
        'qty': str(product.available_stock + 999),
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert 'доступно' in r.content.decode()


def test_item_edit_qty_above_issued_ok(client_admin, rental):
    item = rental.items.first()  # qty=5, issued=5
    r = client_admin.post(
        f'/rentals/{rental.pk}/item/{item.pk}/edit/',
        {'qty': '8'}, HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    item.refresh_from_db()
    assert item.qty == 8


def test_item_edit_qty_below_issued_rejected(client_admin, rental):
    item = rental.items.first()  # issued=5
    r = client_admin.post(
        f'/rentals/{rental.pk}/item/{item.pk}/edit/',
        {'qty': '2'}, HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    item.refresh_from_db()
    assert item.qty == 5  # unchanged
    assert 'меньше уже выданного' in r.content.decode()


def test_item_remove_blocked_when_issued(client_admin, rental):
    item = rental.items.first()  # issued=5
    r = client_admin.post(
        f'/rentals/{rental.pk}/item/{item.pk}/remove/',
        HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    assert rental.items.filter(pk=item.pk).exists()  # not deleted


def test_item_remove_ok_when_no_issue(client_admin, rental, product, admin_user):
    fresh = RentalItem.objects.create(
        rental=rental, product=product, qty=2,
        price_per_day=product.daily_price,
    )
    r = client_admin.post(
        f'/rentals/{rental.pk}/item/{fresh.pk}/remove/',
        HTTP_HX_REQUEST='true',
    )
    assert r.status_code == 200
    assert not RentalItem.objects.filter(pk=fresh.pk).exists()


def test_item_add_reopens_closed_rental(client_admin, rental, product):
    rental.status = Rental.Status.CLOSED
    rental.closed_at = timezone.now()
    rental.save(update_fields=['status', 'closed_at'])
    r = client_admin.post(f'/rentals/{rental.pk}/item/add/', {
        'product': str(product.pk), 'qty': '1',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    rental.refresh_from_db()
    assert rental.status == Rental.Status.ACTIVE
    assert rental.closed_at is None


# ---------- return-movement time edit ----------

def test_movement_time_edit_changes_date_keeps_amount(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    new_local = timezone.localtime(timezone.now() - timedelta(days=3)).replace(
        second=0, microsecond=0,
    )
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': new_local.strftime('%Y-%m-%dT%H:%M')},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    m1.refresh_from_db()
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') == \
        new_local.strftime('%Y-%m-%dT%H:%M')
    assert m1.amount == Decimal('400.00')  # сумма не тронута


def test_movement_time_edit_modal_prefills_current_time(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    resp = client_admin.get(f'/rentals/{r.pk}/movement/{m1.pk}/edit/')
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'name="date"' in body
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') in body


def test_movement_time_edit_works_on_closed_rental(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    r.status = Rental.Status.CLOSED
    r.closed_at = timezone.now()
    r.save(update_fields=['status', 'closed_at'])
    new_local = timezone.localtime(timezone.now() - timedelta(days=1)).replace(
        second=0, microsecond=0,
    )
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': new_local.strftime('%Y-%m-%dT%H:%M')},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    m1.refresh_from_db()
    assert timezone.localtime(m1.date).strftime('%Y-%m-%dT%H:%M') == \
        new_local.strftime('%Y-%m-%dT%H:%M')


def test_movement_time_edit_rejects_invalid_date(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    original = m1.date
    resp = client_admin.post(
        f'/rentals/{r.pk}/movement/{m1.pk}/edit/',
        {'date': 'garbage'},
        HTTP_HX_REQUEST='true',
    )
    assert resp.status_code == 200
    assert 'корректные дату и время' in resp.content.decode()
    m1.refresh_from_db()
    assert m1.date == original


def test_movement_time_edit_forbidden_for_staff(
    client_staff, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/movement/{m1.pk}/edit/')
    assert resp.status_code in (302, 403)


def test_movement_time_edit_rejects_issue_movement(
    client_admin, rental_with_returns,
):
    r, item, m1, m2 = rental_with_returns
    issue = Movement.objects.get(rental_item=item, kind=Movement.Kind.ISSUE)
    resp = client_admin.get(f'/rentals/{r.pk}/movement/{issue.pk}/edit/')
    assert resp.status_code == 404


# ---------- timeline edit affordance ----------

def test_timeline_shows_edit_pencil_for_admin(client_admin, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_admin.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{m1.pk}/edit/' in resp.content.decode()


def test_timeline_hides_edit_pencil_for_staff(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{m1.pk}/edit/' not in resp.content.decode()


def test_timeline_no_edit_pencil_on_issue_row(client_admin, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    issue = Movement.objects.get(rental_item=item, kind=Movement.Kind.ISSUE)
    resp = client_admin.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert f'/rentals/{r.pk}/movement/{issue.pk}/edit/' \
        not in resp.content.decode()
