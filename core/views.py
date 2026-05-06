import uuid
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
)

from .decorators import role_required
from .forms import CategoryForm, CustomerForm, ProductForm, RentalCreateForm
from .models import (
    Category,
    Customer,
    Movement,
    Payment,
    Product,
    Rental,
    RentalItem,
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


@login_required
def dashboard(request):
    return render(request, 'core/dashboard.html')


@role_required('admin')
def reports(request):
    return render(request, 'core/stub.html', {'title': 'Отчёты'})


# ---------- products ----------

class ProductListView(StaffOrAdminRequiredMixin, ListView):
    model = Product
    template_name = 'core/products/list.html'
    context_object_name = 'products'
    paginate_by = 25

    def get_queryset(self):
        qs = Product.objects.select_related('category').order_by('name')
        q = self.request.GET.get('q', '').strip()
        category_id = self.request.GET.get('category', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        if category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))
        return qs

    def get_template_names(self):
        if self.request.htmx:
            return ['core/products/_table.html']
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
    template_name = 'core/products/form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Новый товар'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Товар «{form.instance.name}» создан.')
        return super().form_valid(form)


class ProductUpdateView(AdminRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'core/products/form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Товар: {self.object.name}'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Товар «{form.instance.name}» сохранён.')
        return super().form_valid(form)


class ProductToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        product.is_active = not product.is_active
        product.save(update_fields=['is_active'])
        state = 'активирован' if product.is_active else 'деактивирован'
        messages.success(request, f'Товар «{product.name}» {state}.')
        return HttpResponseRedirect(
            request.META.get('HTTP_REFERER') or reverse('product_list')
        )


class CategoryCreateView(AdminRequiredMixin, CreateView):
    model = Category
    form_class = CategoryForm
    template_name = 'core/products/form.html'
    success_url = reverse_lazy('product_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Новая категория'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Категория «{form.instance.name}» создана.')
        return super().form_valid(form)


# ---------- customers ----------

class CustomerListView(StaffOrAdminRequiredMixin, ListView):
    model = Customer
    template_name = 'core/customers/list.html'
    context_object_name = 'customers'
    paginate_by = 25

    def get_queryset(self):
        qs = Customer.objects.order_by('full_name')
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(phone__icontains=q))
        return qs

    def get_template_names(self):
        if self.request.htmx:
            return ['core/customers/_table.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        return ctx


class CustomerCreateView(StaffOrAdminRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'core/customers/form.html'

    def get_success_url(self):
        return reverse('customer_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = 'Новый клиент'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Клиент «{form.instance.full_name}» создан.')
        return super().form_valid(form)


class CustomerUpdateView(StaffOrAdminRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'core/customers/form.html'

    def get_success_url(self):
        return reverse('customer_detail', args=[self.object.pk])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f'Клиент: {self.object.full_name}'
        return ctx

    def form_valid(self, form):
        messages.success(self.request, f'Клиент «{form.instance.full_name}» сохранён.')
        return super().form_valid(form)


class CustomerDetailView(StaffOrAdminRequiredMixin, DetailView):
    model = Customer
    template_name = 'core/customers/detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['rentals'] = (
            self.object.rentals
            .select_related('created_by')
            .prefetch_related('items__product')
            .order_by('-created_at')
        )
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


class RentalListView(StaffOrAdminRequiredMixin, ListView):
    model = Rental
    template_name = 'core/rentals/list.html'
    context_object_name = 'rentals'
    paginate_by = 25

    SORT_FIELDS = {
        'due_date': 'due_date',
        '-due_date': '-due_date',
        'created_at': 'created_at',
        '-created_at': '-created_at',
    }

    def get_queryset(self):
        qs = (
            Rental.objects
            .select_related('customer', 'created_by')
        )
        qs = _annotate_rental_qs(qs)

        today = timezone.localdate()
        status = self.request.GET.get('status', '').strip()
        if status == Rental.Status.CLOSED:
            qs = qs.filter(status=Rental.Status.CLOSED)
        elif status == 'overdue':
            qs = qs.filter(
                status=Rental.Status.ACTIVE,
                due_date__lt=today,
                outstanding_total__gt=0,
            )
        elif status == Rental.Status.ACTIVE:
            qs = qs.filter(status=Rental.Status.ACTIVE).filter(
                Q(due_date__gte=today) | Q(outstanding_total=0)
            )

        date_from = self.request.GET.get('date_from', '').strip()
        date_to = self.request.GET.get('date_to', '').strip()
        for raw, lookup in ((date_from, 'created_at__date__gte'),
                            (date_to, 'created_at__date__lte')):
            if raw:
                try:
                    parsed = datetime.strptime(raw, '%Y-%m-%d').date()
                    qs = qs.filter(**{lookup: parsed})
                except ValueError:
                    pass

        customer_id = self.request.GET.get('customer', '').strip()
        if customer_id.isdigit():
            qs = qs.filter(customer_id=int(customer_id))

        sort = self.request.GET.get('sort', 'due_date')
        sort_field = self.SORT_FIELDS.get(sort, 'due_date')
        return qs.order_by(sort_field, '-created_at')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['today'] = timezone.localdate()
        ctx['filters'] = {
            'status': self.request.GET.get('status', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
            'customer': self.request.GET.get('customer', ''),
            'sort': self.request.GET.get('sort', 'due_date'),
        }
        if ctx['filters']['customer'].isdigit():
            ctx['filter_customer_obj'] = Customer.objects.filter(
                pk=int(ctx['filters']['customer'])
            ).first()
        return ctx


class RentalDetailView(StaffOrAdminRequiredMixin, DetailView):
    model = Rental
    template_name = 'core/rentals/detail.html'
    context_object_name = 'rental'

    def get_queryset(self):
        return (
            Rental.objects
            .select_related('customer', 'created_by')
            .prefetch_related(
                'items__product',
                'items__movements__created_by',
                'payments',
            )
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rental = self.object
        items = list(rental.items.all())
        all_movements = []
        for it in items:
            for m in it.movements.all():
                all_movements.append(m)
        all_movements.sort(key=lambda m: m.date, reverse=True)

        ctx['items'] = items
        ctx['movements'] = all_movements
        ctx['payments'] = list(rental.payments.all())
        ctx['paid_total'] = sum(
            (p.amount for p in ctx['payments']
             if p.kind in (Payment.Kind.RENT, Payment.Kind.FINE)),
            Decimal('0.00'),
        )
        ctx['deposit_total'] = sum(
            (p.amount for p in ctx['payments'] if p.kind == Payment.Kind.DEPOSIT),
            Decimal('0.00'),
        )
        ctx['today'] = timezone.localdate()
        return ctx


class RentalCreateView(StaffOrAdminRequiredMixin, View):
    template_name = 'core/rentals/create.html'

    def get(self, request):
        return render(request, self.template_name, self._initial_context(request))

    def post(self, request):
        form = RentalCreateForm(request.POST)
        rows = self._parse_item_rows(request.POST)
        item_errors = self._validate_items(rows)
        ok = form.is_valid() and not item_errors

        if ok:
            try:
                rental = self._create_rental(request, form, rows)
            except ValueError as e:
                item_errors.append(str(e))
                ok = False
            else:
                messages.success(
                    request,
                    f'Аренда #{rental.pk} создана. Выдано {sum(r["qty"] for r in rows)} шт.',
                )
                return HttpResponseRedirect(
                    reverse('rental_detail', args=[rental.pk])
                )

        ctx = self._initial_context(request)
        ctx['form'] = form
        ctx['item_rows'] = self._rows_for_template(rows)
        ctx['item_errors'] = item_errors
        if form.cleaned_data.get('customer'):
            ctx['picked_customer'] = form.cleaned_data['customer']
        return render(request, self.template_name, ctx)

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
            errors.append('Добавьте хотя бы одну позицию.')
            return errors
        for i, r in enumerate(rows, start=1):
            if r.get('invalid'):
                errors.append(f'Строка {i}: некорректные значения.')
                continue
            if r['qty'] <= 0:
                errors.append(f'Строка {i}: количество должно быть больше нуля.')
                continue
            try:
                p = Product.objects.get(pk=r['product_id'], is_active=True)
            except Product.DoesNotExist:
                errors.append(f'Строка {i}: товар не найден или отключён.')
                continue
            if r['qty'] > p.available_stock:
                errors.append(
                    f'Строка {i}: «{p.name}» — доступно {p.available_stock} {p.unit}, '
                    f'запрошено {r["qty"]}.'
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
                    f'«{product.name}»: доступно {product.available_stock}, '
                    f'запрошено {r["qty"]}'
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
            return render(request, 'core/rentals/_customer_search_results.html',
                          {'customers': [], 'q': q, 'too_short': True})
        customers = (
            Customer.objects
            .filter(Q(full_name__icontains=q) | Q(phone__icontains=q))
            .order_by('full_name')[:10]
        )
        return render(request, 'core/rentals/_customer_search_results.html',
                      {'customers': customers, 'q': q, 'too_short': False})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerPickView(View):
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        return render(request, 'core/rentals/_customer_picked.html',
                      {'picked_customer': customer})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class CustomerClearView(View):
    def get(self, request):
        return render(request, 'core/rentals/_customer_search_input.html')


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ProductInfoView(View):
    def get(self, request):
        pid = request.GET.get('item_product') or ''
        if not pid.isdigit():
            return HttpResponse('')
        product = Product.objects.filter(pk=int(pid)).first()
        if not product:
            return HttpResponse('')
        return render(request, 'core/rentals/_product_info.html',
                      {'product': product})


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemRowNewView(View):
    def get(self, request):
        return render(request, 'core/rentals/_item_row.html', {
            'row': {'row_id': uuid.uuid4().hex[:8], 'product': None, 'qty': ''},
            'products': Product.objects.filter(is_active=True).order_by('name'),
        })


@method_decorator(role_required('staff', 'admin'), name='dispatch')
class ItemRowRemoveView(View):
    """No-op endpoint; the actual removal is done client-side via hx-swap=delete."""
    def post(self, request):
        return HttpResponse(status=204)
