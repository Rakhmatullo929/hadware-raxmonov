"""Детальная страница клиента: аренды — аккордеон с ленивой карточкой."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from config.models import Movement, Payment, Rental, RentalItem


@pytest.fixture
def rental_for_customer(db, customer, product, staff_user):
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    item = RentalItem.objects.create(
        rental=r, product=product, qty=7, price_per_day=product.daily_price,
    )
    Movement.objects.create(
        rental_item=item, kind=Movement.Kind.ISSUE, qty=7, created_by=staff_user,
    )
    Payment.objects.create(
        rental=r, amount=Decimal('500.00'), kind=Payment.Kind.DEPOSIT,
    )
    return r, item


def test_customer_detail_links_to_rental(client_staff, customer, rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    body = resp.content.decode()
    # Кнопка «Открыть» ведёт на полную страницу аренды.
    assert reverse('rental_detail', args=[r.pk]) in body
    assert f'#{r.id}' in body


def test_customer_detail_shows_rental_summary(client_staff, customer,
                                              rental_for_customer):
    r, item = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Свёрнутый заголовок показывает позицию и залог.
    assert item.product.name in body
    assert '×7' in body
    assert '/ 500' in body
    rentals = list(resp.context['rentals'])
    assert rentals[0].outstanding_total == 7
    assert rentals[0].deposit_total == Decimal('500.00')


def test_customer_detail_accordion_wiring(client_staff, customer,
                                          rental_for_customer):
    r, _ = rental_for_customer
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    body = resp.content.decode()
    # Строка-заголовок раскрывает карточку через rental_card в свой контейнер.
    assert f'data-card-url="{reverse("rental_card", args=[r.pk])}"' in body
    assert f'id="crow-{r.id}"' in body
    assert f'id="rbody-{r.id}"' in body
    assert 'rental-acc-header' in body


def test_customer_detail_no_rentals(client_staff, customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert resp.status_code == 200
    assert 'Аренд пока нет' in resp.content.decode()


def test_customer_detail_includes_accordion_js(client_staff, customer,
                                                rental_for_customer):
    resp = client_staff.get(reverse('customer_detail', args=[customer.pk]))
    assert 'js/customer-rentals.js' in resp.content.decode()


def test_rental_history_line_is_bounded(client_staff, customer, category,
                                        staff_user):
    """Список товаров в строке аренды ограничен 6 позициями + «ещё K» —
    вёрстка не ломается даже на сотнях позиций (баг с overflow)."""
    from config.models import Product
    r = Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=staff_user,
    )
    for i in range(9):                      # 9 разных товаров, по 1 позиции
        p = Product.objects.create(
            name=f'УникТовар{i:02d}', category=category, unit='шт',
            daily_price=Decimal('10.00'),
        )
        item = RentalItem.objects.create(
            rental=r, product=p, qty=1, price_per_day=p.daily_price,
        )
        Movement.objects.create(
            rental_item=item, kind=Movement.Kind.ISSUE, qty=1,
            created_by=staff_user,
        )

    body = client_staff.get(
        reverse('customer_detail', args=[customer.pk])
    ).content.decode()
    assert 'ещё 3' in body                  # 9 − 6 = 3 в остатке
    assert 'УникТовар00' in body            # первый показан
    assert 'УникТовар08' not in body        # 9-й (за пределом 6) не рендерится
    # Комментарий шаблона не должен просачиваться в вывод (был баг: многострочный
    # {# #} не является комментарием в Django и рендерился как текст).
    assert 'CSS-обрезки' not in body
    assert 'Показываем не более' not in body
    assert '{#' not in body and '{%' not in body

