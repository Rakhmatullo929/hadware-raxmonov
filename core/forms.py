from django import forms
from django.utils import timezone

from .models import Category, Customer, Product, Rental


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
                'placeholder': 'оставьте пустым — присвоится автоматически',
            }),
        }


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']


class RentalCreateForm(BootstrapFormMixin, forms.ModelForm):
    due_date = forms.DateField(
        label='Срок возврата',
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        input_formats=['%Y-%m-%d'],
    )
    initial_deposit = forms.DecimalField(
        label='Начальный платёж/залог (опционально)',
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
            'note': forms.Textarea(attrs={'rows': 2, 'placeholder': 'Произвольный комментарий'}),
        }

    def clean_due_date(self):
        d = self.cleaned_data['due_date']
        if d <= timezone.localdate():
            raise forms.ValidationError('Срок возврата должен быть позже сегодняшнего дня.')
        return d

    def clean_customer(self):
        c = self.cleaned_data.get('customer')
        if not c:
            raise forms.ValidationError('Выберите клиента.')
        return c
