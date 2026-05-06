from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
)

from .decorators import role_required
from .forms import CategoryForm, CustomerForm, ProductForm
from .models import Category, Customer, Product


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


@login_required
def rentals(request):
    return render(request, 'core/stub.html', {'title': 'Аренды'})


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
