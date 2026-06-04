import re
from decimal import Decimal

from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import (
    Category, Customer, Payment, Product, Rental, SalaryEntry, Worker,
)


# Корректная группировка тысяч: «40 000», «1 234 567», «40 000.50».
# \s покрывает обычный/неразрывный/тонкий пробелы. Группы — ровно по 3 цифры.
_MONEY_GROUPED_RE = re.compile(r'^-?\d{1,3}(?:\s\d{3})+(?:[.,]\d+)?$')


def _strip_money_spaces(raw):
    """JS показывает «40 000», но юзер может отправить значение руками или
    копипастом. Убираем пробелы-разделители тысяч ТОЛЬКО если группировка
    корректная. Кривой ввод вроде «40 00 0 5» оставляем как есть — пусть
    Decimal-валидация его отвергнет, а не молча склеит в «400005» (значение
    другого порядка)."""
    if not isinstance(raw, str):
        return raw
    s = raw.strip()
    if not re.search(r'\s', s):
        return s
    if _MONEY_GROUPED_RE.match(s):
        return re.sub(r'\s+', '', s)
    return s


class MoneyDecimalField(forms.DecimalField):
    """DecimalField, который терпит пробелы-разделители в исходном значении.

    Виджет (money-input) показывает «40 000» — JS снимает пробелы перед
    submit'ом, но если он не отработал (старый браузер, копипаст в
    devtools, отправка curl'ом), бэкенд тоже должен принять значение.
    """
    def to_python(self, value):
        return super().to_python(_strip_money_spaces(value))


def _money_widget(**extra):
    """TextInput для денежных полей: единый набор атрибутов + класс
    ``money-input`` (его ловит static/js/money-input.js). ``type=text``,
    а не ``number`` — иначе браузер не даст вводить пробелы-разделители."""
    attrs = {
        'class': 'form-control money-input',
        'inputmode': 'decimal',
        'placeholder': '0',
        'autocomplete': 'off',
    }
    attrs.update(extra)
    return forms.TextInput(attrs=attrs)



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
        # Предзаполняем текущим временем (локальным), чтобы оператору не нужно
        # было ничего вводить; значение остаётся редактируемым. callable —
        # чтобы «сейчас» вычислялось при каждом открытии формы, а не на старте.
        initial=timezone.localtime,
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
        help_text=_('По умолчанию — текущее время; измените при необходимости.'),
    )
    due_date = forms.DateTimeField(
        label=_('Срок и время возврата'),
        widget=_datetime_local_widget(),
        input_formats=_DT_INPUT_FORMATS,
    )
    initial_deposit = MoneyDecimalField(
        label=_('Начальный платёж/залог (опционально)'),
        required=False,
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=_money_widget(),
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

    amount = MoneyDecimalField(
        label=_('Сумма'),
        max_digits=12,
        decimal_places=2,
        widget=_money_widget(),
    )

    class Meta:
        model = Payment
        fields = ['kind', 'method', 'amount', 'note']
        widgets = {
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
    monthly_salary = MoneyDecimalField(
        label=_('Оклад за месяц'),
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=_money_widget(),
    )

    class Meta:
        model = Worker
        fields = ['full_name', 'position', 'phone', 'monthly_salary',
                  'note', 'is_active']
        widgets = {
            'note': forms.TextInput(attrs={
                'placeholder': _('необязательно'),
            }),
        }

    def clean_monthly_salary(self):
        value = self.cleaned_data.get('monthly_salary')
        if value is None:
            return Decimal('0.00')
        return value


class SalaryEntryForm(BootstrapFormMixin, forms.ModelForm):
    amount = MoneyDecimalField(
        label=_('Сумма'),
        min_value=0,
        max_digits=12,
        decimal_places=2,
        widget=_money_widget(autofocus='autofocus'),
    )

    class Meta:
        model = SalaryEntry
        fields = ['kind', 'amount', 'reason']
        widgets = {
            'reason': forms.TextInput(attrs={
                'placeholder': _('за что (необязательно)'),
                'maxlength': '255',
            }),
        }

    def clean_amount(self):
        value = self.cleaned_data.get('amount') or Decimal('0.00')
        if value <= 0:
            raise forms.ValidationError(_('Сумма должна быть больше нуля.'))
        return value
