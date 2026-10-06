# core/forms.py
from django import forms
from .models import Table

class TableForm(forms.ModelForm):
    class Meta:
        model = Table
        fields = ['number', 'seats', 'is_occupied']
        widgets = {
            'number': forms.NumberInput(attrs={'class': 'form-control'}),
            'seats':  forms.NumberInput(attrs={'class': 'form-control'}),
            'is_occupied': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# core/forms.py
from django import forms
from .models import Expense, CashFlow

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['date','category','amount','description']

class CashFlowForm(forms.ModelForm):
    class Meta:
        model = CashFlow
        fields = ['date','flow_type','amount','bank_account','description']


# core/forms.py

from django import forms
from .models import BankAccount, BankMovement

class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields = ['name','bank_name','account_number','branch','opening_balance','is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class':'form-control'}),
            'bank_name': forms.TextInput(attrs={'class':'form-control'}),
            'account_number': forms.TextInput(attrs={'class':'form-control'}),
            'branch': forms.TextInput(attrs={'class':'form-control'}),
            'opening_balance': forms.NumberInput(attrs={'class':'form-control','step':'0.01'}),
            'is_active': forms.CheckboxInput(attrs={'class':'form-check-input'}),
        }

class BankMovementForm(forms.ModelForm):
    class Meta:
        model = BankMovement
        fields = [
            'date','movement_type','amount',
            'from_bank','to_bank','method','reference_no','notes'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type':'date','class':'form-control'}),
            'movement_type': forms.Select(attrs={'class':'form-select'}),
            'amount': forms.NumberInput(attrs={'class':'form-control','step':'0.01','min':'0'}),
            'from_bank': forms.Select(attrs={'class':'form-select'}),
            'to_bank': forms.Select(attrs={'class':'form-select'}),
            'method': forms.TextInput(attrs={'class':'form-control','placeholder':'Cash / Cheque / Online'}),
            'reference_no': forms.TextInput(attrs={'class':'form-control','placeholder':'Txn/cheque ref'}),
            'notes': forms.TextInput(attrs={'class':'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        # We rely on model.clean() for core validation
        return cleaned


# forms.py
from django import forms
from django.contrib.auth import get_user_model
from core.models import Staff

User = get_user_model()


class StaffForm(forms.ModelForm):
    has_software_access = forms.BooleanField(required=False)

    class Meta:
        model = Staff
        fields = [
            'full_name', 'role', 'phone', 'cnic', 'address',
            'has_software_access',
            'joined_on', 'salary_start', 'monthly_salary',
            'access_sales', 'access_inventory', 'access_accounts',
        ]
        widgets = {
            'joined_on': forms.DateInput(attrs={'type': 'date'}),
            'salary_start': forms.DateInput(attrs={'type': 'date'}),
            'monthly_salary': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'address': forms.Textarea(attrs={'rows': 2}),
        }

    def clean(self):
        cleaned_data = super().clean()
        has_access = cleaned_data.get('has_software_access')

        if has_access:
            # Username/password will be handled in the view when access is enabled.
            pass
        else:
            # Auto-create a user with default password "1122" if not exists.
            name = cleaned_data.get('full_name')
            if name:
                username = name.lower().replace(' ', '_')
                user, created = User.objects.get_or_create(username=username)
                if created:
                    user.set_password('1122')
                    user.save()
                # Stash it so we can apply it on save()
                cleaned_data['user'] = user
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        user_from_clean = self.cleaned_data.get('user')
        if user_from_clean and not getattr(instance, 'user', None):
            instance.user = user_from_clean
        if commit:
            instance.save()
        return instance



# core/forms/expense_forms.py
from django import forms
from django.contrib.auth import get_user_model
from core.models import Expense, Supplier, Staff, BankAccount

User = get_user_model()

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'date', 'category', 'amount', 'description', 'reference', 'attachment',
            'supplier', 'staff',
            'payment_source', 'bank_account',
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Details (optional)'}),
            'reference': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Bill/Invoice # (optional)'}),
            'supplier': forms.Select(attrs={'class': 'form-select'}),
            'staff': forms.Select(attrs={'class': 'form-select'}),
            'payment_source': forms.Select(attrs={'class': 'form-select'}),
            'bank_account': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Friendly empty label
        self.fields['supplier'].empty_label = "— Select supplier —"
        self.fields['staff'].empty_label = "— Select staff —"
        self.fields['bank_account'].empty_label = "— Select bank account —"

        # Optional by default; JS + model.clean enforce rules
        self.fields['supplier'].required = False
        self.fields['staff'].required = False
        self.fields['bank_account'].required = False

    def save(self, commit=True):
        obj = super().save(commit=False)
        if not obj.created_by_id and self.request and self.request.user.is_authenticated:
            obj.created_by = self.request.user
        if commit:
            obj.save()
        return obj


from django import forms
from django.forms import inlineformset_factory
from core.models import KitchenVoucher, KitchenVoucherItem

class KitchenVoucherForm(forms.ModelForm):
    class Meta:
        model = KitchenVoucher
        fields = ['date','vtype','handler','notes']
        widgets = {
            'date': forms.DateInput(attrs={'type':'date','class':'form-control'}),
            'vtype': forms.Select(attrs={'class':'form-select'}),
            'handler': forms.Select(attrs={'class':'form-select'}),
            'notes': forms.TextInput(attrs={'class':'form-control', 'placeholder':'Optional notes'}),
        }

class KitchenVoucherItemForm(forms.ModelForm):
    class Meta:
        model = KitchenVoucherItem
        fields = ['raw_material','quantity']
        widgets = {
            'raw_material': forms.Select(attrs={'class':'form-select'}),
            'quantity': forms.NumberInput(attrs={'class':'form-control','step':'0.01','min':'0'}),
        }

VoucherItemFormSet = inlineformset_factory(
    KitchenVoucher, KitchenVoucherItem,
    form=KitchenVoucherItemForm, extra=1, can_delete=True, min_num=1, validate_min=True
)

from django import forms
from .models import POSSettings, PrintStation

class POSSettingsForm(forms.ModelForm):
    class Meta:
        model = POSSettings
        fields = ['restaurant_name', 'start_of_day_time', 'logo', 'theme_color']
        widgets = {
            'start_of_day_time': forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
            'restaurant_name': forms.TextInput(attrs={'class': 'form-control'}),
            'theme_color': forms.TextInput(attrs={'type': 'color', 'class': 'form-control form-control-color'}),
            'logo': forms.FileInput(attrs={'class': 'form-control'}),
        }
        labels = {
            'start_of_day_time': 'Business Day Start Time (Token Reset Time)'
        }

class PrintStationForm(forms.ModelForm):
    class Meta:
        model = PrintStation
        fields = ['name', 'printer_name', 'print_separate_slip', 'use_separate_sequence']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'printer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. EPSON TM-T82'}),
            'print_separate_slip': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'use_separate_sequence': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'print_separate_slip': 'If checked, items for this station get their own paper slip.',
            'use_separate_sequence': 'If checked, this station counts tokens 1, 2, 3 independently from the Main Kitchen.'
        }


# ---------- Taxes & Modifiers ----------
from django.forms import inlineformset_factory
from django.forms.formsets import DELETION_FIELD_NAME
from django.forms.utils import ErrorDict
from core.models import TaxRate, ModifierGroup, Modifier


class TaxRateForm(forms.ModelForm):
    class Meta:
        model = TaxRate
        fields = [
            'name', 'tax_type', 'rate', 'fixed_amount',
            'active', 'is_default', 'is_optional',
            'applies_after_discount', 'sort_order',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. VAT'}),
            'tax_type': forms.Select(attrs={'class': 'form-select'}),
            'rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'fixed_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': 0}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'step': 1}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_default': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_optional': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'applies_after_discount': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('active', 'is_default', 'is_optional', 'applies_after_discount'):
            self.fields[name].required = False


class ModifierGroupForm(forms.ModelForm):
    class Meta:
        model = ModifierGroup
        fields = ['name', 'min_select', 'max_select', 'active', 'sort_order', 'menu_items']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Size, Add-ons'}),
            'min_select': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'max_select': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'step': 1}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'menu_items': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['active'].required = False
        self.fields['menu_items'].required = False
        self.fields['menu_items'].help_text = (
            'Leave empty to offer this group on every menu item.'
        )

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get('min_select')
        maximum = cleaned.get('max_select')
        if minimum is not None and maximum is not None and minimum > maximum:
            raise forms.ValidationError(
                'Minimum selections cannot be greater than the maximum.'
            )
        return cleaned


class ModifierForm(forms.ModelForm):
    class Meta:
        model = Modifier
        fields = ['name', 'price', 'active', 'sort_order']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Large'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'sort_order': forms.NumberInput(attrs={'class': 'form-control', 'step': 1}),
            'active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['active'].required = False

    def _is_blank_row(self):
        return not (self.cleaned_data.get('name') or '').strip()

    def clean(self):
        cleaned = super().clean()
        # A row the user left completely blank means "no option here".
        # Without this the spare rows would fail on every save, because an
        # unticked 'active' box makes an otherwise empty row look changed.
        if self._is_blank_row():
            self._errors = ErrorDict()
            # Tell the formset to skip this row instead of saving an empty option.
            if DELETION_FIELD_NAME in self.fields:
                cleaned[DELETION_FIELD_NAME] = True
        return cleaned

    def _post_clean(self):
        # Blank rows must also skip the model's unique_together checks,
        # otherwise every spare row fails with "name cannot be blank".
        if self._is_blank_row():
            self._errors = ErrorDict()
            return
        super()._post_clean()


ModifierOptionFormSet = inlineformset_factory(
    ModifierGroup, Modifier, form=ModifierForm,
    extra=3, can_delete=True,
)


from django import forms
from core.models import PaymentReceived

class PaymentReceivedForm(forms.ModelForm):
    class Meta:
        model = PaymentReceived
        fields = [
            'date', 'party_type', 'customer', 'supplier', 
            'amount', 'payment_method', 'bank_account', 'description'
        ]
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'party_type': forms.Select(attrs={'class': 'form-select', 'id': 'id_party_type'}),
            'customer': forms.Select(attrs={'class': 'form-select search-select'}), 
            'supplier': forms.Select(attrs={'class': 'form-select search-select'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'payment_method': forms.Select(attrs={'class': 'form-select', 'id': 'id_payment_method'}),
            'bank_account': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        self.fields['bank_account'].required = False
        self.fields['customer'].required = False
        self.fields['supplier'].required = False

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.request:
            obj.created_by = self.request.user
        if commit:
            obj.save()
        return obj


# ---------- Production (batch manufacturing) ----------
from .models import ProductionRun, Recipe


class ProductionRunForm(forms.ModelForm):
    """Plan a batch: pick a recipe and the number of portions to make.

    The raw-material sufficiency check happens server-side on submit, so a
    short batch never half-deducts stock before the user confirms.
    """
    class Meta:
        model = ProductionRun
        fields = ['recipe', 'planned_qty', 'notes']
        widgets = {
            'recipe': forms.Select(attrs={'class': 'form-select', 'id': 'id_recipe'}),
            'planned_qty': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01', 'id': 'id_planned_qty'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Optional production notes'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only recipes that produce a finished menu item are eligible for
        # batch production — a recipe with no menu_item cannot stock anything.
        self.fields['recipe'].queryset = (
            Recipe.objects.select_related('menu_item').filter(menu_item__track_finished_stock=True)
        )
        self.fields['recipe'].empty_label = "— Select a recipe —"
        self.fields['recipe'].required = True
        self.fields['planned_qty'].required = True
        self.fields['notes'].required = False


class ProductionCompleteForm(forms.Form):
    """Confirm a batch: how many portions were actually produced / lost."""
    produced_qty = forms.DecimalField(
        min_value=0.01, max_digits=10, decimal_places=2, required=True,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0.01', 'id': 'id_produced_qty'}),
    )
    wastage_qty = forms.DecimalField(
        min_value=0, max_digits=10, decimal_places=2, required=False, initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'id': 'id_wastage_qty'}),
    )