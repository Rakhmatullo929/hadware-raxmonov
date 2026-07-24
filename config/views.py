import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, Replace
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.views import View
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
)

from . import billing
from .decorators import role_required, user_is_admin
from .forms import (
    CategoryForm,
    CustomerForm,
    MoneyDecimalField,
    PaymentForm,
    ProductForm,
    RentalCreateForm,
    RentalEditForm,
    SalaryEntryForm,
    WorkerForm,
)
from .models import (
    Attendance,
    Category,
    Customer,
    MonthlySalaryBase,
    Movement,
    Payment,
    Product,
    Rental,
    RentalItem,
    SalaryEntry,
    Worker,
)


# ---------- access mixins ----------

class StaffOrAdminRequiredMixin:
    @method_decorator(role_required('staff', 'admin'))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)


class AdminRequiredMixin:
    @method_decorator(role_required('admin'))
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)


# ---------- entry / stubs ----------

def root(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse('dashboard'))
    return HttpResponseRedirect(reverse('login'))


@cache_page(60)
@vary_on_headers('Cookie')
@role_required('staff', 'admin')
def dashboard(request):
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    active_statuses = [Rental.Status.ACTIVE, Rental.Status.OVERDUE]

    # Per-rental outstanding via independent Subqueries
    issued_sub = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.ISSUE)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    returned_sub = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.RETURN)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    rentals_open = (
        Rental.objects
        .filter(status__in=active_statuses)
        .annotate(
            _issued=Coalesce(Subquery(issued_sub, output_field=IntegerField()), 0),
            _returned=Coalesce(Subquery(returned_sub, output_field=IntegerField()), 0),
        )
        .annotate(_outstanding=F('_issued') - F('_returned'))
    )

    # 1) Cards
    active_count = Rental.objects.filter(status__in=active_statuses).count()

    now = timezone.now()
    overdue_qs = rentals_open.filter(due_date__lt=now, _outstanding__gt=0)
    overdue_count = overdue_qs.count()
    overdue_outstanding_qty = overdue_qs.aggregate(s=Sum('_outstanding'))['s'] or 0

    # due_date теперь DateTimeField — сравниваем дневную часть.
    returns_today_count = (
        Rental.objects
        .filter(status__in=active_statuses, due_date__date=today)
        .count()
    )

    top_products = list(
        Product.objects.filter(is_active=True).order_by('-stock_total')[:5]
    )
    top_pids = [p.pk for p in top_products]
    if top_pids:
        rows = (
            Movement.objects
            .filter(
                rental_item__product_id__in=top_pids,
                rental_item__rental__status__in=active_statuses,
            )
            .values('rental_item__product_id')
            .annotate(
                issued=Coalesce(Sum('qty', filter=Q(kind=Movement.Kind.ISSUE)), 0),
                returned=Coalesce(Sum('qty', filter=Q(kind=Movement.Kind.RETURN)), 0),
            )
        )
        out_map = {
            r['rental_item__product_id']: r['issued'] - r['returned']
            for r in rows
        }
    else:
        out_map = {}
    top_park = []
    for p in top_products:
        out = out_map.get(p.pk, 0)
        available = max(0, p.stock_total - out)
        stock_total = p.stock_total or 1
        utilization = min(100, int(round(100 * out / stock_total)))
        if utilization >= 90:
            tone = 'danger'
        elif utilization >= 70:
            tone = 'warn'
        else:
            tone = 'ok'
        top_park.append({
            'product': p,
            'available': available,
            'in_rent': out,
            'stock_total': p.stock_total,
            'utilization_pct': utilization,
            'tone': tone,
        })

    # 2) Overdue table — top 50 by days
    items_with_outstanding = (
        RentalItem.objects
        .annotate(
            issued=Coalesce(
                Sum('movements__qty', filter=Q(movements__kind=Movement.Kind.ISSUE)),
                0,
            ),
            returned=Coalesce(
                Sum('movements__qty', filter=Q(movements__kind=Movement.Kind.RETURN)),
                0,
            ),
        )
        .annotate(outstanding=F('issued') - F('returned'))
        .filter(outstanding__gt=0)
        .select_related('product')
    )
    overdue_list = list(
        overdue_qs
        .select_related('customer')
        .prefetch_related(Prefetch(
            'items',
            queryset=items_with_outstanding,
            to_attr='outstanding_list',
        ))
        .order_by('due_date')[:50]
    )
    for r in overdue_list:
        r.days_overdue = (today - r.due_date.date()).days

    # 3) Returns today/tomorrow
    returns_soon = list(
        Rental.objects
        .filter(status__in=active_statuses, due_date__date__in=[today, tomorrow])
        .select_related('customer')
        .annotate(items_count=Count('items', distinct=True))
        .order_by('due_date', 'id')
    )

    # 4) Last 20 movements
    last_movements = list(
        Movement.objects
        .select_related(
            'rental_item__product',
            'rental_item__rental__customer',
            'created_by',
        )
        .order_by('-date')[:20]
    )

    # 5) «Подозрения по нормам товаров» — берём готовый helper, который
    # шарим со страницей в сайдбаре, и обрезаем дашборд первыми 30.
    suspicious_rows = _collect_product_suspicions()[:30]

    return render(request, 'config/dashboard.html', {
        'active_count': active_count,
        'overdue_count': overdue_count,
        'overdue_outstanding_qty': overdue_outstanding_qty,
        'returns_today_count': returns_today_count,
        'top_park': top_park,
        'overdue_list': overdue_list,
        'returns_soon': returns_soon,
        'last_movements': last_movements,
        'suspicious_rows': suspicious_rows,
        'today': today,
        'tomorrow': tomorrow,
        'now': now,
    })


@role_required('admin')
def reports(request):
    return render(request, 'config/reports/index.html')


# ---------- reports: revenue ----------

def _parse_period(request, default_days=None):
    """Parse ?date_from / ?date_to from request; default = current month."""
    today = timezone.localdate()
    raw_from = (request.GET.get('date_from') or '').strip()
    raw_to = (request.GET.get('date_to') or '').strip()
    try:
        date_from = datetime.strptime(raw_from, '%Y-%m-%d').date()
    except ValueError:
        date_from = today.replace(day=1)
    try:
        date_to = datetime.strptime(raw_to, '%Y-%m-%d').date()
    except ValueError:
        date_to = today
    if date_to < date_from:
        date_from, date_to = date_to, date_from
    return date_from, date_to


@role_required('admin')
def report_revenue(request):
    date_from, date_to = _parse_period(request)
    period_days = (date_to - date_from).days + 1
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=period_days - 1)

    def _series(df, dt):
        rows = (
            Payment.objects
            .filter(
                kind__in=[Payment.Kind.RENT, Payment.Kind.FINE],
                date__date__gte=df,
                date__date__lte=dt,
            )
            .values('date__date')
            .annotate(s=Sum('amount'))
        )
        by_day = {r['date__date']: r['s'] or Decimal('0') for r in rows}
        labels = []
        values = []
        cur = df
        while cur <= dt:
            labels.append(cur.isoformat())
            values.append(float(by_day.get(cur, Decimal('0'))))
            cur += timedelta(days=1)
        return labels, values, sum((Decimal(str(v)) for v in values), Decimal('0'))

    labels, current_values, current_total = _series(date_from, date_to)
    _, prev_values, prev_total = _series(prev_from, prev_to)

    delta = current_total - prev_total
    delta_pct = None
    if prev_total > 0:
        delta_pct = float(((current_total - prev_total) / prev_total) * 100)

    return render(request, 'config/reports/revenue.html', {
        'date_from': date_from,
        'date_to': date_to,
        'prev_from': prev_from,
        'prev_to': prev_to,
        'labels': labels,
        'current_values': current_values,
        'prev_values': prev_values,
        'current_total': current_total,
        'prev_total': prev_total,
        'delta': delta,
        'delta_pct': delta_pct,
    })


# ---------- reports: payment methods ----------


@role_required('admin')
def report_payment_methods(request):
    """Сводка по способам оплаты: сколько прошло наличными / картой,
    с разбивкой по типу платежа (залог/аванс/аренда/штраф/возврат)."""
    date_from, date_to = _parse_period(request)

    qs = (
        Payment.objects
        .filter(date__date__gte=date_from, date__date__lte=date_to)
    )

    # Сводка по (method, kind) — Σ amount + N
    rows = (
        qs.values('method', 'kind')
        .annotate(total=Sum('amount'), count=Count('id'))
        .order_by('method', 'kind')
    )

    # Перегруппируем под удобный шаблон.
    kinds_order = [
        Payment.Kind.DEPOSIT, Payment.Kind.ADVANCE, Payment.Kind.RENT,
        Payment.Kind.FINE, Payment.Kind.REFUND,
    ]
    methods_order = [Payment.Method.CASH, Payment.Method.CARD]

    matrix = {m: {k: {'total': Decimal('0.00'), 'count': 0}
                  for k in kinds_order} for m in methods_order}
    for r in rows:
        m = r['method']
        k = r['kind']
        if m in matrix and k in matrix[m]:
            matrix[m][k]['total'] = r['total'] or Decimal('0.00')
            matrix[m][k]['count'] = r['count'] or 0

    # Итоги по способам и по типам.
    by_method = {m: sum((matrix[m][k]['total'] for k in kinds_order),
                        Decimal('0.00')) for m in methods_order}
    by_kind = {k: sum((matrix[m][k]['total'] for m in methods_order),
                      Decimal('0.00')) for k in kinds_order}
    grand_total = sum(by_method.values(), Decimal('0.00'))

    method_labels = {
        Payment.Method.CASH: _('Наличные'),
        Payment.Method.CARD: _('Карта'),
    }
    kind_labels = {
        Payment.Kind.DEPOSIT: _('Залог'),
        Payment.Kind.ADVANCE: _('Аванс'),
        Payment.Kind.RENT: _('Аренда'),
        Payment.Kind.FINE: _('Штраф'),
        Payment.Kind.REFUND: _('Возврат залога'),
    }

    return render(request, 'config/reports/payment_methods.html', {
        'date_from': date_from,
        'date_to': date_to,
        'methods': methods_order,
        'kinds': kinds_order,
        'matrix': matrix,
        'by_method': by_method,
        'by_kind': by_kind,
        'grand_total': grand_total,
        'method_labels': method_labels,
        'kind_labels': kind_labels,
    })


# ---------- reports: top products ----------

@role_required('admin')
def report_top_products(request):
    date_from, date_to = _parse_period(request)

    items = (
        RentalItem.objects
        .filter(
            rental__created_at__date__gte=date_from,
            rental__created_at__date__lte=date_to,
        )
        .select_related('product')
        .prefetch_related('movements')
    )

    by_product = {}
    for it in items:
        days = billing.compute_item_unit_days(it)
        bucket = by_product.setdefault(it.product_id, {
            'product': it.product,
            'turnover': Decimal('0.00'),
            'issues': 0,
            'total_qty': 0,
        })
        bucket['turnover'] += Decimal(days) * it.price_per_day
        bucket['issues'] += 1
        bucket['total_qty'] += it.qty

    rows = list(by_product.values())
    rows.sort(key=lambda r: r['turnover'], reverse=True)
    rows_by_turnover = rows[:15]
    rows_by_freq = sorted(rows, key=lambda r: r['issues'], reverse=True)[:15]

    return render(request, 'config/reports/top_products.html', {
        'date_from': date_from,
        'date_to': date_to,
        'rows_by_turnover': rows_by_turnover,
        'rows_by_freq': rows_by_freq,
    })


# ---------- reports: debtors ----------

def _debtors_rows():
    """Walk non-closed rentals, group by customer, compute total_due/outstanding."""
    today = timezone.localdate()
    rentals = (
        Rental.objects
        .filter(status__in=[Rental.Status.ACTIVE, Rental.Status.OVERDUE])
        .select_related('customer')
        .prefetch_related('items__movements', 'payments')
    )
    by_cust = {}
    for r in rentals:
        summary = billing.compute_rental_billing(r)
        outstanding_qty = sum(it.outstanding_qty for it in r.items.all())
        days_overdue = max(0, (today - r.due_date.date()).days)
        bucket = by_cust.setdefault(r.customer_id, {
            'customer': r.customer,
            'rentals': 0,
            'total_due': Decimal('0.00'),
            'outstanding_qty': 0,
            'max_days_overdue': 0,
        })
        bucket['rentals'] += 1
        bucket['total_due'] += summary['total_due']
        bucket['outstanding_qty'] += outstanding_qty
        if days_overdue > bucket['max_days_overdue']:
            bucket['max_days_overdue'] = days_overdue

    return [
        b for b in by_cust.values()
        if b['outstanding_qty'] > 0 or b['total_due'] > 0
    ]


@role_required('admin')
def report_debtors(request):
    rows = _debtors_rows()
    rows.sort(key=lambda r: r['total_due'], reverse=True)
    grand_total = sum((r['total_due'] for r in rows), Decimal('0.00'))
    grand_qty = sum((r['outstanding_qty'] for r in rows), 0)
    return render(request, 'config/reports/debtors.html', {
        'rows': rows,
        'grand_total': grand_total,
        'grand_qty': grand_qty,
    })


@role_required('admin')
def report_debtors_csv(request):
    import csv
    from io import StringIO

    rows = _debtors_rows()
    rows.sort(key=lambda r: r['total_due'], reverse=True)

    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow([
        _('ФИО'), _('Телефон'), _('Аренд'), _('Невозвращено (шт)'),
        _('Дней просрочки (макс)'), _('К получению'),
    ])
    for r in rows:
        writer.writerow([
            r['customer'].full_name,
            r['customer'].phone or '',
            r['rentals'],
            r['outstanding_qty'],
            r['max_days_overdue'],
            f"{r['total_due']:.2f}",
        ])

    body = '﻿' + buffer.getvalue()  # UTF-8 BOM for Excel
    response = HttpResponse(
        body.encode('utf-8'),
        content_type='text/csv; charset=utf-8',
    )
    today = timezone.localdate().isoformat()
    response['Content-Disposition'] = f'attachment; filename="debtors-{today}.csv"'
    return response


# ---------- reports: stock snapshot ----------

@role_required('admin')
def report_stock(request):
    raw = (request.GET.get('date') or '').strip()
    today = timezone.localdate()
    try:
        on_date = datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        on_date = today
    end_dt = datetime.combine(
        on_date + timedelta(days=1),
        datetime.min.time(),
        tzinfo=timezone.get_current_timezone(),
    )

    products = list(Product.objects.filter(is_active=True).order_by('name'))
    rows = (
        Movement.objects
        .filter(date__lt=end_dt)
        .values('rental_item__product_id')
        .annotate(
            issued=Coalesce(Sum('qty', filter=Q(kind=Movement.Kind.ISSUE)), 0),
            returned=Coalesce(Sum('qty', filter=Q(kind=Movement.Kind.RETURN)), 0),
        )
    )
    out_map = {
        r['rental_item__product_id']: r['issued'] - r['returned']
        for r in rows
    }
    table = []
    for p in products:
        in_rent = max(0, out_map.get(p.pk, 0))
        free = p.stock_total - in_rent
        table.append({
            'product': p,
            'in_rent': in_rent,
            'free': free,
        })

    return render(request, 'config/reports/stock.html', {
        'on_date': on_date,
        'today': today,
        'rows': table,
    })


# ---------- reports: returns (приёмка возврата товара) ----------

def _movement_local_date(m):
    """Локальная дата движения (как у фильтра ``date__date``)."""
    dt = m.date
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.date()


def _returns_rows(date_from, date_to):
    """``(rows, daily, totals)`` по движениям ВОЗВРАТА за период.

    * ``rows``   — ``[{date, customer, rental_id, product, qty, amount}]``, по дате;
    * ``daily``  — ``{'labels': [...], 'values': [float, ...]}`` Σ начислено по дням;
    * ``totals`` — ``{'amount': Decimal, 'qty': int, 'count': int}``.

    Сумма берётся из ``billing.return_charge_map`` (сохранённый ``Movement.amount``
    либо авто-расчёт ``unit_days × price``) — один вызов на аренду, FIFO не дублируем.
    """
    movements = list(
        Movement.objects
        .filter(
            kind=Movement.Kind.RETURN,
            date__date__gte=date_from,
            date__date__lte=date_to,
        )
        .select_related(
            'rental_item__product',
            'rental_item__rental__customer',
        )
        .order_by('date', 'id')
    )

    charge_by_mid = {}
    seen_rentals = set()
    for m in movements:
        rental = m.rental_item.rental
        if rental.id not in seen_rentals:
            seen_rentals.add(rental.id)
            charge_by_mid.update(billing.return_charge_map(rental))

    rows = []
    by_day = {}
    total_amount = Decimal('0.00')
    total_qty = 0
    for m in movements:
        amount = charge_by_mid.get(m.id, Decimal('0.00'))
        d = _movement_local_date(m)
        rows.append({
            'date': m.date,
            'customer': m.rental_item.rental.customer,
            'rental_id': m.rental_item.rental_id,
            'product': m.rental_item.product,
            'qty': m.qty,
            'amount': amount,
        })
        by_day[d] = by_day.get(d, Decimal('0.00')) + amount
        total_amount += amount
        total_qty += m.qty

    labels, values = [], []
    cur = date_from
    while cur <= date_to:
        labels.append(cur.isoformat())
        values.append(float(by_day.get(cur, Decimal('0.00'))))
        cur += timedelta(days=1)

    daily = {'labels': labels, 'values': values}
    totals = {'amount': total_amount, 'qty': total_qty, 'count': len(movements)}
    return rows, daily, totals


@role_required('admin')
def report_returns(request):
    date_from, date_to = _parse_period(request)
    rows, daily, totals = _returns_rows(date_from, date_to)
    return render(request, 'config/reports/returns.html', {
        'today': timezone.localdate(),
        'date_from': date_from,
        'date_to': date_to,
        'rows': rows,
        'labels': daily['labels'],
        'values': daily['values'],
        'totals': totals,
    })


@role_required('admin')
def report_returns_csv(request):
    import csv
    from io import StringIO

    date_from, date_to = _parse_period(request)
    rows, _daily, _totals = _returns_rows(date_from, date_to)

    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=';')
    writer.writerow([
        _('Дата'), _('Клиент'), _('Телефон'), _('Аренда №'),
        _('Товар'), _('Кол-во'), _('Начислено'),
    ])
    for r in rows:
        dt = r['date']
        if timezone.is_aware(dt):
            dt = timezone.localtime(dt)
        writer.writerow([
            dt.strftime('%Y-%m-%d %H:%M'),
            r['customer'].full_name,
            r['customer'].phone or '',
            r['rental_id'],
            r['product'].name,
            r['qty'],
            f"{r['amount']:.2f}",
        ])

    body = '﻿' + buffer.getvalue()  # UTF-8 BOM for Excel
    response = HttpResponse(
        body.encode('utf-8'),
        content_type='text/csv; charset=utf-8',
    )
    fname = f'returns-{date_from.isoformat()}_{date_to.isoformat()}.csv'
    response['Content-Disposition'] = f'attachment; filename="{fname}"'
    return response


# ---------- products ----------

# Разделитель размера в названиях товаров пишется кириллической «х»
# (напр. «Корейская опалубка 2х1»). Но оператор при поиске может набрать
# латинскую x, знак умножения × или кириллическую х — и в любом регистре.
# Эти помощники приводят и запрос, и поле к одной форме, чтобы поиск находил
# товар независимо от того, каким символом записан размер. Запятая → точка:
# в прайс-листе размеры писались через запятую (2,2x40), в каталоге — точкой.
_SIZE_SEP_CHARS = '×xXхХ'


def normalize_size_query(q: str) -> str:
    """Канонизировать пользовательский ввод поиска товара."""
    q = re.sub(f'[{_SIZE_SEP_CHARS}]', 'х', q)
    return q.replace(',', '.')


def annotate_size_normalized_name(qs):
    """Добавить `_norm_name` — название с разделителем размера, приведённым к
    кириллической «х», и запятой → точке."""
    expr = F('name')
    for ch in ('×', 'x', 'X', 'Х'):
        expr = Replace(expr, Value(ch), Value('х'))
    expr = Replace(expr, Value(','), Value('.'))
    return qs.annotate(_norm_name=expr)


class ProductListView(StaffOrAdminRequiredMixin, ListView):
    model = Product
    template_name = 'config/products/list.html'
    context_object_name = 'products'
    paginate_by = 25

    def get_queryset(self):
        qs = Product.objects.select_related('category').order_by('name')
        q = self.request.GET.get('q', '').strip()
        category_id = self.request.GET.get('category', '').strip()
        if q:
            qs = annotate_size_normalized_name(qs).filter(
                _norm_name__icontains=normalize_size_query(q))
        if category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))
        return qs

    def get_template_names(self):
        if self.request.htmx:
            return ['config/products/_table.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['categories'] = Category.objects.all()
        ctx['q'] = self.request.GET.get('q', '')
        ctx['selected_category'] = self.request.GET.get('category', '')
        return ctx


class ProductCreateView(AdminRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'config/products/form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Новый товар')
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            _('Товар «%(name)s» создан.') % {'name': form.instance.name},
        )
        return super().form_valid(form)


class ProductUpdateView(AdminRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'config/products/form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Товар: %(name)s') % {'name': self.object.name}
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            _('Товар «%(name)s» сохранён.') % {'name': form.instance.name},
        )
        return super().form_valid(form)


class ProductToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = not product.is_active
        product.save(update_fields=['is_active'])
        if product.is_active:
            msg = _('Товар «%(name)s» активирован.') % {'name': product.name}
        else:
            msg = _('Товар «%(name)s» деактивирован.') % {'name': product.name}
        messages.success(request, msg)
        return HttpResponseRedirect(
            request.META.get('HTTP_REFERER') or reverse('product_list')
        )


class CategoryCreateView(AdminRequiredMixin, View):
    """Создание категории двумя путями.

    Полная страница (ссылка «Категория» в списке товаров) — как обычная форма
    с редиректом в список. htmx-запрос (кнопка «+» рядом с полем «Категория» в
    форме товара) — модалка + OOB-подстановка новой категории в select, не
    сбрасывая наполовину заполненную форму товара.
    """

    full_page_context = {'title': _('Новая категория')}

    def get(self, request):
        form = CategoryForm()
        if request.headers.get('HX-Request'):
            return render(request, 'config/products/_category_create_modal.html',
                          {'form': form})
        return render(request, 'config/products/form.html',
                      {'form': form, **self.full_page_context})

    def post(self, request):
        form = CategoryForm(request.POST)
        is_htmx = bool(request.headers.get('HX-Request'))
        if not form.is_valid():
            if is_htmx:
                return render(request, 'config/products/_category_create_modal.html',
                              {'form': form})
            return render(request, 'config/products/form.html',
                          {'form': form, **self.full_page_context})
        category = form.save()
        if is_htmx:
            # Отдаём только OOB-версию поля категории: модалка (в #modal-slot)
            # получает пустой innerHTML и закрывается, а select обновляется на
            # месте с уже выбранной новой категорией.
            pform = ProductForm(initial={'category': category.pk})
            return render(request, 'config/products/_category_field.html',
                          {'category_field': pform['category'], 'oob': True})
        messages.success(
            request,
            _('Категория «%(name)s» создана.') % {'name': category.name},
        )
        return HttpResponseRedirect(reverse('product_list'))


# ---------- customers ----------

class CustomerListView(StaffOrAdminRequiredMixin, ListView):
    model = Customer
    template_name = 'config/customers/list.html'
    context_object_name = 'customers'
    paginate_by = 25

    def get_queryset(self):
        qs = Customer.objects.order_by('full_name')
        # По умолчанию архивные клиенты скрыты; ?archived=1 — показать архив.
        if self.request.GET.get('archived') != '1':
            qs = qs.filter(archived_at__isnull=True)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(code__icontains=q)
            )
        return qs

    def get_template_names(self):
        if self.request.htmx:
            return ['config/customers/_table.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['show_archived'] = self.request.GET.get('archived') == '1'
        ctx['archived_count'] = Customer.objects.filter(
            archived_at__isnull=False
        ).count()
        return ctx


class CustomerCreateView(StaffOrAdminRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'config/customers/form.html'

    def get_success_url(self):
        return reverse('customer_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Новый клиент')
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            _('Клиент «%(name)s» создан.') % {'name': form.instance.full_name},
        )
        return super().form_valid(form)


class CustomerUpdateView(StaffOrAdminRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'config/customers/form.html'

    def get_success_url(self):
        return reverse('customer_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = _('Клиент: %(name)s') % {'name': self.object.full_name}
        return ctx

    def form_valid(self, form):
        messages.success(
            self.request,
            _('Клиент «%(name)s» сохранён.') % {'name': form.instance.full_name},
        )
        return super().form_valid(form)


class CustomerArchiveView(StaffOrAdminRequiredMixin, View):
    """Архивировать клиента, завершившего сделку (нет активных аренд).

    Архив обратим (см. CustomerUnarchiveView) и лишь скрывает клиента из
    списка и поиска — данные и история аренд остаются."""

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        if customer.is_archived:
            messages.info(request, _('Клиент уже в архиве.'))
        elif not customer.can_archive:
            messages.error(
                request,
                _('Нельзя архивировать «%(name)s»: есть активные аренды. '
                  'Сначала закройте все аренды клиента.')
                % {'name': customer.full_name},
            )
        else:
            customer.archived_at = timezone.now()
            customer.save(update_fields=['archived_at'])
            messages.success(
                request,
                _('Клиент «%(name)s» отправлен в архив.')
                % {'name': customer.full_name},
            )
        return redirect('customer_detail', pk=customer.pk)


class CustomerUnarchiveView(StaffOrAdminRequiredMixin, View):
    """Вернуть клиента из архива."""

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        if customer.is_archived:
            customer.archived_at = None
            customer.save(update_fields=['archived_at'])
            messages.success(
                request,
                _('Клиент «%(name)s» возвращён из архива.')
                % {'name': customer.full_name},
            )
        return redirect('customer_detail', pk=customer.pk)


class CustomerDetailView(StaffOrAdminRequiredMixin, DetailView):
    model = Customer
    template_name = 'config/customers/detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = (
            self.object.rentals
            .select_related('created_by')
            .prefetch_related('items__product')
            .order_by('-created_at')
        )
        # Аннотируем теми же суммами, что и список аренд: items_count,
        # paid_total, deposit_total, outstanding_total — чтобы показать
        # финансовые детали и остаток «на руках» прямо в карточке клиента.
        ctx['rentals'] = _annotate_rental_qs(qs)
        ctx['now'] = timezone.now()
        return ctx


# ---------- rentals ----------

def _annotate_rental_qs(qs):
    """Attach issued/returned/outstanding/items_count and money totals as
    Subquery annotations to keep aggregates from interfering with each other."""
    issued_sum = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.ISSUE)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    returned_sum = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.RETURN)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    paid_sum = (
        Payment.objects
        .filter(
            rental=OuterRef('pk'),
            kind__in=[Payment.Kind.RENT, Payment.Kind.FINE],
        )
        .values('rental')
        .annotate(s=Sum('amount'))
        .values('s')
    )
    deposit_sum = (
        Payment.objects
        .filter(rental=OuterRef('pk'), kind=Payment.Kind.DEPOSIT)
        .values('rental')
        .annotate(s=Sum('amount'))
        .values('s')
    )
    money = DecimalField(max_digits=12, decimal_places=2)
    return qs.annotate(
        items_count=Count('items', distinct=True),
        issued_total=Coalesce(Subquery(issued_sum, output_field=IntegerField()), 0),
        returned_total=Coalesce(Subquery(returned_sum, output_field=IntegerField()), 0),
        paid_total=Coalesce(
            Subquery(paid_sum, output_field=money), Value(Decimal('0.00')), output_field=money,
        ),
        deposit_total=Coalesce(
            Subquery(deposit_sum, output_field=money), Value(Decimal('0.00')), output_field=money,
        ),
    ).annotate(
        outstanding_total=F('issued_total') - F('returned_total'),
    )


class RentalListView(StaffOrAdminRequiredMixin, View):
    """Список аренд, сгруппированный по клиенту.

    Клиент — заголовок группы с итогами, под ним его аренды. Пагинация — по
    клиентам (аренды одного клиента не разрываются между страницами)."""

    template_name = 'config/rentals/list.html'
    paginate_by = 20  # клиентов на страницу

    SORT_FIELDS = {
        'due_date': 'due_date',
        '-due_date': '-due_date',
        'created_at': 'created_at',
        '-created_at': '-created_at',
    }

    def _filtered_rentals(self, request):
        """Отфильтрованный по GET-параметрам и отсортированный queryset аренд."""
        qs = (
            Rental.objects
            .select_related('customer', 'created_by')
        )
        qs = _annotate_rental_qs(qs)

        status = request.GET.get('status', '').strip()
        if status == Rental.Status.CLOSED:
            qs = qs.filter(status=Rental.Status.CLOSED)
        elif status == 'overdue':
            qs = qs.filter(
                status=Rental.Status.ACTIVE,
                due_date__lt=timezone.now(),
                outstanding_total__gt=0,
            )
        elif status == Rental.Status.ACTIVE:
            qs = qs.filter(status=Rental.Status.ACTIVE).filter(
                Q(due_date__gte=timezone.now()) | Q(outstanding_total=0)
            )

        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()
        for raw, lookup in ((date_from, 'created_at__date__gte'),
                            (date_to, 'created_at__date__lte')):
            if raw:
                try:
                    parsed = datetime.strptime(raw, '%Y-%m-%d').date()
                    qs = qs.filter(**{lookup: parsed})
                except ValueError:
                    pass

        # Текстовый поиск по клиенту: ФИО, телефон или код (как в форме
        # создания аренды — CustomerSearchView). Работает независимо от
        # фильтра по ID ниже, поэтому оба можно комбинировать.
        query = request.GET.get('q', '').strip()
        if query:
            qs = qs.filter(
                Q(customer__full_name__icontains=query)
                | Q(customer__phone__icontains=query)
                | Q(customer__code__icontains=query)
            )

        customer_id = request.GET.get('customer', '').strip()
        if customer_id.isdigit():
            qs = qs.filter(customer_id=int(customer_id))

        sort = request.GET.get('sort', 'due_date')
        sort_field = self.SORT_FIELDS.get(sort, 'due_date')
        return qs.order_by(sort_field, '-created_at')

    @staticmethod
    def _is_overdue(r, now):
        return (r.status == Rental.Status.ACTIVE
                and r.due_date < now and r.outstanding_total > 0)

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        rqs = self._filtered_rentals(request)

        # Порядок клиентов = порядок их первого появления в наборе аренд,
        # отсортированном по срочности. Так первый (ближайший срок / просрочка)
        # задаёт позицию клиента. Без GROUP BY — не конфликтует с
        # подзапросами-аннотациями _annotate_rental_qs.
        seen = set()
        customer_ids = []
        for cid in rqs.values_list('customer_id', flat=True):
            if cid not in seen:
                seen.add(cid)
                customer_ids.append(cid)

        paginator = Paginator(customer_ids, self.paginate_by)
        page_obj = paginator.get_page(request.GET.get('page'))
        page_ids = list(page_obj.object_list)

        # Аренды клиентов текущей страницы, сгруппированные в Python.
        by_cust = {}
        for r in rqs.filter(customer_id__in=page_ids):
            by_cust.setdefault(r.customer_id, []).append(r)

        def rank(r):
            # Внутри группы: просроченные → активные → закрытые.
            if self._is_overdue(r, now):
                return 0
            if r.status == Rental.Status.ACTIVE:
                return 1
            return 2

        groups = []
        for cid in page_ids:
            rs = by_cust.get(cid)
            if not rs:
                continue
            rs.sort(key=lambda r: (rank(r), r.due_date))
            overdue_count = sum(1 for r in rs if self._is_overdue(r, now))
            groups.append({
                'customer': rs[0].customer,
                'rentals': rs,
                'count': len(rs),
                'on_hand': sum(r.outstanding_total for r in rs),
                'overdue_count': overdue_count,
                'has_overdue': overdue_count > 0,
            })

        filters = {
            'status': request.GET.get('status', ''),
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
            'q': request.GET.get('q', ''),
            'customer': request.GET.get('customer', ''),
            'sort': request.GET.get('sort', 'due_date'),
        }
        ctx = {
            'groups': groups,
            # Плоский список аренд текущей страницы (в порядке групп) — для
            # обратной совместимости и тестов; шаблон рендерит через `groups`.
            'rentals': [r for g in groups for r in g['rentals']],
            'page_obj': page_obj,
            'paginator': paginator,
            'is_paginated': page_obj.has_other_pages(),
            'now': now,
            'today': timezone.localdate(),
            'filters': filters,
            'customer_total': len(customer_ids),
            'rental_total': rqs.count(),
        }
        if filters['customer'].isdigit():
            ctx['filter_customer_obj'] = Customer.objects.filter(
                pk=int(filters['customer'])
            ).first()
        return render(request, self.template_name, ctx)


def _rental_card_context(rental):
    """Shared context for the detail page and OOB refreshes after a return."""
    now = timezone.now()
    items = list(rental.items.select_related('product').all())
    movements = []
    for it in items:
        # Полная аренда по строке (возвращённое + набег по остатку до `now`) —
        # построчная расшифровка базы аренды; вешаем на объект для шаблона.
        it.line_base = billing.compute_item_base(it, as_of=now).quantize(Decimal('0.01'))
        movements.extend(list(it.movements.select_related('created_by').all()))
    movements.sort(key=lambda m: m.date, reverse=True)
    # Сумма начисления по каждому возврату (сохранённая либо авто-расчёт) —
    # навешиваем прямо на объект движения, чтобы шаблон проверял `m.charge`.
    charges = billing.return_charge_map(rental)
    for m in movements:
        m.charge = charges.get(m.id)
    payments = list(rental.payments.all())
    summary = billing.compute_rental_billing(rental, as_of=now)
    has_outstanding = any(it.outstanding_qty > 0 for it in items)
    return {
        'rental': rental,
        'items': items,
        'movements': movements,
        'payments': payments,
        'summary': summary,
        'has_outstanding': has_outstanding,
        'today': timezone.localdate(),
        'now': now,
    }


class RentalDetailView(StaffOrAdminRequiredMixin, DetailView):
    model = Rental
    template_name = 'config/rentals/detail.html'
    context_object_name = 'rental'

    def get_queryset(self):
        return (
            Rental.objects
            .select_related('customer', 'created_by', 'closed_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_rental_card_context(self.object))
        return ctx


@role_required('staff', 'admin')
def rental_card(request, pk):
    """HTML-фрагмент полной карточки аренды для встраивания в аккордеон
    карточки клиента. Тот же контент, что на странице аренды (_card.html),
    но без base.html — грузится HTMX-запросом при раскрытии строки."""
    rental = get_object_or_404(
        Rental.objects
        .select_related('customer', 'created_by', 'closed_by')
        .prefetch_related(
            'items__product',
            'items__movements__created_by',
            'payments',
        ),
        pk=pk,
    )
    return render(request, 'config/rentals/_card.html', _rental_card_context(rental))


def _parse_local_dt(raw):
    """'2026-07-14T03:22' (datetime-local) → aware-datetime в текущем поясе.

    Пусто или неразбираемо → None (вызывающий решает: дефолт «сейчас» или ошибка).
    """
    raw = (raw or '').strip()
    if not raw:
        return None
    try:
        naive = datetime.strptime(raw, '%Y-%m-%dT%H:%M')
    except ValueError:
        return None
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _return_modal_context(rental, outstanding_items, *, inputs, errors, note,
                          amount_inputs=None, return_at_value=None):
    """Контекст для модалки возврата.

    Для каждой позиции считаем ``days_avg`` — округлённые «дни на единицу»
    (unit_days / outstanding). Поле суммы начисления авто-подставляется на
    клиенте как ``qty × days_avg × price`` (см. static/js/return-amount.js) и
    правится оператором; итог в подвале тоже считается вживую.
    """
    rows = []
    for it in outstanding_items:
        out = it.outstanding_qty
        unit_days = billing.compute_item_unit_days(it)
        days_avg = (unit_days // out) if out > 0 else 0
        rows.append({
            'item': it,
            'outstanding': out,
            'value': (inputs or {}).get(it.pk, ''),
            'amount_value': (amount_inputs or {}).get(it.pk, ''),
            'days_avg': days_avg,
            'price_per_day': it.price_per_day,
        })
    return {
        'rental': rental,
        'rows': rows,
        'errors': errors,
        'note': note,
        'period_from': rental.created_at,
        'period_to': timezone.now(),
        'return_at_value': return_at_value or timezone.localtime(
            timezone.now()).strftime('%Y-%m-%dT%H:%M'),
    }


def _parse_movement_ids(raw):
    """'1,2,x,3' → [1, 2, 3]. Невалидные токены отбрасываются."""
    ids = []
    for tok in (raw or '').split(','):
        tok = tok.strip()
        if tok.isdigit():
            ids.append(int(tok))
    return ids


def _receipt_days(unit_days, qty):
    """Число дней аренды для строки чека: ``unit_days / qty``.

    Обычно партию выдают одной датой, поэтому дни у всех единиц одинаковы и
    деление точное (целое). Если единицы партии выданы в разные даты (FIFO по
    нескольким чанкам), дни на единицу различаются — показываем среднее с одним
    знаком, чтобы Кол-во × За день × Дней всё равно сходилось с суммой.
    """
    if not qty:
        return 0
    if unit_days % qty == 0:
        return unit_days // qty
    return round(unit_days / qty, 1)


def build_return_receipt_context(rental, movement_ids):
    """Контекст чека возврата по партии движений (см. ?m=...).

    Берём только движения ВОЗВРАТА этой аренды с указанными id (чужие/
    несуществующие отбрасываются). Суммы — через billing.return_charge_map
    (тот же источник, что таймлайн/отчёт). Строки отсортированы по дате;
    receipt_dt — момент самого раннего движения партии.
    """
    charges = billing.return_charge_map(rental)
    unit_days_map = billing.return_unit_days_map(rental)
    movements = (
        Movement.objects
        .filter(
            rental_item__rental=rental,
            kind=Movement.Kind.RETURN,
            id__in=movement_ids,
        )
        .select_related('rental_item__product__category')
        .order_by('date', 'id')
    )
    rows = []
    total_qty = 0
    total_amount = Decimal('0.00')
    note = ''
    for m in movements:
        it = m.rental_item
        amount = charges.get(m.id) or Decimal('0.00')
        rows.append({
            'category': it.product.category,
            'name': it.product.name,
            'qty': m.qty,
            'unit': it.product.unit,
            'price_per_day': it.price_per_day,
            'days': _receipt_days(unit_days_map.get(m.id, 0), m.qty),
            'amount': amount,
            'date': m.date,
            # Допы комплекта, домноженные на кол-во в этой партии возврата:
            # «Зажим ×3» на 12 шт → 36 шт.
            'kit': [
                {'name': name, 'qty': per_unit * m.qty}
                for name, per_unit in it.product.kit_items()
            ],
        })
        total_qty += m.qty
        total_amount += amount
        if not note and m.note:
            note = m.note
    return {
        'rental': rental,
        'customer': rental.customer,
        'rows': rows,
        'total_qty': total_qty,
        'total_amount': total_amount,
        'receipt_dt': rows[0]['date'] if rows else None,
        'note': note,
    }


class RentalReturnView(StaffOrAdminRequiredMixin, View):
    def get(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        if rental.status == Rental.Status.CLOSED:
            return HttpResponse(status=204)
        outstanding = list(rental.outstanding_items().select_related('product'))
        return render(request, 'config/rentals/_return_modal.html',
                      _return_modal_context(rental, outstanding,
                                            inputs=None, errors=[], note=''))

    def post(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        if rental.status == Rental.Status.CLOSED:
            return HttpResponse(status=409)

        outstanding_items = list(rental.outstanding_items().select_related('product'))
        item_by_id = {it.pk: it for it in outstanding_items}

        note = (request.POST.get('note') or '').strip()
        inputs = {}
        amount_inputs = {}
        plan = []  # list of (item, qty, amount|None)
        errors = []
        return_at_raw = (request.POST.get('return_at') or '').strip()
        return_at = _parse_local_dt(return_at_raw)
        if return_at is None:
            if return_at_raw:
                errors.append(_('Укажите корректные дату и время возврата.'))
            return_at = timezone.now()
        amount_parser = MoneyDecimalField(
            max_digits=12, decimal_places=2, required=False,
        )

        for it in outstanding_items:
            raw = (request.POST.get(f'qty_{it.pk}') or '').strip()
            inputs[it.pk] = raw
            raw_amount = (request.POST.get(f'amount_{it.pk}') or '').strip()
            amount_inputs[it.pk] = raw_amount
            if raw == '':
                continue
            try:
                qty = int(raw)
            except (TypeError, ValueError):
                errors.append(
                    _('«%(name)s»: некорректное количество.')
                    % {'name': it.product.name}
                )
                continue
            if qty < 0:
                errors.append(
                    _('«%(name)s»: количество не может быть отрицательным.')
                    % {'name': it.product.name}
                )
                continue
            if qty == 0:
                continue
            if qty > it.outstanding_qty:
                errors.append(
                    _('«%(name)s»: возвращаете %(qty)d, а к возврату только %(out)d.')
                    % {
                        'name': it.product.name,
                        'qty': qty,
                        'out': it.outstanding_qty,
                    }
                )
                continue
            # Сумма начисления: пусто → посчитаем авто-расчёт при создании.
            amount = None
            if raw_amount:
                try:
                    amount = amount_parser.clean(raw_amount)
                except ValidationError:
                    errors.append(
                        _('«%(name)s»: некорректная сумма.')
                        % {'name': it.product.name}
                    )
                    continue
                if amount is not None and amount < 0:
                    errors.append(
                        _('«%(name)s»: сумма не может быть отрицательной.')
                        % {'name': it.product.name}
                    )
                    continue
            plan.append((it, qty, amount))

        if not errors and not plan:
            errors.append(_('Укажите количество хотя бы по одной позиции.'))

        if errors:
            return render(request, 'config/rentals/_return_modal.html',
                          _return_modal_context(rental, outstanding_items,
                                                inputs=inputs, errors=errors,
                                                note=note,
                                                amount_inputs=amount_inputs,
                                                return_at_value=return_at_raw))

        created_ids = []
        with transaction.atomic():
            for it, qty, amount in plan:
                if amount is None:
                    amount = billing.compute_return_amount_for_qty(
                        it, qty, as_of=return_at)
                mv = Movement.objects.create(
                    rental_item=it,
                    kind=Movement.Kind.RETURN,
                    qty=qty,
                    amount=amount,
                    date=return_at,
                    note=note,
                    created_by=request.user,
                )
                created_ids.append(mv.pk)
            rental.refresh_from_db()
            rental.maybe_auto_close()

        rental = (
            Rental.objects
            .select_related('customer', 'created_by', 'closed_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
            .get(pk=rental.pk)
        )
        ctx = _rental_card_context(rental)
        ctx['is_admin'] = user_is_admin(request.user)
        response = render(request, 'config/rentals/_oob_refresh.html', ctx)
        if created_ids:
            ids_q = ','.join(str(i) for i in created_ids)
            receipt_url = (
                reverse('rental_return_receipt', args=[rental.pk])
                + f'?m={ids_q}&autoprint=1'
            )
            response['HX-Trigger'] = json.dumps(
                {'openReturnReceipt': {'url': receipt_url}}
            )
        return response


class RentalCloseView(AdminRequiredMixin, View):
    """Early close: write off remaining outstanding qty as 'списание'."""

    def get(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        if rental.status == Rental.Status.CLOSED:
            return HttpResponse(status=204)
        return render(request, 'config/rentals/_close_modal.html', {
            'rental': rental,
            'outstanding_items': list(rental.outstanding_items().select_related('product')),
            'errors': [],
            'note': '',
        })

    def post(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        if rental.status == Rental.Status.CLOSED:
            return HttpResponse(status=409)

        note = (request.POST.get('note') or '').strip()
        if not note:
            return render(request, 'config/rentals/_close_modal.html', {
                'rental': rental,
                'outstanding_items': list(rental.outstanding_items().select_related('product')),
                'errors': [_('Укажите причину досрочного закрытия (списание / потеря).')],
                'note': note,
            })

        with transaction.atomic():
            outstanding = list(rental.outstanding_items().select_related('product'))
            for it in outstanding:
                qty = it.outstanding_qty
                if qty > 0:
                    Movement.objects.create(
                        rental_item=it,
                        kind=Movement.Kind.RETURN,
                        qty=qty,
                        note=f'списание: {note}',
                        created_by=request.user,
                    )
            rental.status = Rental.Status.CLOSED
            rental.closed_at = timezone.now()
            rental.closed_by = request.user
            rental.save(update_fields=['status', 'closed_at', 'closed_by'])

        rental = (
            Rental.objects
            .select_related('customer', 'created_by', 'closed_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
            .get(pk=rental.pk)
        )
        ctx = _rental_card_context(rental)
        ctx['is_admin'] = True
        return render(request, 'config/rentals/_oob_refresh.html', ctx)


class RentalModalCloseView(StaffOrAdminRequiredMixin, View):
    """Empty-200 endpoint to wipe out #modal-slot's content via hx-swap=innerHTML."""

    def get(self, request):
        return HttpResponse('')


@role_required('staff', 'admin')
def rental_contract(request, pk):
    from .contract_pdf import normalize_size

    rental = get_object_or_404(
        Rental.objects.select_related('customer'), pk=pk,
    )
    items = list(
        rental.items.select_related('product', 'product__category').all()
    )
    # Стоимость позиции = кол-во × цена/сут (аренда за сутки за эту позицию).
    for it in items:
        it.line_cost = it.qty * it.price_per_day
    total_cost = sum((it.line_cost for it in items), Decimal('0.00'))
    deposit_paid = sum(
        (p.amount for p in rental.payments.filter(kind=Payment.Kind.DEPOSIT)),
        Decimal('0.00'),
    )
    total_deposit_due = sum(
        (it.product.deposit_per_unit * it.qty for it in items),
        Decimal('0.00'),
    )
    # «Сколько вернул и на какую сумму»: суммарный возврат по аренде.
    charges = billing.return_charge_map(rental)
    returned_amount = sum(charges.values(), Decimal('0.00'))
    returned_qty = (
        Movement.objects
        .filter(rental_item__rental=rental, kind=Movement.Kind.RETURN)
        .aggregate(q=Sum('qty'))['q'] or 0
    )
    from django.conf import settings as _s
    size = normalize_size(request.GET.get('size'))
    return render(request, 'config/rentals/contract.html', {
        'rental': rental,
        'items': items,
        'total_cost': total_cost,
        'deposit_paid': deposit_paid,
        'total_deposit_due': total_deposit_due,
        'returned_qty': returned_qty,
        'returned_amount': returned_amount,
        'back_url': reverse('rental_detail', args=[rental.pk]),
        'size': size,
    })


@role_required('staff', 'admin')
def rental_return_receipt(request, pk):
    """HTML-чек возврата (печать из браузера). ?m=ids — партия движений,
    ?size=full|half|quarter (по умолчанию quarter), ?autoprint=1 — печать сразу."""
    from .contract_pdf import ALLOWED_SIZES

    rental = get_object_or_404(
        Rental.objects.select_related('customer'), pk=pk,
    )
    ids = _parse_movement_ids(request.GET.get('m'))
    ctx = build_return_receipt_context(rental, ids)
    if not ctx['rows']:
        raise Http404('Нет движений возврата для чека.')

    size = request.GET.get('size')
    if size not in ALLOWED_SIZES:
        size = 'quarter'
    ids_q = ','.join(str(i) for i in ids)
    ctx.update({
        'size': size,
        'autoprint': request.GET.get('autoprint') == '1',
        'pdf_url': reverse('rental_return_receipt_pdf', args=[rental.pk]) + f'?m={ids_q}',
        'back_url': reverse('rental_detail', args=[rental.pk]),
    })
    return render(request, 'config/rentals/return_receipt.html', ctx)


@role_required('staff', 'admin')
def rental_contract_pdf(request, pk):
    """Скачать договор аренды как PDF (fpdf2, без системных зависимостей).

    Параметр ?size=full|half|quarter определяет формат:
    A4 / A5 / A6 соответственно.
    """
    from .contract_pdf import (
        ContractDependencyMissing,
        ContractFontMissing,
        build_contract_pdf,
        normalize_size,
    )

    rental = get_object_or_404(
        Rental.objects
        .select_related('customer')
        .prefetch_related('items__product', 'payments'),
        pk=pk,
    )
    size = normalize_size(request.GET.get('size'))
    try:
        pdf_bytes = build_contract_pdf(rental, size=size)
    except (ContractFontMissing, ContractDependencyMissing) as e:
        messages.error(request, str(e))
        return HttpResponseRedirect(reverse('rental_detail', args=[rental.pk]))

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    filename = f'contract-{rental.pk}-{size}.pdf'
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response


@role_required('staff', 'admin')
def rental_return_receipt_pdf(request, pk):
    """Скачать чек возврата как PDF (fpdf2). Параметр ?m=ids — партия движений."""
    from .pdf_common import PdfDependencyMissing, PdfFontMissing
    from .return_receipt_pdf import build_return_receipt_pdf

    rental = get_object_or_404(
        Rental.objects.select_related('customer'), pk=pk,
    )
    ids = _parse_movement_ids(request.GET.get('m'))
    ctx = build_return_receipt_context(rental, ids)
    if not ctx['rows']:
        raise Http404('Нет движений возврата для чека.')
    try:
        pdf_bytes = build_return_receipt_pdf(ctx)
    except (PdfFontMissing, PdfDependencyMissing) as e:
        messages.error(request, str(e))
        return HttpResponseRedirect(reverse('rental_detail', args=[rental.pk]))

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if request.GET.get('inline') else 'attachment'
    response['Content-Disposition'] = (
        f'{disposition}; filename="return-receipt-{rental.pk}.pdf"'
    )
    return response


class RentalCreateView(StaffOrAdminRequiredMixin, View):
    template_name = 'config/rentals/create.html'

    def get(self, request):
        customer = self._modal_customer(request)
        if customer is not None:
            ctx = self._initial_context(request)
            ctx['customer'] = customer
            return render(request,
                          'config/rentals/_create_rental_modal.html', ctx)
        return render(request, self.template_name, self._initial_context(request))

    def post(self, request):
        form = RentalCreateForm(request.POST)
        rows = self._parse_item_rows(request.POST)
        item_errors = self._validate_items(rows)
        ok = form.is_valid() and not item_errors
        # Модальный режим (карточка клиента): ?customer=<pk> + htmx.
        modal_customer = self._modal_customer(request)

        if ok:
            try:
                rental = self._create_rental(request, form, rows)
            except ValueError as e:
                item_errors.append(str(e))
                ok = False
            else:
                messages.success(
                    request,
                    _('Аренда #%(pk)d создана. Выдано %(qty)d шт.')
                    % {
                        'pk': rental.pk,
                        'qty': sum(r['qty'] for r in rows),
                    },
                )
                url = reverse('rental_detail', args=[rental.pk])
                if modal_customer is not None:
                    # htmx-модалка: полный редирект браузера на страницу аренды.
                    resp = HttpResponse(status=204)
                    resp['HX-Redirect'] = url
                    return resp
                return HttpResponseRedirect(url)

        ctx = self._initial_context(request)
        ctx['form'] = form
        ctx['item_rows'] = self._rows_for_template(rows)
        ctx['item_errors'] = item_errors
        if modal_customer is not None:
            # Ошибки валидации — перерисовываем модалку на месте.
            ctx['customer'] = modal_customer
            return render(request,
                          'config/rentals/_create_rental_modal.html', ctx)
        if form.cleaned_data.get('customer'):
            ctx['picked_customer'] = form.cleaned_data['customer']
        return render(request, self.template_name, ctx)

    def _modal_customer(self, request):
        """Клиент для модального режима создания аренды с карточки клиента:
        ?customer=<pk> и htmx-запрос. Архивных не обслуживаем (их не выбрать
        и в обычном поиске)."""
        pk = request.GET.get('customer', '')
        if getattr(request, 'htmx', False) and pk.isdigit():
            return Customer.objects.filter(
                pk=int(pk), archived_at__isnull=True,
            ).first()
        return None

    def _initial_context(self, request):
        return {
            'form': RentalCreateForm(),
            'item_rows': [{'row_id': uuid.uuid4().hex[:8], 'product': None, 'qty': ''}],
            'item_errors': [],
            'picked_customer': None,
            'today_iso': timezone.localdate().isoformat(),
            'products': Product.objects.filter(is_active=True).order_by('name'),
        }

    def _parse_item_rows(self, post):
        product_ids = post.getlist('item_product')
        qtys = post.getlist('item_qty')
        rows = []
        for pid_raw, qty_raw in zip(product_ids, qtys):
            pid_raw = (pid_raw or '').strip()
            qty_raw = (qty_raw or '').strip()
            if not pid_raw and not qty_raw:
                continue
            try:
                pid = int(pid_raw)
                qty = int(qty_raw)
            except (TypeError, ValueError):
                rows.append({'product_id': pid_raw, 'qty': qty_raw, 'invalid': True})
                continue
            rows.append({'product_id': pid, 'qty': qty, 'invalid': False})
        return rows

    def _validate_items(self, rows):
        errors = []
        if not rows:
            errors.append(_('Добавьте хотя бы одну позицию.'))
            return errors
        for i, r in enumerate(rows, start=1):
            if r.get('invalid'):
                errors.append(
                    _('Строка %(i)d: некорректные значения.') % {'i': i}
                )
                continue
            if r['qty'] <= 0:
                errors.append(
                    _('Строка %(i)d: количество должно быть больше нуля.')
                    % {'i': i}
                )
                continue
            try:
                p = Product.objects.get(pk=r['product_id'], is_active=True)
            except Product.DoesNotExist:
                errors.append(
                    _('Строка %(i)d: товар не найден или отключён.') % {'i': i}
                )
                continue
            if r['qty'] > p.available_stock:
                errors.append(
                    _(
                        'Строка %(i)d: «%(name)s» — доступно %(avail)d %(unit)s, '
                        'запрошено %(qty)d.'
                    )
                    % {
                        'i': i,
                        'name': p.name,
                        'avail': p.available_stock,
                        'unit': p.unit,
                        'qty': r['qty'],
                    }
                )
            r['product_obj'] = p
        return errors

    @transaction.atomic
    def _create_rental(self, request, form, rows):
        rental = form.save(commit=False)
        rental.created_by = request.user
        if not rental.created_at:
            rental.created_at = timezone.now()
        rental.status = Rental.Status.ACTIVE
        rental.save()

        for r in rows:
            product = r['product_obj']
            if r['qty'] > product.available_stock:
                raise ValueError(
                    _('«%(name)s»: доступно %(avail)d, запрошено %(qty)d')
                    % {
                        'name': product.name,
                        'avail': product.available_stock,
                        'qty': r['qty'],
                    }
                )
            item = RentalItem.objects.create(
                rental=rental,
                product=product,
                qty=r['qty'],
                price_per_day=product.daily_price,
            )
            Movement.objects.create(
                rental_item=item,
                kind=Movement.Kind.ISSUE,
                qty=r['qty'],
                created_by=request.user,
            )

        deposit = form.cleaned_data.get('initial_deposit') or Decimal('0')
        if deposit > 0:
            Payment.objects.create(
                rental=rental,
                amount=deposit,
                kind=Payment.Kind.DEPOSIT,
                note='Платёж при выдаче',
            )
        return rental

    def _rows_for_template(self, rows):
        out = []
        for r in rows:
            row_id = uuid.uuid4().hex[:8]
            product = r.get('product_obj')
            if product is None and isinstance(r.get('product_id'), int):
                product = Product.objects.filter(pk=r['product_id']).first()
            out.append({
                'row_id': row_id,
                'product': product,
                'qty': r.get('qty', ''),
            })
        if not out:
            out = [{'row_id': uuid.uuid4().hex[:8], 'product': None, 'qty': ''}]
        return out


# ---------- HTMX endpoints for rental form ----------

@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerSearchView(View):
    def get(self, request):
        q = request.GET.get('customer_q', '').strip()
        if len(q) < 2:
            return render(request, 'config/rentals/_customer_search_results.html',
                          {'customers': [], 'q': q, 'too_short': True})
        customers = (
            Customer.objects
            .filter(archived_at__isnull=True)  # архивных не предлагаем в аренду
            .filter(
                Q(full_name__icontains=q)
                | Q(phone__icontains=q)
                | Q(code__icontains=q)
            )
            .order_by('full_name')[:10]
        )
        return render(request, 'config/rentals/_customer_search_results.html',
                      {'customers': customers, 'q': q, 'too_short': False})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerPickView(View):
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        return render(request, 'config/rentals/_customer_picked.html',
                      {'picked_customer': customer})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerClearView(View):
    def get(self, request):
        return render(request, 'config/rentals/_customer_search_input.html')


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerCreateInlineView(View):
    """Создание клиента прямо со страницы аренды.

    GET — открывает модалку (опционально с предзаполненным ФИО из поисковой
    строки `customer_q`).
    POST — валидирует и сохраняет; в случае успеха возвращает HTML, который
    одновременно закрывает модалку и подставляет нового клиента как выбранного
    (через hx-swap-oob по `#customer-section`).
    """

    def get(self, request):
        prefill = (request.GET.get('customer_q') or '').strip()
        form = CustomerForm(initial={'full_name': prefill} if prefill else None)
        return render(request,
                      'config/rentals/_customer_create_modal.html',
                      {'form': form})

    def post(self, request):
        form = CustomerForm(request.POST)
        if not form.is_valid():
            return render(request,
                          'config/rentals/_customer_create_modal.html',
                          {'form': form})
        customer = form.save()
        return render(request,
                      'config/rentals/_customer_create_oob.html',
                      {'picked_customer': customer})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ProductInfoView(View):
    def get(self, request):
        pid = request.GET.get('item_product') or ''
        if not pid.isdigit():
            return HttpResponse('')
        product = Product.objects.filter(pk=int(pid)).first()
        if not product:
            return HttpResponse('')
        return render(request, 'config/rentals/_product_info.html',
                      {'product': product})


# ---------- product picker (typeahead для позиций аренды) ----------


def _safe_row_id(raw):
    """Защита от XSS/injection: row_id используется в HTML id и hx-target,
    поэтому пропускаем только короткие alphanumeric-токены (uuid4-хвосты
    или явные литералы вроде 'modal')."""
    import re
    raw = (raw or '').strip()
    if re.fullmatch(r'[a-zA-Z0-9]{4,16}', raw):
        return raw
    return ''


def _safe_field_name(raw):
    """Имя поля используется как `name=` у скрытого input. Допускаем только
    латиницу, цифры и подчёркивания. Пустое — отдаём дефолт."""
    import re
    raw = (raw or '').strip()
    if re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,31}', raw):
        return raw
    return 'item_product'


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemProductSearchView(View):
    def get(self, request):
        q = (request.GET.get('item_product_q') or '').strip()
        row_id = _safe_row_id(request.GET.get('row_id'))
        field_name = _safe_field_name(request.GET.get('field_name'))
        ctx = {'q': q, 'row_id': row_id, 'field_name': field_name}
        if len(q) < 2:
            ctx.update(products=[], too_short=True)
            return render(request,
                          'config/rentals/_item_product_results.html', ctx)
        products = (
            annotate_size_normalized_name(
                Product.objects.filter(is_active=True))
            .filter(_norm_name__icontains=normalize_size_query(q))
            .order_by('name')[:10]
        )
        ctx.update(products=products, too_short=False)
        return render(request,
                      'config/rentals/_item_product_results.html', ctx)


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemProductPickView(View):
    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk, is_active=True)
        row_id = _safe_row_id(request.GET.get('row_id'))
        field_name = _safe_field_name(request.GET.get('field_name'))
        return render(request,
                      'config/rentals/_item_product_picked.html',
                      {'product': product, 'row_id': row_id,
                       'field_name': field_name})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemProductClearView(View):
    def get(self, request):
        row_id = _safe_row_id(request.GET.get('row_id'))
        field_name = _safe_field_name(request.GET.get('field_name'))
        return render(request,
                      'config/rentals/_item_product_search.html',
                      {'row_id': row_id, 'field_name': field_name})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemRowNewView(View):
    def get(self, request):
        return render(request, 'config/rentals/_item_row.html', {
            'row': {'row_id': uuid.uuid4().hex[:8], 'product': None, 'qty': ''},
        })


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemRowRemoveView(View):
    """No-op endpoint; the actual removal is done client-side via hx-swap=delete."""
    def post(self, request):
        return HttpResponse(status=204)


# ---------- Admin: edit rental, payments, items (HTMX modals) ----------

def _reload_rental(pk):
    return (
        Rental.objects
        .select_related('customer', 'created_by', 'closed_by')
        .prefetch_related(
            'items__product',
            'items__movements__created_by',
            'payments',
        )
        .get(pk=pk)
    )


def _oob_response(request, rental):
    ctx = _rental_card_context(rental)
    ctx['is_admin'] = user_is_admin(request.user)
    return render(request, 'config/rentals/_oob_refresh.html', ctx)


class RentalEditView(AdminRequiredMixin, View):
    """Правка срока возврата и примечания у существующей аренды."""

    def get(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        form = RentalEditForm(instance=rental)
        return render(request, 'config/rentals/_edit_modal.html', {
            'rental': rental, 'form': form,
        })

    def post(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        form = RentalEditForm(request.POST, instance=rental)
        if not form.is_valid():
            return render(request, 'config/rentals/_edit_modal.html', {
                'rental': rental, 'form': form,
            })
        form.save()
        messages.success(request, _('Аренда #%(pk)d обновлена.') % {'pk': rental.pk})
        return _oob_response(request, _reload_rental(rental.pk))


class RentalPaymentAddView(AdminRequiredMixin, View):
    def get(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        return render(request, 'config/rentals/_payment_modal.html', {
            'rental': rental, 'form': PaymentForm(), 'is_edit': False,
        })

    def post(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        form = PaymentForm(request.POST)
        if not form.is_valid():
            return render(request, 'config/rentals/_payment_modal.html', {
                'rental': rental, 'form': form, 'is_edit': False,
            })
        payment = form.save(commit=False)
        payment.rental = rental
        payment.save()
        messages.success(
            request,
            _('Платёж %(a)s добавлен.') % {'a': payment.amount},
        )
        return _oob_response(request, _reload_rental(rental.pk))


class RentalPaymentEditView(AdminRequiredMixin, View):
    def _get_objs(self, pk, payment_pk):
        rental = get_object_or_404(Rental, pk=pk)
        payment = get_object_or_404(Payment, pk=payment_pk, rental=rental)
        return rental, payment

    def get(self, request, pk, payment_pk):
        rental, payment = self._get_objs(pk, payment_pk)
        return render(request, 'config/rentals/_payment_modal.html', {
            'rental': rental,
            'form': PaymentForm(instance=payment),
            'is_edit': True,
            'payment': payment,
        })

    def post(self, request, pk, payment_pk):
        rental, payment = self._get_objs(pk, payment_pk)
        form = PaymentForm(request.POST, instance=payment)
        if not form.is_valid():
            return render(request, 'config/rentals/_payment_modal.html', {
                'rental': rental, 'form': form,
                'is_edit': True, 'payment': payment,
            })
        form.save()
        messages.success(request, _('Платёж обновлён.'))
        return _oob_response(request, _reload_rental(rental.pk))


class RentalPaymentDeleteView(AdminRequiredMixin, View):
    def post(self, request, pk, payment_pk):
        rental = get_object_or_404(Rental, pk=pk)
        payment = get_object_or_404(Payment, pk=payment_pk, rental=rental)
        payment.delete()
        messages.success(request, _('Платёж удалён.'))
        return _oob_response(request, _reload_rental(rental.pk))


class RentalItemAddView(AdminRequiredMixin, View):
    """Добавить новую позицию к существующей аренде (с выдачей со склада)."""

    def get(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        return render(request, 'config/rentals/_item_modal.html', {
            'rental': rental,
            'errors': [],
            'picked_product': None,
            'qty_value': '',
        })

    def post(self, request, pk):
        rental = get_object_or_404(Rental, pk=pk)
        pid = (request.POST.get('product') or '').strip()
        qty_raw = (request.POST.get('qty') or '').strip()
        errors = []

        product = None
        if not pid.isdigit():
            errors.append(_('Выберите товар.'))
        else:
            product = Product.objects.filter(pk=int(pid), is_active=True).first()
            if product is None:
                errors.append(_('Товар не найден или отключён.'))

        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            errors.append(_('Количество должно быть больше нуля.'))
        elif product is not None and qty > product.available_stock:
            errors.append(
                _('«%(name)s» — доступно %(avail)d, запрошено %(qty)d.')
                % {
                    'name': product.name,
                    'avail': product.available_stock,
                    'qty': qty,
                }
            )

        if errors:
            return render(request, 'config/rentals/_item_modal.html', {
                'rental': rental,
                'errors': errors,
                'picked_product': product,
                'qty_value': qty_raw,
            })

        with transaction.atomic():
            item = RentalItem.objects.create(
                rental=rental, product=product, qty=qty,
                price_per_day=product.daily_price,
            )
            Movement.objects.create(
                rental_item=item, kind=Movement.Kind.ISSUE,
                qty=qty, created_by=request.user,
            )
            if rental.status == Rental.Status.CLOSED:
                rental.status = Rental.Status.ACTIVE
                rental.closed_at = None
                rental.closed_by = None
                rental.save(update_fields=['status', 'closed_at', 'closed_by'])

        messages.success(
            request,
            _('Позиция «%(name)s» × %(qty)d добавлена.')
            % {'name': product.name, 'qty': qty},
        )
        return _oob_response(request, _reload_rental(rental.pk))


class RentalItemEditView(AdminRequiredMixin, View):
    """Изменить позицию аренды: количество (не меньше уже выданного) и цену
    за сутки (снимок этой аренды, не влияет на справочник товара)."""

    def _get_objs(self, pk, item_pk):
        rental = get_object_or_404(Rental, pk=pk)
        item = get_object_or_404(
            RentalItem.objects.select_related('product'),
            pk=item_pk, rental=rental,
        )
        return rental, item

    def get(self, request, pk, item_pk):
        rental, item = self._get_objs(pk, item_pk)
        return render(request, 'config/rentals/_item_edit_modal.html', {
            'rental': rental, 'item': item, 'errors': [],
        })

    def post(self, request, pk, item_pk):
        rental, item = self._get_objs(pk, item_pk)
        qty_raw = (request.POST.get('qty') or '').strip()
        errors = []
        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            qty = -1
        issued = item.issued_qty
        if qty <= 0:
            errors.append(_('Количество должно быть больше нуля.'))
        elif qty < issued:
            errors.append(
                _('Нельзя заказать меньше уже выданного (%(n)d).')
                % {'n': issued}
            )

        # Цена — снимок именно этой аренды, правит только админ. Обрабатываем
        # только если поле пришло (модалка его всегда шлёт); посты без него
        # оставляют цену как есть. Терпим пробелы-разделители и запятую-дробь.
        new_price = None
        if 'price_per_day' in request.POST:
            price_raw = (request.POST.get('price_per_day') or '').strip()
            price_norm = (price_raw.replace(' ', '')
                          .replace('\xa0', '').replace(',', '.'))
            try:
                parsed = Decimal(price_norm)
            except (InvalidOperation, TypeError, ValueError):
                parsed = None
            if parsed is None:
                errors.append(_('Цена за сутки указана неверно.'))
            elif parsed < 0:
                errors.append(_('Цена за сутки не может быть отрицательной.'))
            else:
                new_price = parsed.quantize(Decimal('0.01'))

        if errors:
            return render(request, 'config/rentals/_item_edit_modal.html', {
                'rental': rental, 'item': item, 'errors': errors,
            })
        item.qty = qty
        update_fields = ['qty']
        if new_price is not None:
            item.price_per_day = new_price
            update_fields.append('price_per_day')
        item.save(update_fields=update_fields)
        messages.success(request, _('Позиция обновлена.'))
        return _oob_response(request, _reload_rental(rental.pk))


class RentalMovementEditView(AdminRequiredMixin, View):
    """Правка времени (Movement.date) у движения ВОЗВРАТА. Только admin.

    Сумму не трогает; работает и на закрытой аренде («в любое время»).
    Движение обязано быть возвратом этой аренды — иначе 404.
    """

    def _get_objs(self, pk, movement_pk):
        rental = get_object_or_404(Rental, pk=pk)
        movement = get_object_or_404(
            Movement.objects.select_related('rental_item__product'),
            pk=movement_pk, rental_item__rental=rental,
            kind=Movement.Kind.RETURN,
        )
        return rental, movement

    def _render_modal(self, request, rental, movement, date_value, errors):
        return render(request, 'config/rentals/_movement_edit_modal.html', {
            'rental': rental, 'movement': movement,
            'date_value': date_value, 'errors': errors,
        })

    def get(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        date_value = timezone.localtime(movement.date).strftime('%Y-%m-%dT%H:%M')
        return self._render_modal(request, rental, movement, date_value, [])

    def post(self, request, pk, movement_pk):
        rental, movement = self._get_objs(pk, movement_pk)
        raw = (request.POST.get('date') or '').strip()
        new_dt = _parse_local_dt(raw)
        if new_dt is None:
            return self._render_modal(
                request, rental, movement, raw,
                [_('Укажите корректные дату и время.')],
            )
        movement.date = new_dt
        movement.save(update_fields=['date'])
        messages.success(request, _('Время возврата обновлено.'))
        return _oob_response(request, _reload_rental(rental.pk))


class RentalItemRemoveView(AdminRequiredMixin, View):
    """Удалить позицию. Разрешено только если по ней ничего не выдано."""

    def post(self, request, pk, item_pk):
        rental = get_object_or_404(Rental, pk=pk)
        item = get_object_or_404(
            RentalItem.objects.select_related('product'),
            pk=item_pk, rental=rental,
        )
        if item.issued_qty > 0:
            messages.error(
                request,
                _('Нельзя удалить «%(name)s»: уже была выдача. '
                  'Сначала оформите возврат или досрочное закрытие.')
                % {'name': item.product.name},
            )
            return _oob_response(request, _reload_rental(rental.pk))
        name = item.product.name
        item.delete()
        messages.success(
            request, _('Позиция «%(name)s» удалена.') % {'name': name},
        )
        return _oob_response(request, _reload_rental(rental.pk))


# ---------- product suspicions (превышение нормы проката) ----------


def _collect_product_suspicions(*, only_over=False):
    """Собрать список позиций, превышающих свою норму (warn/over).

    Возвращает list-of-dicts уже отсортированный: сначала ``over``,
    внутри — по убыванию превышения. Используется и страницей-листингом,
    и контекст-процессором (для счётчика в сайдбаре, там нужен только
    `len`).
    """
    items = (
        RentalItem.objects
        .filter(
            rental__status__in=[Rental.Status.ACTIVE, Rental.Status.OVERDUE],
            product__expected_max_days__isnull=False,
        )
        .select_related('product', 'rental', 'rental__customer')
        .prefetch_related('movements')
    )
    rows = []
    for it in items:
        status = it.expected_status()
        if only_over and status != 'over':
            continue
        if not only_over and status not in ('warn', 'over'):
            continue
        if it.outstanding_qty <= 0:
            continue
        rows.append({
            'item': it,
            'status': status,
            'days_elapsed': it.days_since_first_issue,
            'max_days': it.product.expected_max_days,
            'over_by': max(0, it.days_since_first_issue - it.product.expected_max_days),
        })
    rows.sort(
        key=lambda r: (0 if r['status'] == 'over' else 1, -r['over_by']),
    )
    return rows


@role_required('staff', 'admin')
def product_suspicions(request):
    """Отдельная страница «Подозрения по нормам товаров».

    Доступна из сайдбара. По умолчанию показывает и warn (на грани),
    и over (превышение). ``?only=over`` оставляет только просрочки.
    """
    only_over = (request.GET.get('only') or '').strip() == 'over'
    rows = _collect_product_suspicions(only_over=only_over)
    warn_count = sum(1 for r in rows if r['status'] == 'warn')
    over_count = sum(1 for r in rows if r['status'] == 'over')
    return render(request, 'config/suspicions/list.html', {
        'rows': rows,
        'only_over': only_over,
        'warn_count': warn_count,
        'over_count': over_count,
        'total': len(rows),
    })


# ---------- attendance ----------


def _parse_attendance_date(request):
    """Прочитать ?date=YYYY-MM-DD; по умолчанию — сегодня."""
    raw = (request.GET.get('date') or '').strip()
    try:
        return datetime.strptime(raw, '%Y-%m-%d').date()
    except ValueError:
        return timezone.localdate()


@role_required('staff', 'admin')
def attendance_journal(request):
    """Главная страница посещаемости: дата + таблица активных рабочих
    с отметками +/−. Каждая строка интерактивна через htmx."""
    date = _parse_attendance_date(request)
    workers = list(Worker.objects.filter(is_active=True))
    by_worker = {
        a.worker_id: a for a in
        Attendance.objects.filter(date=date, worker__in=workers)
    }
    rows = [{
        'worker': w,
        'attendance': by_worker.get(w.pk),
    } for w in workers]

    present = sum(1 for r in rows if r['attendance'] and r['attendance'].is_present)
    absent = sum(1 for r in rows
                 if r['attendance'] and not r['attendance'].is_present)
    unmarked = len(rows) - present - absent

    return render(request, 'config/attendance/journal.html', {
        'date': date,
        'date_iso': date.isoformat(),
        'rows': rows,
        'total': len(rows),
        'present': present,
        'absent': absent,
        'unmarked': unmarked,
        'prev_date': (date - timedelta(days=1)).isoformat(),
        'next_date': (date + timedelta(days=1)).isoformat(),
        'today_iso': timezone.localdate().isoformat(),
    })


@role_required('staff', 'admin')
def attendance_mark_all(request):
    """POST: отметить всех активных рабочих присутствующими на выбранный день.

    Заполняет только НЕотмеченных — существующие отметки (и «+», и «−»)
    не трогаются. Так безопасно: если сначала отметили отсутствующих,
    кнопка их не перезапишет. Дата — из ?date=YYYY-MM-DD (как у toggle).
    """
    if request.method != 'POST':
        return HttpResponse(status=405)

    date = _parse_attendance_date(request)
    workers = list(Worker.objects.filter(is_active=True))
    already = set(
        Attendance.objects
        .filter(date=date, worker__in=workers)
        .values_list('worker_id', flat=True)
    )
    to_create = [
        Attendance(
            worker=w, date=date, is_present=True,
            marked_by=request.user, marked_at=timezone.now(),
        )
        for w in workers if w.pk not in already
    ]
    if to_create:
        # ignore_conflicts — предохранитель от гонки (двойной клик /
        # два админа): уникальный (worker, date) не даст дублей и 500.
        Attendance.objects.bulk_create(to_create, ignore_conflicts=True)
        messages.success(
            request,
            _('Отмечено присутствующими: %(n)d') % {'n': len(to_create)},
        )
    else:
        messages.info(request, _('Все рабочие уже отмечены на этот день.'))

    return redirect(f"{reverse('attendance_journal')}?date={date.isoformat()}")


@role_required('staff', 'admin')
def attendance_toggle(request, worker_id):
    """htmx POST: переключить отметку рабочего на дату ?date=YYYY-MM-DD.

    Тело принимает ``status``: ``present`` | ``absent`` | ``clear``.
    Возвращает HTML-фрагмент новой строки (одна `<tr>`).
    """
    if request.method != 'POST':
        return HttpResponse(status=405)
    worker = get_object_or_404(Worker, pk=worker_id, is_active=True)
    date = _parse_attendance_date(request)
    status = (request.POST.get('status') or '').strip()

    if status == 'clear':
        Attendance.objects.filter(worker=worker, date=date).delete()
        attendance = None
    elif status in ('present', 'absent'):
        attendance, _created = Attendance.objects.update_or_create(
            worker=worker, date=date,
            defaults={
                'is_present': (status == 'present'),
                'marked_by': request.user,
                'marked_at': timezone.now(),
            },
        )
    else:
        return HttpResponse(status=400)

    return render(request, 'config/attendance/_row.html', {
        'row': {'worker': worker, 'attendance': attendance},
        'date_iso': date.isoformat(),
    })


# ---------- workers (CRUD, admin) ----------


class WorkerListView(StaffOrAdminRequiredMixin, ListView):
    model = Worker
    template_name = 'config/workers/list.html'
    context_object_name = 'workers'
    paginate_by = 50

    def get_queryset(self):
        qs = Worker.objects.all()
        q = (self.request.GET.get('q') or '').strip()
        if q:
            qs = qs.filter(
                Q(full_name__icontains=q)
                | Q(position__icontains=q)
                | Q(phone__icontains=q)
            )
        status = (self.request.GET.get('status') or '').strip()
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'archived':
            qs = qs.filter(is_active=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': self.request.GET.get('status', ''),
        }
        return ctx


class WorkerCreateView(AdminRequiredMixin, CreateView):
    model = Worker
    form_class = WorkerForm
    template_name = 'config/workers/form.html'
    success_url = reverse_lazy('worker_list')

    def form_valid(self, form):
        messages.success(
            self.request,
            _('Рабочий «%(n)s» добавлен.') % {'n': form.instance.full_name},
        )
        return super().form_valid(form)


class WorkerUpdateView(AdminRequiredMixin, UpdateView):
    model = Worker
    form_class = WorkerForm
    template_name = 'config/workers/form.html'
    success_url = reverse_lazy('worker_list')

    def form_valid(self, form):
        messages.success(self.request, _('Изменения сохранены.'))
        return super().form_valid(form)


class WorkerToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        w = get_object_or_404(Worker, pk=pk)
        w.is_active = not w.is_active
        w.save(update_fields=['is_active'])
        return HttpResponseRedirect(reverse('worker_list'))


# ---------- payroll / salary ----------


def _parse_year_month(request):
    """Прочитать ?month=YYYY-MM; по умолчанию — текущий месяц."""
    raw = (request.GET.get('month') or '').strip()
    today = timezone.localdate()
    try:
        d = datetime.strptime(raw, '%Y-%m').date()
        return d.year, d.month
    except ValueError:
        return today.year, today.month


def _month_bounds(year, month):
    """Начало месяца и эксклюзивная верхняя граница (1-е число следующего)."""
    start = datetime(year, month, 1).date()
    if month == 12:
        end = datetime(year + 1, 1, 1).date()
    else:
        end = datetime(year, month + 1, 1).date()
    return start, end


def _working_days_in_month(year, month):
    """Количество будних дней (Пн–Пт) в месяце."""
    start, end = _month_bounds(year, month)
    days = (end - start).days
    return sum(
        1 for i in range(days)
        if (start + timedelta(days=i)).weekday() < 5
    )


def _month_nav(year, month):
    """Соседние месяцы строкой YYYY-MM (для кнопок «‹ / ›»)."""
    if month == 1:
        prev_y, prev_m = year - 1, 12
    else:
        prev_y, prev_m = year, month - 1
    if month == 12:
        next_y, next_m = year + 1, 1
    else:
        next_y, next_m = year, month + 1
    return f'{prev_y}-{prev_m:02d}', f'{next_y}-{next_m:02d}'


def _quantize_money(value):
    # ROUND_HALF_UP — общепринятое денежное округление; дефолтный для Decimal
    # ROUND_HALF_EVEN (банковский) даёт расхождение с ручным расчётом ЗП.
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _resolve_month_base(worker, year, month):
    """Базовый оклад за месяц: снимок ``MonthlySalaryBase`` если он есть,
    иначе текущий контрактный ``Worker.monthly_salary``."""
    snapshot = (
        MonthlySalaryBase.objects
        .filter(worker=worker, year=year, month=month)
        .values_list('amount', flat=True)
        .first()
    )
    if snapshot is not None:
        return snapshot
    return worker.monthly_salary


def _compute_payroll(worker, year, month, present_days=None,
                     entries=None, working_days=None, monthly_base=None):
    """Свод за месяц: оклад × явка + премии − штрафы.

    Параметры ``present_days``, ``entries``, ``working_days``,
    ``monthly_base`` можно передать заранее (когда мы посчитали их пакетом
    по всем рабочим / месяцам), чтобы не дёргать БД на каждого.
    """
    if working_days is None:
        working_days = _working_days_in_month(year, month)
    if monthly_base is None:
        monthly_base = _resolve_month_base(worker, year, month)
    if present_days is None:
        start, end = _month_bounds(year, month)
        present_dates = Attendance.objects.filter(
            worker=worker, date__gte=start, date__lt=end, is_present=True,
        ).values_list('date', flat=True)
        # Считаем только будни — пропорция base = оклад × явка / рабочие дни,
        # а рабочие дни (_working_days_in_month) это Пн–Пт. Явка в выходные не
        # должна раздувать базу выше полного оклада (числитель и знаменатель
        # должны опираться на один и тот же набор дней).
        present_days = sum(1 for d in present_dates if d.weekday() < 5)
    if entries is None:
        # select_related('created_by') — модалка начислений рендерит
        # e.created_by.username; иначе был бы N+1 на каждую запись.
        entries = list(SalaryEntry.objects.filter(
            worker=worker, year=year, month=month,
        ).select_related('created_by').order_by('-created_at'))

    # monthly_base здесь всегда задан (резолвится выше); Decimal(...) сохраняет
    # 0.00 как Decimal('0.00') — `or 0` схлопнул бы реальный нулевой снимок в '0'.
    base_full = Decimal(monthly_base)
    if working_days > 0:
        base = _quantize_money(
            base_full * Decimal(present_days) / Decimal(working_days)
        )
    else:
        base = _quantize_money(0)

    bonuses = sum(
        (e.amount for e in entries if e.kind == SalaryEntry.Kind.BONUS),
        Decimal('0.00'),
    )
    penalties = sum(
        (e.amount for e in entries if e.kind == SalaryEntry.Kind.PENALTY),
        Decimal('0.00'),
    )
    total = _quantize_money(base + bonuses - penalties)

    return {
        'worker': worker,
        'year': year,
        'month': month,
        'monthly_salary': base_full,
        'working_days': working_days,
        'present_days': present_days,
        'absent_days': max(0, working_days - present_days),
        'base': base,
        'bonuses': _quantize_money(bonuses),
        'penalties': _quantize_money(penalties),
        'total': total,
        'entries': entries,
    }


def _row_context(worker, year, month):
    """Контекст для одной строки таблицы зарплат (используется и в htmx).

    is_admin=True задаём явно: _row.html гейтит редактор оклада по is_admin, а
    раздел зарплат admin-only — не полагаемся на context-processor в htmx-фрагменте.
    """
    payroll = _compute_payroll(worker, year, month)
    return {
        'row': payroll,
        'year': year,
        'month': month,
        'month_iso': f'{year}-{month:02d}',
        'is_admin': True,
    }


@role_required('admin')
def salary_index(request):
    """Таблица зарплат на месяц: оклад × явка, премии/штрафы, итого.

    Весь раздел зарплат — только для админов: оклады/премии/штрафы это
    чувствительные данные (роль staff к ним доступа не имеет).
    """
    year, month = _parse_year_month(request)
    workers = list(Worker.objects.filter(is_active=True))
    working_days = _working_days_in_month(year, month)

    start, end = _month_bounds(year, month)

    # Явка батчем — считаем только будни (Пн–Пт), согласованно с working_days.
    present_rows = (
        Attendance.objects
        .filter(worker__in=workers, date__gte=start, date__lt=end,
                is_present=True)
        .values_list('worker_id', 'date')
    )
    present_map = {}
    for wid, d in present_rows:
        if d.weekday() < 5:
            present_map[wid] = present_map.get(wid, 0) + 1

    # Начисления/удержания батчем. created_by здесь НЕ нужен (таблица
    # показывает только счётчик записей), поэтому без select_related —
    # JOIN на auth_user был бы лишней работой на этом пути.
    entries_qs = (
        SalaryEntry.objects
        .filter(worker__in=workers, year=year, month=month)
        .order_by('-created_at')
    )
    entries_map = {}
    for e in entries_qs:
        entries_map.setdefault(e.worker_id, []).append(e)

    # Помесячные снимки оклада батчем (месяц без снимка → текущий оклад).
    base_rows = (
        MonthlySalaryBase.objects
        .filter(worker__in=workers, year=year, month=month)
        .values_list('worker_id', 'amount')
    )
    base_map = {wid: amt for wid, amt in base_rows}

    rows = [
        _compute_payroll(
            w, year, month,
            present_days=present_map.get(w.pk, 0),
            entries=entries_map.get(w.pk, []),
            working_days=working_days,
            monthly_base=base_map[w.pk] if w.pk in base_map
            else w.monthly_salary,
        )
        for w in workers
    ]

    totals = {
        'base': _quantize_money(sum((r['base'] for r in rows), Decimal('0'))),
        'bonuses': _quantize_money(
            sum((r['bonuses'] for r in rows), Decimal('0'))
        ),
        'penalties': _quantize_money(
            sum((r['penalties'] for r in rows), Decimal('0'))
        ),
        'total': _quantize_money(
            sum((r['total'] for r in rows), Decimal('0'))
        ),
    }

    prev_month, next_month = _month_nav(year, month)
    today = timezone.localdate()
    return render(request, 'config/salary/index.html', {
        'rows': rows,
        'totals': totals,
        'year': year,
        'month': month,
        'month_iso': f'{year}-{month:02d}',
        'month_label': f'{month:02d}.{year}',
        'working_days': working_days,
        'prev_month': prev_month,
        'next_month': next_month,
        'this_month': f'{today.year}-{today.month:02d}',
    })


@role_required('admin')
def salary_base_update(request, worker_id):
    """htmx POST: зафиксировать оклад рабочего ЗА ЭТОТ МЕСЯЦ, вернуть строку.

    Пишем снимок ``MonthlySalaryBase`` для (worker, year, month), а не
    глобальный ``Worker.monthly_salary`` — иначе правка одного месяца
    меняла бы расчёт за все остальные.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)
    worker = get_object_or_404(Worker, pk=worker_id, is_active=True)
    year, month = _parse_year_month(request)

    # Переиспользуем MoneyDecimalField: один и тот же парсинг пробелов,
    # диапазон (>=0) и предел max_digits=12, что и у WorkerForm.
    field = MoneyDecimalField(max_digits=12, decimal_places=2, min_value=0)
    try:
        new_value = field.clean(request.POST.get('monthly_salary') or '0')
    except ValidationError:
        return HttpResponse(_('Некорректная сумма'), status=400)

    MonthlySalaryBase.objects.update_or_create(
        worker=worker, year=year, month=month,
        defaults={
            'amount': _quantize_money(new_value),
            'created_by': request.user,
        },
    )

    ctx = _row_context(worker, year, month)
    return render(request, 'config/salary/_row.html', ctx)


@role_required('admin')
def salary_entry_create(request, worker_id):
    """htmx POST: добавить премию/штраф; возвращает строку рабочего."""
    if request.method != 'POST':
        return HttpResponse(status=405)
    worker = get_object_or_404(Worker, pk=worker_id, is_active=True)
    year, month = _parse_year_month(request)

    form = SalaryEntryForm(request.POST)
    if not form.is_valid():
        ctx = _row_context(worker, year, month)
        ctx['entry_form'] = form
        return render(request, 'config/salary/_entries_modal.html', ctx)

    entry = form.save(commit=False)
    entry.worker = worker
    entry.year = year
    entry.month = month
    entry.created_by = request.user
    entry.save()

    ctx = _row_context(worker, year, month)
    ctx['entry_form'] = SalaryEntryForm()
    return render(request, 'config/salary/_entry_created.html', ctx)


@role_required('admin')
def salary_entry_delete(request, entry_id):
    """htmx POST: удалить запись начисления, вернуть строку.

    Раздел зарплат admin-only, поэтому отдельная проверка «админ или автор»
    больше не нужна — до сюда доходят только админы.
    """
    if request.method != 'POST':
        return HttpResponse(status=405)
    entry = get_object_or_404(SalaryEntry, pk=entry_id)
    worker = entry.worker
    year, month = entry.year, entry.month
    entry.delete()

    ctx = _row_context(worker, year, month)
    ctx['entry_form'] = SalaryEntryForm()
    return render(request, 'config/salary/_entry_created.html', ctx)


@role_required('admin')
def salary_entries_modal(request, worker_id):
    """Открыть модалку со списком начислений за месяц + форма добавления."""
    worker = get_object_or_404(Worker, pk=worker_id, is_active=True)
    year, month = _parse_year_month(request)
    ctx = _row_context(worker, year, month)
    ctx['entry_form'] = SalaryEntryForm()
    return render(request, 'config/salary/_entries_modal.html', ctx)


@role_required('admin')
def salary_worker_detail(request, worker_id):
    """Помесячная история и статистика по одному рабочему."""
    worker = get_object_or_404(Worker, pk=worker_id, is_active=True)
    today = timezone.localdate()

    # Сколько месяцев показать (по умолчанию 12)
    try:
        months_back = int(request.GET.get('months') or 12)
    except ValueError:
        months_back = 12
    months_back = max(1, min(36, months_back))

    months = []
    y, m = today.year, today.month
    for _i in range(months_back):
        months.append((y, m))
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1

    # --- пакетные выборки, чтобы не плодить N+1 по месяцам ---
    oldest_y, oldest_m = months[-1]
    newest_y, newest_m = months[0]
    range_start = date(oldest_y, oldest_m, 1)
    range_end = _month_bounds(newest_y, newest_m)[1]

    # Явка по месяцам (только будни — как в _compute_payroll).
    present_map = {}
    for d in (Attendance.objects
              .filter(worker=worker, date__gte=range_start, date__lt=range_end,
                      is_present=True)
              .values_list('date', flat=True)):
        if d.weekday() < 5:
            key = (d.year, d.month)
            present_map[key] = present_map.get(key, 0) + 1

    # Запрос по нужным (year, month) — строим OR-условие из явного списка.
    month_q = Q(year=months[0][0], month=months[0][1])
    for (yy, mm) in months[1:]:
        month_q |= Q(year=yy, month=mm)

    entries_map = {}
    for e in (SalaryEntry.objects.filter(worker=worker).filter(month_q)
              .select_related('created_by').order_by('-created_at')):
        entries_map.setdefault((e.year, e.month), []).append(e)

    base_map = {
        (yy, mm): amt
        for yy, mm, amt in (
            MonthlySalaryBase.objects.filter(worker=worker).filter(month_q)
            .values_list('year', 'month', 'amount')
        )
    }

    rows = [
        _compute_payroll(
            worker, yy, mm,
            present_days=present_map.get((yy, mm), 0),
            entries=entries_map.get((yy, mm), []),
            working_days=_working_days_in_month(yy, mm),
            monthly_base=base_map[(yy, mm)] if (yy, mm) in base_map
            else worker.monthly_salary,
        )
        for (yy, mm) in months
    ]
    grand_total = _quantize_money(
        sum((r['total'] for r in rows), Decimal('0'))
    )
    grand_bonuses = _quantize_money(
        sum((r['bonuses'] for r in rows), Decimal('0'))
    )
    grand_penalties = _quantize_money(
        sum((r['penalties'] for r in rows), Decimal('0'))
    )
    grand_present = sum(r['present_days'] for r in rows)
    grand_working = sum(r['working_days'] for r in rows)

    return render(request, 'config/salary/worker_detail.html', {
        'worker': worker,
        'rows': rows,
        'months_back': months_back,
        'grand_total': grand_total,
        'grand_bonuses': grand_bonuses,
        'grand_penalties': grand_penalties,
        'grand_present': grand_present,
        'grand_working': grand_working,
    })
