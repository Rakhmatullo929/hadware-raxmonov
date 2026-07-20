"""Тесты чека возврата: контекст, HTML-страница, авто-триггер."""
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Rental, RentalItem
from config.views import _parse_movement_ids, build_return_receipt_context


def test_parse_movement_ids_drops_invalid():
    assert _parse_movement_ids('1,2,x,3,') == [1, 2, 3]
    assert _parse_movement_ids('') == []
    assert _parse_movement_ids(None) == []


def test_build_context_totals(rental_with_returns, product):
    r, item, m1, m2 = rental_with_returns
    ctx = build_return_receipt_context(r, [m1.id, m2.id])
    assert len(ctx['rows']) == 2
    assert ctx['total_qty'] == 7
    assert ctx['total_amount'] == Decimal('700.00')
    assert ctx['rows'][0]['name'] == product.name
    assert str(ctx['rows'][0]['category']) == str(product.category)
    assert ctx['customer'] == r.customer
    assert ctx['receipt_dt'] is not None


def test_build_context_exposes_days(rental_with_multiday_return):
    """Строка чека несёт число дней аренды (unit_days / qty), чтобы
    Кол-во × За день × Дней = Стоимость сходилось на глазах у клиента."""
    r, item, m = rental_with_multiday_return
    ctx = build_return_receipt_context(r, [m.id])
    row = ctx['rows'][0]
    assert row['qty'] == 16
    assert row['days'] == 6
    assert row['price_per_day'] == Decimal('100.00')
    assert row['amount'] == Decimal('9600.00')
    # Разбивка сходится: 16 × 100 × 6 == 9600.
    assert row['qty'] * row['price_per_day'] * row['days'] == row['amount']


def test_receipt_html_shows_days_column(client_staff, rental_with_multiday_return):
    r, item, m = rental_with_multiday_return
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m.id}'
    body = client_staff.get(url).content.decode()
    assert 'Дней' in body      # заголовок новой колонки
    assert '9600.00' in body   # стоимость с учётом дней


def test_build_context_ignores_foreign_movements(
    rental_with_returns, customer, product, staff_user,
):
    r, item, m1, m2 = rental_with_returns
    other = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    oitem = RentalItem.objects.create(
        rental=other, product=product, qty=2, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.ISSUE, qty=2,
        created_by=staff_user,
    )
    om = Movement.objects.create(
        rental_item=oitem, kind=Movement.Kind.RETURN, qty=2,
        amount=Decimal('200.00'), created_by=staff_user,
    )
    # om принадлежит другой аренде — должен быть отброшен.
    ctx = build_return_receipt_context(r, [m1.id, om.id])
    assert len(ctx['rows']) == 1
    assert ctx['rows'][0]['qty'] == 4


def test_receipt_html_renders(client_staff, rental_with_returns, product):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id},{m2.id}'
    resp = client_staff.get(url)
    assert resp.status_code == 200
    body = resp.content.decode()
    assert 'ЧЕК ВОЗВРАТА' in body
    assert r.customer.full_name in body
    assert product.name in body
    assert 'Тип товара' in body
    assert '700.00' in body               # итоговая сумма
    assert 'print-page--quarter' in body  # размер по умолчанию
    assert 'return-receipt.pdf' in body   # ссылка «Скачать PDF»


def test_receipt_html_autoprint_flag(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    base = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
    assert 'data-autoprint' in client_staff.get(base + '&autoprint=1').content.decode()
    assert 'data-autoprint' not in client_staff.get(base).content.decode()


def test_receipt_html_404_when_no_valid_ids(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + '?m=999999'
    assert client_staff.get(url).status_code == 404


def test_receipt_html_requires_auth(client, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
    assert client.get(url).status_code in (302, 403)


def test_return_post_emits_open_receipt_trigger(
    client_admin, customer, product, admin_user,
):
    rental = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=admin_user,
    )
    item = RentalItem.objects.create(
        rental=rental, product=product, qty=5, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=5, created_by=admin_user,
    )

    resp = client_admin.post(f'/rentals/{rental.pk}/return/', data={
        f'qty_{item.pk}': '2',
    }, HTTP_HX_REQUEST='true')
    assert resp.status_code == 200
    assert 'HX-Trigger' in resp

    payload = json.loads(resp['HX-Trigger'])
    assert 'openReturnReceipt' in payload
    url = payload['openReturnReceipt']['url']
    ret = Movement.objects.get(rental_item=item, kind=Movement.Kind.RETURN)
    assert f'm={ret.id}' in url
    assert 'autoprint=1' in url
    assert str(rental.pk) in url


def test_return_receipt_js_asset_exists():
    from pathlib import Path

    from django.conf import settings

    p = Path(settings.BASE_DIR) / 'static' / 'js' / 'return-receipt.js'
    assert p.is_file(), 'static/js/return-receipt.js отсутствует'
    content = p.read_text(encoding='utf-8')
    assert 'openReturnReceipt' in content
    assert 'window.open' in content


def test_base_includes_return_receipt_js(client_staff, rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    resp = client_staff.get(f'/rentals/{r.pk}/')
    assert resp.status_code == 200
    assert 'js/return-receipt.js' in resp.content.decode()


def test_receipt_uz_translation(client_staff, rental_with_returns):
    # i18n_patterns(prefix_default_language=False): ru без префикса, uz — через
    # /uz/. reverse под uz-локалью даёт /uz/...-URL, который LocaleMiddleware
    # распознаёт и отдаёт чек по-узбекски. Запрос делаем внутри override, чтобы
    # активный язык потока вернулся к дефолту и не «протёк» в следующие тесты
    # (их reverse() иначе начал бы генерить /uz/-URL).
    from django.utils import translation

    r, item, m1, m2 = rental_with_returns
    with translation.override('uz'):
        url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m1.id}'
        assert url.startswith('/uz/')
        body = client_staff.get(url).content.decode()
    assert 'Tovar turi' in body   # узбекский заголовок «Тип товара»
    assert 'Qaytarish' in body    # узбекский «возврат» (Qaytarish cheki)


def test_build_context_scales_kit_totals(rental_with_kit_return):
    r, item, m = rental_with_kit_return
    ctx = build_return_receipt_context(r, [m.id])
    kit = ctx['rows'][0]['kit']
    assert [(k['name'], k['qty']) for k in kit] == [
        ('Зажим', 36), ('Фиксатор', 36), ('Тайрод р/калпокча', 36), ('Штир/шайба', 36),
    ]


def test_build_context_kit_empty_for_plain_product(rental_with_returns):
    r, item, m1, m2 = rental_with_returns
    ctx = build_return_receipt_context(r, [m1.id, m2.id])
    assert ctx['rows'][0]['kit'] == []


def test_receipt_html_omits_kit_line(client_staff, rental_with_kit_return):
    """Строка «Доп.» с составом комплекта убрана из чека — позиции компактнее."""
    r, item, m = rental_with_kit_return
    url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m.id}'
    body = client_staff.get(url).content.decode()
    assert 'Корейская опалубка' in body   # сама позиция на месте
    assert 'Зажим' not in body            # состав комплекта не выводится


def test_receipt_html_omits_kit_label_uz(client_staff, rental_with_kit_return):
    """И в UZ-локали строки «Доп.» больше нет."""
    from django.utils import translation

    r, item, m = rental_with_kit_return
    with translation.override('uz'):
        url = reverse('rental_return_receipt', args=[r.pk]) + f'?m={m.id}'
        body = client_staff.get(url).content.decode()
    assert "Qo'shimcha" not in body   # узбекский ярлык «Доп.» тоже убран
    assert 'Зажим' not in body
