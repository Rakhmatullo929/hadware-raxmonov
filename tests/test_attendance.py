"""Тесты журнала посещаемости рабочих."""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from config.models import Attendance, Worker


@pytest.fixture
def worker(db):
    return Worker.objects.create(full_name='Иван Иванов', position='Монтажник')


@pytest.fixture
def archived_worker(db):
    return Worker.objects.create(
        full_name='Архивный', position='—', is_active=False,
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


# ---------- journal page ----------

def test_journal_renders_today_by_default(client_staff, worker):
    r = client_staff.get(reverse('attendance_journal'))
    assert r.status_code == 200
    body = r.content.decode()
    assert worker.full_name in body
    assert timezone.localdate().isoformat() in body


def test_journal_lists_only_active_workers(client_staff, worker, archived_worker):
    r = client_staff.get(reverse('attendance_journal'))
    body = r.content.decode()
    assert worker.full_name in body
    assert archived_worker.full_name not in body


def test_journal_accepts_date_query(client_staff, worker):
    d = (timezone.localdate() - timedelta(days=3)).isoformat()
    r = client_staff.get(reverse('attendance_journal') + f'?date={d}')
    assert r.status_code == 200
    assert d.encode() in r.content


def test_journal_summary_counts(client_staff, worker, admin_user):
    other = Worker.objects.create(full_name='Второй')
    today = timezone.localdate()
    Attendance.objects.create(worker=worker, date=today, is_present=True,
                              marked_by=admin_user)
    Attendance.objects.create(worker=other, date=today, is_present=False,
                              marked_by=admin_user)
    r = client_staff.get(reverse('attendance_journal'))
    body = r.content.decode()
    # 1 присутствует, 1 отсутствует, 0 не отмечены (т.к. оба отмечены).
    # Просто проверяем что показатели присутствия в DOM.
    assert 'Присутствуют' in body
    assert 'Отсутствуют' in body


# ---------- toggle endpoint ----------

def test_toggle_creates_present(client_staff, worker):
    today = timezone.localdate().isoformat()
    url = reverse('attendance_toggle', args=[worker.pk]) + f'?date={today}'
    r = client_staff.post(url, {'status': 'present'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    a = Attendance.objects.get(worker=worker, date=timezone.localdate())
    assert a.is_present is True


def test_toggle_creates_absent(client_staff, worker):
    today = timezone.localdate().isoformat()
    url = reverse('attendance_toggle', args=[worker.pk]) + f'?date={today}'
    r = client_staff.post(url, {'status': 'absent'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    a = Attendance.objects.get(worker=worker, date=timezone.localdate())
    assert a.is_present is False


def test_toggle_overwrites_existing(client_staff, worker, admin_user):
    today = timezone.localdate()
    Attendance.objects.create(worker=worker, date=today, is_present=True,
                              marked_by=admin_user)
    url = reverse('attendance_toggle', args=[worker.pk]) + f'?date={today.isoformat()}'
    r = client_staff.post(url, {'status': 'absent'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert Attendance.objects.filter(worker=worker, date=today).count() == 1
    a = Attendance.objects.get(worker=worker, date=today)
    assert a.is_present is False


def test_toggle_clear_removes_record(client_staff, worker, admin_user):
    today = timezone.localdate()
    Attendance.objects.create(worker=worker, date=today, is_present=True,
                              marked_by=admin_user)
    url = reverse('attendance_toggle', args=[worker.pk]) + f'?date={today.isoformat()}'
    r = client_staff.post(url, {'status': 'clear'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert not Attendance.objects.filter(worker=worker, date=today).exists()


def test_toggle_rejects_bad_status(client_staff, worker):
    url = reverse('attendance_toggle', args=[worker.pk])
    r = client_staff.post(url, {'status': 'maybe'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 400


def test_toggle_requires_post(client_staff, worker):
    r = client_staff.get(reverse('attendance_toggle', args=[worker.pk]))
    assert r.status_code in (405, 302)


def test_toggle_404_for_archived(client_staff, archived_worker):
    url = reverse('attendance_toggle', args=[archived_worker.pk])
    r = client_staff.post(url, {'status': 'present'}, HTTP_HX_REQUEST='true')
    assert r.status_code == 404


def test_toggle_records_marker(client_admin, worker):
    url = reverse('attendance_toggle', args=[worker.pk])
    client_admin.post(url, {'status': 'present'}, HTTP_HX_REQUEST='true')
    a = Attendance.objects.get(worker=worker, date=timezone.localdate())
    assert a.marked_by is not None
    assert a.marked_by.username == 'bob'


# ---------- workers CRUD permissions ----------

def test_worker_list_visible_to_staff(client_staff, worker):
    r = client_staff.get(reverse('worker_list'))
    assert r.status_code == 200
    assert worker.full_name in r.content.decode()


def test_worker_create_admin_only(client_staff):
    r = client_staff.get(reverse('worker_create'))
    assert r.status_code in (302, 403)


def test_worker_create_works_for_admin(client_admin):
    r = client_admin.post(reverse('worker_create'), {
        'full_name': 'Новый рабочий',
        'position': 'Сварщик',
        'phone': '+998 90 000 00 00',
        'note': '',
        'is_active': 'on',
    })
    assert r.status_code in (200, 302)
    assert Worker.objects.filter(full_name='Новый рабочий').exists()


def test_worker_archive_toggle(client_admin, worker):
    assert worker.is_active is True
    client_admin.post(reverse('worker_toggle_active', args=[worker.pk]))
    worker.refresh_from_db()
    assert worker.is_active is False
    client_admin.post(reverse('worker_toggle_active', args=[worker.pk]))
    worker.refresh_from_db()
    assert worker.is_active is True


def test_worker_unique_attendance_per_day(db, worker):
    """Constraint: один (worker, date) — одна запись."""
    today = timezone.localdate()
    Attendance.objects.create(worker=worker, date=today, is_present=True)
    from django.db import IntegrityError
    with pytest.raises(IntegrityError):
        Attendance.objects.create(worker=worker, date=today, is_present=False)


# ---------- CSRF integration ----------

def test_journal_page_exposes_csrf_for_htmx(admin_user, worker):
    """Регресс-тест: hx-headers с X-CSRFToken должен попадать в HTML,
    иначе btn'ы +/− упадут с 403. Эту проблему словили в проде."""
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    r = c.get(reverse('attendance_journal'))
    body = r.content.decode()
    assert 'hx-headers' in body
    assert 'X-CSRFToken' in body


def test_toggle_works_with_csrf_enforced(admin_user, worker):
    """Полный путь: страница → CSRF token → POST с заголовком → 200."""
    c = Client(SERVER_NAME='localhost', enforce_csrf_checks=True)
    c.login(username='bob', password='pwpwpwpw')
    # 1) рендерим страницу — Django выставит csrftoken cookie
    page = c.get(reverse('attendance_journal'))
    assert page.status_code == 200
    token = c.cookies['csrftoken'].value

    # 2) POST с заголовком X-CSRFToken — как сделает htmx с hx-headers
    today = timezone.localdate().isoformat()
    url = reverse('attendance_toggle', args=[worker.pk]) + f'?date={today}'
    r = c.post(url, {'status': 'present'},
               HTTP_X_CSRFTOKEN=token,
               HTTP_HX_REQUEST='true')
    assert r.status_code == 200, f'CSRF не пропустил: {r.status_code}'
    assert Attendance.objects.filter(worker=worker).exists()
