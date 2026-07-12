"""Проставить норму срока 3/10 товарам опалубки (по запросу пользователя).

Формализует ручную правку боевой БД, сделанную напрямую: для перечисленных
точных имён и групп «Финская опалубка *» / «Корейская опалубка (фин. фанера) *»
выставляем expected_min_days=3, expected_max_days=10 (перезаписью — в т.ч.
«Корейская опалубка», у которой из 0012 стояло 10/14).

Идемпотентно и безопасно на любой БД: несуществующие имена просто не совпадут,
повторный прогон лишь заново проставит те же 3/10. Откат — no-op (прежние
значения были разными: 10/14 и пусто, однозначно не восстановить).
"""
from django.db import migrations
from django.db.models import Q


EXACT_NAMES = [
    'Корейская опалубка',
    'Корейская опалубка вуг50',
    'Корейская опалубка наруг1м',
    'Корейская опалубка наруг2м',
    'Корейская опалубка наруг50',
]
PREFIXES = [
    'Финская опалубка',
    'Корейская опалубка (фин. фанера)',
]

MIN_DAYS = 3
MAX_DAYS = 10


def set_opalubka_norms(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    q = Q(name__in=EXACT_NAMES)
    for pref in PREFIXES:
        q |= Q(name__startswith=pref)
    Product.objects.filter(q).update(
        expected_min_days=MIN_DAYS,
        expected_max_days=MAX_DAYS,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_customer_archived_at'),
    ]

    operations = [
        migrations.RunPython(set_opalubka_norms, migrations.RunPython.noop),
    ]
