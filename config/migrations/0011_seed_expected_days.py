"""Заполнить expected_min_days / expected_max_days для известных товаров.

Best-effort по подстроке в названии. Если товар не найден — пропускаем,
ничего не падает. При откате обнуляем поля.
"""
from django.db import migrations


# (name_substring, min_days, max_days). Подстрока ищется ICONTAINS,
# чтобы переживать варианты названий («корейская опалубка», «опалубка корейская»).
SEEDS = [
    ('Колонна', 3, 3),
    ('Леса', 15, 15),
    ('Корейская опалубка', 10, 14),
    ('Стойка', 25, 25),
    ('Аробача', 5, 5),
    ('Отбойник', 1, 2),
    ('Мешалка', 1, 2),
    ('Тахта', 15, 15),
    ('Финская фанера', 3, 15),
    ('Галош', 1, 2),
    ('Таирод Резва', 5, 10),
]


def seed_expected(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    for substring, lo, hi in SEEDS:
        qs = Product.objects.filter(name__icontains=substring)
        # Только если у пользователя ещё не было своих значений —
        # не трогаем заполненные руками.
        qs.filter(expected_max_days__isnull=True).update(
            expected_min_days=lo,
            expected_max_days=hi,
        )


def clear_expected(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Product.objects.all().update(
        expected_min_days=None, expected_max_days=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_product_expected_max_days_product_expected_min_days'),
    ]

    operations = [
        migrations.RunPython(seed_expected, clear_expected),
    ]
