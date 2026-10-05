"""
Single source of truth for the left sidebar.

Keeping the menu here (instead of hard-coding links in base.html) means the
navigation can be reordered, renamed or extended in one place, and every page
gets the same menu automatically.

Each item:
    label    text shown in the sidebar
    icon     Font Awesome 6 class, e.g. 'fa-utensils'
    url_name route name; it is reversed at render time, so a missing route is
             reported loudly instead of producing a dead link.
    match    extra url_names that should also highlight this item (e.g. the
             create/edit screens highlight their list entry)
    accent   draw the item as the primary call to action
    warn     draw the item in the "needs attention" colour
"""
from django.urls import reverse, NoReverseMatch
from core.permissions import SIDEBAR_AREA
import logging

logger = logging.getLogger(__name__)


SIDEBAR = [
    {
        'heading': None,
        'items': [
            {'label': 'Dashboard', 'icon': 'fa-gauge-high', 'url_name': 'dashboard'},
        ],
    },
    {
        'heading': 'Sales',
        'items': [
            {'label': 'New Order', 'icon': 'fa-file-circle-plus', 'url_name': 'order_create',
             'short': 'New', 'accent': True},
            {'label': 'Orders', 'icon': 'fa-receipt', 'url_name': 'order_list',
             'match': ['order_detail', 'order_edit', 'order_update']},
            {'label': 'Tables', 'icon': 'fa-table-cells', 'url_name': 'table_list',
             'match': ['table_edit']},
        ],
    },
    {
        'heading': 'Menu',
        'items': [
            {'label': 'Categories', 'icon': 'fa-folder-open', 'url_name': 'category_list',
             'match': ['category_detail', 'category_edit']},
            {'label': 'Menu Items', 'icon': 'fa-utensils', 'url_name': 'menuitem_list',
             'match': ['menuitem_detail', 'menuitem_edit']},
            {'label': 'Deals', 'icon': 'fa-tags', 'url_name': 'deal_list',
             'match': ['deal_detail', 'deal_edit']},
            {'label': 'Modifiers', 'icon': 'fa-sliders', 'url_name': 'modifiergroup_list',
             'match': ['modifiergroup_edit']},
            {'label': 'Taxes', 'icon': 'fa-percent', 'url_name': 'taxrate_list',
             'match': ['taxrate_edit']},
        ],
    },
    {
        'heading': 'Kitchen',
        'items': [
            {'label': 'Kitchen Vouchers', 'icon': 'fa-fire-burner', 'url_name': 'kitchen_voucher_list'},
            {'label': 'Stock Summary', 'icon': 'fa-clipboard-list', 'url_name': 'kitchen_stock_summary'},
        ],
    },
    {
        'heading': 'Inventory',
        'items': [
            {'label': 'Raw Materials', 'icon': 'fa-boxes-stacked', 'url_name': 'raw_material_list',
             'match': ['raw_material_detail', 'raw_material_edit']},
            {'label': 'Recipes', 'icon': 'fa-book-open', 'url_name': 'recipe_list',
             'match': ['recipe_detail', 'recipe_edit']},
            {'label': 'Purchase Orders', 'icon': 'fa-cart-flatbed', 'url_name': 'purchase_order_list',
             'match': ['purchase_order_detail', 'purchase_order_edit']},
            {'label': 'Suppliers', 'icon': 'fa-truck-field', 'url_name': 'supplier_list',
             'match': ['supplier_detail', 'supplier_edit']},
            {'label': 'Low Stock', 'icon': 'fa-triangle-exclamation', 'url_name': 'low_stock',
             'warn': True},
            {'label': 'Units', 'icon': 'fa-scale-balanced', 'url_name': 'unit_list'},
        ],
    },
    {
        'heading': 'Finance',
        'items': [
            {'label': 'Expenses', 'icon': 'fa-money-bill-transfer', 'url_name': 'expense_list',
             'match': ['expense_edit']},
            {'label': 'Payments In', 'icon': 'fa-hand-holding-dollar', 'url_name': 'payment_received_list',
             'match': ['payment_received_edit']},
            {'label': 'Bank Accounts', 'icon': 'fa-building-columns', 'url_name': 'bankaccount_list',
             'match': ['bankaccount_update']},
            {'label': 'Bank Movements', 'icon': 'fa-arrow-right-arrow-left', 'url_name': 'bankmovement_list'},
            {'label': 'Ledgers', 'icon': 'fa-book', 'url_name': 'ledger_home'},
        ],
    },
    {
        'heading': 'People',
        'items': [
            {'label': 'Waiters', 'icon': 'fa-user-tie', 'url_name': 'waiter_list',
             'match': ['waiter_detail', 'waiter_edit']},
            {'label': 'Staff', 'icon': 'fa-id-card-clip', 'url_name': 'staff_list',
             'match': ['staff_edit']},
            {'label': 'Customers', 'icon': 'fa-users', 'url_name': 'customer_list',
             'match': ['customer_edit']},
        ],
    },
    {
        'heading': 'Insights',
        'items': [
            {'label': 'Reports', 'icon': 'fa-chart-line', 'url_name': 'reports',
             'match': ['cost_report']},
        ],
    },
    {
        'heading': 'System',
        'items': [
            {'label': 'Settings', 'icon': 'fa-gear', 'url_name': 'configuration',
             'match': ['station_create', 'station_edit']},
        ],
    },
]


def build_sidebar(current_url_name='', areas=None):
    """
    Turn SIDEBAR into template-friendly sections with resolved URLs.

    Items whose route cannot be reversed are dropped instead of breaking every
    page (handy while a screen is still being written). Each item also gets an
    `is_active` flag - Django templates cannot call functions with arguments, so
    the "which link is highlighted" decision is made here.

    When `areas` is given, only links the user may actually open are returned,
    so a cashier simply never sees the menu/inventory/accounts screens.
    """
    sections = []
    for section in SIDEBAR:
        rendered_items = []
        for item in section['items']:
            if areas is not None and not route_allowed(item['url_name'], areas):
                continue
            try:
                url = reverse(item['url_name'])
            except NoReverseMatch:
                # Surfaced loudly while developing so a renamed/missing route
                # never silently disappears from the menu.
                logger.warning(
                    'Sidebar link %r has no matching route and was skipped.', item['url_name']
                )
                continue
            rendered_items.append({
                **item,
                'url': url,
                'is_active': is_active(item, current_url_name),
            })
        if rendered_items:
            sections.append({'heading': section['heading'], 'items': rendered_items})
    return sections


def route_allowed(url_name, areas):
    """Route-level check against an explicit set of permitted areas."""
    area = SIDEBAR_AREA.get(url_name)
    if area is None:
        return True                      # unknown route: leave it alone
    return area in areas


def active_url_name(request):
    match = getattr(request, 'resolver_match', None)
    return getattr(match, 'url_name', '') if match else ''


def is_active(item, current_url_name):
    if item['url_name'] == current_url_name:
        return True
    return current_url_name in item.get('match', [])

# Branding shown across the UI (header, page titles). Kept in one place so the
# name only ever has to be changed in settings.py (RESTAURANT_NAME).
DEFAULT_RESTAURANT_NAME = 'RestroPOS'


def app_branding(request):
    """Expose RESTAURANT_NAME from settings.py to every template."""
    return {
        'RESTAURANT_NAME': getattr(settings, 'RESTAURANT_NAME', DEFAULT_RESTAURANT_NAME),
    }


def localization(request):
    """
    Expose the active country's currency/locale details to every template,
    so templates never hardcode a currency symbol.
    """
    cfg = active_country()
    return {
        'COUNTRY_CODE': cfg['code'],
        'COUNTRY_NAME': cfg['name'],
        'CURRENCY_CODE': cfg['currency_code'],
        'CURRENCY_SYMBOL': cfg['currency_symbol'],
        'CURRENCY_LOCALE': cfg['locale'],
        'PHONE_CODE': cfg['phone_code'],
        'VAT_RATE': cfg['vat_rate'],
    }