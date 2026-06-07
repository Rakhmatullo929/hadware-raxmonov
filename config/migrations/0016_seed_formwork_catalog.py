from django.db import migrations

# Комплекты «на 1 шт» для корейской опалубки.
KIT_KOR_3 = 'Зажим ×3, Фиксатор ×3, Тайрод р/калпокча ×3, Штир/шайба ×3'
KIT_KOR_2 = 'Зажим ×2, Фиксатор ×2, Тайрод р/калпокча ×2, Штир/шайба ×2'
KIT_KOR_ANGLE = 'Зажим ×2'

KOREAN = [
    ('2×1', KIT_KOR_3), ('2×80', KIT_KOR_3), ('2×70', KIT_KOR_3),
    ('2×60', KIT_KOR_3), ('2×50', KIT_KOR_3), ('2×40', KIT_KOR_3),
    ('2×20', KIT_KOR_3), ('2×10', KIT_KOR_3), ('2×30', KIT_KOR_3),
    ('1.5×1', KIT_KOR_3), ('1×1', KIT_KOR_3), ('1×80', KIT_KOR_3),
    ('1×70', KIT_KOR_3),
    ('1×60', KIT_KOR_2), ('1×50', KIT_KOR_2), ('1×40', KIT_KOR_2),
    ('1×30', KIT_KOR_2), ('1×20', KIT_KOR_2), ('1×10', KIT_KOR_2),
    ('1×05', KIT_KOR_2), ('50×50', KIT_KOR_2), ('50×40', KIT_KOR_2),
    ('50×30', KIT_KOR_2), ('50×20', KIT_KOR_2), ('50×10', KIT_KOR_2),
    ('вуг1м', KIT_KOR_ANGLE), ('вуг50', KIT_KOR_ANGLE),
    ('вуг2м', KIT_KOR_ANGLE), ('наруг2м', KIT_KOR_ANGLE),
    ('наруг1м', KIT_KOR_ANGLE), ('наруг50', KIT_KOR_ANGLE),
]

FINNISH = [
    ('2.2×60', 'Штир/шайба ×3'), ('2.2×50', 'Штир/шайба ×3'),
    ('2.2×40', 'Штир/шайба ×3'), ('2.2×30', 'Штир/шайба ×3'),
    ('2.2×20', 'Штир/шайба ×3'),
]

COLUMN = [
    ('3.11×40', 'Тайрод ×20'), ('3.11×60', 'Тайрод ×20'),
    ('3.11×80', 'Тайрод ×20'), ('3.11×1', 'Тайрод ×20'),
    ('3.7×40', 'Тайрод ×24'), ('3.72×60', 'Тайрод ×24'),
    ('1.22×040', 'Тайрод ×8'), ('1.22×0.60', 'Тайрод ×8'),
    ('3×50', 'Тайрод ×24'),
]

# категория -> (префикс названия товара, список (размер, kit))
GROUPS = [
    ('Корейская опалубка', 'Корейская опалубка', KOREAN),
    ('Финская опалубка', 'Финская опалубка', FINNISH),
    ('Колонна', 'Колонна', COLUMN),
]

# одиночные товары: (категория, имя товара, kit)
SINGLES = [
    ('Стойка телескопическая домкрат', 'Стойка телескопическая домкрат', 'Крючок ×1'),
    ('Леса строительные', 'Леса строительные', 'Крестик ×2'),
]

# старые обобщённые товары — деактивировать
DEACTIVATE_NAMES = [
    'Корейская опалубка',
    'Колонна',
    'Финская фанера',
    'Стойка телескопическая 3.0 м',
]

NEW_CATEGORY_NAMES = [
    'Корейская опалубка', 'Финская опалубка', 'Колонна',
    'Стойка телескопическая домкрат', 'Леса строительные',
]


def seed(apps, schema_editor):
    Category = apps.get_model('core', 'Category')
    Product = apps.get_model('core', 'Product')

    # Деактивируем старые ДО создания новых, чтобы не задеть новые по имени.
    Product.objects.filter(name__in=DEACTIVATE_NAMES).update(is_active=False)

    for cat_name, prefix, rows in GROUPS:
        cat, _ = Category.objects.get_or_create(name=cat_name)
        for size, kit in rows:
            name = f'{prefix} {size}'
            Product.objects.get_or_create(
                name=name,
                defaults={
                    'category': cat,
                    'unit': 'шт',
                    'stock_total': 0,
                    'daily_price': 0,
                    'deposit_per_unit': 0,
                    'is_active': True,
                    'included_kit': kit,
                },
            )

    for cat_name, name, kit in SINGLES:
        cat, _ = Category.objects.get_or_create(name=cat_name)
        Product.objects.get_or_create(
            name=name,
            defaults={
                'category': cat,
                'unit': 'шт',
                'stock_total': 0,
                'daily_price': 0,
                'deposit_per_unit': 0,
                'is_active': True,
                'included_kit': kit,
            },
        )


def unseed(apps, schema_editor):
    # Мягкий откат: удаляем только созданные товары и пустые новые категории.
    # Старые деактивированные товары обратно НЕ включаем (состояние неизвестно).
    Category = apps.get_model('core', 'Category')
    Product = apps.get_model('core', 'Product')

    names = []
    for _cat, prefix, rows in GROUPS:
        names += [f'{prefix} {size}' for size, _kit in rows]
    names += [name for _cat, name, _kit in SINGLES]
    Product.objects.filter(name__in=names).delete()

    for cat_name in NEW_CATEGORY_NAMES:
        cat = Category.objects.filter(name=cat_name).first()
        if cat and not cat.products.exists():
            cat.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_product_included_kit'),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
