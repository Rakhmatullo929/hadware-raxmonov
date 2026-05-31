from decimal import Decimal

from django.db import migrations


CATEGORIES = [
    'Леса рамные',
    'Опалубка',
    'Подмости и стойки',
    'Электроинструмент',
    'Ручной инструмент',
]


PRODUCTS = [
    # name, category, unit, stock_total, daily_price, deposit_per_unit
    ('Рама лесов 2.0 м', 'Леса рамные', 'шт', 200, '5000.00', '120000.00'),
    ('Диагональ для рамных лесов', 'Леса рамные', 'шт', 300, '2500.00', '60000.00'),
    ('Настил деревянный 2.0 м', 'Леса рамные', 'шт', 80, '4000.00', '90000.00'),
    ('Щит опалубки 1.2×0.6', 'Опалубка', 'шт', 120, '6000.00', '180000.00'),
    ('Стяжка опалубочная', 'Опалубка', 'шт', 500, '300.00', '5000.00'),
    ('Стойка телескопическая 3.0 м', 'Подмости и стойки', 'шт', 150, '3500.00', '90000.00'),
    ('Тренога для стойки', 'Подмости и стойки', 'шт', 100, '1500.00', '40000.00'),
    ('Перфоратор SDS-Plus', 'Электроинструмент', 'шт', 12, '15000.00', '900000.00'),
    ('Виброплита 90 кг', 'Электроинструмент', 'шт', 6, '40000.00', '3500000.00'),
    ('Лом-гвоздодёр 1 м', 'Ручной инструмент', 'шт', 25, '500.00', '20000.00'),
]


def seed(apps, schema_editor):
    Category = apps.get_model('core', 'Category')
    Product = apps.get_model('core', 'Product')

    cats = {name: Category.objects.create(name=name) for name in CATEGORIES}

    for name, cat_name, unit, stock, daily, deposit in PRODUCTS:
        Product.objects.create(
            name=name,
            category=cats[cat_name],
            unit=unit,
            stock_total=stock,
            daily_price=Decimal(daily),
            deposit_per_unit=Decimal(deposit),
            is_active=True,
        )


def unseed(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Category = apps.get_model('core', 'Category')
    Product.objects.filter(name__in=[p[0] for p in PRODUCTS]).delete()
    Category.objects.filter(name__in=CATEGORIES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
