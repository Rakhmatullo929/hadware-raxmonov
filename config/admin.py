from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Category,
    Customer,
    DebtorNotification,
    Movement,
    Payment,
    Product,
    Rental,
    RentalItem,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'category',
        'unit',
        'stock_total',
        'available_stock_display',
        'daily_price',
        'deposit_per_unit',
        'is_active',
    )
    list_filter = ('category', 'unit', 'is_active')
    search_fields = ('name',)
    list_select_related = ('category',)
    fields = (
        'name', 'category', 'unit', 'stock_total',
        'daily_price', 'deposit_per_unit',
        'expected_min_days', 'expected_max_days',
        'is_active', 'included_kit',
    )

    @admin.display(description='Доступно')
    def available_stock_display(self, obj):
        return obj.available_stock


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('code', 'full_name', 'phone', 'passport', 'created_at')
    search_fields = ('code', 'full_name', 'phone', 'passport')
    list_filter = ('created_at',)
    readonly_fields = ()


class RentalItemInline(admin.TabularInline):
    model = RentalItem
    extra = 0
    fields = ('product', 'qty', 'price_per_day', 'outstanding_display')
    readonly_fields = ('outstanding_display',)
    autocomplete_fields = ('product',)

    @admin.display(description='Не возвращено')
    def outstanding_display(self, obj):
        if obj.pk is None:
            return '—'
        outstanding = obj.outstanding_qty
        color = 'red' if outstanding > 0 else 'green'
        return format_html('<b style="color: {};">{}</b>', color, outstanding)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Rental)
class RentalAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'customer',
        'created_at',
        'due_date',
        'status',
        'is_overdue_display',
        'created_by',
    )
    list_filter = ('status', 'created_at', 'due_date')
    search_fields = ('customer__full_name', 'customer__phone', 'note')
    autocomplete_fields = ('customer',)
    list_select_related = ('customer', 'created_by')
    readonly_fields = ('created_at',)
    inlines = [RentalItemInline, PaymentInline]

    @admin.display(description='Просрочена', boolean=True)
    def is_overdue_display(self, obj):
        return obj.is_overdue

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in instances:
            if isinstance(obj, RentalItem) and not obj.price_per_day:
                obj.price_per_day = obj.product.daily_price
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()


@admin.register(RentalItem)
class RentalItemAdmin(admin.ModelAdmin):
    list_display = ('rental', 'product', 'qty', 'price_per_day', 'outstanding_qty')
    list_filter = ('product__category',)
    search_fields = ('product__name', 'rental__customer__full_name')
    autocomplete_fields = ('rental', 'product')


@admin.register(Movement)
class MovementAdmin(admin.ModelAdmin):
    list_display = ('rental_item', 'kind', 'qty', 'date', 'created_by')
    list_filter = ('kind', 'date')
    search_fields = ('rental_item__product__name', 'rental_item__rental__customer__full_name')
    autocomplete_fields = ('rental_item',)

    def save_model(self, request, obj, form, change):
        if not change and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('rental', 'kind', 'amount', 'date')
    list_filter = ('kind', 'date')
    search_fields = ('rental__customer__full_name',)
    autocomplete_fields = ('rental',)


@admin.register(DebtorNotification)
class DebtorNotificationAdmin(admin.ModelAdmin):
    list_display = ('sent_at', 'rental', 'kind', 'target_chat_id', 'ok')
    list_filter = ('kind', 'ok', 'sent_at')
    search_fields = ('rental__customer__full_name', 'target_chat_id')
    readonly_fields = ('sent_at', 'response')
    autocomplete_fields = ('rental',)
