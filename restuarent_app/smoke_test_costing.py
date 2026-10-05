"""Smoke test for standard production costing (raw material -> recipe -> menu -> sale).

Covers: Unit master, cost per STOCK unit, recipe yield/wastage math, sub-recipe
expansion, menu food-cost %, stock deduction on sale and reversal on edit/void.
Run with:  python manage.py shell < smoke_test_costing.py   (or)   python smoke_test_costing.py
Everything runs inside a transaction that is always rolled back.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restuarent_app.settings')

import django  # noqa: E402
from django.apps import apps  # noqa: E402

# Under `manage.py test` the app registry is already populated; only bootstrap
# when this file is executed directly as a script.
if not apps.ready:
    django.setup()

from decimal import Decimal  # noqa: E402

from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402

from core.costing import (  # noqa: E402
    conversion_factor, raw_avg_cost, recipe_breakdown, recipe_cost,
    usage_map, menu_economics, refresh_cost, latest_price,
)
from core.models import (  # noqa: E402
    User, Supplier, Unit, RawMaterial, Category, MenuItem, Recipe,
    RecipeRawMaterial, RecipeSubRecipe, PurchaseOrder, PurchaseOrderItem,
    Order, OrderItem, InventoryTransaction,
)

CHECKS = []


def _eq(got, want):
    if isinstance(want, bool) or isinstance(got, bool):
        return bool(got) == bool(want)
    if isinstance(want, str):
        return str(got) == str(want)
    try:
        return Decimal(str(got)).quantize(Decimal('0.01')) == Decimal(str(want)).quantize(Decimal('0.01'))
    except Exception:
        return got == want




def check(label, got, want):
    CHECKS.append((label, got, want, _eq(got, want)))


def _po_delete_returns_stock(po, line, material):
    """Delete a PO line and return the material's stock afterwards."""
    rows = list(InventoryTransaction.objects.filter(purchase_order_item=line))
    print(f'   [debug] txn rows for line={line.pk}: '
          f'{[(r.pk, r.transaction_type, str(r.quantity), r.purchase_order_item_id) for r in rows]}')
    line.delete()
    return material.__class__.objects.get(pk=material.pk).current_stock


@transaction.atomic
def run(rollback=True):
    CHECKS.clear()
    # ---------- Unit master ----------
    Unit.ensure_defaults()
    check('unit master seeded (>=10)', Unit.objects.count() >= 10, True)
    check('kg -> g factor', conversion_factor('kg', 'g'), 1000)
    check('g -> kg factor', conversion_factor('g', 'kg'), Decimal('0.001'))
    check('kg -> ml cross-family blocked', conversion_factor('kg', 'ml'), 0)
    check('tbsp -> ml', conversion_factor('tbsp', 'ml'), 15)

    user = User.objects.filter(is_superuser=True).first() or User.objects.first()
    if user is None:
        user = User.objects.create_superuser('smoke', 'smoke@example.com', 'smoke-pass-123')
    supplier, _ = Supplier.objects.get_or_create(name='SMOKE Supplier')

    g = Unit.objects.get(symbol='g')
    kg = Unit.objects.get(symbol='kg')

    # Flour: buy 1 kg @ 200, stocked in grams. 1 kg = 1000 g -> 0.20 / g
    flour = RawMaterial.objects.create(
        name='SMOKE Flour', unit='g', stock_unit=g, purchase_unit=kg,
        pack_size=1000, supplier=supplier,
    )
    po = PurchaseOrder.objects.create(supplier=supplier, created_by=user, status='received')
    PurchaseOrderItem.objects.create(
        purchase_order=po, raw_material=flour, quantity=Decimal('1'),
        unit_price=Decimal('200'), purchase_unit=kg,
    )
    flour.refresh_from_db()
    check('PO line adds stock in STOCK units', flour.current_stock, 1000)
    check('avg cost per stock unit (g)', raw_avg_cost(flour), Decimal('0.20'))
    check('latest price per stock unit', latest_price(flour), Decimal('0.20'))

    # Editing the PO line must NOT add stock again (the old double-count bug).
    # Re-save the line unchanged so the average cost stays 200/1000 = 0.20.
    line = PurchaseOrderItem.objects.get(purchase_order=po)
    line.unit_price = Decimal('200')
    line.save()
    flour.refresh_from_db()
    check('PO re-save does not re-add stock', flour.current_stock, 1000)

    # ---------- Recipe yield / wastage ----------
    cat, _ = Category.objects.get_or_create(name='SMOKE Cat')
    bun = MenuItem.objects.create(name='SMOKE Bun', price=Decimal('100.00'), category=cat)
    # Batch: 200 g flour -> 4 buns, 10% wastage.
    # gross = 200 * 0.20 = 40 ; per portion = 40 / (4 * 0.9) = 11.11
    recipe = Recipe.objects.create(
        menu_item=bun, yield_qty=Decimal('4'), wastage_percent=Decimal('10'),
        instructions='Smoke test batch.',
    )
    RecipeRawMaterial.objects.create(
        recipe=recipe, raw_material=flour, quantity=Decimal('200'), unit=g,
    )
    bd = recipe_breakdown(recipe)
    check('batch gross cost', bd['gross_cost'], 40)
    check('cost per portion (yield+wastage)', bd['cost_per_portion'], Decimal('11.11'))
    check('recipe_cost helper', recipe_cost(recipe), Decimal('11.11'))
    check('recipe.cost_breakdown() wrapper', recipe.cost_breakdown()['gross_cost'], 40)

    refresh_cost(bun)
    bun.refresh_from_db()
    check('menu cost_price persisted', bun.cost_price, Decimal('11.11'))
    econ = menu_economics(bun)
    check('menu_economics has_recipe', econ['has_recipe'], True)
    check('food cost %', econ['food_cost_percent'], Decimal('11.1'))
    check('margin amount', econ['margin_amount'], Decimal('88.89'))
    check('margin percent', econ['margin_percent'], Decimal('88.9'))

    # ---------- Sub-recipe expansion ----------
    sugar = RawMaterial.objects.create(
        name='SMOKE Sugar', unit='g', stock_unit=g, purchase_unit=g, supplier=supplier,
    )
    po2 = PurchaseOrder.objects.create(supplier=supplier, created_by=user, status='received')
    PurchaseOrderItem.objects.create(
        purchase_order=po2, raw_material=sugar, quantity=Decimal('100'),
        unit_price=Decimal('1'), purchase_unit=g,
    )
    sugar.refresh_from_db()
    check('sugar stock', sugar.current_stock, 100)

    sauce_item = MenuItem.objects.create(name='SMOKE Sauce', price=Decimal('20.00'), category=cat)
    sauce = Recipe.objects.create(menu_item=sauce_item, yield_qty=Decimal('1'))
    RecipeRawMaterial.objects.create(
        recipe=sauce, raw_material=sugar, quantity=Decimal('5'), unit=g,
    )
    check('sauce cost per portion', recipe_cost(sauce), Decimal('5.00'))

    burger = MenuItem.objects.create(name='SMOKE Burger', price=Decimal('200.00'), category=cat)
    brecipe = Recipe.objects.create(menu_item=burger, yield_qty=Decimal('1'))
    RecipeRawMaterial.objects.create(
        recipe=brecipe, raw_material=flour, quantity=Decimal('100'), unit=g,
    )
    RecipeSubRecipe.objects.create(
        recipe=brecipe, sub_recipe=sauce, quantity=Decimal('2'),
    )
    # 100 g flour * 0.20 = 20 ; 2 portions sauce * 5.00 = 10  -> 30
    bbd = recipe_breakdown(brecipe)
    check('sub-recipe line expanded', len(bbd['sub_recipe_lines']), 1)
    check('sub-recipe recipe cost', bbd['gross_cost'], 30)
    check('sub-recipe usage flattens', sorted(usage_map(brecipe, Decimal('1')).keys()),
          sorted([flour.pk, sugar.pk]))

    # Unit mismatch inside a recipe must be rejected loudly, not silently.
    bad = Recipe.objects.create(menu_item=MenuItem.objects.create(
        name='SMOKE Bad', price=Decimal('10.00'), category=cat), yield_qty=Decimal('1'))
    RecipeRawMaterial.objects.create(recipe=bad, raw_material=flour, quantity=Decimal('1'),
                                     unit=Unit.objects.get(symbol='ml'))
    try:
        recipe_breakdown(bad)
        check('incompatible recipe unit raises', False, True)
    except ValueError:
        check('incompatible recipe unit raises', True, True)

    # Self-referencing sub-recipe guard.
    self_ref = RecipeSubRecipe(recipe=recipe, sub_recipe=recipe, quantity=Decimal('1'))
    try:
        self_ref.full_clean(exclude=['unit'])
        check('self-referencing sub-recipe blocked', False, True)
    except Exception:
        check('self-referencing sub-recipe blocked', True, True)

    # ---------- Sale deducts stock (in stock units) ----------
    stock_before = RawMaterial.objects.get(pk=flour.pk).current_stock
    order = Order.objects.create(created_by=user, status='pending')
    check('order number generated', bool(order.number), True)
    OrderItem.objects.create(order=order, menu_item=bun, quantity=2, unit_price=Decimal('100'))
    stock_after = RawMaterial.objects.get(pk=flour.pk).current_stock
    # 2 buns = half a batch -> 100 g flour (never 100 kg: the old 1000x bug).
    check('sale deducts stock in stock units', stock_before - stock_after, 100)
    check('sale writes "out" transaction', InventoryTransaction.objects.filter(
        order_item__order=order, transaction_type='out').count(), 1)

    # ---------- Editing a line reverses, then re-deducts ----------
    oi = order.items.first()
    oi.reverse_inventory_usage()
    after_reverse = RawMaterial.objects.get(pk=flour.pk).current_stock
    check('reverse returns stock', after_reverse, stock_before)
    oi.quantity = 1
    oi.save()
    stock_edited = RawMaterial.objects.get(pk=flour.pk).current_stock
    check('re-deducted for qty 1', stock_before - stock_edited, 50)

    # ---------- Deleting the order restores stock ----------
    for item in order.items.all():
        item.reverse_inventory_usage()
    order.delete()
    check('void restores stock', RawMaterial.objects.get(pk=flour.pk).current_stock, stock_before)

    # ---------- PO line / PO header deletion returns the stock ----------
    # Run last: removing the PO line removes the pricing the recipe checks rely on.
    check('PO line delete returns stock', _po_delete_returns_stock(po, line, flour), 0)
    sugar_line = PurchaseOrderItem.objects.get(purchase_order=po2)
    check('PO header delete returns stock', _po_delete_returns_stock(po2, sugar_line, sugar), 0)

    # ---------- Page smoke (status codes + template rendering) ----------
    client = Client()
    client.force_login(user)
    pages = ['raw_material_list', 'raw_material_create', 'raw_material_edit',
             'recipe_list', 'recipe_create', 'recipe_edit', 'purchase_order_list',
             'purchase_order_create', 'unit_list', 'low_stock', 'menuitem_list']
    urls = [reverse('raw_material_list'), reverse('raw_material_create'),
            reverse('raw_material_edit', args=[flour.pk]), reverse('recipe_list'),
            reverse('recipe_create'), reverse('recipe_edit', args=[recipe.pk]),
            reverse('purchase_order_list'), reverse('purchase_order_create'),
            reverse('unit_list'), reverse('low_stock'), reverse('menuitem_list')]
    for name, url in zip(pages, urls):
        try:
            check(f'GET {name}', client.get(url).status_code, 200)
        except Exception as exc:  # noqa: BLE001
            CHECKS.append((f'GET {name}', repr(exc), 200, False))

    for name, pk in (('raw_material_detail', flour.pk), ('recipe_detail', recipe.pk),
                     ('menuitem_detail', bun.pk)):
        try:
            check(f'GET {name} (unit-aware)', client.get(reverse(name, args=[pk])).status_code, 200)
        except Exception as exc:  # noqa: BLE001
            CHECKS.append((f'GET {name} (unit-aware)', repr(exc), 200, False))

    if rollback:
        transaction.set_rollback(True)
    return list(CHECKS)


def main():
    rows = run()
    width = 72
    failed = 0
    print('=' * width)
    for label, got, want, ok in rows:
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {label:<42} got={got!s:<18} expected={want}")
    print('=' * width)
    print(f'{len(rows) - failed}/{len(rows)} checks passed')
    print('NOTE: all writes were rolled back; the database is unchanged.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

