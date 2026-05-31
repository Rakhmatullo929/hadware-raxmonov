"""Convert Rental.due_date from DateField to DateTimeField.

Existing rows had only a date; after AlterField Django stores them as
midnight datetimes. That would retroactively turn rentals «due today»
into overdue, so we shift every row's due_date to 23:59:59 (end of the
original day) — preserving the previous "still not overdue on the due
date itself" semantics.
"""
from datetime import datetime, time

from django.db import migrations, models
from django.utils import timezone


def shift_due_to_end_of_day(apps, schema_editor):
    Rental = apps.get_model('core', 'Rental')
    tz = timezone.get_current_timezone()
    eod = time(23, 59, 59)
    updates = []
    for r in Rental.objects.all():
        # После AlterField это уже DateTimeField со временем 00:00:00.
        d = r.due_date
        if d is None:
            continue
        if timezone.is_aware(d):
            new_dt = datetime.combine(d.date(), eod).replace(tzinfo=d.tzinfo)
        else:
            new_dt = datetime.combine(d.date(), eod)
            if timezone.is_aware(timezone.now()):
                new_dt = timezone.make_aware(new_dt, tz)
        if d != new_dt:
            r.due_date = new_dt
            updates.append(r)
    Rental.objects.bulk_update(updates, ['due_date'], batch_size=500)


def shift_due_to_midnight(apps, schema_editor):
    """Reverse step — обратно в полночь, чтобы данные не сломались
    при откате на DateField."""
    Rental = apps.get_model('core', 'Rental')
    updates = []
    for r in Rental.objects.all():
        d = r.due_date
        if d is None:
            continue
        midnight = datetime.combine(d.date(), time.min)
        if timezone.is_aware(d):
            midnight = midnight.replace(tzinfo=d.tzinfo)
        if d != midnight:
            r.due_date = midnight
            updates.append(r)
    Rental.objects.bulk_update(updates, ['due_date'], batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_debtornotification_options_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='rental',
            name='due_date',
            field=models.DateTimeField(verbose_name='Срок возврата'),
        ),
        migrations.RunPython(shift_due_to_end_of_day, shift_due_to_midnight),
    ]
