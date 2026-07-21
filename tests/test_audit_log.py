"""Журнал действий (аудит): запись создания/изменения/удаления, IP, доступ."""

from decimal import Decimal

import pytest

from config.models import AuditLog, Category, Customer


@pytest.fixture(autouse=True)
def _clean_audit(db):
    """Начинаем каждый тест с пустого журнала — фикстуры conftest могли писать."""
    AuditLog.objects.all().delete()
    yield


def test_create_writes_audit_entry(client_admin):
    """POST-создание объекта пишет запись CREATE с пользователем и IP."""
    resp = client_admin.post(
        '/categories/new/',
        {'name': 'Новая категория'},
        REMOTE_ADDR='203.0.113.7',
    )
    assert resp.status_code in (200, 302)

    log = AuditLog.objects.filter(action=AuditLog.Action.CREATE).latest('id')
    assert log.username == 'bob'
    assert log.ip_address == '203.0.113.7'
    assert 'Новая категория' in log.object_repr


def test_update_records_changed_fields(admin_user):
    """Изменение поля попадает в changes как [старое, новое]."""
    from config import audit

    cat = Category.objects.create(name='Старое имя')
    AuditLog.objects.all().delete()

    audit.set_current(admin_user, '198.51.100.5')
    try:
        cat.name = 'Новое имя'
        cat.save()
    finally:
        audit.clear_current()

    log = AuditLog.objects.get(action=AuditLog.Action.UPDATE)
    assert log.ip_address == '198.51.100.5'
    assert log.changes['name'] == ['Старое имя', 'Новое имя']


def test_delete_writes_audit_entry(admin_user):
    from config import audit

    cust = Customer.objects.create(full_name='Удаляемый', phone='+998900000000')
    AuditLog.objects.all().delete()

    audit.set_current(admin_user, '192.0.2.1')
    try:
        cust.delete()
    finally:
        audit.clear_current()

    log = AuditLog.objects.get(action=AuditLog.Action.DELETE)
    assert 'Удаляемый' in log.object_repr
    assert log.ip_address == '192.0.2.1'


def test_x_forwarded_for_is_used(client_admin):
    """За прокси реальный IP берётся из первого адреса X-Forwarded-For."""
    client_admin.post(
        '/categories/new/',
        {'name': 'За прокси'},
        HTTP_X_FORWARDED_FOR='70.41.3.18, 10.0.0.1',
        REMOTE_ADDR='10.0.0.1',
    )
    log = AuditLog.objects.filter(action=AuditLog.Action.CREATE).latest('id')
    assert log.ip_address == '70.41.3.18'


def test_audit_page_requires_admin(client_staff):
    """Оператору (staff) журнал недоступен."""
    resp = client_staff.get('/audit/')
    assert resp.status_code == 403


def test_audit_page_visible_to_admin(client_admin):
    resp = client_admin.get('/audit/')
    assert resp.status_code == 200


def test_audit_page_filters_by_action(client_admin, admin_user):
    from config import audit

    audit.set_current(admin_user, '203.0.113.9')
    try:
        Category.objects.create(name='Ф')
    finally:
        audit.clear_current()

    resp = client_admin.get('/audit/?action=create')
    assert resp.status_code == 200
    assert b'203.0.113.9' in resp.content
