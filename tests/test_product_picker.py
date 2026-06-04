"""Тесты typeahead-поиска товара в форме создания аренды."""
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from config.models import Category, Product


@pytest.fixture
def client_staff(staff_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='alice', password='pwpwpwpw')
    return c


@pytest.fixture
def cat(db):
    return Category.objects.get_or_create(name='Тест')[0]


@pytest.fixture
def kolonna(cat):
    return Product.objects.create(
        name='Колонна 3.0м', category=cat, unit='шт',
        stock_total=10, daily_price=Decimal('120.00'),
        deposit_per_unit=Decimal('0.00'),
    )


@pytest.fixture
def lesa(cat):
    return Product.objects.create(
        name='Леса рамные', category=cat, unit='шт',
        stock_total=20, daily_price=Decimal('80.00'),
        deposit_per_unit=Decimal('0.00'),
    )


@pytest.fixture
def archived(cat):
    return Product.objects.create(
        name='Старый товар', category=cat, unit='шт',
        stock_total=0, daily_price=Decimal('0.00'),
        deposit_per_unit=Decimal('0.00'),
        is_active=False,
    )


# ---------- search ----------

def test_search_too_short_returns_hint(client_staff, kolonna):
    url = reverse('rental_item_product_search') + '?item_product_q=К&row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'минимум 2 символа' in body
    # И никаких товаров.
    assert 'Колонна' not in body


def test_search_finds_by_name_substring(client_staff, kolonna, lesa):
    url = reverse('rental_item_product_search') + '?item_product_q=Кол&row_id=abc123'
    r = client_staff.get(url)
    body = r.content.decode()
    assert 'Колонна 3.0м' in body
    assert 'Леса рамные' not in body


def test_search_excludes_archived_products(client_staff, archived):
    url = reverse('rental_item_product_search') + '?item_product_q=Стар&row_id=abc123'
    r = client_staff.get(url)
    assert 'Старый товар' not in r.content.decode()


def test_search_empty_query_returns_nothing(client_staff, kolonna):
    """Пустой запрос — список пустой (как у customer)."""
    url = reverse('rental_item_product_search') + '?item_product_q=&row_id=abc123'
    r = client_staff.get(url)
    assert 'Колонна' not in r.content.decode()


def test_search_renders_target_with_row_id(client_staff, kolonna):
    """hx-target в результатах должен указывать на правильный picker-{row_id}."""
    url = reverse('rental_item_product_search') + '?item_product_q=Кол&row_id=abc123'
    r = client_staff.get(url)
    body = r.content.decode()
    assert 'picker-abc123' in body


def test_search_rejects_unsafe_row_id(client_staff, kolonna):
    """row_id с подозрительными символами — обнуляется (не вставляется в HTML).
    Защита от XSS через hx-target."""
    url = reverse('rental_item_product_search') + \
        '?item_product_q=Кол&row_id=<script>alert(1)</script>'
    r = client_staff.get(url)
    body = r.content.decode()
    assert '<script>' not in body
    # picker- встречается, но без значения.
    assert 'picker-#' not in body


# ---------- pick ----------

def test_pick_returns_picked_html_with_hidden_input(client_staff, kolonna):
    url = reverse('rental_item_product_pick', args=[kolonna.pk]) + '?row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'Колонна 3.0м' in body
    # Скрытое поле со значением товара и data-price для JS-расчёта.
    assert f'value="{kolonna.pk}"' in body
    assert 'data-price="120.00"' in body
    assert 'name="item_product"' in body


def test_pick_404_for_unknown_product(client_staff):
    url = reverse('rental_item_product_pick', args=[999999]) + '?row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 404


def test_pick_404_for_archived(client_staff, archived):
    url = reverse('rental_item_product_pick', args=[archived.pk]) + '?row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 404


# ---------- clear ----------

def test_clear_returns_search_input(client_staff):
    url = reverse('rental_item_product_clear') + '?row_id=abc123'
    r = client_staff.get(url)
    assert r.status_code == 200
    body = r.content.decode()
    assert 'item_product_q' in body
    # Скрытый input остаётся, но с пустым value — иначе getlist уедет.
    assert 'name="item_product"' in body
    assert 'value=""' in body


# ---------- auth ----------

def test_search_requires_auth(client, kolonna):
    url = reverse('rental_item_product_search') + '?item_product_q=Кол&row_id=abc'
    r = client.get(url)
    assert r.status_code in (302, 403)


# ---------- end-to-end через форму создания ----------

def test_create_form_renders_search_input_not_select(client_staff, kolonna):
    """В шаблоне новой аренды должен быть search-input, а не <select> со всеми
    товарами (старый UX)."""
    r = client_staff.get(reverse('rental_create'))
    body = r.content.decode()
    assert 'name="item_product_q"' in body
    # Если бы остался старый select — был бы option со значением товара.
    # Проверяем, что массивного дропдауна нет.
    assert '<option value="' not in body or 'item_product' not in body


# ---------- field_name parametrisation (модалка «Добавить позицию») ----------

def test_search_forwards_field_name(client_staff, kolonna):
    """Скрытый input в search-партиале должен иметь имя из field_name."""
    url = (reverse('rental_item_product_search')
           + '?item_product_q=&row_id=modal&field_name=product')
    r = client_staff.get(url)
    # Search-результаты не содержат hidden input — они только список.
    # Но clear возвращает search-input, проверяем там.
    url2 = reverse('rental_item_product_clear') + '?row_id=modal&field_name=product'
    r2 = client_staff.get(url2)
    body = r2.content.decode()
    assert 'name="product"' in body
    assert 'name="item_product"' not in body


def test_pick_uses_field_name(client_staff, kolonna):
    url = (reverse('rental_item_product_pick', args=[kolonna.pk])
           + '?row_id=modal&field_name=product')
    r = client_staff.get(url)
    body = r.content.decode()
    assert 'name="product"' in body
    assert f'value="{kolonna.pk}"' in body


def test_safe_field_name_rejects_garbage(client_staff, kolonna):
    """Невалидное field_name должно откатываться на дефолт, не вставляться
    в HTML «как есть» (защита от инъекции атрибута)."""
    url = (reverse('rental_item_product_pick', args=[kolonna.pk])
           + '?row_id=modal&field_name=" onfocus="alert(1)')
    r = client_staff.get(url)
    body = r.content.decode()
    assert 'onfocus' not in body
    # fallback — дефолтное имя.
    assert 'name="item_product"' in body


def test_safe_row_id_accepts_modal_literal(client_staff, kolonna):
    """row_id='modal' (не hex) теперь разрешён — нужно для модалки."""
    url = (reverse('rental_item_product_pick', args=[kolonna.pk])
           + '?row_id=modal&field_name=product')
    r = client_staff.get(url)
    body = r.content.decode()
    assert 'id="picker-modal"' in body


# ---------- модалка «Добавить позицию» ----------

@pytest.fixture
def client_admin(admin_user):
    c = Client(SERVER_NAME='localhost')
    c.login(username='bob', password='pwpwpwpw')
    return c


@pytest.fixture
def rental_for_admin(db, customer, admin_user):
    from datetime import timedelta
    from django.utils import timezone
    from config.models import Rental
    return Rental.objects.create(
        customer=customer,
        due_date=timezone.now() + timedelta(days=5),
        created_by=admin_user,
    )


def test_add_item_modal_uses_picker_not_select(client_admin, rental_for_admin,
                                               kolonna, lesa):
    url = reverse('rental_item_add', args=[rental_for_admin.pk])
    r = client_admin.get(url, HTTP_HX_REQUEST='true')
    body = r.content.decode()
    # search-вход вместо большого select.
    assert 'name="item_product_q"' in body
    # Сами товары не должны висеть статично в DOM.
    assert 'Колонна 3.0м' not in body
    assert 'Леса рамные' not in body
    # И поле должно называться `product` для бэкенда.
    assert 'name="product"' in body
