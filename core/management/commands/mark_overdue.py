"""Flip status='active' → 'overdue' for rentals past due with outstanding qty.

Idempotent: safe to run repeatedly. Schedule once an hour from cron / launchd /
systemd timer (see README).
"""
from django.core.management.base import BaseCommand
from django.db.models import Exists, F, OuterRef, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import Movement, Rental, RentalItem


class Command(BaseCommand):
    help = (
        'Перевести аренды со статусом active в overdue, если due_date '
        '< сегодня и есть невозвращённые позиции.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не делать UPDATE, только показать список ID.',
        )

    def handle(self, *args, dry_run, **opts):
        today = timezone.localdate()

        outstanding_item_exists = (
            RentalItem.objects
            .filter(rental=OuterRef('pk'))
            .annotate(
                _issued=Coalesce(
                    Sum('movements__qty',
                        filter=Q(movements__kind=Movement.Kind.ISSUE)),
                    0,
                ),
                _returned=Coalesce(
                    Sum('movements__qty',
                        filter=Q(movements__kind=Movement.Kind.RETURN)),
                    0,
                ),
            )
            .filter(_issued__gt=F('_returned'))
        )

        candidates = (
            Rental.objects
            .filter(status=Rental.Status.ACTIVE, due_date__lt=today)
            .filter(Exists(outstanding_item_exists))
        )

        if dry_run:
            ids = list(candidates.values_list('id', flat=True))
            self.stdout.write(
                self.style.WARNING(f'[dry-run] {len(ids)} аренд: {ids}')
            )
            return

        # Materialise ids to avoid issues with UPDATE + Exists subquery
        ids = list(candidates.values_list('id', flat=True))
        if not ids:
            self.stdout.write('Нет аренд для пометки.')
            return

        n = Rental.objects.filter(pk__in=ids).update(status=Rental.Status.OVERDUE)
        self.stdout.write(
            self.style.SUCCESS(f'Помечено просроченными: {n}.')
        )
