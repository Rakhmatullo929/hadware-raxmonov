from django.db import migrations, models


def backfill_codes(apps, schema_editor):
    Customer = apps.get_model('core', 'Customer')
    for c in Customer.objects.filter(code__isnull=True).only('id'):
        Customer.objects.filter(pk=c.pk).update(code=f'{c.pk:05d}')


def clear_codes(apps, schema_editor):
    Customer = apps.get_model('core', 'Customer')
    Customer.objects.update(code=None)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_rental_closed_at_rental_closed_by'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='code',
            field=models.CharField(
                blank=True, db_index=True, max_length=16, null=True,
                verbose_name='Код клиента',
            ),
        ),
        migrations.RunPython(backfill_codes, clear_codes),
        migrations.AlterField(
            model_name='customer',
            name='code',
            field=models.CharField(
                blank=True, db_index=True, max_length=16, null=True,
                unique=True, verbose_name='Код клиента',
                help_text='Внутренний номер для прикрепления '
                          'паспорта/документов. Если оставить пустым — '
                          'присвоится автоматически.',
            ),
        ),
    ]
