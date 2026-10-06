from django.contrib import admin
from django.contrib import admin
from .models import Unit, RawMaterialUnitConversion


from django.contrib import admin
from .models import (
    POSSettings, PrintStation, TokenSequence, Category, MenuItem,
    TaxRate, OrderTax, ModifierGroup, Modifier, OrderItemModifier,
    RawMaterial, ProductionRun, InventoryTransaction,
)


@admin.register(RawMaterial)
class RawMaterialAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'current_stock', 'reorder_level', 'supplier', 'stock_badge')
    list_filter = ('supplier',)
    search_fields = ('name',)
    ordering = ('name',)

    @admin.display(description='Status')
    def stock_badge(self, obj):
        return {'out': 'OUT OF STOCK', 'low': 'LOW', 'ok': 'OK'}[obj.stock_status]


# ---------- Taxes ----------
@admin.register(TaxRate)
class TaxRateAdmin(admin.ModelAdmin):
    """Create as many taxes as you need (VAT, WHT, Service Levy, ...)."""
    list_display = ('name', 'tax_type', 'rate', 'fixed_amount', 'active', 'is_default', 'is_optional', 'sort_order')
    list_filter = ('active', 'tax_type', 'is_default', 'is_optional')
    search_fields = ('name',)
    ordering = ('sort_order', 'name')
    fieldsets = (
        (None, {'fields': ('name', 'tax_type', 'rate', 'fixed_amount')}),
        ('Behaviour', {'fields': ('active', 'is_default', 'is_optional', 'applies_after_discount', 'sort_order')}),
    )


@admin.register(OrderTax)
class OrderTaxAdmin(admin.ModelAdmin):
    list_display = ('order', 'name', 'tax_type', 'rate', 'amount')
    list_filter = ('tax_type',)
    search_fields = ('name', 'order__number')
    readonly_fields = ('created_at',)


# ---------- Modifiers ----------
class ModifierInline(admin.TabularInline):
    model = Modifier
    extra = 1


@admin.register(ModifierGroup)
class ModifierGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'min_select', 'max_select', 'active', 'sort_order')
    list_filter = ('active',)
    search_fields = ('name',)
    filter_horizontal = ('menu_items',)
    inlines = [ModifierInline]


@admin.register(Modifier)
class ModifierAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'price', 'active', 'sort_order')
    list_filter = ('group', 'active')
    search_fields = ('name', 'group__name')


@admin.register(OrderItemModifier)
class OrderItemModifierAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'order_item')
    search_fields = ('name', 'order_item__order__number')

@admin.register(POSSettings)
class POSSettingsAdmin(admin.ModelAdmin):
    list_display = ('restaurant_name', 'start_of_day_time', 'updated_at')

@admin.register(PrintStation)
class PrintStationAdmin(admin.ModelAdmin):
    list_display = ('name', 'print_separate_slip', 'use_separate_sequence')

@admin.register(TokenSequence)
class TokenSequenceAdmin(admin.ModelAdmin):
    list_display = ('business_date', 'station', 'last')
    list_filter = ('station',)

# Make sure Category and MenuItem admins allow selecting the Station
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'default_station', 'show_in_orders')

@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'station', 'price',
                    'track_finished_stock', 'finished_stock', 'finished_reorder_level')
    list_filter = ('category', 'station', 'track_finished_stock')
    fieldsets = (
        (None, {'fields': ('category', 'name', 'description', 'price',
                           'food_panda_price', 'rank', 'is_available',
                           'image', 'station', 'weight', 'unit')}),
        ('Batch production', {'fields': ('track_finished_stock', 'finished_reorder_level'),
                              'description': 'Finished portions are increased by completed '
                                             'production runs and decreased by sales.'}),
    )


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    list_display = ('id', 'recipe', 'planned_qty', 'produced_qty',
                    'wastage_qty', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('recipe__menu_item__name', 'recipe__name', 'notes')
    ordering = ('-created_at',)
    readonly_fields = ('produced_qty', 'completed_at')


@admin.register(InventoryTransaction)
class InventoryTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'transaction_type', 'raw_material', 'menu_item',
                    'quantity', 'production_run', 'order_item', 'date')
    list_filter = ('transaction_type', 'date')
    search_fields = ('raw_material__name', 'menu_item__name', 'notes')
    ordering = ('-timestamp',)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('symbol','name','unit_type')
    list_filter  = ('unit_type',)
    search_fields = ('symbol','name')

@admin.register(RawMaterialUnitConversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = ('raw_material','unit','to_base_factor')
    list_filter  = ('unit','raw_material')
    search_fields = ('raw_material__name',)


# core/admin.py
from django.contrib import admin
from .models import Expense, CashFlow, BankAccount

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('date','category','amount','created_by')
    list_filter  = ('category','date')

@admin.register(CashFlow)
class CashFlowAdmin(admin.ModelAdmin):
    list_display = ('date','flow_type','amount','bank_account','created_by')
    list_filter  = ('flow_type','bank_account','date')

@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ('name','account_number')

# admin.py
from .models import Staff, Role

admin.site.register(Staff)
admin.site.register(Role)

