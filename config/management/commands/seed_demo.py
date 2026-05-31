"""Generate a sizeable demo dataset for performance / manual testing.

Defaults: 30 customers, 1000 rentals, ~3 items per rental, 0–2 returns per
item ⇒ roughly 10k movements.
"""
import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from config.models import (
    Customer,
    Movement,
    Product,
    Rental,
    RentalItem,
)


FIRST_NAMES = ['Алишер', 'Бахтияр', 'Дилором', 'Ёкуб', 'Зухра', 'Иван',
               'Камола', 'Лола', 'Мансур', 'Нодира', 'Ойбек', 'Пётр',
               'Рустам', 'Санжар', 'Тимур', 'Умида', 'Фархад', 'Шахзода']
LAST_NAMES = ['Алиев', 'Каримов', 'Юсупов', 'Хасанов', 'Иванов', 'Турсунов',
              'Раджабов', 'Ахмедов', 'Эргашев', 'Сафаров', 'Назаров',
              'Махмудов', 'Тошматов', 'Қодиров']


class Command(BaseCommand):
    help = 'Сидер демо-данных для дашборда: клиенты, аренды, движения.'

    def add_arguments(self, parser):
        parser.add_argument('--customers', type=int, default=30)
        parser.add_argument('--rentals', type=int, default=1000)
        parser.add_argument('--seed', type=int, default=42)

    @transaction.atomic
    def handle(self, *args, customers, rentals, seed, **opts):
        rnd = random.Random(seed)

        User = get_user_model()
        creator = User.objects.filter(is_superuser=True).first()
        if not creator:
            self.stderr.write(self.style.ERROR(
                'Нет суперпользователя. Сначала создайте: '
                'python manage.py createsuperuser'
            ))
            return

        products = list(Product.objects.filter(is_active=True))
        if not products:
            self.stderr.write(self.style.ERROR('Нет активных товаров.'))
            return

        # Customers (skip ones we already created — idempotent on label)
        existing = set(
            Customer.objects.filter(notes='[seed_demo]')
            .values_list('full_name', flat=True)
        )
        new_custs = []
        for i in range(customers):
            full_name = (
                f'{rnd.choice(LAST_NAMES)} {rnd.choice(FIRST_NAMES)} #{i+1:03d}'
            )
            if full_name in existing:
                continue
            new_custs.append(Customer(
                full_name=full_name,
                phone=f'+998{rnd.randint(700000000, 999999999)}',
                notes='[seed_demo]',
            ))
        Customer.objects.bulk_create(new_custs, batch_size=500)
        all_demo_custs = list(Customer.objects.filter(notes='[seed_demo]'))
        self.stdout.write(
            f'Customers: +{len(new_custs)} (всего демо: {len(all_demo_custs)})'
        )

        now = timezone.now()
        rentals_to_create = []
        for _ in range(rentals):
            created_at = now - timedelta(
                days=rnd.randint(0, 60),
                hours=rnd.randint(0, 23),
                minutes=rnd.randint(0, 59),
            )
            due_date = created_at.date() + timedelta(days=rnd.randint(3, 21))
            rentals_to_create.append(Rental(
                customer=rnd.choice(all_demo_custs),
                created_at=created_at,
                due_date=due_date,
                status=Rental.Status.ACTIVE,
                created_by=creator,
                note='[seed_demo]',
            ))
        Rental.objects.bulk_create(rentals_to_create, batch_size=500)
        all_demo_rentals = list(
            Rental.objects.filter(note='[seed_demo]').order_by('-id')[:rentals]
        )
        self.stdout.write(f'Rentals: +{len(all_demo_rentals)}')

        items_to_create = []
        for r in all_demo_rentals:
            for _ in range(rnd.randint(1, 4)):
                p = rnd.choice(products)
                qty = rnd.randint(1, 20)
                items_to_create.append(RentalItem(
                    rental=r,
                    product=p,
                    qty=qty,
                    price_per_day=p.daily_price,
                ))
        RentalItem.objects.bulk_create(items_to_create, batch_size=1000)
        rental_ids = [r.pk for r in all_demo_rentals]
        all_demo_items = list(
            RentalItem.objects
            .filter(rental_id__in=rental_ids)
            .select_related('rental')
        )
        self.stdout.write(f'RentalItems: +{len(all_demo_items)}')

        movs_to_create = []
        for it in all_demo_items:
            issue_dt = it.rental.created_at
            movs_to_create.append(Movement(
                rental_item=it,
                kind=Movement.Kind.ISSUE,
                qty=it.qty,
                date=issue_dt,
                created_by=creator,
            ))
            outstanding = it.qty
            for _ in range(rnd.randint(0, 2)):
                if outstanding <= 0:
                    break
                qty_ret = rnd.randint(1, outstanding)
                ret_dt = issue_dt + timedelta(
                    days=rnd.randint(1, 25), hours=rnd.randint(0, 23),
                )
                movs_to_create.append(Movement(
                    rental_item=it,
                    kind=Movement.Kind.RETURN,
                    qty=qty_ret,
                    date=ret_dt,
                    created_by=creator,
                ))
                outstanding -= qty_ret
        Movement.objects.bulk_create(movs_to_create, batch_size=1000)
        self.stdout.write(f'Movements: +{len(movs_to_create)}')

        self.stdout.write(self.style.SUCCESS('Готово.'))
