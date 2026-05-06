from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import F, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone


class Category(models.Model):
    name = models.CharField('Название', max_length=100, unique=True)

    class Meta:
        verbose_name = 'Категория'
        verbose_name_plural = 'Категории'
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    class Unit(models.TextChoices):
        PIECE = 'шт', 'шт'
        METER = 'м', 'м'
        KILOGRAM = 'кг', 'кг'
        SET = 'компл', 'компл'

    name = models.CharField('Название', max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='Категория',
    )
    unit = models.CharField(
        'Ед. изм.',
        max_length=10,
        choices=Unit.choices,
        default=Unit.PIECE,
    )
    stock_total = models.PositiveIntegerField('Всего на складе', default=0)
    daily_price = models.DecimalField(
        'Цена за сутки',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    deposit_per_unit = models.DecimalField(
        'Залог за единицу',
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    is_active = models.BooleanField('Активен', default=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товары'
        ordering = ['name']

    def __str__(self):
        return f'{self.name} ({self.unit})'

    @property
    def available_stock(self) -> int:
        """stock_total минус сумма outstanding по всем активным/просроченным арендам."""
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
        outstanding = (agg['issued'] or 0) - (agg['returned'] or 0)
        return self.stock_total - outstanding


class Customer(models.Model):
    full_name = models.CharField('ФИО', max_length=200)
    phone = models.CharField('Телефон', max_length=32, blank=True)
    passport = models.CharField('Паспорт', max_length=64, blank=True)
    address = models.CharField('Адрес', max_length=255, blank=True)
    notes = models.TextField('Заметки', blank=True)
    created_at = models.DateTimeField('Создан', default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Клиент'
        verbose_name_plural = 'Клиенты'
        ordering = ['full_name']

    def __str__(self):
        return self.full_name

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
        ACTIVE = 'active', 'Активна'
        CLOSED = 'closed', 'Закрыта'
        OVERDUE = 'overdue', 'Просрочена'

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name='rentals',
        verbose_name='Клиент',
    )
    created_at = models.DateTimeField('Создана', default=timezone.now)
    due_date = models.DateField('Срок возврата')
    status = models.CharField(
        'Статус',
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    note = models.TextField('Примечание', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rentals_created',
        verbose_name='Оформил',
    )
    closed_at = models.DateTimeField('Закрыта', null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rentals_closed',
        verbose_name='Закрыл',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Аренда'
        verbose_name_plural = 'Аренды'
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
        verbose_name='Аренда',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='rental_items',
        verbose_name='Товар',
    )
    qty = models.PositiveIntegerField('Количество')
    price_per_day = models.DecimalField(
        'Цена за сутки (снимок)',
        max_digits=12,
        decimal_places=2,
    )

    class Meta:
        verbose_name = 'Позиция аренды'
        verbose_name_plural = 'Позиции аренды'

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
        ISSUE = 'issue', 'Выдача'
        RETURN = 'return', 'Возврат'

    rental_item = models.ForeignKey(
        RentalItem,
        on_delete=models.CASCADE,
        related_name='movements',
        verbose_name='Позиция аренды',
    )
    kind = models.CharField('Тип', max_length=10, choices=Kind.choices)
    qty = models.PositiveIntegerField('Количество')
    date = models.DateTimeField('Дата', default=timezone.now)
    note = models.CharField('Примечание', max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='movements_created',
        verbose_name='Оформил',
    )

    class Meta:
        verbose_name = 'Движение'
        verbose_name_plural = 'Движения'
        ordering = ['-date']

    def __str__(self):
        return f'{self.get_kind_display()} {self.qty} — {self.rental_item}'


class Payment(models.Model):
    class Kind(models.TextChoices):
        DEPOSIT = 'deposit', 'Залог'
        RENT = 'rent', 'Аренда'
        FINE = 'fine', 'Штраф'
        REFUND = 'refund', 'Возврат залога'

    rental = models.ForeignKey(
        Rental,
        on_delete=models.CASCADE,
        related_name='payments',
        verbose_name='Аренда',
    )
    amount = models.DecimalField('Сумма', max_digits=12, decimal_places=2)
    date = models.DateTimeField('Дата', default=timezone.now)
    kind = models.CharField('Тип', max_length=10, choices=Kind.choices)
    note = models.CharField('Примечание', max_length=255, blank=True)

    class Meta:
        verbose_name = 'Платёж'
        verbose_name_plural = 'Платежи'
        ordering = ['-date']

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount} — {self.rental}'
