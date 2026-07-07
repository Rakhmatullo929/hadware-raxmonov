"""Тесты быстрого создания категории кнопкой «+» в форме товара.

Полная страница (ссылка «Категория» в списке товаров) должна работать
как раньше — редиректом в список. htmx-путь — модалка и OOB-подстановка
новой категории в select без сброса формы товара.
"""
import pytest
from django.urls import reverse

from config.models import Category


# ---------- интеграция с формой товара ----------

def test_product_form_has_category_button_and_modal_slot(client_admin):
    r = client_admin.get(reverse('product_create'))
    assert r.status_code == 200
    body = r.content.decode()
    assert 'id="modal-slot"' in body
    assert 'id="product-category-field"' in body
    # Кнопка «+» открывает модалку создания категории.
    assert reverse('category_create') in body


# ---------- GET (открыть модалку) ----------

def test_htmx_get_opens_modal(client_admin):
    r = client_admin.get(reverse('category_create'), HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    body = r.content.decode()
    assert 'Новая категория' in body
    assert 'name="name"' in body


def test_plain_get_renders_full_page(client_admin):
    r = client_admin.get(reverse('category_create'))
    assert r.status_code == 200
    body = r.content.decode()
    # Полная страница расширяет base.html (есть сайдбар/боди приложения).
    assert 'Новая категория' in body
    assert 'name="name"' in body


# ---------- POST (создание) ----------

def test_htmx_post_creates_and_returns_oob(client_admin):
    r = client_admin.post(reverse('category_create'),
                          {'name': 'Уникальная тест-категория ЯЯЯ'},
                          HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    cat = Category.objects.get(name='Уникальная тест-категория ЯЯЯ')
    body = r.content.decode()
    # OOB-подстановка поля категории с уже выбранной новой категорией.
    assert 'id="product-category-field"' in body
    assert 'hx-swap-oob' in body
    assert f'value="{cat.pk}" selected' in body or f'value="{cat.pk}"\n' in body
    # Именно новая категория выбрана.
    assert 'selected' in body


def test_htmx_post_invalid_returns_modal_no_create(client_admin):
    before = Category.objects.count()
    r = client_admin.post(reverse('category_create'), {'name': ''},
                          HTTP_HX_REQUEST='true')
    assert r.status_code == 200
    assert Category.objects.count() == before
    body = r.content.decode()
    assert 'Новая категория' in body       # модалка перерендерилась
    assert 'hx-swap-oob' not in body       # создания не было


def test_plain_post_redirects_to_product_list(client_admin):
    r = client_admin.post(reverse('category_create'),
                          {'name': 'Полностраничная тест-категория ЮЮЮ'})
    assert r.status_code == 302
    assert r.url == reverse('product_list')
    assert Category.objects.filter(name='Полностраничная тест-категория ЮЮЮ').exists()


# ---------- доступ ----------

def test_requires_admin(client_staff):
    """staff (не admin) не может создавать категории."""
    r = client_staff.get(reverse('category_create'), HTTP_HX_REQUEST='true')
    assert r.status_code in (302, 403)
