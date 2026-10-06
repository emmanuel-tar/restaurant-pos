"""Batch production runs: raw materials in, finished portions out.

Covers the ProductionRun lifecycle behind the "Production Runs" screen:
draft -> complete (deducts raws via costing.produce_portions, credits
MenuItem.finished_stock) -> cancel/delete (reverses both sides row by row),
plus the tracked-item sale path where OrderItem consumes finished portions
instead of exploding the recipe into raw materials.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.costing import check_producible, produce_portions
from core.forms import ProductionCompleteForm, ProductionRunForm
from core.models import (
    Category, InventoryTransaction, MenuItem, ProductionRun,
    PurchaseOrder, PurchaseOrderItem, RawMaterial, Recipe,
    RecipeRawMaterial, Supplier, Unit,
)

User = get_user_model()


class ProductionTestMixin:
    """One tracked menu item with a simple one-material recipe and stock."""

    def make_production_setup(self, stock=Decimal('1000'), price=Decimal('50')):
        Unit.ensure_defaults()
        g = Unit.objects.get(symbol='g')
        supplier = Supplier.objects.create(name='Prod Supplier')
        flour = RawMaterial.objects.create(
            name='Prod Flour', unit='g', stock_unit=g, purchase_unit=g,
            pack_size=1, supplier=supplier,
        )
        user = User.objects.create_superuser('prod-admin', 'p@example.com', 'x')
        po = PurchaseOrder.objects.create(
            supplier=supplier, created_by=user, status='received')
        PurchaseOrderItem.objects.create(
            purchase_order=po, raw_material=flour, quantity=stock,
            unit_price=price, purchase_unit=g,
        )
        flour.refresh_from_db()
        cat = Category.objects.create(name='Prod Cat')
        bun = MenuItem.objects.create(
            name='Prod Bun', price=Decimal('200.00'), category=cat,
            track_finished_stock=True, finished_reorder_level=Decimal('5'),
        )
        recipe = Recipe.objects.create(
            menu_item=bun, yield_qty=Decimal('4'),
            wastage_percent=Decimal('0'),
        )
        # One batch of 4 buns needs 200 g flour -> 50 g per portion.
        RecipeRawMaterial.objects.create(
            recipe=recipe, raw_material=flour,
            quantity=Decimal('200'), unit=g,
        )
        return {
            'user': user, 'flour': flour, 'bun': bun,
            'recipe': recipe, 'supplier': supplier, 'unit': g,
        }


class ProductionRunModelTests(ProductionTestMixin, TestCase):

    def test_complete_deducts_raw_and_credits_finished(self):
        fx = self.make_production_setup()
        before = fx['flour'].current_stock
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('4'), created_by=fx['user'])
        run.complete()
        fx['flour'].refresh_from_db()
        fx['bun'].refresh_from_db()
        run.refresh_from_db()
        # 4 portions x 50 g = 200 g flour consumed.
        self.assertEqual(fx['flour'].current_stock, before - Decimal('200'))
        self.assertEqual(fx['bun'].finished_stock, Decimal('4.00'))
        self.assertEqual(run.status, 'completed')
        self.assertEqual(run.produced_qty, Decimal('4'))
        self.assertEqual(run.net_produced, Decimal('4.00'))

    def test_complete_records_wastage_as_net_only(self):
        fx = self.make_production_setup()
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('4'), created_by=fx['user'])
        run.complete(produced_qty=Decimal('4'), wastage_qty=Decimal('1'))
        fx['bun'].refresh_from_db()
        run.refresh_from_db()
        # Raws are consumed for all 4 produced; only 3 reach finished stock.
        self.assertEqual(fx['bun'].finished_stock, Decimal('3.00'))
        self.assertEqual(run.net_produced, Decimal('3.00'))

    def test_complete_is_atomic_on_shortage(self):
        fx = self.make_production_setup(stock=Decimal('100'))
        before = fx['flour'].current_stock
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('40'),  # needs 2000 g
            created_by=fx['user'])
        with self.assertRaisesMessage(ValueError, 'Insufficient stock'):
            run.complete()
        fx['flour'].refresh_from_db()
        fx['bun'].refresh_from_db()
        run.refresh_from_db()
        # Nothing half-deducted: raw stock, finished stock, status untouched.
        self.assertEqual(fx['flour'].current_stock, before)
        self.assertEqual(fx['bun'].finished_stock, Decimal('0'))
        self.assertEqual(run.status, 'draft')

    def test_cancel_reverses_completed_run(self):
        fx = self.make_production_setup()
        before = fx['flour'].current_stock
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('4'), created_by=fx['user'])
        run.complete()
        run.cancel()
        fx['flour'].refresh_from_db()
        fx['bun'].refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled')
        self.assertEqual(fx['flour'].current_stock, before)
        self.assertEqual(fx['bun'].finished_stock, Decimal('0'))
        self.assertFalse(
            InventoryTransaction.objects.filter(production_run=run).exists())

    def test_delete_returns_stock(self):
        fx = self.make_production_setup()
        before = fx['flour'].current_stock
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('4'), created_by=fx['user'])
        run.complete()
        run_id = run.pk
        run.delete()
        fx['flour'].refresh_from_db()
        fx['bun'].refresh_from_db()
        self.assertEqual(fx['flour'].current_stock, before)
        self.assertEqual(fx['bun'].finished_stock, Decimal('0'))
        self.assertFalse(
            InventoryTransaction.objects.filter(
                production_run_id=run_id).exists())

class ProductionHelpersTests(ProductionTestMixin, TestCase):

    def test_check_producible_lists_shortages(self):
        fx = self.make_production_setup(stock=Decimal('100'))
        short = check_producible(fx['recipe'], Decimal('40'))
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]['raw_material'], fx['flour'])
        self.assertEqual(short[0]['need'], Decimal('2000.00'))
        self.assertEqual(check_producible(fx['recipe'], Decimal('1')), [])

    def test_produce_portions_rejects_zero(self):
        fx = self.make_production_setup()
        with self.assertRaisesMessage(ValueError, 'greater than zero'):
            produce_portions(fx['recipe'], 0)

    def test_finished_stock_status_helpers(self):
        fx = self.make_production_setup()
        bun = fx['bun']
        self.assertTrue(bun.is_finished_out_of_stock)
        self.assertTrue(bun.is_finished_low_stock)
        bun.finished_stock = Decimal('3')
        self.assertFalse(bun.is_finished_out_of_stock)
        self.assertTrue(bun.is_finished_low_stock)
        bun.finished_stock = Decimal('10')
        self.assertEqual(bun.finished_stock_status, 'ok')
        # ~1000 g / 50 g per portion = 20 portions producible.
        self.assertEqual(bun.max_producible, Decimal('20'))

    def test_untracked_item_has_no_producible(self):
        fx = self.make_production_setup()
        fx['bun'].track_finished_stock = False
        fx['bun'].save(update_fields=['track_finished_stock'])
        self.assertIsNone(fx['bun'].max_producible)
        self.assertEqual(fx['bun'].finished_stock_status, 'ok')


class ProductionFormTests(ProductionTestMixin, TestCase):

    def test_run_form_lists_only_tracked_recipes(self):
        fx = self.make_production_setup()
        cat = fx['bun'].category
        plain = MenuItem.objects.create(
            name='Plain', price=Decimal('10'), category=cat)
        plain_recipe = Recipe.objects.create(menu_item=plain, yield_qty=1)
        form = ProductionRunForm()
        self.assertIn(fx['recipe'], form.fields['recipe'].queryset)
        self.assertNotIn(plain_recipe, form.fields['recipe'].queryset)

    def test_complete_guards_wastage_above_produced(self):
        form = ProductionCompleteForm(
            data={'produced_qty': '4', 'wastage_qty': '5'})
        self.assertTrue(form.is_valid())  # field-level ok; model guards rest
        fx = self.make_production_setup()
        run = ProductionRun.objects.create(
            recipe=fx['recipe'], planned_qty=Decimal('4'))
        with self.assertRaisesMessage(ValueError, 'Wastage cannot exceed'):
            run.complete(produced_qty=Decimal('4'), wastage_qty=Decimal('5'))


class ProductionViewTests(ProductionTestMixin, TestCase):

    def setUp(self):
        fx = self.make_production_setup()
        self.__dict__.update(fx)
        self.client.force_login(self.user)

    def test_full_screen_flow(self):
        self.assertEqual(
            self.client.get(reverse('production_run_list')).status_code, 200)
        self.assertEqual(
            self.client.get(reverse('production_run_create')).status_code, 200)
        resp = self.client.post(reverse('production_run_create'), {
            'recipe': self.recipe.pk, 'planned_qty': '4', 'notes': 'prep',
        })
        self.assertEqual(resp.status_code, 302)
        run = ProductionRun.objects.get()
        self.assertEqual(run.status, 'draft')
        self.flour.refresh_from_db()
        before = self.flour.current_stock
        self.assertEqual(
            self.client.get(
                reverse('production_run_complete',
                        args=[run.pk])).status_code, 200)
        resp = self.client.post(
            reverse('production_run_complete', args=[run.pk]),
            {'produced_qty': '4', 'wastage_qty': '1'})
        self.assertEqual(resp.status_code, 302)
        self.flour.refresh_from_db()
        self.bun.refresh_from_db()
        self.assertEqual(self.flour.current_stock, before - Decimal('200'))
        self.assertEqual(self.bun.finished_stock, Decimal('3.00'))
        resp = self.client.get(
            reverse('production_run_detail', args=[run.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Stock movements')
        resp = self.client.post(
            reverse('production_run_cancel', args=[run.pk]))
        self.assertEqual(resp.status_code, 302)
        self.flour.refresh_from_db()
        self.bun.refresh_from_db()
        self.assertEqual(self.flour.current_stock, before)
        self.assertEqual(self.bun.finished_stock, Decimal('0'))

    def test_complete_shortage_returns_400(self):
        run = ProductionRun.objects.create(
            recipe=self.recipe, planned_qty=Decimal('400'))  # needs 20 kg
        resp = self.client.post(
            reverse('production_run_complete', args=[run.pk]),
            {'produced_qty': '400', 'wastage_qty': '0'})
        self.assertEqual(resp.status_code, 400)
        run.refresh_from_db()
        self.assertEqual(run.status, 'draft')

    def test_cancel_confirm_page_renders(self):
        run = ProductionRun.objects.create(
            recipe=self.recipe, planned_qty=Decimal('2'))
        self.assertEqual(
            self.client.get(
                reverse('production_run_cancel',
                        args=[run.pk])).status_code, 200)

    def test_cashier_is_blocked(self):
        from core.permissions import can_access_route
        cashier = User.objects.create_user(
            'prod_cashier', password='x', role='cashier')
        self.assertFalse(can_access_route(cashier, 'production_run_list'))
        self.client.force_login(cashier)
        self.assertEqual(
            self.client.get(reverse('production_run_list')).status_code, 403)

