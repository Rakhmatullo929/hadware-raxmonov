"""Telegram-напоминания арендодателю (админу/оператору).

Запускается cron'ом каждый час. Логика:

  • За 1 день до возврата (только в час TELEGRAM_REMINDER_HOUR):
      сводка по арендам, у которых due_date == завтра и есть outstanding.
      Дедуп: одно сообщение на админский chat_id в сутки.

  • Каждый час по просроченным (status active/overdue, due_date < today,
    есть outstanding qty):
      сводка по всем просрочкам.
      Дедуп: одно сообщение на админский chat_id в час.

Получатели — только chat_id из TELEGRAM_ADMIN_CHAT_IDS (те, кто даёт
в аренду). Клиентам бот ничего не шлёт.

Без TELEGRAM_BOT_TOKEN / без админов команда корректно завершается.
"""
from datetime import timedelta
from html import escape

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Exists, F, OuterRef, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from config.models import DebtorNotification, Movement, Rental, RentalItem
from config.telegram import send_message


def _outstanding_subquery():
    return (
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


def _items_with_outstanding_qs():
    return (
        RentalItem.objects
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
        .annotate(outstanding=F('_issued') - F('_returned'))
        .filter(outstanding__gt=0)
        .select_related('product')
    )


def _format_items(items):
    if not items:
        return '—'
    return ', '.join(
        f'{escape(it.product.name)} × {it.outstanding} {escape(it.product.unit)}'
        for it in items
    )


def _admin_msg_day_before(rentals):
    lines = [
        f'🔔 <b>Завтра возврат — {len(rentals)} аренд(ы)</b>',
        '',
    ]
    for r in rentals:
        items = list(getattr(r, 'outstanding_list', []))
        phone = escape(r.customer.phone or '—')
        lines.append(
            f'• #{r.pk} — <b>{escape(r.customer.full_name)}</b> ({phone}): '
            f'{_format_items(items)}'
        )
    return '\n'.join(lines)


def _admin_msg_overdue(rentals_with_days):
    lines = [
        f'⚠️ <b>Просрочки — {len(rentals_with_days)} аренд(ы)</b>',
        '',
    ]
    for r, days in rentals_with_days:
        items = list(getattr(r, 'outstanding_list', []))
        phone = escape(r.customer.phone or '—')
        lines.append(
            f'• #{r.pk} — <b>{escape(r.customer.full_name)}</b> ({phone}) '
            f'— {days} дн.: {_format_items(items)}'
        )
    return '\n'.join(lines)


class Command(BaseCommand):
    help = (
        'Telegram-напоминания арендодателю: «за день до возврата» (в '
        'TELEGRAM_REMINDER_HOUR) и «каждый час по просрочкам».'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Не отправлять и не писать в БД, только показать что будет.',
        )
        parser.add_argument(
            '--force-daily', action='store_true',
            help='Игнорировать TELEGRAM_REMINDER_HOUR, отправить дневное сразу.',
        )

    def handle(self, *, dry_run, force_daily, **opts):
        token = (settings.TELEGRAM_BOT_TOKEN or '').strip()
        admin_ids = settings.TELEGRAM_ADMIN_CHAT_IDS
        reminder_hour = settings.TELEGRAM_REMINDER_HOUR

        if not dry_run and (not token or not admin_ids):
            self.stdout.write(self.style.WARNING(
                'TELEGRAM_BOT_TOKEN или TELEGRAM_ADMIN_CHAT_IDS не заданы — '
                'отправка пропущена. Используйте --dry-run для проверки.'
            ))
            return

        now = timezone.now()
        today = timezone.localdate()
        tomorrow = today + timedelta(days=1)

        # 1) За день до возврата (active, due_date == завтра, outstanding > 0)
        day_before_rentals = []
        if force_daily or now.hour == reminder_hour:
            day_before_rentals = list(
                Rental.objects
                .filter(status=Rental.Status.ACTIVE, due_date__date=tomorrow)
                .filter(Exists(_outstanding_subquery()))
                .select_related('customer')
                .prefetch_related(Prefetch(
                    'items',
                    queryset=_items_with_outstanding_qs(),
                    to_attr='outstanding_list',
                ))
                .order_by('pk')
            )

        # 2) Просрочки (active/overdue, due_date < today, outstanding > 0)
        overdue_rentals = list(
            Rental.objects
            .filter(
                status__in=[Rental.Status.ACTIVE, Rental.Status.OVERDUE],
                due_date__lt=now,
            )
            .filter(Exists(_outstanding_subquery()))
            .select_related('customer')
            .prefetch_related(Prefetch(
                'items',
                queryset=_items_with_outstanding_qs(),
                to_attr='outstanding_list',
            ))
            .order_by('due_date', 'pk')
        )
        overdue_with_days = [
            (r, (today - r.due_date.date()).days) for r in overdue_rentals
        ]

        self.stdout.write(
            f'[notify_debtors] {now:%Y-%m-%d %H:%M} '
            f'day_before={len(day_before_rentals)}, '
            f'overdue={len(overdue_rentals)}, '
            f'admins={len(admin_ids)}'
        )

        sent = 0
        skipped = 0

        if day_before_rentals:
            text = _admin_msg_day_before(day_before_rentals)
            pivot = day_before_rentals[0]
            for chat_id in admin_ids:
                if self._already_sent(
                    pivot, DebtorNotification.Kind.DAY_BEFORE, chat_id,
                    window='day',
                ):
                    skipped += 1
                    continue
                sent += int(self._dispatch(
                    rental=pivot, chat_id=chat_id, text=text,
                    kind=DebtorNotification.Kind.DAY_BEFORE,
                    dry_run=dry_run,
                ))

        if overdue_with_days:
            text = _admin_msg_overdue(overdue_with_days)
            pivot = overdue_with_days[0][0]
            for chat_id in admin_ids:
                if self._already_sent(
                    pivot, DebtorNotification.Kind.HOUR_OVERDUE, chat_id,
                    window='hour',
                ):
                    skipped += 1
                    continue
                sent += int(self._dispatch(
                    rental=pivot, chat_id=chat_id, text=text,
                    kind=DebtorNotification.Kind.HOUR_OVERDUE,
                    dry_run=dry_run,
                ))

        self.stdout.write(self.style.SUCCESS(
            f'Готово: отправлено {sent}, пропущено (дедуп) {skipped}'
            + (' [dry-run]' if dry_run else '')
        ))

    # ---------- helpers ----------
    def _already_sent(self, rental, kind, chat_id, *, window):
        now = timezone.now()
        qs = DebtorNotification.objects.filter(
            rental=rental, kind=kind, target_chat_id=chat_id, ok=True,
        )
        if window == 'day':
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif window == 'hour':
            since = now.replace(minute=0, second=0, microsecond=0)
        else:
            return False
        return qs.filter(sent_at__gte=since).exists()

    def _dispatch(self, *, rental, chat_id, text, kind, dry_run):
        if dry_run:
            preview = text.replace('\n', ' | ')[:160]
            self.stdout.write(f'  [DRY] → {chat_id} ({kind}): {preview}')
            return True
        ok, body = send_message(chat_id, text)
        DebtorNotification.objects.create(
            rental=rental,
            kind=kind,
            target_chat_id=chat_id,
            ok=ok,
            response=(str(body)[:2000] if body else ''),
        )
        prefix = self.style.SUCCESS('OK') if ok else self.style.ERROR('FAIL')
        self.stdout.write(f'  {prefix} → {chat_id} ({kind})')
        return ok
