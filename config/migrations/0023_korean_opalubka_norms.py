"""Норма срока 3/10 всем «Корейская опалубка *» (включая размерные варианты).

0022 проставил норму отдельным корейским позициям и группам; здесь охватываем
ВСЕ «Корейская опалубка *» — размерные N×M (1х05…50х50), вуг1м/вуг2м и т.д. По
запросу пользователя: у всех корейских опалубок срок 3–10 дней.

Не затрагивает «корейски опалубка тайрод» (другое написание/товар, своя норма).
Идемпотентно; откат — no-op (прежние значения были разными: пусто и 10/пусто).
"""
from django.db import migrations


def set_korean_norms(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Product.objects.filter(name__startswith='Корейская опалубка').update(
        expected_min_days=3,
        expected_max_days=10,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_set_opalubka_norms'),
    ]

    operations = [
        migrations.RunPython(set_korean_norms, migrations.RunPython.noop),
    ]
