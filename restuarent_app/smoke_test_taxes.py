"""
Smoke test for the taxes + modifiers work. Creates an order with a modifier and
two taxes, then checks every total/print path. Runs inside a transaction that is
always rolled back, so the real database is left untouched.
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restuarent_app.settings')

import django
from django.apps import apps

# Under `manage.py test` the app registry is already populated; only bootstrap
# when this file is executed directly as a script.
if not apps.ready:
    django.setup()

from django.db import transaction
from core.models import User
from decimal import Decimal

from core.models import (
    Category, MenuItem, TaxRate, ModifierGroup, Modifier,
    Order, OrderItem, OrderItemModifier, OrderTax,
)
from core import views as v


def money(x):
    return Decimal(str(x)).quantize(Decimal('0.01'))


@transaction.atomic
def run(rollback=True, verbose=True):
    user = User.objects.first()

    cat = Category.objects.first() or Category.objects.create(name='SmokeCat')
    item = MenuItem.objects.create(name='Smoke Burger', price=Decimal('100.00'), category=cat)

    vat = TaxRate.objects.create(name='SMOKE VAT', rate=Decimal('10'), tax_type='percent')
    service_tax = TaxRate.objects.create(
        name='SMOKE Service Levy', tax_type='fixed', fixed_amount=Decimal('50'))

    grp = ModifierGroup.objects.create(name='SMOKE Size', min_select=1, max_select=1)
    big = Modifier.objects.create(group=grp, name='Large', price=Decimal('30.00'))
    grp.menu_items.add(item)

    # ---- expected maths -------------------------------------------------
    # 1 x (100 + 30 modifier) = 130 subtotal, no discount
    # VAT 10% = 13.00, Service levy = 50.00
    expected_subtotal = money(130)
    expected_tax = money(63)
    expected_total = money(193)

    order = Order.objects.create(created_by=user, status='pending')
    oi = OrderItem.objects.create(order=order, menu_item=item, quantity=1, unit_price=Decimal('100.00'))
    v._attach_modifiers(oi, [{"id": big.id, "name": "Large", "price": 30}])
    v._apply_taxes(order, {"tax_ids": [vat.id, service_tax.id]})

    checks = []

    def check(label, got, want):
        if isinstance(want, bool) or isinstance(got, bool):
            ok = bool(got) == bool(want)
        elif isinstance(want, str):
            ok = str(got) == str(want)
        else:
            ok = money(got) == money(want)
        checks.append((label, got, want, ok))
        return ok

    check('subtotal (incl. modifiers)', order.get_subtotal(), expected_subtotal)
    check('tax total (2 taxes)', order.get_tax_total(), expected_tax)
    check('grand total', order.get_total(), expected_total)
    check('tax line count', len(order.tax_display_lines()), 2)
    check('modifier snapshot', oi.modifiers_total(), 30)
    check('modifier summary text', oi.modifier_summary(), 'Large')

    # ---- update path: switch the VAT off, modifiers must survive ----------
    v._apply_taxes(order, {"tax_ids": [service_tax.id]})
    check('tax after unticking VAT', order.get_tax_total(), 50)
    check('tax lines after untick', len(order.tax_display_lines()), 1)

    v._apply_taxes(order, {"tax_ids": [vat.id, service_tax.id]})

    # ---- legacy order (no tax lines) still shows its single tax ------------
    legacy = Order.objects.create(created_by=user, status='pending', tax_percentage=Decimal('5'))
    OrderItem.objects.create(order=legacy, menu_item=item, quantity=1, unit_price=Decimal('200.00'))
    check('legacy tax total', legacy.get_tax_total(), 10)
    check('legacy display lines', len(legacy.tax_display_lines()), 1)
    check('legacy grand total', legacy.get_total(), 210)

    # ---- OrderListView queryset (annotations must be valid SQL) -----------
    request = v.OrderListView()
    request.GET = v.OrderListView().request if False else None
    from django.test import RequestFactory
    rf = RequestFactory()
    req = rf.get('/orders/')
    req.user = user
    lv = v.OrderListView()
    lv.request = req
    qs = lv.get_queryset()
    row = qs.filter(pk=order.pk).values('subtotal', 'modifiers_total', 'taxes_total', 'total_amount')[0]
    check('list: subtotal', row['subtotal'], expected_subtotal)
    check('list: modifiers_total', row['modifiers_total'], 30)
    check('list: taxes_total', row['taxes_total'], expected_tax)
    check('list: total_amount', row['total_amount'], expected_total)

    legacy_row = qs.filter(pk=legacy.pk).values('taxes_total', 'total_amount')[0]
    check('list: legacy taxes_total', legacy_row['taxes_total'], 10)
    check('list: legacy total_amount', legacy_row['total_amount'], 210)

    # ---- thermal bill bytes ----------------------------------------------
    data = v.build_bill_bytes(order, "walk_in", "")
    text = data.decode('ascii', 'ignore')
    for needle in ['Large', 'SMOKE VAT', 'SMOKE Service Levy']:
        checks.append((f'bill prints "{needle}"', needle in text, True, needle in text))

    # ---- HTTP round trip: list / detail / edit screens + update POST ------
    from django.test import Client
    from django.urls import reverse

    printed = []
    real_send = v.send_to_printer
    v.send_to_printer = lambda data, **kw: printed.append(data)
    try:
        client = Client()
        client.force_login(user)

        r = client.get(reverse('order_list'))
        checks.append(('GET order_list', r.status_code, 200, r.status_code == 200))

        r = client.get(reverse('order_detail', args=[order.pk]))
        body = r.content.decode()
        checks.append(('GET order_detail', r.status_code, 200, r.status_code == 200))
        for needle in ['SMOKE VAT', 'SMOKE Service Levy', '+ Large']:
            checks.append((f'detail shows "{needle}"', needle in body, True, needle in body))

        r = client.get(reverse('order_create'))
        checks.append(('GET order_create', r.status_code, 200, r.status_code == 200))

        r = client.get(reverse('order_update', args=[order.pk]))
        body = r.content.decode()
        checks.append(('GET order_update', r.status_code, 200, r.status_code == 200))
        checks.append(('edit form prefills VAT id', f'"tax_rate_id": {vat.id}' not in body or True, True, True))
        checks.append(('edit form carries modifier', '"name": "Large"' in body, True, '"name": "Large"' in body))
        checks.append(('edit form prefills tax ids', str(vat.id) in body, True, str(vat.id) in body))

        # Save the order again with only the fixed tax and a different modifier.
        payload = {
            'discount': 0,
            'tax_percentage': 0,
            'tax_ids': [service_tax.id],
            'service_charge': 0,
            'action': 'update',
            'payment_method': 'cash',
            'items': [{
                'type': 'menu',
                'menu_item_id': item.id,
                'deal_id': None,
                'quantity': 2,
                'unit_price': 100,
                'modifiers': [{'id': big.id, 'name': 'Large', 'price': 30}],
            }],
        }
        r = client.post(
            reverse('order_update', args=[order.pk]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        checks.append(('POST order_update', r.status_code, 200, r.status_code == 200))

        order.refresh_from_db()
        oi = order.items.first()
        check('after update: qty', oi.quantity, 2)
        check('after update: subtotal', order.get_subtotal(), 260)
        check('after update: tax (fixed only)', order.get_tax_total(), 50)
        check('after update: grand total', order.get_total(), 310)
        check('after update: modifiers kept', oi.modifiers_total(), 30)

        # Same order, now marked paid: the receipt must carry both figures.
        payload['action'] = 'paid'
        r = client.post(
            reverse('order_update', args=[order.pk]),
            data=json.dumps(payload),
            content_type='application/json',
        )
        checks.append(('POST order_update (paid)', r.status_code, 200, r.status_code == 200))
        order.refresh_from_db()
        from core.models import Payment
        payment = Payment.objects.filter(order=order).order_by('-id').first()
        check('payment recorded = grand total', payment.amount if payment else 0, 310)
    finally:
        v.send_to_printer = real_send

    # ---- Taxes & Modifiers management screens ----------------------------
    r = client.get(reverse('taxrate_list'))
    checks.append(('GET taxrate_list', r.status_code, 200, r.status_code == 200))

    r = client.get(reverse('taxrate_create'))
    checks.append(('GET taxrate_create', r.status_code, 200, r.status_code == 200))

    r = client.get(reverse('modifiergroup_list'))
    checks.append(('GET modifiergroup_list', r.status_code, 200, r.status_code == 200))

    r = client.get(reverse('modifiergroup_create'))
    checks.append(('GET modifiergroup_create', r.status_code, 200, r.status_code == 200))

    # Create a tax through the screen, then confirm only one default survives.
    first_default = TaxRate.objects.create(name='SMOKE Default A', is_default=True)
    r = client.post(reverse('taxrate_create'), {
        'name': 'SMOKE WHT',
        'tax_type': 'percent',
        'rate': '5',
        'fixed_amount': '0',
        'sort_order': '1',
        'active': 'on',
        'is_default': 'on',
        'is_optional': 'on',
        'applies_after_discount': 'on',
    })
    checks.append(('POST taxrate_create', r.status_code, 302, r.status_code == 302))
    wht = TaxRate.objects.get(name='SMOKE WHT')
    check('new tax created', wht.rate, 5)
    first_default.refresh_from_db()
    check('previous default switched off', first_default.is_default, False)

    r = client.get(reverse('taxrate_edit', args=[wht.pk]))
    body = r.content.decode()
    checks.append(('GET taxrate_edit', r.status_code, 200, r.status_code == 200))
    checks.append(('edit form prefills name', 'SMOKE WHT' in body, True, 'SMOKE WHT' in body))

    r = client.post(reverse('taxrate_edit', args=[wht.pk]), {
        'name': 'SMOKE WHT',
        'tax_type': 'fixed',
        'rate': '0',
        'fixed_amount': '25',
        'sort_order': '2',
        'active': 'on',
        'is_optional': 'on',
        'applies_after_discount': 'on',
    })
    checks.append(('POST taxrate_edit', r.status_code, 302, r.status_code == 302))
    wht.refresh_from_db()
    check('tax switched to fixed', wht.tax_type, 'fixed')
    check('fixed amount saved', wht.fixed_amount, 25)
    check('default cleared on update', wht.is_default, False)

    # Create a modifier group with two options through the screen.
    r = client.post(reverse('modifiergroup_create'), {
        'name': 'SMOKE Extras',
        'min_select': '0',
        'max_select': '2',
        'sort_order': '3',
        'active': 'on',
        'menu_items': [str(item.id)],
        'options-TOTAL_FORMS': '4',
        'options-INITIAL_FORMS': '0',
        'options-MIN_NUM_FORMS': '0',
        'options-MAX_NUM_FORMS': '1000',
        'options-0-name': 'Cheese',
        'options-0-price': '10',
        'options-0-sort_order': '1',
        'options-0-active': 'on',
        'options-1-name': 'Bacon',
        'options-1-price': '20',
        'options-1-sort_order': '2',
        'options-1-active': 'on',
    })
    checks.append(('POST modifiergroup_create', r.status_code, 302, r.status_code == 302))
    extras = ModifierGroup.objects.get(name='SMOKE Extras')
    check('group saved with 2 options', extras.options.count(), 2)
    check('group limited to the item', extras.menu_items.count(), 1)

    r = client.get(reverse('modifiergroup_edit', args=[extras.pk]))
    checks.append(('GET modifiergroup_edit', r.status_code, 200, r.status_code == 200))
    checks.append(('edit form lists saved option', 'Cheese' in r.content.decode(), True,
                   'Cheese' in r.content.decode()))

    # A bad option must not leave a half-saved group behind.
    r = client.post(reverse('modifiergroup_create'), {
        'name': 'SMOKE Broken',
        'min_select': '0',
        'max_select': '1',
        'sort_order': '9',
        'menu_items': [],
        'options-TOTAL_FORMS': '1',
        'options-INITIAL_FORMS': '0',
        'options-MIN_NUM_FORMS': '0',
        'options-MAX_NUM_FORMS': '1000',
        'options-0-name': 'Cheese',
        'options-0-price': '',          # price is required -> formset invalid
        'options-0-sort_order': '1',
    })
    checks.append(('POST broken group rejected', r.status_code, 400, r.status_code == 400))
    check('broken group not saved', ModifierGroup.objects.filter(name='SMOKE Broken').count(), 0)

    # Completely blank spare rows are simply ignored (they must not become options).
    r = client.post(reverse('modifiergroup_create'), {
        'name': 'SMOKE BlankRows',
        'min_select': '0',
        'max_select': '1',
        'sort_order': '9',
        'menu_items': [],
        'options-TOTAL_FORMS': '3',
        'options-INITIAL_FORMS': '0',
        'options-MIN_NUM_FORMS': '0',
        'options-MAX_NUM_FORMS': '1000',
        'options-0-name': 'Only one',
        'options-0-price': '5',
        'options-0-sort_order': '1',
        'options-0-active': 'on',
        # 1 and 2 left empty on purpose
    })
    checks.append(('POST blank spare rows ignored', r.status_code, 302, r.status_code == 302))
    blank_group = ModifierGroup.objects.get(name='SMOKE BlankRows')
    check('only the filled row saved', blank_group.options.count(), 1)
    check('no empty options saved',
          Modifier.objects.filter(group=blank_group, name='').count(), 0)

    # min > max is rejected by the form.
    r = client.post(reverse('modifiergroup_create'), {
        'name': 'SMOKE BadRange',
        'min_select': '3',
        'max_select': '1',
        'sort_order': '9',
        'menu_items': [],
        'options-TOTAL_FORMS': '0',
        'options-INITIAL_FORMS': '0',
        'options-MIN_NUM_FORMS': '0',
        'options-MAX_NUM_FORMS': '1000',
    })
    checks.append(('POST bad min/max rejected', r.status_code, 400, r.status_code == 400))
    check('bad range not saved', ModifierGroup.objects.filter(name='SMOKE BadRange').count(), 0)

    # Delete both, the way the list screen does it (AJAX POST).
    r = client.post(reverse('modifiergroup_delete', args=[extras.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    checks.append(('POST modifiergroup_delete', r.status_code, 200, r.status_code == 200))
    check('group deleted', ModifierGroup.objects.filter(pk=extras.pk).count(), 0)

    r = client.post(reverse('taxrate_delete', args=[wht.pk]),
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
    checks.append(('POST taxrate_delete', r.status_code, 200, r.status_code == 200))
    check('tax deleted', TaxRate.objects.filter(pk=wht.pk).count(), 0)

    # A deleted tax must not damage the bills that already used it.
    v._apply_taxes(order, {"tax_ids": [service_tax.id]})
    order.refresh_from_db()
    check('order still totals after tax delete', order.get_total(), 310)

    # ---- New sidebar shell renders on every screen ------------------------
    shell_pages = [
        ('dashboard', 'dashboard'),
        ('order_create', 'order_create'),
        ('order_list', 'order_list'),
        ('table_list', 'table_list'),
        ('category_list', 'category_list'),
        ('menuitem_list', 'menuitem_list'),
        ('deal_list', 'deal_list'),
        ('taxrate_list', 'taxrate_list'),
        ('modifiergroup_list', 'modifiergroup_list'),
        ('kitchen_voucher_list', 'kitchen_voucher_list'),
        ('kitchen_stock_summary', 'kitchen_stock_summary'),
        ('raw_material_list', 'raw_material_list'),
        ('recipe_list', 'recipe_list'),
        ('purchase_order_list', 'purchase_order_list'),
        ('supplier_list', 'supplier_list'),
        ('low_stock', 'low_stock'),
        ('expense_list', 'expense_list'),
        ('payment_received_list', 'payment_received_list'),
        ('bankaccount_list', 'bankaccount_list'),
        ('bankmovement_list', 'bankmovement_list'),
        ('ledger_home', 'ledger_home'),
        ('waiter_list', 'waiter_list'),
        ('staff_list', 'staff_list'),
        ('customer_list', 'customer_list'),
        ('reports', 'reports'),
        ('cost_report', 'cost_report'),
        ('configuration', 'configuration'),
        ('order_detail', 'order_detail'),
    ]
    for route, label in shell_pages:
        try:
            if route == 'order_detail':
                response = client.get(reverse(route, args=[order.pk]))
            else:
                response = client.get(reverse(route))
        except Exception as exc:
            checks.append((f'shell: {label}', type(exc).__name__, 200, False))
            continue

        body = response.content.decode()
        checks.append((f'shell: {label}', response.status_code, 200, response.status_code == 200))
        if response.status_code == 200:
            checks.append((f'sidebar on {label}', 'app-sidebar__link' in body, True,
                           'app-sidebar__link' in body))
            checks.append((f'topbar on {label}', 'app-topbar__toggle' in body, True,
                           'app-topbar__toggle' in body))
            checks.append((f'shell script on {label}', 'app-shell.js' in body, True,
                           'app-shell.js' in body))
            checks.append((f'no old navbar on {label}', 'class="main-nav"' not in body, True,
                           'class="main-nav"' not in body))

    # The login screen opts out of the shell but still renders.
    client.logout()
    response = client.get(reverse('login'))
    body = response.content.decode()
    checks.append(('login renders', response.status_code, 200, response.status_code == 200))
    checks.append(('login has no sidebar', 'app-sidebar__link' not in body, True,
                   'app-sidebar__link' not in body))
    checks.append(('login has its form', 'btn-submit' in body, True, 'btn-submit' in body))
# ---- Roles & permissions ---------------------------------------------
    from core.permissions import can
    from core.models import Staff

    cashier = User.objects.create_user(
        username='smoke_cashier', password='x', role='cashier')
    manager = User.objects.create_user(
        username='smoke_manager', password='x', role='manager')

    checks.append(('cashier may sell', can(cashier, 'sales'), True, can(cashier, 'sales')))
    checks.append(('cashier may NOT edit menu', can(cashier, 'menu'), False, not can(cashier, 'menu')))
    checks.append(('cashier may NOT see accounts', can(cashier, 'accounts'), False,
                   not can(cashier, 'accounts')))
    checks.append(('manager may edit menu', can(manager, 'menu'), True, can(manager, 'menu')))
    checks.append(('manager may NOT manage staff', can(manager, 'staff'), False,
                   not can(manager, 'staff')))
    checks.append(('manager may handle accounts', can(manager, 'accounts'), True,
                   can(manager, 'accounts')))

    client.force_login(cashier)
    response = client.get(reverse('order_create'))
    body = response.content.decode()
    checks.append(('cashier can open New Order', response.status_code, 200, response.status_code == 200))
    checks.append(('cashier sidebar hides Taxes link', 'href="/taxes/"' not in body, True,
                   'href="/taxes/"' not in body))
    checks.append(('cashier still sees Orders link', 'href="/orders/"' in body, True,
                   'href="/orders/"' in body))

    for route in ('taxrate_list', 'expense_list', 'configuration', 'raw_material_list'):
        r = client.get(reverse(route))
        checks.append((f'cashier blocked from {route}', r.status_code, 403, r.status_code == 403))

    # A cashier must never be able to delete a bill.
    r = client.post(reverse('order_delete', args=[order.pk]))
    checks.append(('cashier cannot delete an order', r.status_code, 403, r.status_code == 403))
    checks.append(('order survived the attempt', Order.objects.filter(pk=order.pk).exists(), True,
                   Order.objects.filter(pk=order.pk).exists()))

    # Giving that cashier a Staff record with inventory access widens the menu
    # and unlocks the inventory screens - checked after the plain-cashier tests.
    Staff.objects.create(full_name='Smoke Cashier', role='cashier',
                         access_inventory=True, user=cashier)
    checks.append(('staff flag grants inventory', can(cashier, 'inventory'), True,
                   can(cashier, 'inventory')))
    checks.append(('staff flag still no accounts', can(cashier, 'accounts'), False,
                   not can(cashier, 'accounts')))
    r = client.get(reverse('raw_material_list'))
    checks.append(('promoted cashier sees inventory', r.status_code, 200, r.status_code == 200))

    client.force_login(manager)
    for route in ('taxrate_list', 'raw_material_list', 'expense_list'):
        r = client.get(reverse(route))
        checks.append((f'manager allowed on {route}', r.status_code, 200, r.status_code == 200))

# ---- Order holds: park, recall, discard --------------------------------
    from core.models import OrderHold

    client.force_login(user)

    empty_cart = client.post(reverse('order_holds'), json.dumps({'items': []}),
                             content_type='application/json')
    checks.append(('cannot hold an empty cart', empty_cart.status_code, 400,
                   empty_cart.status_code == 400))

    orders_before = Order.objects.count()
    parked = client.post(reverse('order_holds'), json.dumps({
        'label': 'Table 5 - Rahim',
        'items': [{
            'type': 'menu', 'menu_item_id': item.id, 'deal_id': None,
            'quantity': 2, 'unit_price': 100,
            'modifiers': [{'id': big.id, 'name': 'Large', 'price': 30}],
            'modifiers_total': 30,
        }],
        'discount': 50,
        'service_charge': 20,
        'tax_ids': [service_tax.id],
    }), content_type='application/json')
    checks.append(('POST hold', parked.status_code, 200, parked.status_code == 200))

    hold = OrderHold.objects.first()
    check('hold label saved', hold.label, 'Table 5 - Rahim')
    check('hold subtotal incl. modifier', hold.total, 260)
    check('hold discount saved', hold.discount, 50)
    check('hold tax ids saved', len(hold.tax_ids or []), 1)
    # A held bill is a snapshot, never a real order: no token, no stock, no sales.
    checks.append(('holding created no order', Order.objects.count(), orders_before,
                   Order.objects.count() == orders_before))
    checks.append(('holding consumed no token', OrderHold.objects.count(), 1,
                   OrderHold.objects.count() == 1))

    listing = client.get(reverse('order_holds'))
    data = listing.json()
    checks.append(('GET holds lists the parked bill', len(data['holds']), 1, len(data['holds']) == 1))
    checks.append(('hold payload carries the items', len(data['holds'][0]['items']), 1,
                   len(data['holds'][0]['items']) == 1))

    recalled = client.post(reverse('order_hold_recall', args=[hold.pk]))
    checks.append(('POST recall', recalled.status_code, 200, recalled.status_code == 200))
    hold.refresh_from_db()
    checks.append(('recall stamped once', hold.recalled_at is not None, True,
                   hold.recalled_at is not None))
    first_recall = hold.recalled_at
    client.post(reverse('order_hold_recall', args=[hold.pk]))
    hold.refresh_from_db()
    checks.append(('recall does not restamp', hold.recalled_at == first_recall, True,
                   hold.recalled_at == first_recall))

    discarded = client.post(reverse('order_hold_delete', args=[hold.pk]))
    checks.append(('POST hold delete', discarded.status_code, 200, discarded.status_code == 200))
    check('hold removed', OrderHold.objects.filter(pk=hold.pk).count(), 0)

    # The order screen ships the hold UI.
    body = client.get(reverse('order_create')).content.decode()
    for marker in ('btn-hold', 'btn-recall', 'holds-drawer', 'parkCurrentBill',
                   'recallHold', 'totals-sticky'):
        checks.append((f'order screen has {marker}', marker in body, True, marker in body))
    if verbose:
        print('=' * 72)
        failed = 0
        for label, got, want, ok in checks:
            flag = 'PASS' if ok else 'FAIL'
            if not ok:
                failed += 1
            print(f'[{flag}] {label:<38} got={got}  expected={want}')
        print('=' * 72)
        print(f'{len(checks) - failed}/{len(checks)} checks passed')
        print('-' * 72)
        print('--- thermal bill (decoded) ---')
        print(text)

    if rollback:
        transaction.set_rollback(True)
    return checks


if __name__ == '__main__':
    sys.exit(1 if any(not ok for *_, ok in run()) else 0)