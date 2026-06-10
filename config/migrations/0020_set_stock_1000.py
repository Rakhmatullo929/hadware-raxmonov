"""Выставить остаток на складе 1000 шт каждому активному товару.

Стартовая инициализация склада: после импорта прайс-листа позиции были с
нулевым остатком. По решению оператора всем активным товарам ставится 1000
(включая то немногое оборудование, где остаток уже был задан — он
перезаписывается). Неактивные (деактивированные дубли) не трогаем.
"""
from django.db import migrations


def set_stock(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    Product.objects.filter(is_active=True).update(stock_total=1000)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_rename_size_separator'),
    ]

    # reverse = noop: прежние остатки не сохраняем, восстановить нечем.
    operations = [
        migrations.RunPython(set_stock, migrations.RunPython.noop),
    ]
