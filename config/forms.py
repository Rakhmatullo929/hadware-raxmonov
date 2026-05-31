from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Category, Customer, Payment, Product, Rental


class BootstrapFormMixin:
    """Adds Bootstrap 5 classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault('class', 'form-check-input')
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault('class', 'form-select')
            elif isinstance(widget, forms.Textarea):
                widget.attrs.setdefault('class', 'form-control')
                widget.attrs.setdefault('rows', 3)
            else:
                widget.attrs.setdefault('class', 'form-control')


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            'name',
            'category',
            'unit',
            'stock_total',
            'daily_price',
            'deposit_per_unit',
            'is_active',
        ]


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['code', 'full_name', 'phone', 'passport', 'address', 'notes']
        widgets = {
            'code': forms.TextInput(attrs={
                'placeholder': _('оставьте пустым — присвоится автоматически'),
            }),
        }


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']


class RentalCreateForm(BootstrapFormMixin, forms.ModelForm):
    due_date = forms.DateField(
        label=_('Срок возврата'),
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
    )
    initial_deposit = forms.DecimalField(
        label=_('Начальный платёж/залог (опционально)'),
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={'step': '0.01', 'placeholder': '0.00'}),
    )

    class Meta:
        model = Rental
        fields = ['customer', 'due_date', 'note']
        widgets = {
            'customer': forms.HiddenInput(),
            'note': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': _('Произвольный комментарий'),
            }),
        }

    def clean_due_date(self):
        d = self.cleaned_data['due_date']
        if d <= timezone.localdate():
            raise forms.ValidationError(
                _('Срок возврата должен быть позже сегодняшнего дня.')
            )
        return d

    def clean_customer(self):
        c = self.cleaned_data.get('customer')
        if not c:
            raise forms.ValidationError(_('Выберите клиента.'))
        return c


class RentalEditForm(BootstrapFormMixin, forms.ModelForm):
    """Правка уже созданной аренды: срок возврата и примечание."""

    due_date = forms.DateField(
        label=_('Срок возврата'),
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
    )

    class Meta:
        model = Rental
        fields = ['due_date', 'note']
        widgets = {
            'note': forms.Textarea(attrs={'rows': 3}),
        }


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    """Платёж по существующей аренде (клиент внёс деньги / возврат залога)."""

    class Meta:
        model = Payment
        fields = ['kind', 'amount', 'note']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'step': '0.01', 'min': '0.01', 'placeholder': '0.00',
            }),
            'note': forms.TextInput(attrs={
                'placeholder': _('необязательно'),
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is None or amount <= 0:
            raise forms.ValidationError(_('Сумма должна быть больше нуля.'))
        return amount
