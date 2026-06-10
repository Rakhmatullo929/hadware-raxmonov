"""Заменить разделитель размера в названиях товаров: × (знак умножения,
U+00D7) → обычная кириллическая «х». Так название проще набрать в поиске
(× с клавиатуры не ввести), и поиск товара при оформлении аренды находит
позицию по размеру.

Затрагивает только названия товаров (× встречается там лишь как разделитель
размера). Количественную запись «×N» в комплектах и движениях не трогаем.
"""
from django.db import migrations


def to_kha(apps, schema_editor):
    Product = apps.get_model('core', 'Product')
    for p in Product.objects.filter(name__contains='×'):
        new = p.name.replace('×', 'х')
        if new != p.name:
            p.name = new
            p.save(update_fields=['name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_seed_pricelist'),
    ]

    # reverse = noop: «х»→«×» вслепую испортил бы слова с буквой «х»
    # (напр. «Тахта»). Откат при необходимости — вручную.
    operations = [
        migrations.RunPython(to_kha, migrations.RunPython.noop),
    ]
