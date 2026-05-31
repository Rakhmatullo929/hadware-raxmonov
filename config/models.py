from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    name = models.CharField(_('Название'), max_length=100, unique=True)

    class Meta:
        verbose_name = _('Категория')
        verbose_name_plural = _('Категории')
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        PIECE = 'шт', _('шт')
        METER = 'м', _('м')
        KILOGRAM = 'кг', _('кг')
        SET = 'компл', _('компл')

    name = models.CharField(_('Название'), max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name=_('Категория'),
    )
    unit = models.CharField(
        _('Ед. изм.'),
        max_length=10,
        choices=Unit.choices,
        default=Unit.PIECE,
    )
    stock_total = models.PositiveIntegerField(_('Всего на складе'), default=0)
    daily_price = models.DecimalField(
        _('Цена за сутки'),
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    deposit_per_unit = models.DecimalField(
        _('Залог за единицу'),
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    is_active = models.BooleanField(_('Активен'), default=True)

    class Meta:
        verbose_name = _('Товар')
        verbose_name_plural = _('Товары')
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.unit})'

    @property
    def outstanding_qty(self) -> int:
        """Сколько единиц этого товара сейчас «на руках» (выдано минус
        возвращено) по активным/просроченным арендам."""
        active_statuses = [Rental.Status.ACTIVE, Rental.Status.OVERDUE]
        agg = (
            Movement.objects
            .filter(
                rental_item__product=self,
                rental_item__rental__status__in=active_statuses,
            )
            .aggregate(
                issued=Sum('qty', filter=Q(kind=Movement.Kind.ISSUE)),
                returned=Sum('qty', filter=Q(kind=Movement.Kind.RETURN)),
            )
        )
        return (agg['issued'] or 0) - (agg['returned'] or 0)

    @property
    def available_stock(self) -> int:
        """Доступно к выдаче. Никогда не отрицательно: если по историческим
        данным выдано больше, чем stock_total (перевыдача), доступно = 0."""
        return max(0, self.stock_total - self.outstanding_qty)


class Customer(models.Model):
    code = models.CharField(
        _('Код клиента'),
        max_length=16,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text=_(
            'Внутренний номер для прикрепления паспорта/документов. '
            'Если оставить пустым — присвоится автоматически.'
        ),
    )
    full_name = models.CharField(_('ФИО'), max_length=200)
    phone = models.CharField(_('Телефон'), max_length=32, blank=True)
    passport = models.CharField(_('Паспорт'), max_length=64, blank=True)
    address = models.CharField(_('Адрес'), max_length=255, blank=True)
    notes = models.TextField(_('Заметки'), blank=True)
    created_at = models.DateTimeField(_('Создан'), default=timezone.now, editable=False)

    class Meta:
        verbose_name = _('Клиент')
        verbose_name_plural = _('Клиенты')
        ordering = ['full_name']

    def __str__(self):
        return f'№ {self.code} · {self.full_name}' if self.code else self.full_name

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = f'{self.pk:05d}'
            super().save(update_fields=['code'])

    @property
    def display_code(self) -> str:
        return f'№ {self.code}' if self.code else ''

    @property
    def active_rentals_count(self) -> int:
        return self.rentals.filter(
            status__in=[Rental.Status.ACTIVE, Rental.Status.OVERDUE]
        ).count()

    @property
    def outstanding_qty(self) -> int:
        active_statuses = [Rental.Status.ACTIVE, Rental.Status.OVERDUE]
        agg = (
            Movement.objects
            .filter(
                rental_item__rental__customer=self,
                rental_item__rental__status__in=active_statuses,
            )
            .aggregate(
                issued=Sum('qty', filter=Q(kind=Movement.Kind.ISSUE)),
                returned=Sum('qty', filter=Q(kind=Movement.Kind.RETURN)),
            )
        )
        return (agg['issued'] or 0) - (agg['returned'] or 0)

    @property
    def total_payments(self):
        from decimal import Decimal as _D
        return self.rentals.aggregate(s=Sum('payments__amount'))['s'] or _D('0.00')


class Rental(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', _('Активна')
        CLOSED = 'closed', _('Закрыта')
        OVERDUE = 'overdue', _('Просрочена')

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='rentals',
        verbose_name=_('Клиент'),
    )
    created_at = models.DateTimeField(_('Создана'), default=timezone.now)
    due_date = models.DateField(_('Срок возврата'))
    status = models.CharField(
        _('Статус'),
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    note = models.TextField(_('Примечание'), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rentals_created',
        verbose_name=_('Оформил'),
    )
    closed_at = models.DateTimeField(_('Закрыта'), null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rentals_closed',
        verbose_name=_('Закрыл'),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _('Аренда')
        verbose_name_plural = _('Аренды')
        ordering = ['-created_at']

    def __str__(self):
        return f'Аренда #{self.pk} — {self.customer}'

    @property
    def is_overdue(self) -> bool:
        if self.status == self.Status.CLOSED:
            return False
        return self.due_date < timezone.localdate() and self.outstanding_items().exists()

    def outstanding_items(self):
        """Позиции аренды, по которым ещё не всё возвращено."""
        return (
            self.items
            .annotate(
                _issued=Coalesce(
                    Sum('movements__qty', filter=Q(movements__kind=Movement.Kind.ISSUE)),
                    0,
                ),
                _returned=Coalesce(
                    Sum('movements__qty', filter=Q(movements__kind=Movement.Kind.RETURN)),
                    0,
                ),
            )
            .filter(_issued__gt=F('_returned'))
        )

    def maybe_auto_close(self):
        """If every item is fully returned, close the rental.
        closed_at = max date of return movements."""
        if self.status == self.Status.CLOSED:
            return False
        if self.outstanding_items().exists():
            return False
        last_return = (
            Movement.objects
            .filter(rental_item__rental=self, kind=Movement.Kind.RETURN)
            .order_by('-date').first()
        )
        self.status = self.Status.CLOSED
        self.closed_at = last_return.date if last_return else timezone.now()
        self.save(update_fields=['status', 'closed_at'])
        return True


class RentalItem(models.Model):
    rental = models.ForeignKey(
        Rental,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name=_('Аренда'),
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='rental_items',
        verbose_name=_('Товар'),
    )
    qty = models.PositiveIntegerField(_('Количество'))
    price_per_day = models.DecimalField(
        _('Цена за сутки (снимок)'),
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        verbose_name = _('Позиция аренды')
        verbose_name_plural = _('Позиции аренды')

    def __str__(self):
        return f'{self.product} × {self.qty}'

    @property
    def issued_qty(self) -> int:
        return (
            self.movements
            .filter(kind=Movement.Kind.ISSUE)
            .aggregate(s=Sum('qty'))['s']
            or 0
        )

    @property
    def returned_qty(self) -> int:
        return (
            self.movements
            .filter(kind=Movement.Kind.RETURN)
            .aggregate(s=Sum('qty'))['s']
            or 0
        )

    @property
    def outstanding_qty(self) -> int:
        return self.issued_qty - self.returned_qty


class Movement(models.Model):
    class Kind(models.TextChoices):
        ISSUE = 'issue', _('Выдача')
        RETURN = 'return', _('Возврат')

    rental_item = models.ForeignKey(
        RentalItem,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name=_('Позиция аренды'),
    )
    kind = models.CharField(_('Тип'), max_length=10, choices=Kind.choices)
    qty = models.PositiveIntegerField(_('Количество'))
    date = models.DateTimeField(_('Дата'), default=timezone.now)
    note = models.CharField(_('Примечание'), max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='movements_created',
        verbose_name=_('Оформил'),
    )

    class Meta:
        verbose_name = _('Движение')
        verbose_name_plural = _('Движения')
        ordering = ['-date']

    def __str__(self):
        return f'{self.get_kind_display()} {self.qty} — {self.rental_item}'


class Payment(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', _('Залог')
        RENT = 'rent', _('Аренда')
        FINE = 'fine', _('Штраф')
        REFUND = 'refund', _('Возврат залога')

    rental = models.ForeignKey(
        Rental,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name=_('Аренда'),
    )
    amount = models.DecimalField(_('Сумма'), max_digits=12, decimal_places=2)
    date = models.DateTimeField(_('Дата'), default=timezone.now)
    kind = models.CharField(_('Тип'), max_length=10, choices=Kind.choices)
    note = models.CharField(_('Примечание'), max_length=255, blank=True)

    class Meta:
        verbose_name = _('Платёж')
        verbose_name_plural = _('Платежи')
        ordering = ['-date']

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount} — {self.rental}'


class DebtorNotification(models.Model):
    """Лог Telegram-напоминаний арендодателю (админу) — для дедупа,
    чтобы не слать дубли в один и тот же час/день."""

    class Kind(models.TextChoices):
        DAY_BEFORE = 'day_before', _('За день до возврата')
        HOUR_OVERDUE = 'hour_overdue', _('Часовое напоминание о просрочке')

    rental = models.ForeignKey(
        Rental,
        on_delete=models.CASCADE,
        related_name='debtor_notifications',
        verbose_name=_('Аренда'),
    )
    kind = models.CharField(_('Тип'), max_length=20, choices=Kind.choices)
    target_chat_id = models.BigIntegerField(_('Telegram chat ID'))
    sent_at = models.DateTimeField(_('Отправлено'), default=timezone.now)
    ok = models.BooleanField(_('Успех'), default=True)
    response = models.TextField(_('Ответ API'), blank=True)

    class Meta:
        verbose_name = _('Уведомление о долге')
        verbose_name_plural = _('Уведомления о долгах')
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['rental', 'kind', 'sent_at']),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} → {self.target_chat_id} ({self.sent_at:%Y-%m-%d %H:%M})'
