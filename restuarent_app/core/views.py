from django.core.serializers.json import DjangoJSONEncoder
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from .license_check import enforce_authorization
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import InventoryTransaction, PrintStatus, PurchaseOrder, RawMaterial, Recipe, RecipeRawMaterial, RecipeSubRecipe
from django.views.decorators.http import require_POST
from django.utils.decorators import method_decorator
from core.permissions import require_permission
from .models import Unit

from .printing import send_to_printer
from .utils import recipe_cost_and_weight
from django.db import transaction
import json
from decimal import Decimal, InvalidOperation
from django.db.models import Sum, F
from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import (
    RawMaterialUnitConversion,
    PurchaseOrderItem,
    MenuItem, Deal,
    TaxRate, OrderTax, Modifier, ModifierGroup, OrderItemModifier,
    OrderHold,
)

from django.urls import reverse_lazy
from django.db.models import Max
from django.utils import timezone
from .models import next_token_for

from .utils import get_next_token_number
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.http import JsonResponse 
from .models import Customer

from django.conf import settings as django_settings

from core.countries import active_country


def _brand_name_bytes():
    """App/restaurant name as ESC/POS-safe bytes, taken from settings.RESTAURANT_NAME."""
    name = getattr(django_settings, 'RESTAURANT_NAME', 'RestroPOS')
    # Thermal printers expect ASCII; drop anything they cannot print.
    return name.encode('ascii', 'ignore')


def _currency_prefix_bytes():
    """
    ASCII-safe currency prefix for receipts, from the active country.
    Thermal printers usually cannot render symbols such as the Naira sign,
    so Nigeria prints 'N1,500.00' rather than '\u20a61,500.00'.
    """
    return (active_country()['receipt_symbol'] + ' ').encode('ascii', 'ignore')


# Mixin to return JSON for AJAX forms
class AjaxableResponseMixin:
    def is_ajax(self):
        return self.request.headers.get('x-requested-with') == 'XMLHttpRequest'

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.is_ajax():
            return JsonResponse({'message': 'OK'})
        return response

    def form_invalid(self, form):
        if self.is_ajax():
            return JsonResponse(form.errors, status=400)
        return super().form_invalid(form)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if self.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)
    
# ---------- CUSTOMERS CRUD ----------

class CustomerListView(LoginRequiredMixin, ListView):
    model = Customer
    template_name = 'customers/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().order_by('-created_at')
        q = self.request.GET.get('q')
        if q:
            # Search by Name or Phone
            qs = qs.filter(name__icontains=q) | qs.filter(phone__icontains=q)
        return qs

class CustomerCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = Customer
    fields = ['name', 'phone', 'address', 'current_balance']
    template_name = 'customers/customer_form.html'
    success_url = reverse_lazy('customer_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = "Add New Customer"
        return ctx

class CustomerUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = Customer
    fields = ['name', 'phone', 'address', 'current_balance']
    template_name = 'customers/customer_form.html'
    success_url = reverse_lazy('customer_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['title'] = f"Edit {self.object.name}"
        return ctx

class CustomerDeleteView(LoginRequiredMixin, DeleteView):
    model = Customer
    success_url = reverse_lazy('customer_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)
    
    
class LoginView(View):
    def get(self, request):
        return render(request, 'login.html')

    def post(self, request):
        try:
            enforce_authorization(request)
        except RuntimeError as e: 
            print(f"message: {str(e)}")
            return render(request, "error_not_authorized.html", {"message": str(e)})
        
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('dashboard')
        return render(request, 'login.html', {'error': 'Invalid credentials'})

class LogoutView(View):
    def get(self, request):
        logout(request)
        return redirect('login')

class DashboardView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('login')
        
        try:
            enforce_authorization(request)
        except RuntimeError as e:
            return render(request, "error_not_authorized.html", {"message": str(e)})

        return render(request, 'dashboard.html')
    

from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.http import JsonResponse
from .models import Category, MenuItem

# Mixin to return JSON for AJAX forms
class AjaxableResponseMixin:
    def is_ajax(self):
        return self.request.headers.get('x-requested-with') == 'XMLHttpRequest'

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.is_ajax():
            return JsonResponse({'message': 'OK'})
        return response

    def form_invalid(self, form):
        if self.is_ajax():
            return JsonResponse(form.errors, status=400)
        return super().form_invalid(form)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if self.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)

# --- Categories ---
@method_decorator(require_permission('menu'), name='dispatch')
class CategoryListView(LoginRequiredMixin, ListView):
    model = Category
    template_name = 'categories/category_list.html'
    context_object_name = 'categories'

    def get_queryset(self):
        qs = super().get_queryset().order_by('-updated_at')
        q = self.request.GET.get('q')
        return qs.filter(name__icontains=q) if q else qs

@method_decorator(require_permission('menu'), name='dispatch')
class CategoryCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = Category
    fields = ['name', 'description', 'rank',  'show_in_orders', 'default_station']
    template_name = 'categories/category_form.html'
    success_url = reverse_lazy('category_list')

@method_decorator(require_permission('menu'), name='dispatch')
class CategoryDetailView(LoginRequiredMixin, DetailView):
    model = Category
    template_name = 'categories/category_detail.html'
    context_object_name = 'category'

@method_decorator(require_permission('menu'), name='dispatch')
class CategoryUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = Category
    fields = ['name', 'description', 'rank',  'show_in_orders', 'default_station']
    template_name = 'categories/category_form.html'
    success_url = reverse_lazy('category_list')

@method_decorator(require_permission('menu'), name='dispatch')
class CategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = Category
    success_url = reverse_lazy('category_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)

# --- Menu Items ---
@method_decorator(require_permission('menu'), name='dispatch')
class MenuItemListView(LoginRequiredMixin, ListView):
    model = MenuItem
    template_name = 'menu_items/menuitem_list.html'
    context_object_name = 'items'

    def get_queryset(self):
        qs = super().get_queryset().select_related('category').order_by('-updated_at')
        q = self.request.GET.get('q')
        return qs.filter(name__icontains=q) if q else qs

@method_decorator(require_permission('menu'), name='dispatch')
class MenuItemCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = MenuItem
    fields = ['category', 'name', 'description', 'price', 'food_panda_price', 'rank', 'is_available', 'image', 'station', 'weight', 'unit']
    template_name = 'menu_items/menuitem_form.html'
    success_url = reverse_lazy('menuitem_list')

@method_decorator(require_permission('menu'), name='dispatch')
class MenuItemDetailView(LoginRequiredMixin, DetailView):
    model = MenuItem
    template_name = 'menu_items/menuitem_detail.html'
    context_object_name = 'item'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .costing import menu_economics, recipe_breakdown
        try:
            ctx['economics'] = menu_economics(self.object)
        except Exception:
            ctx['economics'] = {'has_recipe': False}
        try:
            ctx['breakdown'] = recipe_breakdown(self.object.recipe)
        except Exception:
            ctx['breakdown'] = None
        return ctx

@method_decorator(require_permission('menu'), name='dispatch')
class MenuItemUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = MenuItem
    fields = ['category', 'name', 'description', 'price', 'food_panda_price', 'rank', 'is_available', 'image', 'station', 'weight', 'unit']
    template_name = 'menu_items/menuitem_form.html'
    success_url = reverse_lazy('menuitem_list')

@method_decorator(require_permission('menu'), name='dispatch')
class MenuItemDeleteView(LoginRequiredMixin, DeleteView):
    model = MenuItem
    success_url = reverse_lazy('menuitem_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)
    

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, View
)
from .models import (
    Category, MenuItem, Deal, DealItem,
    Table, Order, OrderItem, Payment
)
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

# ---------- DEALS CRUD ----------

@method_decorator(require_permission('menu'), name='dispatch')
class DealListView(LoginRequiredMixin, ListView):
    model = Deal
    template_name = 'deals/deal_list.html'
    context_object_name = 'deals'
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().order_by('-updated_at')
        q = self.request.GET.get('q')
        return qs.filter(name__icontains=q) if q else qs

@method_decorator(require_permission('menu'), name='dispatch')
class DealCreateView(LoginRequiredMixin, CreateView):
    model = Deal
    fields = ['name', 'description', 'price', 'food_panda_price', 'rank', 'is_available', 'image']
    template_name = 'deals/deal_form.html'
    success_url = reverse_lazy('deal_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Serialize all available MenuItems to JSON
        menu_items_qs = MenuItem.objects.filter(is_available=True).order_by('name')
        menu_items_data = [
            {'pk': mi.pk, 'name': mi.name, 'price': float(mi.price)}
            for mi in menu_items_qs
        ]
        context['menu_items_json'] = json.dumps(menu_items_data, cls=DjangoJSONEncoder)
        # For create view, no initial items
        context['initial_deal_items'] = []
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        data = json.loads(self.request.POST.get('deal_items_json', '[]'))
        for item in data:
            mi = MenuItem.objects.get(pk=item['menu_item_id'])
            DealItem.objects.create(deal=self.object, menu_item=mi, quantity=item['quantity'])
        return response


@method_decorator(require_permission('menu'), name='dispatch')
class DealUpdateView(LoginRequiredMixin, UpdateView):
    model = Deal
    fields = ['name', 'description', 'price', 'food_panda_price', 'rank', 'is_available', 'image']
    template_name = 'deals/deal_form.html'
    success_url = reverse_lazy('deal_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Serialize all available MenuItems to JSON
        menu_items_qs = MenuItem.objects.filter(is_available=True).order_by('name')
        menu_items_data = [
            {'pk': mi.pk, 'name': mi.name, 'price': float(mi.price)}
            for mi in menu_items_qs
        ]
        context['menu_items_json'] = json.dumps(menu_items_data, cls=DjangoJSONEncoder)
        # Pass existing DealItem rows as JSON
        context['initial_deal_items'] = [
            {'menu_item_id': di.menu_item.id, 'quantity': di.quantity}
            for di in self.object.deal_items.all()
        ]
        return context

    def form_valid(self, form):
        # Delete all existing items, then recreate from JSON
        DealItem.objects.filter(deal=self.object).delete()
        response = super().form_valid(form)
        data = json.loads(self.request.POST.get('deal_items_json', '[]'))
        for item in data:
            mi = MenuItem.objects.get(pk=item['menu_item_id'])
            DealItem.objects.create(deal=self.object, menu_item=mi, quantity=item['quantity'])
        return response

@method_decorator(require_permission('menu'), name='dispatch')
class DealDetailView(LoginRequiredMixin, DetailView):
    model = Deal
    template_name = 'deals/deal_detail.html'
    context_object_name = 'deal'


@method_decorator(require_permission('menu'), name='dispatch')
class DealDeleteView(LoginRequiredMixin, AjaxableResponseMixin, DeleteView):
    model = Deal
    success_url = reverse_lazy('deal_list')


# ---------- ORDER CRUD ----------

# core/views.py

import json
from django.urls import reverse_lazy
from django.views.generic import ListView
from django.db.models import F, Sum, ExpressionWrapper, DecimalField
from .models import Order
from django.utils.dateparse import parse_datetime

from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView
from .models import Order, Payment, Customer

class OrderListView(LoginRequiredMixin, ListView):
    model = Order
    template_name = 'orders/order_list.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get_paginate_by(self, queryset):
        # Turn off pagination if either date filter is present
        if self.request.GET.get('date_from') or self.request.GET.get('date_to'):
            return None
        return super().get_paginate_by(queryset)

    def get_queryset(self):
        qs = super().get_queryset().select_related('table', 'created_by').order_by('-created_at')

        q         = self.request.GET.get('q')
        status    = self.request.GET.get('status')
        date_from = self.request.GET.get('date_from')
        date_to   = self.request.GET.get('date_to')

        if q:
            qs = qs.filter(number__icontains=q)
        if status:
            qs = qs.filter(status=status)

        if date_from:
            dt = parse_datetime(date_from)
            if dt:
                qs = qs.filter(created_at__gte=timezone.make_aware(dt))
        if date_to:
            dt = parse_datetime(date_to)
            if dt:
                qs = qs.filter(created_at__lte=timezone.make_aware(dt))

        line_total = ExpressionWrapper(
            F('items__quantity') * F('items__unit_price'),
            output_field=DecimalField(max_digits=12, decimal_places=2)
        )
        money = DecimalField(max_digits=12, decimal_places=2)

        # Modifiers are charged per item unit and the tax lines can hold fixed
        # amounts, so both are pulled in with subqueries (they don't multiply rows).
        modifiers_per_order = (
            OrderItemModifier.objects
            .filter(order_item__order=OuterRef('pk'))
            .values('order_item__order')
            .annotate(total=Sum(F('price') * F('order_item__quantity')))
            .values('total')
        )
        taxes_per_order = (
            OrderTax.objects
            .filter(order=OuterRef('pk'))
            .values('order')
            .annotate(total=Sum('amount'))
            .values('total')
        )

        qs = qs.annotate(
            items_subtotal=Coalesce(Sum(line_total), Value(Decimal('0')), output_field=money),
            modifiers_total=Coalesce(Subquery(modifiers_per_order, output_field=money),
                                     Value(Decimal('0')), output_field=money),
        )

        # The bill treats modifiers as part of the subtotal, so the list does too.
        qs = qs.annotate(subtotal=F('items_subtotal') + F('modifiers_total'))

        qs = qs.annotate(
            # Sum() over zero rows is NULL, so orders saved before tax lines
            # existed keep using the legacy tax_percentage formula.
            taxes_total=Coalesce(
                Subquery(taxes_per_order, output_field=money),
                (F('subtotal') - F('discount')) * F('tax_percentage') / 100,
                output_field=money,
            ),
        )

        qs = qs.annotate(
            total_amount=ExpressionWrapper(
                (F('subtotal') - F('discount'))
                + F('taxes_total')
                + F('service_charge'),
                output_field=money
            )
        )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders_list = ctx['orders']  # page or full list

        # serial numbering
        if ctx.get('is_paginated'):
            ctx['start_index'] = ctx['page_obj'].start_index()
        else:
            ctx['start_index'] = 1

        # per‐page (or overall) total
        ctx['page_total'] = sum(
            (o.total_amount or Decimal('0')) for o in orders_list
        )

        # summary for the entire filtered set
        full_qs = self.get_queryset()
        ctx['summary_total_orders']  = full_qs.count()
        ctx['summary_total_amount']  = full_qs.aggregate(
            total=Sum(F('items__quantity') * F('items__unit_price'))
        )['total'] or Decimal('0')
        ctx['summary_received']      = Payment.objects.filter(
            order__in=full_qs
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        ctx['summary_remaining']     = ctx['summary_total_amount'] - ctx['summary_received']

        # keep the filters in the form
        ctx['date_from'] = self.request.GET.get('date_from', '')
        ctx['date_to']   = self.request.GET.get('date_to', '')

        return ctx

import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseServerError
from django.views import View
from django.utils.timezone import now
from django.utils.decorators import method_decorator
from core.permissions import require_permission
from django.db.models import F, Sum, ExpressionWrapper, DecimalField
from .models import (
    Category, MenuItem, Deal, Table,
    Order, OrderItem
)
from .escpos_printers import print_token, print_bill  # our new printing helpers


import json
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Category, MenuItem, Deal, Table, Order, OrderItem, PrintStatus
from .printing import send_to_printer
from .models import Waiter
from django.utils import timezone

# core/views.py
import json
from decimal import Decimal
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.db import transaction

from .models import (
    Category, MenuItem, Deal, Table, Order, OrderItem, 
    PrintStatus, Waiter, TableSession, Payment, PrintStation
)
from .utils import get_next_token_number
from .printing import send_to_printer




def _tax_and_modifier_payload():
    """
    JSON blobs for the order form: the active (optional) taxes and the modifier
    groups each menu item offers. Shared by the create and update views.
    """
    taxes_list = [
        {
            "id": t.id,
            "name": t.name,
            "rate": float(t.rate),
            "fixed_amount": float(t.fixed_amount),
            "tax_type": t.tax_type,
            "is_default": t.is_default,
            "is_optional": t.is_optional,
            "applies_after_discount": t.applies_after_discount,
        }
        for t in TaxRate.objects.filter(active=True)
    ]

    groups = (
        ModifierGroup.objects
        .filter(active=True)
        .prefetch_related('options', 'menu_items')
    )
    modifier_map = {}
    for group in groups:
        option_ids = set(group.menu_items.values_list('id', flat=True))
        payload = {
            "id": group.id,
            "name": group.name,
            "min_select": group.min_select,
            "max_select": group.max_select,
            "options": [
                {"id": o.id, "name": o.name, "price": float(o.price)}
                for o in group.options.filter(active=True)
            ],
        }
        if option_ids:
            for item_id in option_ids:
                modifier_map.setdefault(str(item_id), []).append(payload)
        else:
            # Empty selection means the group applies to every menu item.
            modifier_map.setdefault("*", []).append(payload)

    return {"taxes_json": json.dumps(taxes_list), "modifiers_json": json.dumps(modifier_map)}


def _attach_modifiers(order_item, modifiers):
    """
    Replace the modifiers on a saved order line with the ones the cashier picked.

    Names/prices are snapshotted onto the row, so editing a Modifier later never
    rewrites a bill that was already printed.
    """
    order_item.modifiers.all().delete()
    for mod in modifiers or []:
        if isinstance(mod, str):          # tolerate "Large + Cheese" style input
            parts = [p.strip() for p in mod.split('+') if p.strip()]
            mod = [{"id": None, "name": p, "price": 0} for p in parts]

        mod_name = (mod.get("name") or "").strip()
        if not mod_name:
            continue
        try:
            mod_price = Decimal(str(mod.get("price", 0) or 0))
        except (InvalidOperation, TypeError):
            mod_price = Decimal('0')
        OrderItemModifier.objects.create(
            order_item=order_item,
            modifier_id=mod.get("id") or None,
            name=mod_name,
            price=mod_price,
        )


def _apply_taxes(order, data):
    """
    Apply the ticked taxes to an order, replacing whatever was there before.

    tax_ids comes from the tax checkboxes; an empty list means no tax (taxes are
    fully optional). Legacy orders that never send the key keep their tax lines.
    """
    if "tax_ids" not in data:
        return
    requested = data.get("tax_ids") or []
    if not isinstance(requested, list):
        requested = [requested]

    order.clear_taxes()
    for tax_id in requested:
        try:
            tax = TaxRate.objects.get(id=tax_id)
        except (TaxRate.DoesNotExist, ValueError, TypeError):
            continue
        order.apply_tax(tax)
    order.refresh_from_db()


class OrderCreateView(LoginRequiredMixin, View):

    def get(self, request):
        # 1. Optimize Categories Query
        categories = (
            Category.objects
            .filter(show_in_orders=True)
            .order_by('rank')
            .prefetch_related('items')
        )

        # 2. Optimize Waiters Query
        all_waiters = list(Waiter.objects.order_by('name').values('id', 'name'))
        waiters_json = json.dumps(all_waiters)

        # 3. Optimize Menu Items Query (fetch foreign keys efficiently)
        all_menu_items = (
            MenuItem.objects
            .filter(is_available=True)
            .select_related('category', 'station') # Fetch station too
            .order_by('rank')
        )

        menu_items_list = [
            {
                "id": mi.id,
                "name": mi.name,
                "price": float(mi.price),
                "food_panda_price": float(mi.food_panda_price) if mi.food_panda_price is not None else 0.0,
                "category_id": mi.category_id,
                "image_url": mi.image.url if mi.image else ""
            }
            for mi in all_menu_items
        ]
        all_menu_items_json = json.dumps(menu_items_list)

        # 4. Optimize Deals Query
        all_deals = (
            Deal.objects
            .filter(is_available=True)
            .prefetch_related('deal_items__menu_item')
        )
        
        deals_list = []
        for dl in all_deals:
            items = [
                {"menu_item_id": di.menu_item_id, "quantity": di.quantity}
                for di in dl.deal_items.all()
            ]
            deals_list.append({
                "id": dl.id,
                "name": dl.name,
                "price": float(dl.price),
                "food_panda_price": float(dl.food_panda_price) if dl.food_panda_price is not None else 0.0,
                "image_url": dl.image.url if dl.image else "",
                "items": items,
            })
        all_deals_json = json.dumps(deals_list)

        initial_po_items_json = json.dumps([])

        # 5. Optimize Tables & Sessions Query
        tables = list(Table.objects.all().order_by("number"))
        
        # Prefetch sessions efficiently
        sessions = (
            TableSession.objects
            .select_related('table')
            .prefetch_related('picked_items')
            .in_bulk(field_name='table_id')
        )
        
        for t in tables:
            sess = sessions.get(t.id)
            if sess:
                total = sum(pi.quantity * pi.unit_price for pi in sess.picked_items.all())
                t.current_order_total = f"{total:.2f}"
                t.has_items = total > 0
            else:
                t.current_order_total = "0.00"
                t.has_items = False

        # === 6. FETCH CUSTOMERS (NEW) ===
        # Fetch ID, Name, Phone, Balance
        customers_qs = Customer.objects.all().values('id', 'name', 'phone', 'current_balance')
        customers_list = [
            {
                'id': c['id'],
                'name': c['name'],
                'phone': c['phone'],
                'balance': float(c['current_balance'] or 0)
            }
            for c in customers_qs
        ]
        all_customers_json = json.dumps(customers_list)

        return render(request, "orders/order_form.html", {
            "categories": categories,
            "all_menu_items_json": all_menu_items_json,
            "all_deals_json": all_deals_json,
            "initial_po_items_json": initial_po_items_json,
            "order": None,
            "tables": tables,
            "waiters_json": waiters_json,
            "all_customers_json": all_customers_json,
            **_tax_and_modifier_payload(),
        })
    
    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        user = request.user
        discount = Decimal(str(data.get("discount", 0) or 0))
        tax_percentage = Decimal(str(data.get("tax_percentage", 0) or 0))
        service_charge = Decimal(str(data.get("service_charge", 0) or 0))
        
        items_data = data.get("items", [])
        action = data.get("action", "create")
        table_id = data.get("table_id")
        
        is_food_panda = data.get("source") 
        is_home_delivery = data.get("isHomeDelivery") 
        
        waiter_id = data.get("waiter_id") or None
        mobile_no  = data.get("mobileNo") or None
        customer_address = data.get("customerAddress") or None
        customer_name = data.get("customerName") or None

        # --- NEW: Extract Credit/Payment Fields ---
        payment_method = data.get("payment_method", "cash")
        customer_id = data.get("customer_id") or None
        received_amount = Decimal(str(data.get("received_amount", 0) or 0))

        # --- VALIDATION: Credit requires Customer ---
        customer_obj = None
        if payment_method == 'credit':
            if not customer_id:
                return JsonResponse({"error": "Registered Customer is required for Credit orders."}, status=400)
            try:
                customer_obj = Customer.objects.get(id=customer_id)
            except Customer.DoesNotExist:
                return JsonResponse({"error": "Invalid Customer ID."}, status=400)
        
        # Resolve Waiter
        waiter = None
        if waiter_id:
            try:
                waiter = Waiter.objects.get(id=waiter_id)
            except Waiter.DoesNotExist:
                return JsonResponse({"error": "Invalid waiter_id"}, status=400)

        my_datetime = timezone.localtime(timezone.now())
        
        # Default status based on action
        status_value = "paid" if action == "paid" else "pending"
        
        # Only force 'pending' for Tables/Delivery IF the user did NOT click Paid.
        if (table_id or is_home_delivery == "yes") and action != "paid":
            status_value = "pending"

        session = None
        order = None
        session_token = None

        # === 1. ORDER CREATION ===
        if table_id:
            with transaction.atomic():
                session = TableSession.objects.select_for_update().get(table_id=table_id)
                
                if session.token_number is None:
                    session.token_number = get_next_token_number(station=None)
                    session.save(update_fields=['token_number'])
                
                session_token = session.token_number

                order = Order.objects.create(
                    created_by=user,
                    table_id=table_id,
                    discount=discount,
                    tax_percentage=tax_percentage,
                    service_charge=service_charge,
                    status=status_value,
                    source=is_food_panda,
                    waiter=waiter,
                    isHomeDelivery=is_home_delivery,
                    mobile_no=mobile_no,
                    customer_name=customer_name,
                    customer_address=customer_address,
                    created_at=my_datetime,
                    token_number=session_token,
                    customer=customer_obj, # Link Customer
                )

                # Reset Session
                session.token_number = None
                session.waiter = None
                session.save(update_fields=['token_number', 'waiter'])
                
                # Update Table Occupancy
                if status_value == "paid":
                    Table.objects.filter(pk=table_id).update(is_occupied=False)
                else:
                    Table.objects.filter(pk=table_id).update(is_occupied=True)

        else:
            # Walk-in / Delivery
            token_number = get_next_token_number(station=None)
            
            order = Order.objects.create(
                created_by=user,
                table_id=None,
                discount=discount,
                tax_percentage=tax_percentage,
                service_charge=service_charge,
                status=status_value,
                source=is_food_panda,
                waiter=waiter,
                isHomeDelivery=is_home_delivery,
                mobile_no=mobile_no,
                customer_name=customer_name,
                customer_address=customer_address,
                created_at=my_datetime,
                token_number=token_number,
                customer=customer_obj, # Link Customer
            )

        # === 2. ITEMS BULK CREATION ===
        order_items_to_create = []

        for it in items_data:
            qty = int(it.get("quantity", 1))
            unit_price = Decimal(str(it.get("unit_price", 0)))

            item_type = it.get("type")

            order_item = OrderItem(
                order=order,
                quantity=qty,
                unit_price=unit_price,
                token_printed=False
            )
            
            if item_type == "menu":
                order_item.menu_item_id = it["menu_item_id"]
            elif item_type == "deal":
                order_item.deal_id = it["deal_id"]
            
            # Keep the modifiers chosen on the frontend so they can be attached below.
            order_item._pending_modifiers = it.get("modifiers", []) or []
            order_items_to_create.append(order_item)

        if order_items_to_create:
            OrderItem.objects.bulk_create(order_items_to_create)

            # bulk_create() bypasses OrderItem.save(), so the stock deduction that
            # normally happens there never runs. Call it explicitly, otherwise
            # selling a dish does not reduce its raw materials.
            for oi in order_items_to_create:
                oi.update_inventory_usage()

            # --- Attach modifiers (snapshotted name/price) ---
            for oi in order_items_to_create:
                _attach_modifiers(oi, getattr(oi, "_pending_modifiers", None))

        # Totals (subtotal incl. modifiers) come from the order model further below.

        # === 2b. TAXES (multiple, optional) ===
        # tax_ids comes from the tax checkboxes; empty means no tax (fully optional).
        _apply_taxes(order, data)

        # === 3. PAYMENT LOGIC (UPDATED FOR CREDIT) ===
        
        # Calculate Grand Total for accurate Credit/Ledger math.
        # Uses the order model so multiple taxes AND modifiers are included;
        # the legacy tax_percentage field only holds percentage taxes.
        grand_total = order.get_total()

        if status_value == 'paid':
            if payment_method == 'credit' and customer_obj:
                # --- A. Credit Logic ---
                # 1. Calculate how much goes to Udhaar
                udhaar_amount = grand_total - received_amount
                
                # 2. Update Customer Balance (Increase receivable)
                customer_obj.current_balance += udhaar_amount
                customer_obj.save()

                # 3. If they paid anything partially, record that payment
                if received_amount > 0:
                    Payment.objects.create(
                        order=order,
                        amount=received_amount,
                        method="cash", # Partial payment is usually cash
                        details=f"Partial payment for Credit Order. Remaining: {udhaar_amount}"
                    )
                # Note: If received_amount is 0, no Payment record is created (pure credit).
                
            else:
                # --- B. Standard Payment (Cash/Card/etc) ---
                # Only create payment if not table/delivery pending (already checked by status_value='paid')
                Payment.objects.create(
                    order=order,
                    amount=grand_total, # Use grand_total to be accurate
                    method=payment_method,
                    details=""
                )

        # === 4. PRINTING LOGIC ===
        if status_value == "paid" or status_value == "pending":
            try:
                ps = PrintStatus.objects.first()
                bill_enabled  = ps.bill  if ps else True 
                token_enabled = ps.token if ps else True

                # --- TOKEN ---
                if token_enabled and not table_id:
                    new_items = list(Order.objects.get(pk=order.id).items.all())
                    
                    grouped_items = {}
                    for oi in new_items:
                        station = None
                        if oi.menu_item:
                            station = oi.menu_item.get_effective_station()
                        key = station if station else 'Global'
                        if key not in grouped_items: grouped_items[key] = []
                        grouped_items[key].append(oi)

                    for key, group_items in grouped_items.items():
                        target_printer = "POS80 Printer" # Default
                        token_num = order.token_number

                        if key == 'Global':
                            header_label = "KITCHEN TOKEN"
                        else:
                            station_obj = key
                            header_label = f"{station_obj.name.upper()} TOKEN"
                            if station_obj.printer_name:
                                target_printer = station_obj.printer_name
                            if station_obj.use_separate_sequence:
                                token_num = get_next_token_number(station=station_obj)

                        from .views import build_token_bytes_for_items
                        token_data = build_token_bytes_for_items(order, group_items, header_label)
                        # Skip printing if printer name is "no print" or empty
                        if target_printer and target_printer.strip().lower() not in ['no print', 'noprint', '']:
                            send_to_printer(token_data, printer_name=target_printer)
                        else:
                            print(f"Skipping print for {header_label} - printer set to 'no print'")

                    item_ids = [i.id for i in new_items]
                    OrderItem.objects.filter(id__in=item_ids).update(token_printed=True)

                # --- BILL ---
                if bill_enabled:
                    bill_printer = "POS80 Printer"
                    
                    bill_data_cust = build_bill_bytes(order, is_food_panda, "")
                    send_to_printer(bill_data_cust, printer_name=bill_printer)
                    
                    # bill_data_office = build_bill_bytes(order, is_food_panda, "Office Copy")
                    # send_to_printer(bill_data_office, printer_name=bill_printer)

            except Exception as e:
                print(f"Printing Error: {e}")
                return JsonResponse({
                    "message": "Order Created (Printing Failed)", 
                    "order_id": order.id,
                    "error": str(e)
                }, status=200)

        return JsonResponse({"message": "Order Created", "order_id": order.id})



import json
from django.shortcuts      import render, get_object_or_404
from django.http           import JsonResponse, HttpResponseBadRequest
from django.views          import View
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import (
    Category, MenuItem, Deal,
    Table, Order, OrderItem, PrintStatus
)
from .printing import send_to_printer


class OrderUpdateView(LoginRequiredMixin, View):
    """
    GET:  Render “Edit Order” form pre-populated + table‑selector annotated.
    POST: Accept JSON (with table_id), diff OrderItems, print if paid.
    """

    def get(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        
        categories = Category.objects.prefetch_related('items').order_by('name')
        all_waiters = Waiter.objects.order_by('name').values('id','name')
        waiters_json = json.dumps(list(all_waiters))

        # Serialize menu items
        all_menu_items = MenuItem.objects.filter(is_available=True).select_related('category')
        menu_items_list = [
            {
                "id": mi.id,
                "name": mi.name,
                "price": float(mi.price),
                "food_panda_price": float(mi.food_panda_price) if mi.food_panda_price is not None else 0.0,
                "category_id": mi.category.id,
                "image_url": mi.image.url if mi.image else ""
            }
            for mi in all_menu_items
        ]
        all_menu_items_json = json.dumps(menu_items_list)

        # Serialize deals
        all_deals = Deal.objects.filter(is_available=True).prefetch_related('deal_items__menu_item')
        deals_list = []
        for dl in all_deals:
            items = [
                {"menu_item_id": di.menu_item.id, "quantity": di.quantity}
                for di in dl.deal_items.all()
            ]
            deals_list.append({
                "id": dl.id,
                "name": dl.name,
                "price": float(dl.price),
                "food_panda_price": float(dl.food_panda_price) if dl.food_panda_price is not None else 0.0,
                "image_url": dl.image.url if dl.image else "",
                "items": items,
            })
        all_deals_json = json.dumps(deals_list)

        # Existing items for JS
        existing_items = []
        for oi in order.items.prefetch_related('modifiers'):
            item_modifiers = [
                {"id": m.modifier_id, "name": m.name, "price": float(m.price)}
                for m in oi.modifiers.all()
            ]
            if oi.menu_item_id:
                existing_items.append({
                    "type": "menu",
                    "menu_item_id": oi.menu_item_id,
                    "name": oi.menu_item.name,
                    "quantity": oi.quantity,
                    "unit_price": float(oi.unit_price),
                    "modifiers": item_modifiers,
                    "modifiers_total": float(oi.modifiers_total()),
                })
            else:
                existing_items.append({
                    "type": "deal",
                    "deal_id": oi.deal_id,
                    "name": oi.deal.name,
                    "quantity": oi.quantity,
                    "unit_price": float(oi.unit_price),
                    "modifiers": item_modifiers,
                    "modifiers_total": float(oi.modifiers_total()),
                })
        initial_po_items_json = json.dumps(existing_items)

        # Taxes already applied to this order, so the checkboxes come up ticked
        # instead of resetting to the catalogue defaults.
        order_tax_ids_json = json.dumps(
            [tl.tax_rate_id for tl in order.tax_lines.all() if tl.tax_rate_id]
        )

        # Annotate tables
        tables = list(Table.objects.all().order_by("number"))
        for t in tables:
            pending = Order.objects.filter(table=t, status="pending").first()
            total   = sum(oi.quantity * oi.unit_price for oi in (pending.items.all() if pending else []))
            t.current_order_total = f"{total:.2f}"
            t.has_items           = (total > 0)

        # === FETCH CUSTOMERS (NEW) ===
        customers_qs = Customer.objects.all().values('id', 'name', 'phone', 'current_balance')
        customers_list = [
            {
                'id': c['id'],
                'name': c['name'],
                'phone': c['phone'],
                'balance': float(c['current_balance'] or 0)
            }
            for c in customers_qs
        ]
        all_customers_json = json.dumps(customers_list)

        return render(request, "orders/order_form.html", {
            "categories":          categories,
            "all_menu_items_json": all_menu_items_json,
            "all_deals_json":      all_deals_json,
            "initial_po_items_json": initial_po_items_json,
            "order":               order,
            "tables":              tables,
            "waiters_json": waiters_json,
            "all_customers_json": all_customers_json,
            "order_tax_ids_json": order_tax_ids_json,
            **_tax_and_modifier_payload(),
        })


    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid JSON")

        # 1) Update order fields
        waiter_id = data.get("waiter_id") or None
        is_home_delivery = data.get("isHomeDelivery") or None
        order.discount       = Decimal(str(data.get("discount", 0) or 0))
        order.tax_percentage = Decimal(str(data.get("tax_percentage", 0) or 0))
        order.service_charge = Decimal(str(data.get("service_charge", 0) or 0))
        order.table_id       = data.get("table_id")
        action               = data.get("action", "update")
        
        # Logic: If action is paid, mark paid. 
        order.status         = "paid" if action == "paid" else "pending"
        
        order.waiter_id = waiter_id
        order.isHomeDelivery = is_home_delivery
        
        # --- NEW: Extract Credit Fields ---
        payment_method = data.get("payment_method", "cash")
        customer_id = data.get("customer_id") or None
        received_amount = Decimal(str(data.get("received_amount", 0) or 0))

        # --- VALIDATION: Credit requires Customer ---
        customer_obj = None
        if payment_method == 'credit':
            if not customer_id:
                return JsonResponse({"error": "Registered Customer is required for Credit orders."}, status=400)
            try:
                customer_obj = Customer.objects.get(id=customer_id)
                order.customer = customer_obj # Link to order
            except Customer.DoesNotExist:
                return JsonResponse({"error": "Invalid Customer ID."}, status=400)
        
        order.save()

        # 2) Table occupancy
        if order.table_id is not None:
            tbl = Table.objects.get(pk=order.table_id)
            tbl.is_occupied = (order.status != "paid")
            tbl.save()

        # 3) Diff algorithm for OrderItems (unchanged logic)
        incoming = data.get("items", [])
        existing_map = {(oi.menu_item_id, oi.deal_id): oi for oi in order.items.all()}

        for it in incoming:
            if it.get("type") == "menu":
                key = (it["menu_item_id"], None)
                m_id, d_id = it["menu_item_id"], None
            else:
                key = (None, it["deal_id"])
                m_id, d_id = None, it["deal_id"]

            if key in existing_map:
                oi = existing_map.pop(key)
                if int(oi.quantity or 0) != int(it["quantity"] or 0):
                    # Quantity changed: return old deduction, apply the new one.
                    oi.reverse_inventory_usage()
                    oi.quantity    = it["quantity"]
                    oi.unit_price = Decimal(str(it["unit_price"]))
                    oi.save()
                else:
                    oi.unit_price = Decimal(str(it["unit_price"]))
                    oi.save(update_fields=['unit_price'])
                # Modifiers belong to the line, so they follow it through an edit.
                _attach_modifiers(oi, it.get("modifiers"))
            else:
                new_oi = OrderItem.objects.create(
                    order=order, menu_item_id=m_id, deal_id=d_id,
                    quantity=it["quantity"], unit_price=Decimal(str(it["unit_price"]))
                )
                _attach_modifiers(new_oi, it.get("modifiers"))

        for oi in existing_map.values():
            # Removed line: return its stock before deleting. reverse_inventory_usage()
            # deletes the 'out' rows individually because QuerySet.delete() would skip
            # the stock-restoring delete() override. The old "dangling rows" cleanup
            # that followed was also deleting unrelated rows: `oi.pk` is already None
            # after oi.delete(), so it filtered on order_item IS NULL.
            oi.reverse_inventory_usage()
            oi.delete()

        # 3b) Taxes (multiple, optional) - same handling as the create view
        _apply_taxes(order, data)

        # 4) If marking paid, Handle Payment & Printing
        if order.status == "paid":

            # --- Recalculate Totals (Items, modifiers and taxes may have changed) ---
            # Percent taxes depend on the discounted subtotal, so refresh them first.
            order.recalculate_taxes()
            grand_total = order.get_total()

            # --- Handle Credit / Payment Logic ---
            if payment_method == 'credit' and customer_obj:
                # 1. Calculate Udhaar
                udhaar_amount = grand_total - received_amount
                
                # 2. Update Customer Balance
                customer_obj.current_balance += udhaar_amount
                customer_obj.save()

                # 3. Record Partial Payment (if any)
                if received_amount > 0:
                    Payment.objects.create(
                        order=order,
                        amount=received_amount,
                        method="cash", 
                        details=f"Partial payment for Credit Order. Remaining: {udhaar_amount}"
                    )
            else:
                # Standard Payment
                # Check if payment already exists (since this is update view), if not create
                if not hasattr(order, 'payment'):
                    Payment.objects.create(
                        order=order,
                        amount=grand_total,
                        method=payment_method,
                        details=""
                    )
                else:
                    # Optional: Update existing payment if user changed method/amount
                    # For now, we assume simple closure.
                    pass

            # --- Printing ---
            try:
                ps             = PrintStatus.objects.first()
                token_on       = ps.token if ps else False
                bill_on        = ps.bill  if ps else True 
                
                printer_name = "POS80 Printer"

                if token_on:
                    token_data = build_token_bytes(order)
                    send_to_printer(token_data, printer_name=printer_name)
                
                if bill_on:
                    bill_data  = build_bill_bytes(order)
                    send_to_printer(bill_data, printer_name=printer_name)

                # free the table
                if order.table_id is not None:
                    tbl = Table.objects.get(pk=order.table_id)
                    tbl.is_occupied = False
                    tbl.save()

            except Exception as e:
                return JsonResponse({"error": f"Print failed: {e}"}, status=500)

        return JsonResponse({"message": "Order Updated", "order_id": order.id})
    

# core/views.py

from decimal import Decimal
from django.views.generic import DetailView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Order

class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    template_name = 'orders/order_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object

        # Prefetch so the items, their modifiers and the tax lines cost 3 queries,
        # not one per line.
        order = (
            Order.objects
            .prefetch_related('items__modifiers', 'tax_lines')
            .get(pk=order.pk)
        )
        ctx['order'] = order

        # Totals come from the model so modifiers and every applied tax
        # (percentage, fixed, optional) are counted exactly once.
        ctx.update({
            'subtotal':      order.get_subtotal(),
            'tax_lines':     order.tax_display_lines(),
            'tax_amount':    order.get_tax_total(),
            'grand_total':   order.get_total(),
        })
        return ctx



@method_decorator(require_permission('accounts'), name='dispatch')
class OrderDeleteView(LoginRequiredMixin, AjaxableResponseMixin, DeleteView):
    model = Order
    success_url = reverse_lazy('order_list')

    def form_valid(self, form):
        # Voiding an order returns its deducted raw materials to stock.
        for oi in self.object.items.all():
            try:
                oi.reverse_inventory_usage()
            except Exception:
                pass
        return super().form_valid(form)

# ---------- Order holds (park / recall) ----------
# A held bill is a snapshot in OrderHold, never a real Order, so parking a bill
# does not consume stock, use a token number or affect the day's sales.
def _hold_payload(hold):
    return {
        'id': hold.id,
        'label': hold.label,
        'table_id': hold.table_id,
        'table_number': hold.table.number if hold.table_id else None,
        'items': hold.items or [],
        'discount': str(hold.discount),
        'service_charge': str(hold.service_charge),
        'tax_ids': hold.tax_ids or [],
        'item_count': hold.item_count,
        'total': str(hold.total),
        'created_at': timezone.localtime(hold.created_at).strftime('%H:%M'),
        'is_active': hold.is_active,
    }


@method_decorator(require_permission('sales'), name='dispatch')
class OrderHoldView(LoginRequiredMixin, View):
    """GET: list parked bills.  POST: park the cart that is currently on screen."""

    def get(self, request):
        holds = (
            OrderHold.objects
            .filter(is_active=True)
            .select_related('table')
            .order_by('-created_at')[:50]
        )
        return JsonResponse({'holds': [_hold_payload(h) for h in holds]})

    def post(self, request):
        try:
            data = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return HttpResponseBadRequest('Invalid JSON')

        items = data.get('items') or []
        if not items:
            return JsonResponse({'error': 'There is nothing to hold.'}, status=400)

        label = (data.get('label') or '').strip()
        if not label:
            label = 'Hold %s' % timezone.localtime().strftime('%H:%M')

        table_id = data.get('table_id') or None
        if table_id and not Table.objects.filter(pk=table_id).exists():
            table_id = None

        hold = OrderHold.objects.create(
            label=label[:80],
            table_id=table_id,
            items=items,
            discount=Decimal(str(data.get('discount', 0) or 0)),
            service_charge=Decimal(str(data.get('service_charge', 0) or 0)),
            tax_ids=data.get('tax_ids') or [],
            created_by=request.user,
        )
        return JsonResponse({'message': 'Bill parked', 'hold': _hold_payload(hold)})


@method_decorator(require_permission('sales'), name='dispatch')
class OrderHoldRecallView(LoginRequiredMixin, View):
    """POST: hand the parked bill back to the order screen."""

    def post(self, request, pk):
        hold = get_object_or_404(OrderHold, pk=pk)

        # Recalling twice is harmless: only the first recall is stamped.
        if hold.recalled_at is None:
            hold.recalled_at = timezone.now()
            hold.save(update_fields=['recalled_at'])

        return JsonResponse({'message': 'Bill recalled', 'hold': _hold_payload(hold)})


@method_decorator(require_permission('sales'), name='dispatch')
class OrderHoldDeleteView(LoginRequiredMixin, View):
    """POST: throw a parked bill away."""

    def post(self, request, pk):
        hold = get_object_or_404(OrderHold, pk=pk)
        hold.delete()
        return JsonResponse({'message': 'Held bill removed'})


from decimal import Decimal
from .utils import compute_recipe_cost

import os
from django.conf import settings
from .escpos_logo import logo_to_escpos_bytes

def build_token_bytes(order, is_food_panda = "walk_in"):
    esc = b"\x1B"
    gs  = b"\x1D"
    lines = []

    # ─── Restaurant name, larger/bold ────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x01")   # center alignment
    # lines.append(esc + b"\x21" + b"\x30")   # double height & width
    lines.append(b"NEW MARHABA\n")
    lines.append(esc + b"\x21" + b"\x00")   # back to normal
    lines.append(b"\n")

    # ─── Header “KITCHEN TOKEN” ───────────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x01")   # center
    lines.append(b"KITCHEN TOKEN\n\n")

    # ─── Token number, bold, slightly bigger ─────────────────────────────
    token_str = str(order.token_number).encode("ascii")

    
    lines.append(esc + b"\x61" + b"\x01")   # center
    lines.append(esc + b"\x21" + b"\x30")   # ESC ! 0x10 → double width, normal height
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    

    lines.append(esc + b"\x61" + b"\x01")
    lines.append(esc + b"\x21" + b"\x30")

    if order.isHomeDelivery == "yes":
        lines.append(b"HOME DELIVERY\n\n")
    if order.isHomeDelivery == "no":
        lines.append(b"PARCEL\n\n")

    lines.append(esc + b"\x21" + b"\x00")   # back to normal
    if order.waiter and order.isHomeDelivery == "yes":
        waiter_bytes = f"Rider: {order.waiter.name}\n".encode("ascii", "ignore")
        lines.append(waiter_bytes)
    elif order.waiter:
        waiter_bytes = f"Waiter: {order.waiter.name}\n".encode("ascii", "ignore")
        lines.append(waiter_bytes)

    
    # now_str = order.created_at.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    now_local = timezone.localtime(timezone.now())
    now_str = now_local.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")

    lines.append(esc + b"\x61" + b"\x00")   # left align
    lines.append(b"Date: " + now_str + b"\n")
    lines.append(b"-" * 32 + b"\n")         # 32-char full width separator
    lines.append(esc + b"\x21" + b"\x10") 

    # ─── Order Items List (left name, right qty) ─────────────────────────
    new_items = order.items.filter(token_printed=False)
    i = 1
    for oi in new_items:
        name = (oi.menu_item.name if oi.menu_item else oi.deal.name)[:20]
        name_field = name.ljust(20).encode("ascii", "ignore")
        serial_number = str(i).encode("ascii", "ignore")
        qty_bytes = str(oi.quantity).rjust(3).encode("ascii")
        lines.append(serial_number + b". " + name_field + b"  x" + qty_bytes + b"\n")
        i += 1

    lines.append(b"\n\n\n\n\n")
    # ─── Feed + Cut ────────────────────────────────────────────────────────
    lines.append(b"\n" * 4)
    lines.append(gs + b"\x56" + b"\x00")    # full cut

    return b"".join(lines)


def build_bill_bytes(order, is_food_panda = "walk_in", copy = ""):
    esc = b"\x1B"
    gs  = b"\x1D"
    lines = []

    # ─── Restaurant name, double size ────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x01")
    lines.append(esc + b"\x21" + b"\x30")
    lines.append(b"NEW MARHABA\n")
    lines.append(esc + b"\x21" + b"\x00")
    lines.append(b"0305 3969040\n\n")
    lines.append(b"\n")
    
    
    # ─── Order metadata (left) ────────────────────────────────────────────
    order_number_str = str(order.number).encode("ascii")
    token_str = str(order.token_number).encode("ascii")
    copy = str(copy).encode("ascii")
    # dt = order.created_at.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    now_local = timezone.localtime(timezone.now())
    dt = now_local.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")

    lines.append(esc + b"\x61" + b"\x00")   # left align
    lines.append(b"" + copy + b"\n")
    lines.append(b"Order #: " + order_number_str + b"\n")
    lines.append(b"Date    : " + dt + b"\n")
    lines.append(b"Token # : " + token_str + b"\n")
    table_number = False
    try:
        table_number = str(order.table.number).encode("ascii")
    except:
        print('')
    if table_number:
        lines.append(b"Table #: "+ table_number + b"\n")
    else:
        if order.isHomeDelivery == "yes":
            lines.append(b"HOME DELIVERY\n\n")
        if order.isHomeDelivery == "no":
            lines.append(b"PARCEL\n\n")
        if order.customer_name:
            customerName = str(order.customer_name).encode("ascii")
            lines.append(b"Customer Name: " + customerName + b"\n")
        if order.mobile_no:
            mobileNo = str(order.mobile_no).encode("ascii")
            lines.append(b"Customer Mobile: " + mobileNo + b"\n")
        if order.customer_address:
            customerAddress = str(order.customer_address).encode("ascii")
            lines.append(b"Customer Add: " + customerAddress + b"\n")

    if order.waiter and order.isHomeDelivery == "yes":
        waiter_bytes = f"Rider: {order.waiter.name}\n".encode("ascii", "ignore")
        lines.append(waiter_bytes)
    elif order.waiter:
        waiter_bytes = f"Waiter: {order.waiter.name}\n".encode("ascii", "ignore")
        lines.append(waiter_bytes)

    lines.append(b"-" * 40 + b"\n")         # 40-char separator

    # ─── Column headers (Item │ Qty │ Price │ Total) ──────────────────────
    lines.append(esc + b"\x45" + b"\x01")   # bold on
    # 16 chars for name, 4 chars for qty, 7 for price, 8 for total = 35 + spacing
    lines.append(b"Item             Qty  Price   Total\n")
    lines.append(esc + b"\x45" + b"\x00")   # bold off
    lines.append(b"-" * 40 + b"\n")

    # ─── Each OrderItem row ───────────────────────────────────────────────
    # unit price shown = item price + its modifiers, so the printed arithmetic
    # (unit x qty = total) always adds up.
    subtotal = 0.0

    for oi in order.items.select_related('menu_item', 'deal').prefetch_related('modifiers'):
        name = (oi.menu_item.name if oi.menu_item else oi.deal.name)[:16]
        name_field = name.ljust(16).encode("ascii", "ignore")

        qty = oi.quantity
        qty_field = str(qty).rjust(3).encode("ascii")

        unit_price_f = float(oi.effective_unit_price())
        price_field = f"{unit_price_f:.2f}".rjust(7).encode("ascii")

        line_total_f = float(oi.line_total())
        total_field = f"{line_total_f:.2f}".rjust(7).encode("ascii")

        subtotal += line_total_f

        # e.g. b"Fish & Chips   2   150.00 300.00\n"
        lines.append(name_field + b" " + qty_field + b" " + price_field + b" " + total_field + b"\n")

        # Modifiers chosen for this line, indented under the item they belong to.
        for mod in oi.modifiers.all():
            mod_name = ("+ " + mod.name)[:16].encode("ascii", "ignore")
            mod_price = f"{float(mod.price or 0):.2f}".rjust(7).encode("ascii")
            lines.append(mod_name.ljust(16) + b"   " + mod_price + b" " * 8 + b"\n")

    lines.append(b"-" * 40 + b"\n\n")

    # ─── Totals section ───────────────────────────────────────────────────
    discount_f = float(order.discount or 0)
    service_f = float(order.service_charge or 0)

    currency = _currency_prefix_bytes()

    lines.append(b"Subtotal : " + currency + f"{subtotal:.2f}".encode("ascii") + b"\n")
    lines.append(b"Discount : " + currency + f"{discount_f:.2f}".encode("ascii") + b"\n")

    # One line per tax (VAT, WHT, Service Levy, ...); old orders that predate
    # tax lines still print their single legacy tax.
    for tax_line in order.tax_display_lines():
        if tax_line.tax_type == 'fixed':
            tax_label = f"{tax_line.name} (fixed)"
        else:
            tax_label = f"{tax_line.name} ({float(tax_line.rate or 0):g}%)"
        lines.append(
            tax_label.encode("ascii", "ignore") + b" : "
            + currency + f"{float(tax_line.amount):.2f}".encode("ascii") + b"\n"
        )

    lines.append(b"Service : " + currency + f"{service_f:.2f}".encode("ascii") + b"\n")
    lines.append(esc + b"\x21" + b"\x20")   # ESC ! 0x20 → double‐width
    lines.append(b"Grand Total: " + currency + f"{float(order.get_total()):.2f}".encode("ascii") + b"\n\n")
    lines.append(esc + b"\x45" + b"\x00")   # bold off

    # ─── Footer / Branding (professional signature) ───────────────────────
    lines.append(esc + b"\x21" + b"\x00")   # back to normal
    lines.append(b"-" * 40 + b"\n\n")
    lines.append(b"Home Delivery Contact:  0310 8000667\n\n")
    lines.append(esc + b"\x61" + b"\x00")   # left align
    lines.append(b"-" * 40 + b"\n\n")
    lines.append(esc + b"\x61" + b"\x01")   # center
    # Company name
    lines.append(esc + b"\x21" + b"\x20")   # ESC ! 0x20 → double‐width
    lines.append(_brand_name_bytes() + b"\n")
    lines.append(esc + b"\x21" + b"\x00")   # back to normal

    # Developer / tagline / contact
    lines.append(b"Developed by Qonkar Technologies\n")
    lines.append(b"www.qonkar.com | +92 305 8214945\n")
    lines.append(b"\n" * 5)

    # ─── Cut paper (full) ─────────────────────────────────────────────────
    lines.append(gs + b"\x56" + b"\x00")

    return b"".join(lines)


from django.views.decorators.http import require_http_methods

@require_http_methods(["GET", "POST"])
def update_print_status(request):
    if request.method == "GET":
        # Return existing status or defaults if none yet
        ps = PrintStatus.objects.first()
        if ps is None:
            return JsonResponse({"token": False, "bill": False})
        return JsonResponse({"token": ps.token, "bill": ps.bill})

    # POST path: toggle one field
    field = request.POST.get("field")
    value = request.POST.get("value")
    if field not in ("token", "bill") or value not in ("true", "false"):
        return JsonResponse(
            {"status": "error", "message": "Invalid field or value."},
            status=400
        )

    ps, created = PrintStatus.objects.get_or_create(defaults={"token": False, "bill": False})
    setattr(ps, field, (value == "true"))
    ps.save()

    return JsonResponse({
        "status": "success",
        "token": ps.token,
        "bill": ps.bill
    })

# core/views.py
from django.shortcuts import render
from django.db.models import Sum, F
from django.utils import timezone
from datetime import date, timedelta
import json

from .models import Order, OrderItem, MenuItem

def reports_view(request):
    """
    Render a page showing:
      - Today's sales
      - This month's sales
      - Total revenue + total orders in a custom date range
      - A 7-day daily-sales line chart (with floats, not Decimals)
      - A top-10 best-selling items horizontal bar chart
    """

    # 1) Parse start_date / end_date from GET or default to today
    if request.GET.get('start_date'):
        try:
            start_date = date.fromisoformat(request.GET['start_date'])
        except ValueError:
            start_date = date.today()
    else:
        start_date = date.today()

    if request.GET.get('end_date'):
        try:
            end_date = date.fromisoformat(request.GET['end_date'])
        except ValueError:
            end_date = date.today()
    else:
        end_date = date.today()

    if end_date < start_date:
        end_date = start_date

    # 2) Paid orders in the custom range
    paid_orders_in_range = Order.objects.filter(
        created_at__date__gte=start_date,
        created_at__date__lte=end_date,
        status='paid'
    )

    # 3) Total orders in that range
    total_orders = paid_orders_in_range.count()

    # 4) Total revenue in that range (sum of quantity * unit_price)
    revenue_agg = OrderItem.objects.filter(
        order__in=paid_orders_in_range
    ).aggregate(
        total_revenue=Sum(F('quantity') * F('unit_price'))
    )
    total_revenue = revenue_agg['total_revenue'] or 0  # This is a Decimal or 0

    # 5) Top 10 best-selling items (sum of quantity). Cast to int.
    top_items_qs = (
        OrderItem.objects
        .filter(order__in=paid_orders_in_range, menu_item__isnull=False)
        .values('menu_item__name')
        .annotate(total_qty=Sum('quantity'))
        .order_by('-total_qty')[:10]
    )
    top_labels = []
    top_data = []
    for row in top_items_qs:
        top_labels.append(row['menu_item__name'])
        # row['total_qty'] might be a Decimal or int. Cast to int() if safe.
        top_data.append(int(row['total_qty']))

    # 6) Compute last 7 calendar days' revenue (float)
    today = date.today()
    daily_labels = []
    daily_data = []

    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        daily_labels.append(d.strftime("%Y-%m-%d"))

        day_sum_agg = (
            OrderItem.objects
            .filter(
                order__created_at__date=d,
                order__status='paid'
            )
            .aggregate(day_sum=Sum(F('quantity') * F('unit_price')))
        )['day_sum'] or 0

        # day_sum_agg is a Decimal or 0; cast to float
        daily_data.append(float(day_sum_agg))

    # 7) Today's total revenue (cast to float)
    today_revenue_agg = (
        OrderItem.objects
        .filter(
            order__created_at__date=today,
            order__status='paid'
        )
        .aggregate(sum=Sum(F('quantity') * F('unit_price')))
    )['sum'] or 0
    today_revenue = float(today_revenue_agg)

    # 8) This month's total revenue (cast to float)
    first_of_month = today.replace(day=1)
    month_revenue_agg = (
        OrderItem.objects
        .filter(
            order__created_at__date__gte=first_of_month,
            order__created_at__date__lte=today,
            order__status='paid'
        )
        .aggregate(sum=Sum(F('quantity') * F('unit_price')))
    )['sum'] or 0
    month_revenue = float(month_revenue_agg)

    # 9) Build context. JSON-dump only the Python lists (floats/ints)
    context = {
        'start_date': start_date.isoformat(),
        'end_date':   end_date.isoformat(),

        'total_orders':     total_orders,
        'total_revenue':    total_revenue,   # Decimal or 0; safe to render in template
        'today_total':      today_revenue,   # Now a float
        'this_month_total': month_revenue,   # Now a float

        # JSON strings for Chart.js
        'daily_labels': json.dumps(daily_labels),
        'daily_data':   json.dumps(daily_data),
        'top_labels':   json.dumps(top_labels),
        'top_data':     json.dumps(top_data),
    }

    return render(request, 'reports.html', context)


# your_app/views.py
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Max
from datetime import datetime, time, timedelta

from .models import OrderItem

def sales_report(request):
    sd = request.GET.get('start_date')
    ed = request.GET.get('end_date')
    if not sd or not ed:
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    try:
        start_date = datetime.strptime(sd, "%Y-%m-%d").date()
        end_date   = datetime.strptime(ed, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format'}, status=400)

    start_dt = timezone.make_aware(datetime.combine(start_date, time(hour=12)))
    next_day = end_date + timedelta(days=1)
    end_dt   = timezone.make_aware(datetime.combine(next_day, time(hour=12)))

    qs = (
        OrderItem.objects
        .filter(order__created_at__gte=start_dt,
                order__created_at__lt=end_dt)
        .values('menu_item__name')
        .annotate(
            total_qty=Sum('quantity'),
            last_sold=Max('order__created_at')
        )
        .order_by('menu_item__name')
    )

    data = []
    for entry in qs:
        # convert to localtime and format
        last_sold_dt = timezone.localtime(entry['last_sold'])
        formatted = last_sold_dt.strftime("%Y-%m-%d")
        print(f"Date formate: {formatted}")
        data.append({
            'name':      entry['menu_item__name'],
            'total_qty': entry['total_qty'],
            'last_sold': formatted
        })

    return JsonResponse(data, safe=False)


# table
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView
from .models import Table
from .forms import TableForm

@method_decorator(require_permission('sales'), name='dispatch')
class TableListView(ListView):
    model = Table
    template_name = 'tables/table_list.html'
    context_object_name = 'tables'
    paginate_by = 20

class TableCreateView(CreateView):
    model = Table
    form_class = TableForm
    template_name = 'tables/table_form.html'
    success_url = reverse_lazy('table_list')

class TableUpdateView(UpdateView):
    model = Table
    form_class = TableForm
    template_name = 'tables/table_form.html'
    success_url = reverse_lazy('table_list')



def build_token_bytes_for_deltas(order, items_with_delta):
    esc = b"\x1B"
    gs  = b"\x1D"
    lines = []
    
    # ─── Restaurant name, larger/bold ────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x01")   # center alignment
    lines.append(b"NEW MARHABA\n")
    lines.append(esc + b"\x21" + b"\x00")   # back to normal
    lines.append(b"\n")

    # ─── Header “KITCHEN TOKEN” ───────────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x01")   # center
    lines.append(b"KITCHEN TOKEN\n\n")

    # ─── Token number, bold, slightly bigger ─────────────────────────────
    token_str = str(order.token_number).encode("ascii")
    table_number = str(order.table.number).encode("ascii")
    lines.append(esc + b"\x61" + b"\x01")   # center
    lines.append(esc + b"\x21" + b"\x30")   # ESC ! 0x10 → double width, normal height
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    lines.append(b"Table #: "+ table_number + b"\n\n")
    lines.append(esc + b"\x21" + b"\x00")   # back to normal

    # ─── Date / Time ──────────────────────────────────────────────────────
    # now_str = order.created_at.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    now_local = timezone.localtime(timezone.now())
    now_str = now_local.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    lines.append(esc + b"\x61" + b"\x00")  # left align
    lines.append(b"Date: " + now_str + b"\n")
    if order.waiter:
        waiter_bytes = f"Waiter: {order.waiter.name}\n".encode("ascii", "ignore")
        lines.append(waiter_bytes)
    lines.append(b"-" * 32 + b"\n")         # 32-char full width separator

    # ─── Only the new items ─────────────────────────────────────────────
    for oi, delta in items_with_delta:
        # truncate name to 20 chars
        name = (oi.menu_item.name if oi.menu_item else oi.deal.name)[:20]
        name_field = name.ljust(20).encode("ascii", "ignore")
        qty_bytes  = str(delta).rjust(3).encode("ascii")
        lines.append(name_field + b"  x" + qty_bytes + b"\n")

    lines.append(b"\n\n\n\n\n")
    # ─── feed + cut ─────────────────────────────────────────────────────
    lines.append(b"\n" * 4)
    lines.append(gs + b"\x56" + b"\x00")    # full cut

    return b"".join(lines)

import json
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Table, Order

from django.db.models import Q

class TableSwitchView(LoginRequiredMixin, View):

    def get(self, request):
        raw = request.GET.get('table_id')

        # ---- Walk-in (no table) ----
        if raw is None or raw == "" or raw.lower() == "null":
            return JsonResponse({
                "order_id": None,
                "table_id": None,
                "items": [],
                "discount": 0,
                "tax_percentage": 0,
                "service_charge": 0,
            })

        # ---- Otherwise try to parse a valid integer ----
        try:
            table_id = int(raw)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid table_id"}, status=400)

        # ---- Lookup table and its pending order ----
        table = get_object_or_404(Table, pk=table_id)
        
        # Try to get the first order with 'pending' status for this table, or create one if none exists
        order = Order.objects.filter(table=table, status="pending").first()

        if not order:
            order = Order.objects.create(
                table=table,
                status="pending",
                created_by=request.user
            )

        # Mark it occupied in the DB
        table.is_occupied = True
        table.save()

        # ─── NEW: fetch only items not yet printed ──────────────────────
        items_to_print = []
        for oi in order.items.all():
            delta = oi.quantity - oi.printed_quantity
            if delta > 0:
                items_to_print.append((oi, delta))

        if items_to_print:
            payload = build_token_bytes_for_deltas(order, items_to_print)
            send_to_printer(payload)
            # mark them as “now fully printed”
            for oi, _ in items_to_print:
                oi.printed_quantity = oi.quantity
                oi.save(update_fields=['printed_quantity'])
        
        # Build items array
        items_data = []
        for oi in order.items.all():
            items_data.append({
                "type":         "menu" if oi.menu_item_id else "deal",
                "menu_item_id": oi.menu_item_id,
                "deal_id":      oi.deal_id,
                "name":         oi.menu_item.name if oi.menu_item_id else oi.deal.name,
                "quantity":     oi.quantity,
                "unit_price":   float(oi.unit_price),
            })

        # Return JSON for the UI to load
        return JsonResponse({
            "order_id":       order.id,
            "table_id":       table.id,
            "items":          items_data,
            "discount":       float(order.discount),
            "tax_percentage": float(order.tax_percentage),
            "service_charge": float(order.service_charge),
        })


from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.http import JsonResponse
from .models import Supplier
from .views import AjaxableResponseMixin  # reuse your existing mixin
from django.contrib.auth.mixins import LoginRequiredMixin

# --- Suppliers CRUD ---
@method_decorator(require_permission('inventory'), name='dispatch')
class SupplierListView(LoginRequiredMixin, ListView):
    model = Supplier
    template_name = 'suppliers/supplier_list.html'
    context_object_name = 'suppliers'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().order_by('-created_at')
        q = self.request.GET.get('q')
        return qs.filter(name__icontains=q) if q else qs

@method_decorator(require_permission('inventory'), name='dispatch')
class SupplierCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = Supplier
    fields = ['name','contact_number','email','address']
    template_name = 'suppliers/supplier_form.html'
    success_url = reverse_lazy('supplier_list')

@method_decorator(require_permission('inventory'), name='dispatch')
class SupplierDetailView(LoginRequiredMixin, DetailView):
    model = Supplier
    template_name = 'suppliers/supplier_detail.html'
    context_object_name = 'supplier'

@method_decorator(require_permission('inventory'), name='dispatch')
class SupplierUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = Supplier
    fields = ['name','contact_number','email','address']
    template_name = 'suppliers/supplier_form.html'
    success_url = reverse_lazy('supplier_list')

@method_decorator(require_permission('inventory'), name='dispatch')
class SupplierDeleteView(LoginRequiredMixin, DeleteView):
    model = Supplier
    success_url = reverse_lazy('supplier_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)


from django.urls import reverse_lazy
from django.http import JsonResponse
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import RawMaterial
from .views import AjaxableResponseMixin  # your existing mixin

from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Q


class UnitListView(LoginRequiredMixin, TemplateView):
    """Read-only Unit master (seeded standard restaurant units)."""
    template_name = 'inventory/unit_list.html'

    def get_context_data(self, **kwargs):
        from .models import Unit
        ctx = super().get_context_data(**kwargs)
        units = list(Unit.objects.all().order_by('unit_type', 'name'))
        for u in units:
            try:
                u.base_factor = Unit.to_base_factor(u.symbol)
            except Exception:
                u.base_factor = 1
        ctx['units'] = units
        return ctx


# --- Raw Materials CRUD ---
class LowStockView(LoginRequiredMixin, TemplateView):
    """
    Everything that needs reordering, with a suggested order quantity and the
    estimated cost, so a purchase order can be raised quickly.
    """
    template_name = 'inventory/low_stock.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        tracked = (
            RawMaterial.objects
            .filter(reorder_level__gt=0)
            .select_related('supplier')
            .order_by('supplier__name', 'name')
        )

        low, out = [], []
        for m in tracked:
            if m.is_out_of_stock:
                out.append(m)
            elif m.is_low_stock:
                low.append(m)

        # Items with no reorder level set yet - opt-in candidates.
        untracked = (
            RawMaterial.objects
            .filter(reorder_level__lte=0)
            .select_related('supplier')
            .order_by('name')
        )

        def total_cost(rows):
            return sum((m.estimated_cost for m in rows), Decimal('0'))

        ctx.update({
            'low_items': low,
            'out_items': out,
            'untracked_items': untracked,
            'low_count': len(low),
            'out_count': len(out),
            'total_estimated_cost': total_cost(low + out),
            'suppliers': sorted({m.supplier for m in (low + out) if m.supplier_id},
                                key=lambda s: s.name.lower()),
        })
        return ctx


@method_decorator(require_permission('inventory'), name='dispatch')
class RawMaterialListView(LoginRequiredMixin, ListView):
    model = RawMaterial
    template_name = 'raw_materials/rawmaterial_list.html'
    context_object_name = 'materials'
    paginate_by = 300

    def get_queryset(self):
        qs = super().get_queryset().select_related('supplier').order_by('-created_at')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        # annotate average unit price from received PurchaseOrderItems
        qs = qs.annotate(
            total_cost=Sum(
                F('purchaseorderitem__quantity') * F('purchaseorderitem__unit_price'),
                filter=Q(purchaseorderitem__purchase_order__status='received'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            ),
            total_qty=Sum(
                'purchaseorderitem__quantity',
                filter=Q(purchaseorderitem__purchase_order__status='received')
            )
        ).annotate(
            avg_unit_price=ExpressionWrapper(
                F('total_cost') / F('total_qty'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
        return qs

@method_decorator(require_permission('inventory'), name='dispatch')
class RawMaterialCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = RawMaterial
    fields = ['name', 'stock_unit', 'purchase_unit', 'pack_size', 'supplier', 'current_stock', 'reorder_level']
    template_name = 'raw_materials/rawmaterial_form.html'
    success_url = reverse_lazy('raw_material_list')

@method_decorator(require_permission('inventory'), name='dispatch')
class RawMaterialDetailView(LoginRequiredMixin, DetailView):
    model = RawMaterial
    template_name = 'raw_materials/rawmaterial_detail.html'
    context_object_name = 'material'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        m = self.object
        ctx['avg_cost'] = m.avg_cost_per_stock_unit
        ctx['latest_cost'] = m.latest_cost_per_stock_unit
        # Recipes this material is used in (RecipeRawMaterial has no related_name,
        # so query the model explicitly and select_related to avoid N+1 queries).
        ctx['used_in'] = (
            RecipeRawMaterial.objects
            .filter(raw_material=m)
            .select_related('recipe__menu_item', 'unit')
            .order_by('recipe__menu_item__name')[:50]
        )
        return ctx

@method_decorator(require_permission('inventory'), name='dispatch')
class RawMaterialUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = RawMaterial
    fields = ['name', 'stock_unit', 'purchase_unit', 'pack_size', 'supplier', 'current_stock', 'reorder_level']
    template_name = 'raw_materials/rawmaterial_form.html'
    success_url = reverse_lazy('raw_material_list')

@method_decorator(require_permission('inventory'), name='dispatch')
class RawMaterialDeleteView(LoginRequiredMixin, DeleteView):
    model = RawMaterial
    success_url = reverse_lazy('raw_material_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.is_ajax():
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)


# ---------- Taxes CRUD ----------
# Cashiers pick these on the order screen, so they are managed in the app
# instead of only through Django admin.
from .forms import TaxRateForm, ModifierGroupForm, ModifierOptionFormSet
from django.http import HttpResponseRedirect


@method_decorator(require_permission('menu'), name='dispatch')
class TaxRateListView(LoginRequiredMixin, ListView):
    model = TaxRate
    template_name = 'taxes/taxrate_list.html'
    context_object_name = 'taxes'
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().order_by('sort_order', 'name')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


class _SingleDefaultTaxMixin:
    """Only one tax may be the pre-ticked default on a new order."""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.object.is_default:
            TaxRate.objects.exclude(pk=self.object.pk).update(is_default=False)
        return response


@method_decorator(require_permission('menu'), name='dispatch')
class TaxRateCreateView(LoginRequiredMixin, _SingleDefaultTaxMixin, CreateView):
    model = TaxRate
    form_class = TaxRateForm
    template_name = 'taxes/taxrate_form.html'
    success_url = reverse_lazy('taxrate_list')


@method_decorator(require_permission('menu'), name='dispatch')
class TaxRateUpdateView(LoginRequiredMixin, _SingleDefaultTaxMixin, UpdateView):
    model = TaxRate
    form_class = TaxRateForm
    template_name = 'taxes/taxrate_form.html'
    success_url = reverse_lazy('taxrate_list')


@method_decorator(require_permission('menu'), name='dispatch')
class TaxRateDeleteView(LoginRequiredMixin, AjaxableResponseMixin, DeleteView):
    model = TaxRate
    success_url = reverse_lazy('taxrate_list')


# ---------- Modifier groups CRUD ----------
@method_decorator(require_permission('menu'), name='dispatch')
class ModifierGroupListView(LoginRequiredMixin, ListView):
    model = ModifierGroup
    template_name = 'modifiers/modifiergroup_list.html'
    context_object_name = 'groups'
    paginate_by = 25

    def get_queryset(self):
        qs = (
            super().get_queryset()
            .prefetch_related('options', 'menu_items')
            .order_by('sort_order', 'name')
        )
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(name__icontains=q)
        return qs


class _InvalidOptions(Exception):
    """Internal signal: the inline options failed validation."""

    def __init__(self, formset):
        super().__init__('Invalid modifier options')
        self.formset = formset


class _ModifierGroupFormMixin:
    """Shared parent-form + inline-options handling for create and update."""

    def _build_option_formset(self):
        return ModifierOptionFormSet(
            self.request.POST, prefix='options', instance=self.object
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.method == 'POST':
            ctx['option_formset'] = self._build_option_formset()
        else:
            ctx['option_formset'] = ModifierOptionFormSet(
                instance=self.object, prefix='options'
            )
        return ctx

    def form_valid(self, form):
        try:
            # The group and its options must land together or not at all,
            # otherwise a bad option list would leave a half-made group behind.
            with transaction.atomic():
                self.object = form.save()
                formset = self._build_option_formset()
                if not formset.is_valid():
                    raise _InvalidOptions(formset)
                formset.save()
        except _InvalidOptions as invalid:
            self.object = None
            return self.form_invalid(form, invalid.formset)

        return HttpResponseRedirect(self.get_success_url())

    def form_invalid(self, form, formset=None):
        ctx = self.get_context_data(form=form)
        if formset is not None:
            ctx['option_formset'] = formset
        return self.render_to_response(ctx, status=400)


@method_decorator(require_permission('menu'), name='dispatch')
class ModifierGroupCreateView(LoginRequiredMixin, _ModifierGroupFormMixin, CreateView):
    model = ModifierGroup
    form_class = ModifierGroupForm
    template_name = 'modifiers/modifiergroup_form.html'
    success_url = reverse_lazy('modifiergroup_list')


@method_decorator(require_permission('menu'), name='dispatch')
class ModifierGroupUpdateView(LoginRequiredMixin, _ModifierGroupFormMixin, UpdateView):
    model = ModifierGroup
    form_class = ModifierGroupForm
    template_name = 'modifiers/modifiergroup_form.html'
    success_url = reverse_lazy('modifiergroup_list')


@method_decorator(require_permission('menu'), name='dispatch')
class ModifierGroupDeleteView(LoginRequiredMixin, AjaxableResponseMixin, DeleteView):
    model = ModifierGroup
    success_url = reverse_lazy('modifiergroup_list')


# Purchase Orders
# core/views (or wherever your PO views live)
import json
from decimal import Decimal
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from .models import RawMaterial, PurchaseOrder, PurchaseOrderItem, InventoryTransaction, Expense, BankAccount, Supplier
from .views import AjaxableResponseMixin

# ----- helper: compute supplier due (across all POs) -----
def supplier_due(supplier_id, exclude_po_id=None):
    po_qs = PurchaseOrder.objects.filter(supplier_id=supplier_id)
    if exclude_po_id:
        po_qs = po_qs.exclude(pk=exclude_po_id)
    gross = po_qs.aggregate(s=Sum('net_total'))['s'] or Decimal('0')

    exp_qs = Expense.objects.filter(category='purchase', supplier_id=supplier_id)
    if exclude_po_id:
        exp_qs = exp_qs.exclude(purchase_order_id=exclude_po_id)
    paid = exp_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')

    return (gross - paid).quantize(Decimal('0.01'))

@require_GET
def supplier_balance_json(request):
    try:
        supplier_id = int(request.GET.get('supplier_id', '0'))
    except ValueError:
        return HttpResponseBadRequest("Invalid supplier_id")
    prev_due = supplier_due(supplier_id)
    return JsonResponse({'previous_due': float(prev_due)})

# ----- List -----
@method_decorator(require_permission('inventory'), name='dispatch')
class PurchaseOrderListView(LoginRequiredMixin, ListView):
    model = PurchaseOrder
    template_name = 'purchase_orders/purchaseorder_list.html'
    context_object_name = 'orders'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related('supplier','created_by').order_by('-created_at')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(supplier__name__icontains=q)
        return qs

# ----- Create -----
@method_decorator(require_permission('inventory'), name='dispatch')
class PurchaseOrderCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = PurchaseOrder
    fields = ['supplier']  # keep simple; we set tax/discount etc. from POST
    template_name = 'purchase_orders/purchaseorder_form.html'
    success_url = reverse_lazy('purchase_order_list')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        rms = RawMaterial.objects.select_related('supplier', 'stock_unit', 'purchase_unit').order_by('name')
        ctx['raw_materials_json'] = json.dumps([{
            'pk': rm.pk, 'name': rm.name, 'unit': rm.stock_symbol,
            'stock_unit': rm.stock_symbol, 'stock_unit_id': rm.stock_unit_id,
            'purchase_unit': getattr(rm.purchase_unit, 'symbol', None) or rm.stock_symbol,
            'purchase_unit_id': rm.purchase_unit_id or rm.stock_unit_id,
            'pack_size': float(rm.pack_size or 1),
            'avg_cost': float(rm.avg_cost_per_stock_unit or 0),
        } for rm in rms])
        ctx['initial_po_items_json'] = json.dumps([])
        ctx['bank_accounts'] = BankAccount.objects.all()
        return ctx

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        # Optional %s
        tax_percent = Decimal(self.request.POST.get('tax_percent') or '0')
        disc_percent = Decimal(self.request.POST.get('discount_percent') or '0')

        resp = super().form_valid(form)

        # Line items
        data = json.loads(self.request.POST.get('po_items_json', '[]'))
        subtotal = Decimal('0')
        for it in data:
            qty = Decimal(str(it['quantity']))
            up  = Decimal(str(it['unit_price']))
            PurchaseOrderItem.objects.create(
                purchase_order=self.object,
                raw_material_id=int(it['raw_material_id']),
                quantity=qty,
                unit_price=up,
                purchase_unit_id=it.get('purchase_unit_id') or None
            )
            subtotal += (qty * up)

        # totals
        self.object.tax_percent = tax_percent
        self.object.discount_percent = disc_percent
        self.object.recompute_totals()   # sets total_cost (subtotal) and net_total
        # overwrite subtotal with computed one to be safe
        self.object.total_cost = subtotal
        self.object.save(update_fields=['total_cost', 'tax_percent', 'discount_percent', 'net_total'])

        # Payment (optional)
        paid_amount = Decimal(self.request.POST.get('paid_amount') or '0')
        pay_source  = self.request.POST.get('payment_source') or 'cash'
        bank_id     = self.request.POST.get('bank_account') or None
        if paid_amount > 0:
            Expense.objects.create(
                date=self.object.created_at.date(),
                category='purchase',
                amount=paid_amount,
                description=f"Payment for PO #{self.object.id}",
                supplier=self.object.supplier,
                staff=None,
                payment_source=pay_source,
                bank_account=BankAccount.objects.get(pk=bank_id) if (pay_source=='bank' and bank_id) else None,
                created_by=self.request.user,
                purchase_order=self.object,
            )
        return resp

# views.py (or wherever your class lives)

import json
from decimal import Decimal
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from .views import AjaxableResponseMixin  # keep your existing mixin
from .models import RawMaterial, PurchaseOrder, PurchaseOrderItem, Expense


@method_decorator(require_permission('inventory'), name='dispatch')
class PurchaseOrderUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = PurchaseOrder
    # keep your original editable fields list (don’t add/remove form fields here)
    fields = ['supplier']
    template_name = 'purchase_orders/purchaseorder_form.html'
    success_url = reverse_lazy('purchase_order_list')

    # ---------- helpers ----------
    def _previous_due_with_fallback(self, supplier_id: int, exclude_po_id: int | None) -> Decimal:
        """
        Sum all earlier POs for this supplier (excluding the one we're editing).
        Use net_total if present; otherwise fall back to total_cost (old records).
        Then subtract any 'purchase' expenses linked to those POs.
        """
        qs = PurchaseOrder.objects.filter(supplier_id=supplier_id)
        if exclude_po_id:
            qs = qs.exclude(pk=exclude_po_id)

        total_charges = Decimal('0')
        for row in qs.values('id', 'net_total', 'total_cost'):
            nt = row.get('net_total') or Decimal('0')
            tc = row.get('total_cost') or Decimal('0')
            total_charges += (nt if nt > 0 else tc)

        po_ids = list(qs.values_list('id', flat=True))
        paid_sum = Expense.objects.filter(
            category='purchase',
            purchase_order_id__in=po_ids
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

        return total_charges - paid_sum

    # ---------- context ----------
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # Materials for the line-items table
        rms = RawMaterial.objects.select_related('supplier', 'stock_unit', 'purchase_unit').order_by('name')
        ctx['raw_materials_json'] = json.dumps([{
            'pk': rm.pk, 'name': rm.name, 'unit': rm.stock_symbol,
            'stock_unit': rm.stock_symbol, 'stock_unit_id': rm.stock_unit_id,
            'purchase_unit': getattr(rm.purchase_unit, 'symbol', None) or rm.stock_symbol,
            'purchase_unit_id': rm.purchase_unit_id or rm.stock_unit_id,
            'pack_size': float(rm.pack_size or 1),
            'avg_cost': float(rm.avg_cost_per_stock_unit or 0),
        } for rm in rms])

        # Existing lines for this PO
        existing_items = [
            {
                'raw_material_id': pi.raw_material_id,
                'quantity': float(pi.quantity),
                'unit_price': float(pi.unit_price),
                'purchase_unit_id': pi.purchase_unit_id,
            }
            for pi in self.object.items.all()
        ]
        ctx['initial_po_items_json'] = json.dumps(existing_items)

        # ---- FIX 1: previous_due must EXCLUDE this PO to avoid double counting on edit
        previous_due = self._previous_due_with_fallback(
            supplier_id=self.object.supplier_id,
            exclude_po_id=self.object.pk
        )
        ctx['previous_due'] = previous_due

        # Some templates/scripts like to have server values as JSON
        # (We DO NOT add previous_due into net_total here — net_total is always just tax/discount math)
        server_net_total = self.object.net_total or self.object.total_cost or Decimal('0')
        ctx['po_meta_json'] = json.dumps({
            'subtotal': float(self.object.total_cost or 0),
            'tax_percent': float(getattr(self.object, 'tax_percent', 0) or 0),
            'discount_percent': float(getattr(self.object, 'discount_percent', 0) or 0),
            'server_net_total': float(server_net_total),
            'previous_due': float(previous_due),
        })

        return ctx

    # ---------- save ----------
    def form_valid(self, form):
        """
        Keep your existing logic:
          - Replace line items from posted JSON
          - Recalculate subtotal (total_cost) on the server
        We do NOT mix in previous_due here (net_total remains pure item/tax/discount math).
        """
        # Wipe old lines and rebuild them from the posted JSON. Delete them one at
        # a time: QuerySet.delete() does a bulk delete that bypasses
        # PurchaseOrderItem.delete(), and that override is what writes the 'return'
        # reversal putting the stock back. Bulk-deleting here silently lost the
        # returned stock and then re-added the new quantities, inflating levels.
        for old_item in list(self.object.items.all()):
            old_item.delete()

        response = super().form_valid(form)

        data = json.loads(self.request.POST.get('po_items_json', '[]'))
        total = Decimal('0')
        for it in data:
            qty = Decimal(str(it['quantity']))
            up = Decimal(str(it['unit_price']))
            PurchaseOrderItem.objects.create(
                purchase_order=self.object,
                raw_material_id=it['raw_material_id'],
                quantity=qty,
                unit_price=up,
                purchase_unit_id=it.get('purchase_unit_id') or None
            )
            total += qty * up

        # Subtotal only (server will keep any tax/discount/net_total logic you already have elsewhere)
        self.object.total_cost = total

        # If you’re already computing net_total (tax/discount) elsewhere, keep that as-is.
        # We intentionally do NOT add previous_due into net_total.
        # Example (only if your model has these fields and the client posts them):
        tax_percent = Decimal(str(self.request.POST.get('tax_percent', '0') or '0'))
        discount_percent = Decimal(str(self.request.POST.get('discount_percent', '0') or '0'))

        # Safe compute if those fields exist on your model; otherwise this is a no-op
        if hasattr(self.object, 'tax_percent'):
            self.object.tax_percent = tax_percent
        if hasattr(self.object, 'discount_percent'):
            self.object.discount_percent = discount_percent
        if hasattr(self.object, 'net_total'):
            tax_amt = (total * tax_percent) / Decimal('100')
            disc_amt = (total * discount_percent) / Decimal('100')
            self.object.net_total = (total + tax_amt - disc_amt)

        self.object.save()
        return response

from decimal import Decimal
from django.db.models import Sum

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView
from .models import PurchaseOrder, InventoryTransaction, Expense


@method_decorator(require_permission('inventory'), name='dispatch')
class PurchaseOrderDetailView(LoginRequiredMixin, DetailView):
    model = PurchaseOrder
    template_name = 'purchase_orders/purchaseorder_detail.html'
    context_object_name = 'order'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object

        # Stock-in transactions for this PO
        ctx['transactions'] = (
            InventoryTransaction.objects
            .filter(purchase_order_item__purchase_order=order)
            .order_by('-timestamp')
        )

        # Payments recorded against this PO (category: purchase)
        ctx['payments'] = (
            Expense.objects
            .filter(purchase_order=order, category='purchase')
            .order_by('-created_at')
        )

        # Sum paid for this PO
        paid_sum = ctx['payments'].aggregate(s=Sum('amount'))['s'] or Decimal('0')
        ctx['paid_sum'] = paid_sum

        # Supplier balance before this PO (exclude this PO from the calc)
        ctx['previous_due'] = supplier_due(order.supplier_id, exclude_po_id=order.pk)

        # Use net_total if you have it; otherwise fall back to total_cost
        net_total = getattr(order, 'net_total', None)
        if net_total is None:
            net_total = order.total_cost

        # Remaining after current PO and its payments
        ctx['remaining_after'] = (ctx['previous_due'] + net_total - paid_sum)

        return ctx


@method_decorator(require_permission('inventory'), name='dispatch')
class PurchaseOrderDeleteView(LoginRequiredMixin, DeleteView):
    model = PurchaseOrder
    success_url = reverse_lazy('purchase_order_list')

@require_POST
def purchase_order_receive(request, pk):
    po = get_object_or_404(PurchaseOrder, pk=pk)
    po.mark_received()
    return JsonResponse({'status':'success'})



from decimal import Decimal
from datetime import date

from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, F, DecimalField

from .models import (
    RawMaterial,
    RawMaterialUnitConversion,
    MenuItem,
    Deal,
    OrderItem,
)

class CostReportView(LoginRequiredMixin, TemplateView):
    template_name = 'reports/cost_report.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = date.today()

        # Standard costing: per-portion estimate incl. yield/wastage.
        from .costing import recipe_cost, menu_economics
        item_rows = []
        for mi in MenuItem.objects.prefetch_related(
                 'recipe__raw_ingredients', 'recipe__subrecipes__sub_recipe'):
            try:
                econ = menu_economics(mi)
                cost = econ['estimated_cost'] if econ['has_recipe'] else Decimal('0')
            except Exception:
                econ, cost = {'has_recipe': False}, Decimal('0')
            sold = OrderItem.objects.filter(menu_item=mi,
                                            order__created_at__date=today)\
                                     .aggregate(q=Sum('quantity'))['q'] or 0
            item_rows.append({
                'name': mi.name,
                'price': mi.price,
                'avg_cost_price': cost,
                'food_cost_percent': (econ.get('food_cost_percent') if isinstance(econ, dict) else None),
                'margin_amount': (econ.get('margin_amount') if isinstance(econ, dict) else None),
                'has_recipe': bool(isinstance(econ, dict) and econ.get('has_recipe')),
                'sold_qty_today': sold,
                'total_cost_today': cost * sold,
            })

        deal_rows = []
        for dl in Deal.objects.prefetch_related('deal_items__menu_item'):
            dcost = sum((next((r['avg_cost_price'] for r in item_rows if r['name']==di.menu_item.name), Decimal('0')) * di.quantity)
                        for di in dl.deal_items.all())
            sold = OrderItem.objects.filter(deal=dl,
                                            order__created_at__date=today)\
                                     .aggregate(q=Sum('quantity'))['q'] or 0
            deal_rows.append({
                'name': dl.name,
                'avg_cost_price': dcost,
                'sold_qty_today': sold,
                'total_cost_today': dcost * sold,
            })

        ctx.update({
            'today': today,
            'item_rows': item_rows,
            'deal_rows': deal_rows,
        })
        return ctx


# --- List & Detail ---
@method_decorator(require_permission('inventory'), name='dispatch')
class RecipeListView(LoginRequiredMixin, ListView):
    model = Recipe
    template_name = 'recipes/recipe_list.html'
    context_object_name = 'recipes'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related('menu_item')
        q = self.request.GET.get('q')
        return qs.filter(menu_item__name__icontains=q) if q else qs

@method_decorator(require_permission('inventory'), name='dispatch')
class RecipeDetailView(LoginRequiredMixin, DetailView):
    model = Recipe
    template_name = 'recipes/recipe_detail.html'
    context_object_name = 'recipe'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .costing import recipe_breakdown, menu_economics
        try:
            ctx['breakdown'] = recipe_breakdown(self.object)
        except Exception as e:
            ctx['breakdown'] = {'lines': [], 'sub_recipe_lines': [], 'gross_cost': 0,
                                'cost_per_portion': 0, 'error': str(e)}
        try:
            ctx['economics'] = menu_economics(self.object.menu_item)
        except Exception:
            ctx['economics'] = {}
        return ctx


# --- Create & Update ---
@method_decorator(require_permission('inventory'), name='dispatch')
class RecipeCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = Recipe
    fields = ['menu_item', 'name', 'yield_qty', 'wastage_percent', 'instructions']
    template_name = 'recipes/recipe_form.html'
    success_url = reverse_lazy('recipe_list')

    def get_context_data(self, **ctx):
        data = super().get_context_data(**ctx)
        # raw materials
        rms = RawMaterial.objects.select_related('stock_unit', 'purchase_unit').order_by('name')
        data['raw_materials_json'] = json.dumps([
            {'pk': rm.pk, 'name': rm.name, 'unit': rm.stock_symbol,
             'stock_unit_id': rm.stock_unit_id,
             'stock_unit': rm.stock_symbol,
             'stock_type': getattr(rm.stock_unit, 'unit_type', ''),
             'avg_cost': float(rm.avg_cost_per_stock_unit or 0)}
            for rm in rms
        ])
        # units
        from .models import Unit
        units = Unit.objects.all().order_by('unit_type', 'name')
        data['units_json'] = json.dumps([
            {'pk': u.pk, 'symbol': u.symbol, 'name': u.name, 'type': u.unit_type} for u in units
        ])
        # existing recipes for nesting
        recs = Recipe.objects.all()
        data['recipes_json'] = json.dumps([
            {'pk': r.pk, 'name': r.menu_item.name} for r in recs
        ])
        data['initial_raw'] = []
        data['initial_sub'] = []
        return data

    def form_valid(self, form):
        resp = super().form_valid(form)
        recipe = self.object
        # clear old if any (should be none)
        RecipeRawMaterial.objects.filter(recipe=recipe).delete()
        RecipeSubRecipe.objects.filter(recipe=recipe).delete()

        raw_data = json.loads(self.request.POST.get('raw_json','[]'))
        for it in raw_data:
            RecipeRawMaterial.objects.create(
                recipe=recipe,
                raw_material_id=it['raw_material_id'],
                quantity=Decimal(str(it['quantity'])),
                unit_id=it['unit_id']
            )

        sub_data = json.loads(self.request.POST.get('sub_json','[]'))
        for it in sub_data:
            RecipeSubRecipe.objects.create(
                recipe=recipe,
                sub_recipe_id=it['sub_recipe_id'],
                quantity=Decimal(str(it['quantity'])),
                unit_id=it.get('unit_id') or None
            )

        # update menu_item.cost_price (per-portion estimate incl. yield/wastage)
        from .costing import refresh_cost
        try:
            refresh_cost(recipe.menu_item)
        except Exception:
            pass

        return resp

@method_decorator(require_permission('inventory'), name='dispatch')
class RecipeUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = Recipe
    fields = ['menu_item', 'name', 'yield_qty', 'wastage_percent', 'instructions']
    template_name = 'recipes/recipe_form.html'
    success_url = reverse_lazy('recipe_list')

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        # 1) All raw materials
        rms = RawMaterial.objects.select_related('stock_unit', 'purchase_unit').order_by('name')
        data['raw_materials_json'] = json.dumps([
            {'pk': rm.pk, 'name': rm.name, 'unit': rm.stock_symbol,
             'stock_unit_id': rm.stock_unit_id,
             'stock_unit': rm.stock_symbol,
             'stock_type': getattr(rm.stock_unit, 'unit_type', ''),
             'avg_cost': float(rm.avg_cost_per_stock_unit or 0)}
            for rm in rms
        ])

        # 2) All units
        units = Unit.objects.all().order_by('unit_type', 'name')
        data['units_json'] = json.dumps([
            {'pk': u.pk, 'symbol': u.symbol, 'name': u.name, 'type': u.unit_type}
            for u in units
        ])

        # 3) All other recipes (for nesting), excluding this one
        recs = Recipe.objects.exclude(pk=self.object.pk)
        data['recipes_json'] = json.dumps([
            {'pk': r.pk, 'name': r.menu_item.name}
            for r in recs
        ])

        # 4) Existing raw‑ingredient lines, as JSON
        initial_raw = [
            {
                'raw_material_id': ri.raw_material_id,
                'quantity': float(ri.quantity),
                'unit_id': ri.unit_id
            }
            for ri in self.object.raw_ingredients.all()
        ]
        data['initial_raw_json'] = json.dumps(initial_raw)

        # 5) Existing sub‑recipe lines, as JSON
        initial_sub = [
            {
                'sub_recipe_id': sr.sub_recipe_id,
                'quantity': float(sr.quantity),
                'unit_id': sr.unit_id
            }
            for sr in self.object.subrecipes.all()
        ]
        data['initial_sub_json'] = json.dumps(initial_sub)

        return data

    def form_valid(self, form):
        # 1) Save the Recipe core fields
        response = super().form_valid(form)
        recipe = self.object

        # 2) Wipe & recreate all raw‑material links
        RecipeRawMaterial.objects.filter(recipe=recipe).delete()
        raw_data = json.loads(self.request.POST.get('raw_json', '[]'))
        for it in raw_data:
            RecipeRawMaterial.objects.create(
                recipe=recipe,
                raw_material_id=it['raw_material_id'],
                quantity=Decimal(str(it['quantity'])),
                unit_id=it['unit_id']
            )

        # 3) Wipe & recreate all sub‑recipe links
        RecipeSubRecipe.objects.filter(recipe=recipe).delete()
        sub_data = json.loads(self.request.POST.get('sub_json', '[]'))
        for it in sub_data:
            RecipeSubRecipe.objects.create(
                recipe=recipe,
                sub_recipe_id=it['sub_recipe_id'],
                quantity=Decimal(str(it['quantity'])),
                unit_id=it.get('unit_id') or None
            )

        # 4) Recompute & store the MenuItem's cost_price
        from .costing import refresh_cost
        try:
            refresh_cost(recipe.menu_item)
        except Exception:
            pass

        return response

@method_decorator(require_permission('inventory'), name='dispatch')
class RecipeDeleteView(LoginRequiredMixin, AjaxableResponseMixin, DeleteView):
    model = Recipe
    success_url = reverse_lazy('recipe_list')


import json
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.views.generic import ListView, CreateView, DetailView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin

from .models import Waiter
from .views import AjaxableResponseMixin  # your existing mixin

# — Waiters CRUD —

@method_decorator(require_permission('staff'), name='dispatch')
class WaiterListView(LoginRequiredMixin, ListView):
    model = Waiter
    template_name = 'waiters/waiter_list.html'
    context_object_name = 'waiters'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().order_by('-created_at')
        q = self.request.GET.get('q')
        return qs.filter(name__icontains=q) if q else qs


@method_decorator(require_permission('staff'), name='dispatch')
class WaiterCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = Waiter
    fields = ['name', 'employee_id', 'phone']
    template_name = 'waiters/waiter_form.html'
    success_url = reverse_lazy('waiter_list')


@method_decorator(require_permission('staff'), name='dispatch')
class WaiterDetailView(LoginRequiredMixin, DetailView):
    model = Waiter
    template_name = 'waiters/waiter_detail.html'
    context_object_name = 'waiter'


@method_decorator(require_permission('staff'), name='dispatch')
class WaiterUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = Waiter
    fields = ['name', 'employee_id', 'phone']
    template_name = 'waiters/waiter_form.html'
    success_url = reverse_lazy('waiter_list')


@method_decorator(require_permission('staff'), name='dispatch')
class WaiterDeleteView(LoginRequiredMixin, DeleteView):
    model = Waiter
    success_url = reverse_lazy('waiter_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.is_ajax():
            return JsonResponse({'message':'Deleted'})
        return super().delete(request, *args, **kwargs)


# core/views.py
from django.shortcuts import render
from decimal import Decimal, getcontext

from .models import MenuItem, RawMaterialUnitConversion, PurchaseOrderItem

# bump precision a bit
getcontext().prec = 28

def debug_costs(request):
    # 1) Build conversion map: (raw_material_id, unit_symbol) -> to_base_factor
    convs = {
        (c.raw_material_id, c.unit.symbol): Decimal(c.to_base_factor)
        for c in RawMaterialUnitConversion.objects.select_related('unit').all()
    }

    # 2) Helper: average cost per **base** unit (g, ml, pcs) for a raw material
    _cache = {}
    def cost_per_base(rm_id):
        if rm_id in _cache:
            return _cache[rm_id]
        pois = PurchaseOrderItem.objects.filter(raw_material_id=rm_id)
        total_cost = Decimal('0')
        total_base = Decimal('0')
        for poi in pois:
            q      = Decimal(poi.quantity)
            p      = Decimal(poi.unit_price)
            symbol = poi.raw_material.unit             # e.g. 'kg' or 'pcs'
            factor = convs.get((rm_id, symbol), Decimal('1'))
            total_base += q * factor
            total_cost += q * p
        avg = (total_cost / total_base) if total_base else Decimal('0')
        _cache[rm_id] = avg
        return avg

    # 3) Recursive breakdown of a recipe
    def breakdown_recipe(recipe):
        raw_lines = []
        for ingr in recipe.raw_ingredients.select_related('raw_material','unit').all():
            rm        = ingr.raw_material
            qty       = Decimal(ingr.quantity)
            symbol    = ingr.unit.symbol
            factor    = convs.get((rm.id, symbol), Decimal('1'))
            base_qty  = qty * factor
            avg_cost  = cost_per_base(rm.id)
            line_cost = base_qty * avg_cost

            # collect PO‐lines for inspection
            po_lines = []
            for poi in PurchaseOrderItem.objects.filter(raw_material_id=rm.id):
                pq     = Decimal(poi.quantity)
                pp     = Decimal(poi.unit_price)
                pf     = convs.get((rm.id, rm.unit), Decimal('1'))
                po_lines.append({
                    'po_qty':            pq,
                    'po_unit_price':     pp,
                    'po_to_base_factor': pf,
                    'po_base_qty':       pq * pf,
                    'po_line_cost':      pq * pp,
                })

            raw_lines.append({
                'name':       rm.name,
                'unit':       symbol,
                'recipe_qty': qty,
                'to_base':    factor,
                'base_qty':   base_qty,
                'avg_cost':   avg_cost,
                'line_cost':  line_cost,
                'po_lines':   po_lines,
            })

        subrecipes = []
        for sub in recipe.subrecipes.select_related('sub_recipe').all():
            sr = sub.sub_recipe
            detail = breakdown_recipe(sr)
            # cost of the FULL sub‐recipe definition
            sub_full_cost = sum(r['line_cost'] for r in detail['raw_lines'])
            # now scale per‐gram
            req = Decimal(sub.quantity)  # interpreted as grams
            per_g = (sub_full_cost / sum(r['base_qty'] for r in detail['raw_lines'])
                     ) if detail['raw_lines'] else Decimal('0')
            subrecipes.append({
                'name':     sr.menu_item.name,
                'qty':      req,
                'detail':   detail,
                'sub_cost': (per_g * req).quantize(Decimal('0.01')),
            })

        total = sum(r['line_cost'] for r in raw_lines) \
              + sum(s['sub_cost']    for s in subrecipes)
        return {
            'raw_lines':  raw_lines,
            'subrecipes': subrecipes,
            'total':      total.quantize(Decimal('0.01')),
        }

    # 4) Assemble per‐MenuItem
    items_debug = []
    for mi in MenuItem.objects.select_related('recipe').all():
        if not hasattr(mi, 'recipe'):
            continue
        detail = breakdown_recipe(mi.recipe)
        items_debug.append({
            'menu_item': mi,
            'detail':    detail,
        })

    return render(request, 'debug_cost.html', {
        'items_debug': items_debug,
    })



from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from .models import Order, Payment

@csrf_exempt
@login_required
def close_order(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            order_id = data['order_id']
            payment_method = data['payment_method']
            amount = data['amount']
            details = data['details']

            # Get the order
            order = Order.objects.get(id=order_id, status='pending')
            
            # Create the payment
            payment = Payment.objects.create(
                order=order,
                amount=amount,
                method=payment_method,
                details = details
            )

            # Update order status to 'paid'
            order.status = 'paid'
            order.save()

            # Return success response
            return JsonResponse({'success': True})

        except Order.DoesNotExist:
            return JsonResponse({'error': 'Order not found or already closed'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request'}, status=400)


from django.views import View
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from .models import Table, TableSession, TableMenuItem, MenuItem, Deal
from django.db.models import F

from django.db import transaction

class TableSessionView(View):
    """GET session data; POST to set waiter & home_delivery"""
    def get(self, request, table_id):
        table = get_object_or_404(Table, pk=table_id)
        with transaction.atomic():
            session, created = TableSession.objects.select_for_update().get_or_create(table=table)
            if created or session.token_number is None:
                # allocate from today's noon→noon sequence
                session.token_number = get_next_token_number()
                session.save(update_fields=['token_number'])
        return JsonResponse({
            'waiter_id': session.waiter_id,
            'home_delivery': session.home_delivery,
            'token_number': session.token_number,
        })

    def post(self, request, table_id):
        import json
        payload = json.loads(request.body)
        table = get_object_or_404(Table, pk=table_id)
        session, _ = TableSession.objects.get_or_create(table=table)
        session.waiter_id     = payload.get('waiter_id')
        session.home_delivery = bool(payload.get('home_delivery'))
        session.save()
        return JsonResponse({'status':'ok'})


class TableItemsView(View):
    """GET items; POST to upsert quantity"""
    def get(self, request, table_id):
        session = get_object_or_404(TableSession, table_id=table_id)
        items = session.picked_items.all()
        data = []
        for ti in items:
            model = MenuItem if ti.source_type == 'menu' else Deal
            obj = model.objects.get(pk=ti.source_id)
            data.append({
                'source_type': ti.source_type,
                'source_id': ti.source_id,
                'name': obj.name,
                'quantity': ti.quantity,
                'unit_price': float(ti.unit_price),
                'printed_quantity': ti.printed_quantity,
                'created_at': ti.created_at.isoformat() if ti.created_at else None,
                'updated_at': ti.updated_at.isoformat() if ti.updated_at else None,
                'last_added_at': ti.last_added_at.isoformat() if ti.last_added_at else None,
            })
        return JsonResponse({'items': data})

    def post(self, request, table_id):
        import json
        my_datetime = timezone.localtime(timezone.now())
        payload = json.loads(request.body)
        session = get_object_or_404(TableSession, table_id=table_id)
        st = payload['source_type']
        sid = payload['source_id']
        qty = payload.get('quantity', 1)
        up = payload['unit_price']
        obj, created = TableMenuItem.objects.get_or_create(
            session=session,
            source_type=st,
            source_id=sid,
            created_at = my_datetime,
            updated_at = my_datetime,
            defaults={'quantity': qty, 'unit_price': up}
        )
        if not created:
            obj.quantity = F('quantity') + qty
            obj.unit_price = up
            obj.save()
        return JsonResponse({'status':'ok'})
    
    def delete(self, request, table_id):
        session = get_object_or_404(TableSession, table_id=table_id)

        # 1) parse and delete
        try:
            payload = json.loads(request.body)
            st = payload['source_type']
            sid = payload['source_id']
        except (ValueError, KeyError):
            return JsonResponse({'error': 'Invalid payload'}, status=400)

        deleted, _ = TableMenuItem.objects.filter(
            session=session,
            source_type=st,
            source_id=sid
        ).delete()

        if not deleted:
            return JsonResponse({'error': 'Item not found'}, status=404)

        # 2) fetch ALL remaining items
        remaining = list(session.picked_items.all())

        # 3) debug‐print to console
        # print(f"[Table {table_id}] after delete, remaining items:")
        # for ti in remaining:
        #     Model = MenuItem if ti.source_type=='menu' else Deal
        #     obj   = Model.objects.get(pk=ti.source_id)
        #     print(f"    • {ti.quantity}× {obj.name} @ {ti.unit_price}")

        # 4) build & send full‐token payload
        # payload = build_full_session_token_bytes(session, remaining)
        # send_to_printer(payload)

        # 5) mark all as printed
        # for ti in remaining:
        #     ti.printed_quantity = 0
        #     ti.save(update_fields=['printed_quantity'])

        # 6) respond
        return JsonResponse({
            'status': 'deleted_and_printed',
            'count': len(remaining)
        })
    
    def put(self, request, table_id):
        """
        JSON body: { source_type, source_id, quantity }
        Overwrites the quantity on the TableMenuItem for this table.
        """
        import json
        from django.shortcuts import get_object_or_404
        from .models import TableSession, TableMenuItem

        session = get_object_or_404(TableSession, table_id=table_id)
        try:
            payload = json.loads(request.body)
            st  = payload['source_type']
            sid = payload['source_id']
            qty = int(payload['quantity'])
        except (ValueError, KeyError):
            return JsonResponse({'error': 'Invalid payload'}, status=400)

        try:
            tmi = TableMenuItem.objects.get(
                session=session,
                source_type=st,
                source_id=sid
            )
        except TableMenuItem.DoesNotExist:
            return JsonResponse({'error': 'Item not found'}, status=404)

        tmi.quantity = qty
        tmi.save(update_fields=['quantity'])
        return JsonResponse({'status': 'updated'})

def build_full_session_token_bytes(session, items):
    from django.utils import timezone
    from .models import MenuItem, Deal

    esc = b"\x1B"
    gs  = b"\x1D"
    lines = []

    # — Header —
    lines.append(esc + b"\x61" + b"\x01")        # center
    lines.append(esc + b"\x21" + b"\x20")        # double-width
    lines.append(b"UPDATED KITCHEN TOKEN\n")
    lines.append(esc + b"\x21" + b"\x00")        # normal
    lines.append(b"\n")

    token_str = str(session.token_number).encode("ascii")
    lines.append(esc + b"\x21" + b"\x30")   # ESC ! 0x10 → double width, normal height
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    lines.append(esc + b"\x21" + b"\x00")     # back to normal
    lines.append(esc + b"\x61" + b"\x00")     # left

    # — Table # (large) —
    table_no = str(session.table.number).encode("ascii")
    lines.append(esc + b"\x61" + b"\x01")        # center
    lines.append(esc + b"\x21" + b"\x30")        # double-height
    lines.append(b"TABLE #: " + table_no + b"\n\n")
    lines.append(esc + b"\x21" + b"\x00")        # normal

    # — Date / Waiter —
    # now = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    now_local = timezone.localtime(timezone.now())
    now = now_local.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    lines.append(esc + b"\x61" + b"\x00")        # left
    lines.append(b"Date   : " + now + b"\n")
    if session.waiter:
        waiter = session.waiter.name.encode("ascii", "ignore")
        lines.append(b"Waiter : " + waiter + b"\n")
    lines.append(b"-" * 32 + b"\n")

    # — Columns —
    lines.append(b"#  Item                 Qty\n")
    lines.append(b"-" * 32 + b"\n")

    # — Items —
    for idx, ti in enumerate(items, start=1):
        Model   = MenuItem if ti.source_type == "menu" else Deal
        name    = Model.objects.get(pk=ti.source_id).name[:18]
        idx_f   = str(idx).rjust(2).encode()                     # " 1", " 2", ...
        name_f  = name.ljust(18).encode("ascii", "ignore")       # pad to 18 chars
        qty_f   = str(ti.quantity).rjust(3).encode()             # "  3", etc.
        lines.append(idx_f + b"  " + name_f + b"  " + qty_f + b"\n")

    lines.append(b"\n\n\n\n\n")
    # — Cut —
    lines.append(b"\n" * 4)
    lines.append(gs + b"\x56" + b"\x00")  # full cut

    return b"".join(lines)

class ClearTableItemsView(View):
    """DELETE all items (e.g. after paid)"""
    def delete(self, request, table_id):
        session = get_object_or_404(TableSession, table_id=table_id)
        session.picked_items.all().delete()
        return JsonResponse({'status': 'cleared'})



from django.shortcuts import get_object_or_404
from django.http      import JsonResponse
from django.views     import View
from django.utils     import timezone

from .models          import TableSession, MenuItem, Deal
from .printing        import send_to_printer


def build_session_token_bytes(session, items_with_delta):
    esc = b"\x1B"
    gs  = b"\x1D"
    lines = []

    # ─── Header ─────────────────────────────────────────────────────────────
    has_removal = any(delta < 0 for _, delta in items_with_delta)
    lines.append(esc + b"\x61" + b"\x01")     # center
    lines.append(esc + b"\x21" + b"\x20")     # double-width
    lines.append(
        b"UPDATED KITCHEN TOKEN\n" if has_removal
        else b"KITCHEN TOKEN\n"
    )
    lines.append(b"\n")
    token_str = str(session.token_number).encode("ascii")
    lines.append(esc + b"\x21" + b"\x30")   # ESC ! 0x10 → double width, normal height
    lines.append(b"TOKEN #: " + token_str + b"\n\n")

    lines.append(esc + b"\x21" + b"\x00")     # back to normal
    # ─── Table Number (large) ─────────────────────────────────────────────
    lines.append(esc + b"\x61" + b"\x00")     # left
    table_no = str(session.table.number).encode("ascii")
    lines.append(esc + b"\x61" + b"\x01")     # center
    lines.append(esc + b"\x21" + b"\x30")     # double height & width
    lines.append(b"TABLE #: " + table_no + b"\n\n")
    lines.append(esc + b"\x21" + b"\x00")     # normal

    # ─── Date / Waiter / Mode ─────────────────────────────────────────────
    # now = timezone.localtime(timezone.now())\
    #                .strftime("%Y-%m-%d %I:%M:%S %p")\
    #                .encode("ascii")
    
    now_local = timezone.localtime(timezone.now())
    now = now_local.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    
    lines.append(esc + b"\x61" + b"\x00")     # left
    lines.append(b"Date  : " + now + b"\n")
    if session.waiter:
        waiter = session.waiter.name.encode("ascii", "ignore")
        lines.append(b"Waiter: " + waiter + b"\n")
    lines.append(b"-" * 32 + b"\n")

    # ─── Column Headers ───────────────────────────────────────────────────
    lines.append(b"#  Item                 Qty\n")
    lines.append(b"-" * 32 + b"\n")

    # ─── Items Section ────────────────────────────────────────────────────
    if has_removal:
        # re-print full current list
        full = session.picked_items.all()
        for idx, ti in enumerate(full, start=1):
            Model = MenuItem if ti.source_type == "menu" else Deal
            name  = Model.objects.get(pk=ti.source_id).name[:18]
            qty   = ti.quantity
            lines.append(
                str(idx).rjust(2).encode() + b"  " +
                name.ljust(18).encode("ascii","ignore") + b"  " +
                str(qty).rjust(3).encode() + b"\n"
            )
    else:
        # only newly added (positive deltas)
        adds = [(ti, d) for ti, d in items_with_delta if d > 0]
        for idx, (ti, d) in enumerate(adds, start=1):
            Model = MenuItem if ti.source_type == "menu" else Deal
            name  = Model.objects.get(pk=ti.source_id).name[:18]
            lines.append(
                str(idx).rjust(2).encode() + b"  " +
                name.ljust(18).encode("ascii","ignore") + b"  " +
                str(d).rjust(3).encode() + b"\n"
            )
    
    lines.append(b"\n\n\n\n\n")
    # ─── Feed + Cut ────────────────────────────────────────────────────────
    lines.append(b"\n" * 4)
    lines.append(gs + b"\x56" + b"\x00")      # full cut

    return b"".join(lines)


from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from .models import Order, PrintStatus
from .printing import send_to_printer

class OrderReprintView(LoginRequiredMixin, View):
    def post(self, request, pk):
        order = get_object_or_404(Order, pk=pk)

        bill_data = build_bill_bytes(order, order.source or 'walk_in', 'Reprint Copy')
        send_to_printer(bill_data)

        return JsonResponse({'status': 'reprinted'})


ESC = b"\x1B"
GS  = b"\x1D"

def build_token_bytes_for_items(order, items, header_label):
    """
    Builds token for Walk-in/Delivery orders.
    """
    ESC = b"\x1B"
    GS  = b"\x1D"
    lines = []

    # 1) Restaurant Name
    lines.append(ESC + b"\x61" + b"\x01")   # Center
    # lines.append(ESC + b"\x21" + b"\x30") # Double height/width (Optional for Rest Name)
    lines.append(b"NEW MARHABA\n")
    lines.append(ESC + b"\x21" + b"\x00")   # Reset
    lines.append(b"\n")

    # 2) STATION NAME (Large) <--- THIS IS THE FIX
    lines.append(ESC + b"\x61" + b"\x01")   # Center
    lines.append(ESC + b"\x21" + b"\x20")   # Double Width (or \x30 for Double Height+Width)
    lines.append(header_label.encode("ascii", "ignore") + b"\n") 
    lines.append(ESC + b"\x21" + b"\x00")   # Reset
    lines.append(b"\n")

    # 3) Token #
    token_str = str(order.token_number).encode("ascii")
    lines.append(ESC + b"\x21" + b"\x30")   # Double Height+Width
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    lines.append(ESC + b"\x21" + b"\x00")   # Reset

    # 4) Date/Time & Waiter
    dt = order.created_at.strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    lines.append(ESC + b"\x61" + b"\x00")   # Left
    lines.append(b"Date: " + dt + b"\n")
    if order.waiter:
        lines.append(f"Waiter: {order.waiter.name}\n".encode("ascii", "ignore"))

    # 5) Order Type
    if order.isHomeDelivery == "yes":
        lines.append(b"HOME DELIVERY\n\n")
    elif order.isHomeDelivery == "no" and not order.table:
        lines.append(b"TAKE AWAY\n\n") # Or PARCEL
    
    lines.append(b"-" * 32 + b"\n")

    # 6) Items
    for idx, oi in enumerate(items, 1):
        name = (oi.menu_item.name if oi.menu_item else oi.deal.name)[:20]
        name_field = name.ljust(20).encode("ascii", "ignore")
        qty = str(oi.quantity).rjust(3).encode("ascii")
        lines.append(f"{idx}. ".encode("ascii") + name_field + b" x" + qty + b"\n")

    lines.append(b"\n\n\n\n" + GS + b"\x56" + b"\x00") # Cut
    return b"".join(lines)


from django.shortcuts import get_object_or_404
from django.http      import JsonResponse
from django.views     import View
from django.utils     import timezone

from .models          import TableSession, MenuItem, Deal
from .printing        import send_to_printer
from .utils           import get_next_token_number

ESC = b"\x1B"
GS  = b"\x1D"


def build_group_token_bytes(session, items_with_delta, header_label):
    lines = []

    # ── Header ─────────────────────────────────────────────
    lines.append(ESC + b"\x61" + b"\x01")            # center
    lines.append(ESC + b"\x21" + b"\x20")            # double-width
    lines.append(header_label.encode("ascii") + b"\n")
    lines.append(ESC + b"\x21" + b"\x00")            # normal
    lines.append(b"\n")

    # ── Token # ────────────────────────────────────────────
    token_str = str(session.token_number).encode("ascii")
    lines.append(ESC + b"\x21" + b"\x30")            # double width
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    lines.append(ESC + b"\x21" + b"\x00")            # normal

    # ── Table # ────────────────────────────────────────────
    table_no = str(session.table.number).encode("ascii")
    lines.append(ESC + b"\x61" + b"\x01")
    lines.append(ESC + b"\x21" + b"\x30")
    lines.append(b"TABLE #: " + table_no + b"\n\n")
    lines.append(ESC + b"\x21" + b"\x00")

    # ── Date / Waiter ───────────────────────────────────────
    now = timezone.localtime(timezone.now())\
                   .strftime("%Y-%m-%d %I:%M:%S %p")\
                   .encode("ascii")
    lines.append(ESC + b"\x61" + b"\x00")
    lines.append(b"Date  : " + now + b"\n")
    if session.waiter:
        waiter = session.waiter.name.encode("ascii", "ignore")
        lines.append(b"Waiter: " + waiter + b"\n")
    lines.append(b"-" * 32 + b"\n")

    # ── Columns ─────────────────────────────────────────────
    lines.append(b"#  Item                 Qty\n")
    lines.append(b"-" * 32 + b"\n")

    # ── Items Section ───────────────────────────────────────
    for idx, (ti, delta) in enumerate(items_with_delta, start=1):
        Model = MenuItem if ti.source_type=='menu' else Deal
        name  = Model.objects.get(pk=ti.source_id).name[:18]
        idx_b = str(idx).rjust(2).encode()
        name_b= name.ljust(18).encode("ascii","ignore")
        qty_b = str(delta).rjust(3).encode()
        lines.append(idx_b + b"  " + name_b + b"  " + qty_b + b"\n")

    lines.append(b"\n\n\n\n\n")
    # ── Cut ───────────────────────────────────────────────────
    lines.append(b"\n" * 4)
    lines.append(GS + b"\x56" + b"\x00")              # full cut

    return b"".join(lines)



# core/views.py

import json
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from .models import TableSession, Table

class TableSessionSwitchView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            old_id = data['from_table']
            new_id = data['to_table']
        except (KeyError, json.JSONDecodeError):
            return JsonResponse({'error': 'Invalid payload'}, status=400)

        # 1) Fetch the existing session on the old table
        try:
            session = TableSession.objects.get(table_id=old_id)
        except TableSession.DoesNotExist:
            return JsonResponse({'error': 'No active session on your current table.'}, status=400)

        # 2) Ensure target table is truly available
        #    (if a session exists there, it must have no picked_items)
        existing = TableSession.objects.filter(table_id=new_id).first()
        if existing and existing.picked_items.exists():
            return JsonResponse({'error': 'That table is not available.'}, status=400)
        # delete any empty session
        if existing:
            existing.delete()

        # 3) Re-assign our session to the new table
        session.table_id = new_id
        session.save(update_fields=['table'])

        # 4) Update occupancy flags
        Table.objects.filter(pk=old_id).update(is_occupied=False)
        Table.objects.filter(pk=new_id).update(is_occupied=True)

        return JsonResponse({'status': 'ok', 'new_table': new_id})
    

# core/views.py

from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.views import View
from .models import TableSession, MenuItem, Deal, PrintStation
from .printing import send_to_printer
from .utils import get_next_token_number
from django.utils import timezone

class TablePrintTokenView(View):
    def post(self, request, table_id):
        session = get_object_or_404(TableSession, table_id=table_id)
        
        # 1. Ensure TableSession has a global token number
        if session.token_number is None:
            session.token_number = get_next_token_number(station=None)
            session.save(update_fields=['token_number'])

        # 2. Identify new items (deltas)
        items = session.picked_items.all()
        deltas = [(ti, ti.quantity - (ti.printed_quantity or 0)) for ti in items]
        items_with_delta = [(ti, d) for ti, d in deltas if d != 0]

        if not items_with_delta:
            return JsonResponse({'status': 'nothing_to_print'})

        # 3. Group items by PrintStation
        grouped_items = {}

        for ti, d in items_with_delta:
            station = None
            if ti.source_type == 'menu':
                try:
                    mi = MenuItem.objects.get(pk=ti.source_id)
                    station = mi.get_effective_station()
                except MenuItem.DoesNotExist:
                    pass
            elif ti.source_type == 'deal':
                pass 

            key = station if station else 'Global'
            if key not in grouped_items:
                grouped_items[key] = []
            
            grouped_items[key].append((ti, d))

        # 4. Process each group and print
        for key, group_items in grouped_items.items():
            
            # Defaults
            target_printer = "POS80 Printer"
            token_num = session.token_number

            if key == 'Global':
                header_label = "KITCHEN TOKEN"
            else:
                station_obj = key
                header_label = f"{station_obj.name.upper()} TOKEN"
                if station_obj.printer_name:
                    target_printer = station_obj.printer_name
                if station_obj.use_separate_sequence:
                    token_num = get_next_token_number(station=station_obj)

            # Build Bytes
            payload = build_dynamic_token_bytes(
                session, 
                group_items, 
                header_label, 
                token_num
            )
            
            # Skip printing if printer name is "no print" or empty
            if target_printer and target_printer.strip().lower() not in ['no print', 'noprint', '']:
                print(f"Printing {header_label} to {target_printer}")
                try:
                    send_to_printer(payload, printer_name=target_printer)
                except Exception as e:
                    print(f"Printer Error for {header_label}: {e}")
            else:
                print(f"Skipping print for {header_label} - printer set to 'no print'")

        # 5. Update printed quantities
        for ti, d in items_with_delta:
            ti.printed_quantity = ti.quantity
            ti.save(update_fields=['printed_quantity'])

        return JsonResponse({
            'status': 'printed', 
            'count': len(items_with_delta)
        }) 

def build_dynamic_token_bytes(session, items_with_delta, header_label, token_number):
    """
    Builds token for Table Sessions.
    """
    ESC = b"\x1B"
    GS  = b"\x1D"
    lines = []

    # 1. Station Header (Large)
    lines.append(ESC + b"\x61" + b"\x01") # Center
    lines.append(ESC + b"\x21" + b"\x20") # Double Width
    lines.append(header_label.encode("ascii", "ignore") + b"\n")
    lines.append(ESC + b"\x21" + b"\x00") # Reset
    lines.append(b"\n")

    # 2. Token #
    token_str = str(token_number).encode("ascii")
    lines.append(ESC + b"\x21" + b"\x30") # Double H/W
    lines.append(b"TOKEN #: " + token_str + b"\n\n")
    lines.append(ESC + b"\x21" + b"\x00") 

    # 3. Table Info
    table_no = str(session.table.number).encode("ascii")
    lines.append(ESC + b"\x61" + b"\x01")
    lines.append(ESC + b"\x21" + b"\x30")
    lines.append(b"TABLE #: " + table_no + b"\n\n")
    lines.append(ESC + b"\x21" + b"\x00")

    # 4. Meta
    now = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %I:%M:%S %p").encode("ascii")
    lines.append(ESC + b"\x61" + b"\x00") 
    lines.append(b"Date  : " + now + b"\n")
    if session.waiter:
        w_name = session.waiter.name.encode("ascii", "ignore")
        lines.append(b"Waiter: " + w_name + b"\n")
    lines.append(b"-" * 32 + b"\n")

    # 5. Items
    lines.append(b"#  Item                 Qty\n")
    lines.append(b"-" * 32 + b"\n")

    for idx, (ti, delta) in enumerate(items_with_delta, start=1):
        if ti.source_type == 'menu':
            from .models import MenuItem
            try:
                obj = MenuItem.objects.get(pk=ti.source_id)
                name = obj.name
            except MenuItem.DoesNotExist:
                name = "Unknown Item"
        else:
            from .models import Deal
            try:
                obj = Deal.objects.get(pk=ti.source_id)
                name = obj.name
            except Deal.DoesNotExist:
                name = "Unknown Deal"
        
        name = name[:18]
        idx_b = str(idx).rjust(2).encode()
        name_b = name.ljust(18).encode("ascii", "ignore")
        qty_b = str(delta).rjust(3).encode()
        
        lines.append(idx_b + b"  " + name_b + b"  " + qty_b + b"\n")

    lines.append(b"\n\n\n\n\n")
    lines.append(b"\n" * 4)
    lines.append(GS + b"\x56" + b"\x00") 

    return b"".join(lines)



from django.urls import reverse_lazy
from django.views.generic import UpdateView, CreateView, DeleteView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib import messages

from .models import POSSettings, PrintStation
from .forms import POSSettingsForm, PrintStationForm

# --- Configuration Dashboard (Settings + Station List) ---
@method_decorator(require_permission('settings'), name='dispatch')
class ConfigurationView(LoginRequiredMixin, View):
    template_name = 'settings/configuration.html'

    def get(self, request):
        # Ensure Settings exist
        settings_obj, created = POSSettings.objects.get_or_create(id=1, defaults={'restaurant_name': 'My Restaurant'})
        
        settings_form = POSSettingsForm(instance=settings_obj)
        stations = PrintStation.objects.all()

        return render(request, self.template_name, {
            'settings_form': settings_form,
            'stations': stations
        })

    def post(self, request):
        # Handle the General Settings Form Post
        settings_obj = POSSettings.objects.first()
        form = POSSettingsForm(request.POST, request.FILES, instance=settings_obj)
        
        if form.is_valid():
            form.save()
            messages.success(request, "General settings updated successfully.")
            return redirect('configuration')
        
        # If invalid, re-render
        stations = PrintStation.objects.all()
        return render(request, self.template_name, {
            'settings_form': form,
            'stations': stations
        })

# --- Print Station CRUD ---
@method_decorator(require_permission('settings'), name='dispatch')
class PrintStationCreateView(LoginRequiredMixin, CreateView):
    model = PrintStation
    form_class = PrintStationForm
    template_name = 'settings/station_form.html'
    success_url = reverse_lazy('configuration')

    def form_valid(self, form):
        messages.success(self.request, "Print Station created.")
        return super().form_valid(form)

@method_decorator(require_permission('settings'), name='dispatch')
class PrintStationUpdateView(LoginRequiredMixin, UpdateView):
    model = PrintStation
    form_class = PrintStationForm
    template_name = 'settings/station_form.html'
    success_url = reverse_lazy('configuration')

    def form_valid(self, form):
        messages.success(self.request, "Print Station updated.")
        return super().form_valid(form)

@method_decorator(require_permission('settings'), name='dispatch')
class PrintStationDeleteView(LoginRequiredMixin, DeleteView):
    model = PrintStation
    success_url = reverse_lazy('configuration')
    
    def get(self, request, *args, **kwargs):
        return self.post(request, *args, **kwargs) 
    

from .models import PaymentReceived
from .forms import PaymentReceivedForm 

# ---------- PAYMENT RECEIVED CRUD ----------

@method_decorator(require_permission('accounts'), name='dispatch')
class PaymentReceivedListView(LoginRequiredMixin, ListView):
    model = PaymentReceived
    template_name = 'payments/payment_received_list.html'
    context_object_name = 'payments'
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related('customer', 'supplier', 'bank_account').order_by('-date', '-created_at')
        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(customer__name__icontains=q) | qs.filter(supplier__name__icontains=q)
        return qs

@method_decorator(require_permission('accounts'), name='dispatch')
class PaymentReceivedCreateView(LoginRequiredMixin, AjaxableResponseMixin, CreateView):
    model = PaymentReceived
    form_class = PaymentReceivedForm
    template_name = 'payments/payment_received_form.html'
    success_url = reverse_lazy('payment_received_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

@method_decorator(require_permission('accounts'), name='dispatch')
class PaymentReceivedUpdateView(LoginRequiredMixin, AjaxableResponseMixin, UpdateView):
    model = PaymentReceived
    form_class = PaymentReceivedForm
    template_name = 'payments/payment_received_form.html'
    success_url = reverse_lazy('payment_received_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

@method_decorator(require_permission('accounts'), name='dispatch')
class PaymentReceivedDeleteView(LoginRequiredMixin, DeleteView):
    model = PaymentReceived
    success_url = reverse_lazy('payment_received_list')

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        self.object.delete()
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'message': 'Deleted'})
        return super().delete(request, *args, **kwargs)
    

# core/views.py
from .printing import build_market_list_bytes

class MarketListView(LoginRequiredMixin, View):
    template_name = 'inventory/market_list.html'

    def get(self, request):
        # Fetch all raw materials to populate the search dropdown
        raw_materials = RawMaterial.objects.all().values('id', 'name', 'unit').order_by('name')
        
        # Serialize to JSON for the frontend JS
        raw_materials_json = json.dumps(list(raw_materials))

        return render(request, self.template_name, {
            'raw_materials_json': raw_materials_json
        })

    def post(self, request):
        try:
            data = json.loads(request.body)
            items = data.get('items', [])
            
            if not items:
                return JsonResponse({'status': 'error', 'message': 'List is empty'})

            # Generate Bytes
            print_data = build_market_list_bytes(items)
            
            # Send to default POS80 Printer
            # (Pass None to use the default defined in printing.py)
            send_to_printer(print_data, printer_name=None)
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            print(f"Market Print Error: {e}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
