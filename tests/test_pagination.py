"""Пагинация: корректные ссылки (без двойного «?») и номера страниц.

Регрессия на баг: href был «?{% querystring %}», а тег querystring сам
добавляет «?» → «??page=2» → параметр ломался, «Вперёд» вёл на 1-ю страницу.
"""
import pytest
from django.urls import reverse

from config.models import Customer


@pytest.fixture
def many_customers(db):
    # CustomerListView.paginate_by = 25 → 30 клиентов = 2 страницы.
    for i in range(30):
        Customer.objects.create(full_name=f'Клиент {i:03d}')


def test_no_double_question_mark(client_staff, many_customers):
    body = client_staff.get(reverse('customer_list')).content.decode()
    assert '??page' not in body            # был двойной «?» — баг
    assert '?page=2' in body               # рабочая ссылка на 2-ю страницу


def test_next_page_actually_loads_page_two(client_staff, many_customers):
    """Ключевой тест бага: переход на ?page=2 отдаёт именно 2-ю страницу."""
    resp = client_staff.get(reverse('customer_list'), {'page': '2'})
    assert resp.status_code == 200
    assert resp.context['page_obj'].number == 2


def test_numbered_pages_render(client_staff, many_customers):
    body = client_staff.get(reverse('customer_list')).content.decode()
    assert '>1</span>' in body             # активная страница 1
    assert '>2</a>' in body                # ссылка на страницу 2
    assert 'Страница 1 из 2' in body


def test_page_two_shows_first_and_prev_links(client_staff, many_customers):
    body = client_staff.get(
        reverse('customer_list'), {'page': '2'}
    ).content.decode()
    assert '??page' not in body
    assert '?page=1' in body               # «Первая»/«Назад» ведут на 1-ю
