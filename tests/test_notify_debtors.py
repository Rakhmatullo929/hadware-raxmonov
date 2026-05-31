"""Тесты notify_debtors — напоминания только арендодателю (админам).

send_message мокается, чтобы не делать настоящих HTTP-запросов.
Время не мокается — для окна «day-before» используем динамический
REMINDER_HOUR (текущий / не-текущий час) и флаг --force-daily.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from config.models import (
    Customer,
    DebtorNotification,
    Movement,
    Rental,
    RentalItem,
)


def _make_rental(*, customer, product, user, due_offset_days, qty=3):
    # due_date теперь DateTimeField — берём end-of-day, чтобы сохранить
    # прежнюю семантику «весь день due_offset_days».
    due_local = timezone.localtime(timezone.now()).replace(
        hour=23, minute=59, second=59, microsecond=0,
    )
    due_date = due_local + timedelta(days=due_offset_days)
    status = Rental.Status.ACTIVE if due_offset_days >= 0 else Rental.Status.OVERDUE
    rental = Rental.objects.create(
        customer=customer, due_date=due_date, created_by=user, status=status,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=qty,
        price_per_day=Decimal('100.00'),
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE,
        qty=qty, created_by=user,
    )
    return rental


@pytest.fixture
def debtor(db):
    return Customer.objects.create(
        full_name='Должник Тест', phone='+998901112233',
    )


_NOW_HOUR = timezone.now().hour
_OFF_HOUR = (_NOW_HOUR + 5) % 24


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000])
@patch('config.management.commands.notify_debtors.send_message')
def test_day_before_sends_to_admin(mock_send, debtor, product, admin_user):
    """В REMINDER_HOUR при аренде на завтра — одно сообщение админу."""
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=1)
    with override_settings(TELEGRAM_REMINDER_HOUR=_NOW_HOUR):
        call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 1
    assert mock_send.call_args.args[0] == 999000
    n = DebtorNotification.objects.get()
    assert n.kind == DebtorNotification.Kind.DAY_BEFORE
    assert n.target_chat_id == 999000


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[111, 222])
@patch('config.management.commands.notify_debtors.send_message')
def test_day_before_sends_to_each_admin(mock_send, debtor, product, admin_user):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=1)
    with override_settings(TELEGRAM_REMINDER_HOUR=_NOW_HOUR):
        call_command('notify_debtors', stdout=StringIO())
    assert {c.args[0] for c in mock_send.call_args_list} == {111, 222}


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000])
@patch('config.management.commands.notify_debtors.send_message')
def test_day_before_skipped_outside_reminder_hour(
    mock_send, debtor, product, admin_user,
):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=1)
    with override_settings(TELEGRAM_REMINDER_HOUR=_OFF_HOUR):
        call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 0


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000])
@patch('config.management.commands.notify_debtors.send_message')
def test_force_daily_ignores_hour(mock_send, debtor, product, admin_user):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=1)
    with override_settings(TELEGRAM_REMINDER_HOUR=_OFF_HOUR):
        call_command('notify_debtors', '--force-daily', stdout=StringIO())
    assert mock_send.call_count == 1


@override_settings(
    TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000],
    TELEGRAM_REMINDER_HOUR=_OFF_HOUR,
)
@patch('config.management.commands.notify_debtors.send_message')
def test_overdue_sends_regardless_of_hour(
    mock_send, debtor, product, admin_user,
):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-3)
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 1
    n = DebtorNotification.objects.get()
    assert n.kind == DebtorNotification.Kind.HOUR_OVERDUE


@override_settings(
    TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000],
    TELEGRAM_REMINDER_HOUR=_OFF_HOUR,
)
@patch('config.management.commands.notify_debtors.send_message')
def test_overdue_dedup_within_same_hour(
    mock_send, debtor, product, admin_user,
):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-2)
    call_command('notify_debtors', stdout=StringIO())
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 1  # второй раз — дедуп


@override_settings(
    TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000],
    TELEGRAM_REMINDER_HOUR=_OFF_HOUR,
)
@patch('config.management.commands.notify_debtors.send_message')
def test_overdue_sends_again_after_hour_boundary(
    mock_send, debtor, product, admin_user,
):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-2)
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 1

    DebtorNotification.objects.update(
        sent_at=timezone.now() - timedelta(hours=2)
    )
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 2


@override_settings(
    TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000],
    TELEGRAM_REMINDER_HOUR=_OFF_HOUR,
)
@patch('config.management.commands.notify_debtors.send_message')
def test_day_before_dedup_within_same_day(
    mock_send, debtor, product, admin_user,
):
    mock_send.return_value = (True, {'ok': True})
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=1)
    call_command('notify_debtors', '--force-daily', stdout=StringIO())
    call_command('notify_debtors', '--force-daily', stdout=StringIO())
    assert mock_send.call_count == 1  # один раз в сутки


@override_settings(TELEGRAM_BOT_TOKEN='', TELEGRAM_ADMIN_CHAT_IDS=[])
@patch('config.management.commands.notify_debtors.send_message')
def test_no_token_no_send(mock_send, debtor, product, admin_user):
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-1)
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 0
    assert DebtorNotification.objects.count() == 0


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[])
@patch('config.management.commands.notify_debtors.send_message')
def test_no_admins_no_send(mock_send, debtor, product, admin_user):
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-1)
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 0


@override_settings(TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000])
@patch('config.management.commands.notify_debtors.send_message')
def test_dry_run_does_not_persist(mock_send, debtor, product, admin_user):
    _make_rental(customer=debtor, product=product, user=admin_user,
                 due_offset_days=-1)
    call_command('notify_debtors', '--dry-run', stdout=StringIO())
    assert mock_send.call_count == 0
    assert DebtorNotification.objects.count() == 0


@override_settings(
    TELEGRAM_BOT_TOKEN='t', TELEGRAM_ADMIN_CHAT_IDS=[999000],
    TELEGRAM_REMINDER_HOUR=_OFF_HOUR,
)
@patch('config.management.commands.notify_debtors.send_message')
def test_closed_rental_is_skipped(mock_send, debtor, product, admin_user):
    mock_send.return_value = (True, {'ok': True})
    rental = _make_rental(customer=debtor, product=product, user=admin_user,
                          due_offset_days=-3)
    rental.status = Rental.Status.CLOSED
    rental.save(update_fields=['status'])
    call_command('notify_debtors', stdout=StringIO())
    assert mock_send.call_count == 0
