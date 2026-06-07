"""Тесты MoneyDecimalField и money-input на формах.

Контракт: пользователь может ввести «40 000» (с пробелом, неразрывным,
тонким и т.д.) — бэкенд должен принять как 40000.
"""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from config.forms import MoneyDecimalField, PaymentForm, _strip_money_spaces
from config.models import Payment


def test_strip_handles_regular_space():
    assert _strip_money_spaces('40 000') == '40000'


def test_strip_handles_nbsp():
    assert _strip_money_spaces('40 000') == '40000'


def test_strip_handles_thin_space():
    assert _strip_money_spaces('40 000') == '40000'


def test_strip_handles_narrow_nbsp():
    assert _strip_money_spaces('40 000') == '40000'


def test_strip_handles_mixed_whitespace():
    assert _strip_money_spaces('  1 234 567 ') == '1234567'


def test_strip_keeps_decimal_point():
    assert _strip_money_spaces('40 000.50') == '40000.50'


def test_strip_normalizes_grouped_comma_decimal():
    # ru-локаль: «40 000,50» — корректная группировка с запятой-разделителем
    # дроби. Нормализуем запятую в точку, чтобы Decimal-парсер принял значение
    # и без JS (money-input.js делает то же на клиенте).
    assert _strip_money_spaces('40 000,50') == '40000.50'


def test_strip_normalizes_bare_comma_decimal():
    # «Голая» запятая-дробь без группировки тоже должна приниматься без JS.
    assert _strip_money_spaces('40000,50') == '40000.50'
    assert _strip_money_spaces('500,50') == '500.50'
    # Две запятые/уже есть точка — не трогаем (пусть валидация отвергнет).
    assert _strip_money_spaces('1,2,3') == '1,2,3'


def test_strip_rejects_irregular_grouping():
    # Кривая группировка не должна молча «склеиваться» в число другого
    # порядка — оставляем пробелы, чтобы Decimal-валидация её отвергла.
    out = _strip_money_spaces('40 00 0 5')
    assert out == '40 00 0 5'  # не '400005'


def test_strip_passthrough_for_none():
    assert _strip_money_spaces(None) is None


def test_strip_passthrough_for_decimal_value():
    assert _strip_money_spaces(Decimal('100')) == Decimal('100')


# ---------- field ----------

def test_money_field_parses_spaced_value():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    assert f.to_python('40 000') == Decimal('40000')


def test_money_field_parses_nbsp_value():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    assert f.to_python('40 000') == Decimal('40000')


def test_money_field_handles_decimals():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    assert f.to_python('40 000.50') == Decimal('40000.50')


def test_money_field_still_rejects_garbage():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        f.clean('abc')


def test_money_field_accepts_grouped_comma_decimal():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    assert f.to_python('40 000,50') == Decimal('40000.50')


def test_money_field_rejects_irregular_grouping():
    f = MoneyDecimalField(max_digits=12, decimal_places=2)
    from django.core.exceptions import ValidationError
    with pytest.raises(ValidationError):
        f.clean('40 00 0 5')


# ---------- max_digits enforced on the salary forms ----------

def test_worker_form_rejects_too_many_digits(db):
    from config.forms import WorkerForm
    form = WorkerForm(data={
        'full_name': 'X', 'monthly_salary': '99999999999999',  # 14 цифр
        'is_active': True,
    })
    assert not form.is_valid()
    assert 'monthly_salary' in form.errors


def test_salary_entry_form_rejects_too_many_digits(db):
    from config.forms import SalaryEntryForm
    form = SalaryEntryForm(data={
        'kind': 'bonus', 'amount': '99999999999999', 'reason': '',
    })
    assert not form.is_valid()
    assert 'amount' in form.errors


# ---------- end-to-end ----------

def test_payment_form_accepts_spaced_amount(db):
    """Pure-Python form validation работает с пробельным вводом."""
    form = PaymentForm(data={
        'kind': Payment.Kind.RENT,
        'method': Payment.Method.CASH,
        'amount': '40 000',
        'note': '',
    })
    assert form.is_valid(), form.errors
    assert form.cleaned_data['amount'] == Decimal('40000')


def test_payment_form_accepts_nbsp_amount(db):
    form = PaymentForm(data={
        'kind': Payment.Kind.RENT,
        'method': Payment.Method.CASH,
        'amount': '1 234 567',
        'note': '',
    })
    assert form.is_valid(), form.errors
    assert form.cleaned_data['amount'] == Decimal('1234567')


@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def rental(db, customer, admin_user):
    from datetime import timedelta
    from django.utils import timezone
    from config.models import Rental
    return Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=admin_user,
    )


def test_payment_add_view_accepts_spaced_amount(client_admin, rental):
    """E2E через ручку добавления платежа."""
    url = reverse('rental_payment_add', args=[rental.pk])
    r = client_admin.post(url, {
        'kind': Payment.Kind.RENT,
        'method': Payment.Method.CASH,
        'amount': '40 000',
        'note': '',
    }, HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    p = rental.payments.get()
    assert p.amount == Decimal('40000')


def test_money_input_js_configrequest_is_scoped_to_money_fields():
    """Регресс-страж: htmx:configRequest НЕ должен вырезать пробелы из
    произвольных параметров — только из полей money-input (по их name).
    Иначе телефоны/причины/числовые строки молча портятся."""
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent
          / 'static' / 'js' / 'money-input.js').read_text(encoding='utf-8')
    # Старый «широкий» паттерн по любому значению должен исчезнуть.
    assert r'/^[\d\s.,\-]+$/' not in js
    # Обработчик должен опираться на класс money-input и e.detail.elt.
    assert 'configRequest' in js
    assert "input.money-input" in js
    assert 'e.detail' in js or 'detail.elt' in js


def test_create_form_renders_money_input_widget(client_admin):
    """В шаблоне новой аренды поле «Начальный платёж» должно быть
    text + money-input, не number — иначе пробелы будут отвергнуты браузером."""
    r = client_admin.get(reverse('rental_create'))
    body = r.content.decode()
    assert 'money-input' in body
    # Поле НЕ должно быть type="number" — иначе браузер не разрешит пробелы.
    assert 'name="initial_deposit"' in body
    # type="text" + inputmode для мобильных.
    assert 'inputmode="decimal"' in body
