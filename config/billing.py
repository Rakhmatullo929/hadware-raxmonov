"""Billing calculations for rentals.

Days are computed FIFO: each return Movement consumes from the oldest
unsettled chunk of issue Movements first. Same-day return counts as 1 day.
"""
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from .models import Movement, Payment, Rental


DEFAULT_OVERDUE_FINE_COEF = Decimal('1.5')


def _billable_days(start_dt, end_dt) -> int:
    """Calendar-day diff, never less than 1."""
    diff = (end_dt.date() - start_dt.date()).days
    return diff if diff >= 1 else 1


def compute_item_unit_days(item, as_of=None) -> int:
    """Sum of (qty * billed_days) over all chunks of an item, FIFO.

    Each issue Movement seeds a chunk (qty, issue_dt). Each return consumes
    from the oldest chunk(s). Outstanding chunks accrue days until ``as_of``.
    """
    if as_of is None:
        as_of = timezone.now()

    movements = list(item.movements.order_by('date', 'id'))
    queue = []  # list of [remaining_qty, issue_dt]
    total = 0

    for m in movements:
        if m.kind == Movement.Kind.ISSUE:
            if m.qty > 0:
                queue.append([m.qty, m.date])
        elif m.kind == Movement.Kind.RETURN:
            need = m.qty
            while need > 0 and queue:
                chunk_qty, issue_dt = queue[0]
                consumed = min(chunk_qty, need)
                total += consumed * _billable_days(issue_dt, m.date)
                chunk_qty -= consumed
                need -= consumed
                if chunk_qty == 0:
                    queue.pop(0)
                else:
                    queue[0][0] = chunk_qty

    for chunk_qty, issue_dt in queue:
        if chunk_qty > 0:
            total += chunk_qty * _billable_days(issue_dt, as_of)
    return total


def _replay_item(item):
    """FIFO-проход по движениям позиции.

    Возвращает ``(return_rows, queue)``:
      * ``return_rows`` — список ``(movement, unit_days)`` по каждому ВОЗВРАТУ,
        где ``unit_days`` — авто-расчёт (qty × дни, FIFO) для этого возврата;
      * ``queue`` — остаток ещё не возвращённых чанков ``[qty, issue_dt]``.
    """
    movements = list(item.movements.order_by('date', 'id'))
    queue = []  # list of [remaining_qty, issue_dt]
    return_rows = []

    for m in movements:
        if m.kind == Movement.Kind.ISSUE:
            if m.qty > 0:
                queue.append([m.qty, m.date])
        elif m.kind == Movement.Kind.RETURN:
            need = m.qty
            unit_days = 0
            while need > 0 and queue:
                chunk_qty, issue_dt = queue[0]
                consumed = min(chunk_qty, need)
                unit_days += consumed * _billable_days(issue_dt, m.date)
                chunk_qty -= consumed
                need -= consumed
                if chunk_qty == 0:
                    queue.pop(0)
                else:
                    queue[0][0] = chunk_qty
            return_rows.append((m, unit_days))
    return return_rows, queue


def compute_item_base(item, as_of=None) -> Decimal:
    """База аренды по позиции.

    Для каждого возврата берём сохранённое ``Movement.amount`` (начисление,
    которое мог поправить оператор), либо авто-расчёт ``unit_days × price``,
    если суммы нет (старые данные, списания). Ещё не возвращённые единицы
    продолжают капать до ``as_of``.
    """
    if as_of is None:
        as_of = timezone.now()
    price = item.price_per_day
    return_rows, queue = _replay_item(item)

    base = Decimal('0.00')
    for m, unit_days in return_rows:
        if m.amount is not None:
            base += m.amount
        else:
            base += Decimal(unit_days) * price
    for chunk_qty, issue_dt in queue:
        if chunk_qty > 0:
            base += Decimal(chunk_qty * _billable_days(issue_dt, as_of)) * price
    return base


def compute_return_amount_for_qty(item, qty, as_of=None) -> Decimal:
    """Авто-сумма аренды за возврат ``qty`` единиц *сейчас* (FIFO по текущему
    остатку на руках). Используется как дефолт, когда оператор оставил поле
    суммы пустым."""
    if as_of is None:
        as_of = timezone.now()
    _, queue = _replay_item(item)
    need = qty
    unit_days = 0
    for chunk_qty, issue_dt in queue:
        if need <= 0:
            break
        consumed = min(chunk_qty, need)
        unit_days += consumed * _billable_days(issue_dt, as_of)
        need -= consumed
    return (Decimal(unit_days) * item.price_per_day).quantize(Decimal('0.01'))


def return_charge_map(rental, as_of=None) -> dict:
    """``{movement_id: сумма}`` по каждому движению ВОЗВРАТА аренды: сохранённое
    ``amount``, либо авто-расчёт. Для показа в «Движениях»."""
    result = {}
    for item in rental.items.all():
        price = item.price_per_day
        return_rows, _ = _replay_item(item)
        for m, unit_days in return_rows:
            charge = m.amount if m.amount is not None else Decimal(unit_days) * price
            result[m.id] = charge.quantize(Decimal('0.01'))
    return result


def overdue_fine_coef() -> Decimal:
    raw = getattr(settings, 'RENTAL_OVERDUE_FINE_COEF', DEFAULT_OVERDUE_FINE_COEF)
    return raw if isinstance(raw, Decimal) else Decimal(str(raw))


def compute_rental_billing(rental, as_of=None) -> dict:
    """Return a dict with base / fine / paid / deposit / total."""
    if as_of is None:
        as_of = timezone.now()
    today = as_of.date()
    coef = overdue_fine_coef()

    base = Decimal('0.00')
    fine = Decimal('0.00')
    # due_date теперь DateTimeField — берём дневную часть для счёта дней
    # просрочки. Один день начинает капать со следующих суток после due_date.
    overdue_days = (today - rental.due_date.date()).days
    if overdue_days < 0:
        overdue_days = 0

    is_closed = rental.status == Rental.Status.CLOSED
    for item in rental.items.all():
        base += compute_item_base(item, as_of=as_of)
        outstanding = item.outstanding_qty
        if not is_closed and overdue_days > 0 and outstanding > 0:
            fine += (
                Decimal(outstanding)
                * item.price_per_day
                * coef
                * Decimal(overdue_days)
            )

    payments = list(rental.payments.all())
    # ADVANCE — это предоплата, фактически зачитывается в счёт аренды,
    # поэтому считаем её вместе с RENT/FINE в «оплачено».
    paid = sum(
        (p.amount for p in payments
         if p.kind in (Payment.Kind.RENT, Payment.Kind.FINE,
                       Payment.Kind.ADVANCE)),
        Decimal('0.00'),
    )
    deposit = sum(
        (p.amount for p in payments if p.kind == Payment.Kind.DEPOSIT),
        Decimal('0.00'),
    )
    refunded = sum(
        (p.amount for p in payments if p.kind == Payment.Kind.REFUND),
        Decimal('0.00'),
    )
    deposit_held = deposit - refunded

    total_due = base + fine - deposit_held - paid

    return {
        'base': base.quantize(Decimal('0.01')),
        'fine': fine.quantize(Decimal('0.01')),
        'overdue_days': overdue_days,
        'paid': paid.quantize(Decimal('0.01')),
        'deposit': deposit.quantize(Decimal('0.01')),
        'refunded': refunded.quantize(Decimal('0.01')),
        'deposit_held': deposit_held.quantize(Decimal('0.01')),
        'total_due': total_due.quantize(Decimal('0.01')),
        'coef': coef,
    }
