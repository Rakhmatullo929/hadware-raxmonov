"""Создать недостающие товары из «списка норм» с их ожидаемыми сроками.

Идемпотентно: повторный запуск ничего не дублирует. Для каждого товара
ищем по точному имени; если нет — создаём с нулевыми ценой/складом
(админ заполнит руками), но с заполненными expected_min_days /
expected_max_days. Если товар уже есть и норма у него ещё не задана —
дозаполняем; ранее проставленные руками значения не трогаем.
"""
from decimal import Decimal

from django.db import migrations


# (имя, категория, min_days, max_days). Категории — из существующих
# в БД (см. 0002_seed_catalog). «Прочее» — fallback для двусмысленных,
# создаётся отдельно.
SEEDS = [
    # name,                       category,                min, max
    ('Колонна',                   'Опалубка',              3,   3),
    ('Корейская опалубка',        'Опалубка',              10,  14),
    ('Финская фанера',            'Опалубка',              3,   15),
    ('Таирод Резва',              'Опалубка',              5,   10),

    ('Тахта',                     'Подмости и стойки',     15,  15),

    ('Аробача',                   'Ручной инструмент',     5,   5),

    ('Отбойник',                  'Электроинструмент',     1,   2),
    ('Мешалка',                   'Электроинструмент',     1,   2),

    ('Галош',                     'Прочее',                1,   2),
]


def seed_norm_products(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Category = apps.get_model('core', 'Category')

    for name, cat_name, lo, hi in SEEDS:
        category, _ = Category.objects.get_or_create(name=cat_name)
        product, created = Product.objects.get_or_create(
            name=name,
            defaults={
                'category': category,
                'unit': 'шт',
                'stock_total': 0,
                'daily_price': Decimal('0.00'),
                'deposit_per_unit': Decimal('0.00'),
                'is_active': True,
                'expected_min_days': lo,
                'expected_max_days': hi,
            },
        )
        if not created:
            # Существовал ранее — не трогаем цену/склад. Заполняем норму,
            # только если её ещё нет.
            changed = False
            if product.expected_max_days is None:
                product.expected_min_days = lo
                product.expected_max_days = hi
                changed = True
            if changed:
                product.save(update_fields=[
                    'expected_min_days', 'expected_max_days',
                ])


def unseed_norm_products(apps, schema_editor):
    """Откат: удалим только те товары, которые мы создали в этом сидере
    И у которых не появилось истории (нет RentalItem). Иначе ON DELETE
    PROTECT не даст удалить, и мы предпочтём не трогать."""
    Product = apps.get_model('core', 'Product')
    RentalItem = apps.get_model('core', 'RentalItem')
    for name, _cat, _lo, _hi in SEEDS:
        for p in Product.objects.filter(name=name):
            if not RentalItem.objects.filter(product=p).exists():
                p.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_seed_expected_days'),
    ]

    operations = [
        migrations.RunPython(seed_norm_products, unseed_norm_products),
    ]
