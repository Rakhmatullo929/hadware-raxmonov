from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Category, Customer, Payment, Product, Rental, Worker


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
            'expected_min_days',
            'expected_max_days',
            'is_active',
        ]

    def clean(self):
        cleaned = super().clean()
        lo = cleaned.get('expected_min_days')
        hi = cleaned.get('expected_max_days')
        if lo and hi and lo > hi:
            self.add_error(
                'expected_max_days',
                _('Максимум не может быть меньше минимума.'),
            )
        return cleaned


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


# Формат `datetime-local` HTML5: 'YYYY-MM-DDTHH:MM' (без секунд),
# но Django ожидает значения с пробелом, поэтому задаём оба формата.
_DT_LOCAL_FORMAT = '%Y-%m-%dT%H:%M'
_DT_INPUT_FORMATS = [
    _DT_LOCAL_FORMAT,
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M',
    '%Y-%m-%d %H:%M:%S',
]


def _datetime_local_widget():
    return forms.DateTimeInput(
        attrs={'type': 'datetime-local', 'class': 'form-control'},
        format=_DT_LOCAL_FORMAT,
    )


class RentalCreateForm(BootstrapFormMixin, forms.ModelForm):
    created_at = forms.DateTimeField(
        label=_('Дата и время выдачи'),
        required=False,
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
        help_text=_('Оставьте пустым — будет проставлено текущее время.'),
    )
    due_date = forms.DateTimeField(
        label=_('Срок и время возврата'),
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
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
        fields = ['customer', 'created_at', 'due_date', 'note']
        widgets = {
            'customer': forms.HiddenInput(),
            'note': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': _('Произвольный комментарий'),
            }),
        }

    def clean_created_at(self):
        dt = self.cleaned_data.get('created_at')
        if dt is None:
            return timezone.now()
        return dt

    def clean(self):
        cleaned = super().clean()
        created = cleaned.get('created_at')
        due = cleaned.get('due_date')
        if created and due and due <= created:
            self.add_error(
                'due_date',
                _('Срок возврата должен быть позже даты выдачи.'),
            )
        elif due is not None and due <= timezone.now():
            # При создании новой аренды дата возврата должна быть в будущем.
            self.add_error(
                'due_date',
                _('Срок возврата должен быть позже текущего времени.'),
            )
        return cleaned

    def clean_customer(self):
        c = self.cleaned_data.get('customer')
        if not c:
            raise forms.ValidationError(_('Выберите клиента.'))
        return c


class RentalEditForm(BootstrapFormMixin, forms.ModelForm):
    """Правка уже созданной аренды: время выдачи, срок и примечание."""

    created_at = forms.DateTimeField(
        label=_('Дата и время выдачи'),
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
    )
    due_date = forms.DateTimeField(
        label=_('Срок и время возврата'),
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
    )

    class Meta:
        model = Rental
        fields = ['created_at', 'due_date', 'note']
        widgets = {
            'note': forms.Textarea(attrs={'rows': 3}),
        }

    def clean(self):
        cleaned = super().clean()
        created = cleaned.get('created_at')
        due = cleaned.get('due_date')
        if created and due and due <= created:
            self.add_error(
                'due_date',
                _('Срок возврата должен быть позже даты выдачи.'),
            )
        return cleaned


class PaymentForm(BootstrapFormMixin, forms.ModelForm):
    """Платёж по существующей аренде (клиент внёс деньги / возврат залога)."""

    class Meta:
        model = Payment
        fields = ['kind', 'method', 'amount', 'note']
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


class WorkerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Worker
        fields = ['full_name', 'position', 'phone', 'note', 'is_active']
        widgets = {
            'note': forms.TextInput(attrs={
                'placeholder': _('необязательно'),
            }),
        }
