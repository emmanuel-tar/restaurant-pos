from django.urls import path
from django.views.generic import RedirectView
from django.contrib import admin

from .views import LoginView, LogoutView, DashboardView, update_print_status, reports_view, sales_report
from .views import TableListView, TableCreateView, TableUpdateView, TableSwitchView

from .views import (
    CategoryListView, CategoryCreateView, CategoryDetailView,
    CategoryUpdateView, CategoryDeleteView,
    MenuItemListView, MenuItemCreateView, MenuItemDetailView,
    MenuItemUpdateView, MenuItemDeleteView,
    OrderListView, OrderDetailView, OrderCreateView, OrderUpdateView, OrderDeleteView,
    DealListView, DealCreateView, DealDetailView, DealUpdateView, DealDeleteView
)

from .escpos_test import(
        simple_win32print_test
)

from .views import (
    SupplierListView, SupplierCreateView,
    SupplierDetailView, SupplierUpdateView, SupplierDeleteView, close_order
)


urlpatterns = [
    
        
    path('orders/close_order/', close_order, name='close_order'),   
    path(
        "",
        RedirectView.as_view(pattern_name="login", permanent=False),
        name="home",
    ),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),

    # Categories CRUD
    path('categories/', CategoryListView.as_view(), name='category_list'),
    path('categories/create/', CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category_detail'),
    path('categories/<int:pk>/edit/', CategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', CategoryDeleteView.as_view(), name='category_delete'),

    # Menu Items CRUD
    path('menu-items/', MenuItemListView.as_view(), name='menuitem_list'),
    path('menu-items/create/', MenuItemCreateView.as_view(), name='menuitem_create'),
    path('menu-items/<int:pk>/', MenuItemDetailView.as_view(), name='menuitem_detail'),
    path('menu-items/<int:pk>/edit/', MenuItemUpdateView.as_view(), name='menuitem_edit'),
    path('menu-items/<int:pk>/delete/', MenuItemDeleteView.as_view(), name='menuitem_delete'),

    # ======== Deals CRUD ========
    path('deals/', DealListView.as_view(), name='deal_list'),
    path('deals/create/', DealCreateView.as_view(), name='deal_create'),
    path('deals/<int:pk>/', DealDetailView.as_view(), name='deal_detail'),
    path('deals/<int:pk>/edit/', DealUpdateView.as_view(), name='deal_edit'),
    path('deals/<int:pk>/delete/', DealDeleteView.as_view(), name='deal_delete'),

    # ======== Orders & Printing ========
    path('orders/', OrderListView.as_view(), name='order_list'),
    path('orders/create/', OrderCreateView.as_view(), name='order_create'),
    path('orders/<int:pk>/', OrderDetailView.as_view(), name='order_detail'),
    path('orders/<int:pk>/edit/', OrderUpdateView.as_view(), name='order_edit'),
    path('orders/<int:pk>/delete/', OrderDeleteView.as_view(), name='order_delete'),
    path('orders/<int:pk>/update/', OrderUpdateView.as_view(), name='order_update'),  # ← Here
    path('print/', simple_win32print_test, name="simple_windows_test_print"),

    path(
        "printstatus/update/",
        update_print_status,
        name="update_print_status"
    ),

    

    path('api/sales-report/', sales_report, name='sales-report'),

    path('tables/',          TableListView.as_view(),   name='table_list'),
    path('tables/create/',   TableCreateView.as_view(), name='table_create'),
    path('tables/<int:pk>/edit/', TableUpdateView.as_view(), name='table_edit'),
    
    path(
      'orders/table-switch/',
      TableSwitchView.as_view(),
      name='table_switch'
    ),
    
]

urlpatterns += [
    # Suppliers CRUD
    path('suppliers/', SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/create/', SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/', SupplierDetailView.as_view(), name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', SupplierUpdateView.as_view(), name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', SupplierDeleteView.as_view(), name='supplier_delete'),
]


from .views import (
    # … other imports …
    LowStockView, RawMaterialListView, RawMaterialCreateView,
    RawMaterialDetailView, RawMaterialUpdateView, RawMaterialDeleteView,
    UnitListView,
)

urlpatterns += [
    # Raw Materials CRUD
    path('inventory/low-stock/', LowStockView.as_view(), name='low_stock'),
    path('inventory/units/', UnitListView.as_view(), name='unit_list'),
  path('raw-materials/', RawMaterialListView.as_view(), name='raw_material_list'),
    path('raw-materials/create/', RawMaterialCreateView.as_view(), name='raw_material_create'),
    path('raw-materials/<int:pk>/', RawMaterialDetailView.as_view(), name='raw_material_detail'),
    path('raw-materials/<int:pk>/edit/', RawMaterialUpdateView.as_view(), name='raw_material_edit'),
    path('raw-materials/<int:pk>/delete/', RawMaterialDeleteView.as_view(), name='raw_material_delete'),
]


from .views import (
    # … other imports …
    OrderHoldView, OrderHoldRecallView, OrderHoldDeleteView,
    PurchaseOrderListView,
    PurchaseOrderCreateView,
    PurchaseOrderDetailView,
    PurchaseOrderUpdateView,
    PurchaseOrderDeleteView,
    purchase_order_receive,
)

urlpatterns += [
    # Parked ("held") bills: park the current cart and recall it later.
    path('orders/holds/',                  OrderHoldView.as_view(),        name='order_holds'),
    path('orders/holds/<int:pk>/recall/',  OrderHoldRecallView.as_view(),  name='order_hold_recall'),
    path('orders/holds/<int:pk>/delete/',  OrderHoldDeleteView.as_view(),  name='order_hold_delete'),
]

urlpatterns += [
    # Purchase Orders CRUD
    path('purchase-orders/', PurchaseOrderListView.as_view(), name='purchase_order_list'),
    path('purchase-orders/create/', PurchaseOrderCreateView.as_view(), name='purchase_order_create'),
    path('purchase-orders/<int:pk>/', PurchaseOrderDetailView.as_view(), name='purchase_order_detail'),
    path('purchase-orders/<int:pk>/edit/', PurchaseOrderUpdateView.as_view(), name='purchase_order_edit'),
    path('purchase-orders/<int:pk>/delete/', PurchaseOrderDeleteView.as_view(), name='purchase_order_delete'),
    # mark received
    path('purchase-orders/<int:pk>/receive/', purchase_order_receive, name='purchase_order_receive'),
]

from .views import CostReportView

urlpatterns += [
    # …
    path('cost-report/', CostReportView.as_view(), name='cost_report'),
]

from .views import (
    RecipeListView,
    RecipeCreateView, RecipeDetailView,
    RecipeUpdateView, RecipeDeleteView,
)

urlpatterns += [
    # Recipes CRUD
    path('recipes/',         RecipeListView.as_view(),   name='recipe_list'),
    path('recipes/create/',  RecipeCreateView.as_view(), name='recipe_create'),
    path('recipes/<int:pk>/',RecipeDetailView.as_view(), name='recipe_detail'),
    path('recipes/<int:pk>/edit/',  RecipeUpdateView.as_view(), name='recipe_edit'),
    path('recipes/<int:pk>/delete/',RecipeDeleteView.as_view(), name='recipe_delete'),
]

from .views import (
    TaxRateListView, TaxRateCreateView, TaxRateUpdateView, TaxRateDeleteView,
    ModifierGroupListView, ModifierGroupCreateView,
    ModifierGroupUpdateView, ModifierGroupDeleteView,
)

urlpatterns += [
    # Taxes CRUD
    path('taxes/',                   TaxRateListView.as_view(),   name='taxrate_list'),
    path('taxes/create/',            TaxRateCreateView.as_view(), name='taxrate_create'),
    path('taxes/<int:pk>/edit/',     TaxRateUpdateView.as_view(), name='taxrate_edit'),
    path('taxes/<int:pk>/delete/',   TaxRateDeleteView.as_view(), name='taxrate_delete'),

    # Modifier groups CRUD (options are edited inline on the form page)
    path('modifiers/',                   ModifierGroupListView.as_view(),   name='modifiergroup_list'),
    path('modifiers/create/',            ModifierGroupCreateView.as_view(), name='modifiergroup_create'),
    path('modifiers/<int:pk>/edit/',     ModifierGroupUpdateView.as_view(), name='modifiergroup_edit'),
    path('modifiers/<int:pk>/delete/',   ModifierGroupDeleteView.as_view(), name='modifiergroup_delete'),
]


from django.urls import path
from .views import (
    WaiterListView, WaiterCreateView, WaiterDetailView,
    WaiterUpdateView, WaiterDeleteView, debug_costs
    # … your other imports …
)

urlpatterns += [
    # … your existing patterns …

    # Waiters
    path('waiters/', WaiterListView.as_view(),     name='waiter_list'),
    path('waiters/create/', WaiterCreateView.as_view(), name='waiter_create'),
    path('waiters/<int:pk>/', WaiterDetailView.as_view(), name='waiter_detail'),
    path('waiters/<int:pk>/edit/',  WaiterUpdateView.as_view(), name='waiter_edit'),
    path('waiters/<int:pk>/delete/',WaiterDeleteView.as_view(), name='waiter_delete'),

    path('debug-cost/', debug_costs, name='debug_costs'),
]


from .views import (
    TableSessionView, TableItemsView,
    ClearTableItemsView, TablePrintTokenView, OrderReprintView,TableSessionSwitchView
)
urlpatterns += [
    path('tables/<int:table_id>/session/', TableSessionView.as_view(), name='table_session'),
    path('tables/<int:table_id>/items/', TableItemsView.as_view(), name='table_items'),
    path('tables/<int:table_id>/items/clear/', ClearTableItemsView.as_view(), name='clear_table_items'),
    path('tables/<int:table_id>/print-token/', TablePrintTokenView.as_view(), name='print_token'),
    path('orders/<int:pk>/reprint/', OrderReprintView.as_view(), name='order_reprint'),
    path('tables/switch/', TableSessionSwitchView.as_view(), name='table_session_switch'),
]

from .bank_account import (
    BankAccountListView, BankAccountCreateView, BankAccountUpdateView, BankAccountDeleteView,
    BankMovementListView, BankMovementCreateView, BankMovementUpdateView, BankMovementDeleteView,
)

urlpatterns += [
    # Bank Accounts
    path('bank-accounts/', BankAccountListView.as_view(), name='bankaccount_list'),
    path('bank-accounts/create/', BankAccountCreateView.as_view(), name='bankaccount_create'),
    path('bank-accounts/<int:pk>/edit/', BankAccountUpdateView.as_view(), name='bankaccount_update'),
    path('bank-accounts/<int:pk>/delete/', BankAccountDeleteView.as_view(), name='bankaccount_delete'),

    # Bank Movements
    path('bank-movements/', BankMovementListView.as_view(), name='bankmovement_list'),
    path('bank-movements/create/', BankMovementCreateView.as_view(), name='bankmovement_create'),
    path('bank-movements/<int:pk>/edit/', BankMovementUpdateView.as_view(), name='bankmovement_update'),
    path('bank-movements/<int:pk>/delete/', BankMovementDeleteView.as_view(), name='bankmovement_delete'),
]

# urls.py
from .staff_management import *

urlpatterns += [
    path('staff/', StaffListView.as_view(), name='staff_list'),
    path('staff/create/', StaffCreateView.as_view(), name='staff_create'),
    path('staff/<int:pk>/edit/', StaffUpdateView.as_view(), name='staff_edit'),
    path('staff/<int:pk>/delete/', StaffDeleteView.as_view(), name='staff_delete'),
]


# core/urls.py (or project's urls.py where others are included)
from django.urls import path
from .expenses import (
    ExpenseListView, ExpenseCreateView, ExpenseUpdateView, ExpenseDeleteView
)

urlpatterns += [
    path('expenses/', ExpenseListView.as_view(), name='expense_list'),
    path('expenses/create/', ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/edit/', ExpenseUpdateView.as_view(), name='expense_update'),
    path('expenses/<int:pk>/delete/', ExpenseDeleteView.as_view(), name='expense_delete'),
]


from .views import supplier_balance_json

urlpatterns += [
    path('api/supplier-balance/', supplier_balance_json, name='supplier_balance_json'),
]


# core/urls.py
from django.urls import path
from .ledger import (
    LedgerHomeView,
    SupplierLedgerView,
    StaffLedgerView,
    RawMaterialLedgerView,
    CustomerLedgerView
)

urlpatterns += [
    path('ledger/', LedgerHomeView.as_view(), name='ledger_home'),
    path('ledger/supplier/<int:pk>/', SupplierLedgerView.as_view(), name='ledger_supplier'),
    path('ledger/staff/<int:pk>/', StaffLedgerView.as_view(), name='ledger_staff'),
    path('ledger/customer/<int:pk>/', CustomerLedgerView.as_view(), name='ledger_customer'),
]

from core.kitchen import (
    KitchenVoucherListView, KitchenVoucherCreateView, KitchenVoucherUpdateView, KitchenVoucherDeleteView,
    KitchenStockSummaryView
)

urlpatterns += [
    path('kitchen/vouchers/', KitchenVoucherListView.as_view(), name='kitchen_voucher_list'),
    path('kitchen/vouchers/new/', KitchenVoucherCreateView.as_view(), name='kitchen_voucher_create'),
    path('kitchen/vouchers/<int:pk>/edit/', KitchenVoucherUpdateView.as_view(), name='kitchen_voucher_update'),
    path('kitchen/vouchers/<int:pk>/delete/', KitchenVoucherDeleteView.as_view(), name='kitchen_voucher_delete'),

    path('kitchen/stock/', KitchenStockSummaryView.as_view(), name='kitchen_stock_summary'),
]


urlpatterns += [
    path('ledger/raw-material/<int:pk>/', RawMaterialLedgerView.as_view(), name='raw_material_ledger'),
]

from core.reports import ReportsOverviewView, api_sales_report

urlpatterns += [
    path('reports/', ReportsOverviewView.as_view(), name='reports'),
    path('api/sales-report/', api_sales_report, name='api_sales_report'),
]

from .views import (
    ConfigurationView, 
    PrintStationCreateView, 
    PrintStationUpdateView, 
    PrintStationDeleteView
)

urlpatterns += [
    path('settings/', ConfigurationView.as_view(), name='configuration'),
    
    # Print Station Routes
    path('settings/station/add/', PrintStationCreateView.as_view(), name='station_create'),
    path('settings/station/<int:pk>/edit/', PrintStationUpdateView.as_view(), name='station_edit'),
    path('settings/station/<int:pk>/delete/', PrintStationDeleteView.as_view(), name='station_delete'),
]

from .views import (
    CustomerListView, CustomerCreateView, 
    CustomerUpdateView, CustomerDeleteView
)

urlpatterns += [
    # Customers CRUD
    path('customers/', CustomerListView.as_view(), name='customer_list'),
    path('customers/create/', CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<int:pk>/edit/', CustomerUpdateView.as_view(), name='customer_edit'),
    path('customers/<int:pk>/delete/', CustomerDeleteView.as_view(), name='customer_delete'),
]

from .views import (
    PaymentReceivedListView, PaymentReceivedCreateView, 
    PaymentReceivedUpdateView, PaymentReceivedDeleteView
)

urlpatterns += [
    path('payments-in/', PaymentReceivedListView.as_view(), name='payment_received_list'),
    path('payments-in/new/', PaymentReceivedCreateView.as_view(), name='payment_received_create'),
    path('payments-in/<int:pk>/edit/', PaymentReceivedUpdateView.as_view(), name='payment_received_edit'),
    path('payments-in/<int:pk>/delete/', PaymentReceivedDeleteView.as_view(), name='payment_received_delete'),
]

from .views import MarketListView

urlpatterns += [
    path('kitchen/market-list/', MarketListView.as_view(), name='market_list_print'),
    # Legacy alias: older links / tests reverse 'market_list'.
    path('kitchen/market-list/', MarketListView.as_view(), name='market_list'),
]

# Legacy aliases for renamed routes: 'reports' was previously
# 'overview_report' and 'kitchen_stock_summary' was 'stock_summary'.
# Keeping the old names means old bookmarks, dashboard links and the
# URL audit (u.out) keep resolving while the sidebar uses the new names.
urlpatterns += [
    path('reports/', ReportsOverviewView.as_view(), name='overview_report'),
    path('kitchen/stock/', KitchenStockSummaryView.as_view(), name='stock_summary'),
]