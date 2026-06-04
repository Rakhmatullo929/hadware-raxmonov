"""Тесты раздела «Зарплата сотрудников»."""
from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Attendance, SalaryEntry, Worker
from config.views import (
    _compute_payroll, _quantize_money, _working_days_in_month,
)


@pytest.fixture
def worker(db):
    return Worker.objects.create(
        full_name='Иван Зарплатный', position='Кладовщик',
        monthly_salary=Decimal('3000000.00'),
    )


@pytest.fixture
def inactive_worker(db):
    return Worker.objects.create(
        full_name='Уволенный Сотрудник', monthly_salary=Decimal('1000000.00'),
        is_active=False,
    )


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


# ---------- pure helpers ----------

def test_quantize_money_rounds_half_up():
    # Деньги округляем «вверх с половины» (ROUND_HALF_UP), а не банковским
    # ROUND_HALF_EVEN — иначе зарплата расходится с ручным расчётом на копейку.
    assert _quantize_money(Decimal('500.025')) == Decimal('500.03')
    assert _quantize_money(Decimal('1.005')) == Decimal('1.01')


def test_working_days_known_month():
    # Июнь 2026: 30 дней. Считаем будни (Пн–Пт).
    # 01.06.2026 — понедельник.
    assert _working_days_in_month(2026, 6) == 22


def test_compute_payroll_pro_rates_by_attendance(db, worker):
    # 22 рабочих дня в июне 2026, отметим 11 присутствий → база = 50% оклада.
    base_date = date(2026, 6, 1)
    weekdays = [
        base_date.replace(day=d)
        for d in range(1, 31)
        if base_date.replace(day=d).weekday() < 5
    ][:11]
    Attendance.objects.bulk_create([
        Attendance(worker=worker, date=d, is_present=True) for d in weekdays
    ])
    payroll = _compute_payroll(worker, 2026, 6)
    assert payroll['present_days'] == 11
    assert payroll['working_days'] == 22
    assert payroll['base'] == Decimal('1500000.00')
    assert payroll['total'] == Decimal('1500000.00')


def test_compute_payroll_ignores_weekend_attendance(db, worker):
    # Июнь 2026: 22 будних дня. Отмечаем присутствие во все 22 будних дня
    # ПЛЮС 2 субботы. Выходные не входят в рабочие дни, по которым считается
    # пропорция, поэтому база не должна превышать полный оклад.
    base_date = date(2026, 6, 1)
    all_days = [base_date.replace(day=i) for i in range(1, 31)]
    weekdays = [d for d in all_days if d.weekday() < 5]
    saturdays = [d for d in all_days if d.weekday() == 5][:2]
    Attendance.objects.bulk_create([
        Attendance(worker=worker, date=d, is_present=True)
        for d in weekdays + saturdays
    ])
    payroll = _compute_payroll(worker, 2026, 6)
    assert payroll['present_days'] == 22          # только будни
    assert payroll['working_days'] == 22
    assert payroll['base'] == Decimal('3000000.00')  # ровно полный оклад
    assert payroll['absent_days'] == 0


def test_compute_payroll_applies_bonus_and_penalty(db, worker):
    SalaryEntry.objects.create(
        worker=worker, year=2026, month=6, kind=SalaryEntry.Kind.BONUS,
        amount=Decimal('200000.00'), reason='хорошо',
    )
    SalaryEntry.objects.create(
        worker=worker, year=2026, month=6, kind=SalaryEntry.Kind.PENALTY,
        amount=Decimal('50000.00'), reason='опоздание',
    )
    payroll = _compute_payroll(worker, 2026, 6)
    # Без явки база = 0, итого = 0 + 200к − 50к = 150к
    assert payroll['base'] == Decimal('0.00')
    assert payroll['bonuses'] == Decimal('200000.00')
    assert payroll['penalties'] == Decimal('50000.00')
    assert payroll['total'] == Decimal('150000.00')


def test_compute_payroll_keeps_negative_total_as_debt(db, worker):
    # Без явки база = 0; штраф больше премий → итог отрицательный. По решению
    # продукта НЕ клампим к нулю: показываем честный минус (работник должен).
    SalaryEntry.objects.create(
        worker=worker, year=2026, month=6, kind=SalaryEntry.Kind.PENALTY,
        amount=Decimal('50000.00'), reason='ущерб',
    )
    payroll = _compute_payroll(worker, 2026, 6)
    assert payroll['base'] == Decimal('0.00')
    assert payroll['total'] == Decimal('-50000.00')


# ---------- views ----------

def test_index_renders_for_admin(client_admin, worker):
    r = client_admin.get(reverse('salary_index') + '?month=2026-06')
    assert r.status_code == 200
    assert 'Иван Зарплатный' in r.content.decode()


def test_index_denies_staff(client_staff, worker):
    # Раздел зарплат — только для админов; staff получает отказ.
    r = client_staff.get(reverse('salary_index') + '?month=2026-06')
    assert r.status_code in (302, 403)


def test_index_redirects_anon(db):
    c = Client(SERVER_NAME='localhost')
    r = c.get(reverse('salary_index'))
    assert r.status_code in (302, 403)


def test_add_bonus_via_htmx(client_admin, worker):
    url = reverse('salary_entry_create', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {
        'kind': 'bonus',
        'amount': '40 000',  # с пробелом — проверяем strip
        'reason': 'тест',
    })
    assert r.status_code == 200
    e = SalaryEntry.objects.get(worker=worker, year=2026, month=6)
    assert e.kind == SalaryEntry.Kind.BONUS
    assert e.amount == Decimal('40000.00')
    assert e.reason == 'тест'
    assert e.created_by_id is not None


def test_add_entry_rejects_zero_amount(client_admin, worker):
    url = reverse('salary_entry_create', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'kind': 'bonus', 'amount': '0', 'reason': ''})
    assert r.status_code == 200  # форма возвращается с ошибкой
    assert not SalaryEntry.objects.filter(worker=worker).exists()


def test_base_update_requires_admin(client_staff, worker):
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_staff.post(url, {'monthly_salary': '5000000'})
    # staff не админ → 403/PermissionDenied
    assert r.status_code in (302, 403)
    worker.refresh_from_db()
    assert worker.monthly_salary == Decimal('3000000.00')


def test_base_update_admin_persists(client_admin, worker):
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'monthly_salary': '5 000 000'})
    assert r.status_code == 200
    # Оклад за июнь зафиксирован снимком (пробельный ввод тоже принимается).
    assert _compute_payroll(worker, 2026, 6)['monthly_salary'] \
        == Decimal('5000000.00')


def test_base_update_is_per_month_snapshot(client_admin, worker):
    # Контрактный оклад 3M. Правим оклад ТОЛЬКО за июнь → 5M.
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'monthly_salary': '5 000 000'})
    assert r.status_code == 200
    # Июнь использует снимок 5M…
    assert _compute_payroll(worker, 2026, 6)['monthly_salary'] \
        == Decimal('5000000.00')
    # …а другой месяц (май) НЕ изменился — остаётся контрактный 3M.
    assert _compute_payroll(worker, 2026, 5)['monthly_salary'] \
        == Decimal('3000000.00')
    # Глобальный Worker.monthly_salary не переписан задним числом.
    worker.refresh_from_db()
    assert worker.monthly_salary == Decimal('3000000.00')


def test_base_update_rejects_too_many_digits(client_admin, worker):
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'monthly_salary': '99999999999999'})  # 14 цифр
    assert r.status_code == 400
    assert _compute_payroll(worker, 2026, 6)['monthly_salary'] \
        == Decimal('3000000.00')


def test_base_update_rejects_negative(client_admin, worker):
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'monthly_salary': '-100'})
    assert r.status_code == 400


def test_base_update_rejects_get(client_admin, worker):
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    assert client_admin.get(url).status_code == 405


def test_delete_entry_denies_staff_allows_admin(client_admin, client_staff,
                                                worker, admin_user):
    e = SalaryEntry.objects.create(
        worker=worker, year=2026, month=6, kind=SalaryEntry.Kind.BONUS,
        amount=Decimal('10000.00'), reason='', created_by=admin_user,
    )
    # staff не имеет доступа к разделу зарплат — удалить не может
    url = reverse('salary_entry_delete', args=[e.pk]) + '?month=2026-06'
    r = client_staff.post(url)
    assert r.status_code in (302, 403)
    assert SalaryEntry.objects.filter(pk=e.pk).exists()
    # админ может
    r = client_admin.post(url)
    assert r.status_code == 200
    assert not SalaryEntry.objects.filter(pk=e.pk).exists()


def test_worker_detail_batches_queries(client_admin, worker,
                                       django_assert_max_num_queries):
    # 36 месяцев не должны порождать N+1 (раньше — ~2 запроса на каждый месяц).
    with django_assert_max_num_queries(12):
        r = client_admin.get(
            reverse('salary_worker_detail', args=[worker.pk]) + '?months=36')
    assert r.status_code == 200


def test_worker_detail_aggregates(client_admin, worker):
    SalaryEntry.objects.create(
        worker=worker, year=2026, month=6,
        kind=SalaryEntry.Kind.BONUS, amount=Decimal('100000.00'),
    )
    SalaryEntry.objects.create(
        worker=worker, year=2026, month=5,
        kind=SalaryEntry.Kind.PENALTY, amount=Decimal('30000.00'),
    )
    r = client_admin.get(reverse('salary_worker_detail', args=[worker.pk])
                         + '?months=12')
    assert r.status_code == 200
    body = r.content.decode()
    assert 'Иван Зарплатный' in body
    # Без явки база = 0: премии 100000, штрафы 30000, итого 100000−30000=70000.
    # Локаль ru → десятичный разделитель запятая.
    assert '100000,00' in body          # сумма премий за период
    assert '30000,00' in body           # сумма штрафов за период
    assert '70000,00' in body           # итог за период (минус как долг)


# ---------- дополнительное покрытие ----------

def test_entries_modal_get_renders_form(client_admin, worker):
    url = reverse('salary_entries_modal', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'Добавить премию или штраф' in body  # форма добавления присутствует
    assert 'entries/add' in body                # action формы


def test_index_shows_editable_salary_for_admin(client_admin, worker):
    # Редактор оклада (money-input editable-salary) виден админу — гейт по
    # is_admin не должен «отвалиться» в htmx-фрагменте строки.
    r = client_admin.get(reverse('salary_index') + '?month=2026-06')
    assert r.status_code == 200
    body = r.content.decode()
    assert 'editable-salary' in body
    assert 'base/' in body  # форма правки оклада постит на salary_base_update


def test_base_update_response_has_editable_salary(client_admin, worker):
    # Ответ htmx после правки оклада — это _row.html; редактор должен остаться.
    url = reverse('salary_base_update', args=[worker.pk]) + '?month=2026-06'
    r = client_admin.post(url, {'monthly_salary': '4 000 000'})
    assert r.status_code == 200
    assert 'editable-salary' in r.content.decode()


def test_entry_create_rejects_get(client_admin, worker):
    url = reverse('salary_entry_create', args=[worker.pk]) + '?month=2026-06'
    assert client_admin.get(url).status_code == 405


def test_entry_delete_rejects_get(client_admin, worker):
    e = SalaryEntry.objects.create(
        worker=worker, year=2026, month=6, kind=SalaryEntry.Kind.BONUS,
        amount=Decimal('1000.00'),
    )
    url = reverse('salary_entry_delete', args=[e.pk]) + '?month=2026-06'
    assert client_admin.get(url).status_code == 405


@pytest.mark.parametrize('view_name,kwargs', [
    ('salary_entries_modal', {}),
    ('salary_worker_detail', {}),
])
def test_inactive_worker_is_404(client_admin, inactive_worker, view_name, kwargs):
    url = reverse(view_name, args=[inactive_worker.pk]) + '?month=2026-06'
    assert client_admin.get(url).status_code == 404


def test_base_update_inactive_worker_is_404(client_admin, inactive_worker):
    url = reverse('salary_base_update', args=[inactive_worker.pk]) + '?month=2026-06'
    assert client_admin.post(url, {'monthly_salary': '100'}).status_code == 404


def test_compute_payroll_rounds_fractional_cent(db, worker):
    # 1000.05 × 1/2 = 500.025 → ROUND_HALF_UP → 500.03 (а не банковское .02).
    payroll = _compute_payroll(
        worker, 2026, 6, present_days=1, working_days=2, entries=[],
        monthly_base=Decimal('1000.05'),
    )
    assert payroll['base'] == Decimal('500.03')


def test_compute_payroll_zero_working_days(db, worker):
    # Защитная ветка: рабочих дней 0 → база 0 (без деления на ноль).
    payroll = _compute_payroll(
        worker, 2026, 6, present_days=0, working_days=0, entries=[],
        monthly_base=Decimal('3000.00'),
    )
    assert payroll['base'] == Decimal('0.00')
