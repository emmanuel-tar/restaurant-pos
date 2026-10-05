"""The two large end-to-end smoke runs, executed as real Django tests."""
from .base import SmokeTestCase  # noqa: I100  (must land on sys.path first)

import smoke_test_costing
import smoke_test_taxes


class TaxesAndModifiersSmokeTests(SmokeTestCase):
    """Order maths, receipts, management screens, RBAC and bill holds.

    Covers the highest-risk paths in the app: totals with modifiers and
    multiple taxes, thermal bill output, the order list annotations, the
    tax/modifier CRUD screens, role gating on 30+ screens, and the
    park/recall/discard hold lifecycle.
    """

    def test_taxes_modifiers_and_screens(self):
        rows = self.run_smoke(smoke_test_taxes, rollback=False, verbose=False)
        # Guards against a refactor silently deleting most of the assertions.
        self.assertGreaterEqual(len(rows), 250, 'taxes smoke test lost checks')


class ProductionCostingSmokeTests(SmokeTestCase):
    """Raw material -> recipe -> menu item -> sale, including stock movements.

    Guards the unit-conversion maths (the historical 1000x bug), yield/wastage
    costing, sub-recipe expansion, food-cost %, and stock deduction/reversal on
    sale, edit, void and purchase-order deletion.
    """

    def test_production_costing(self):
        rows = self.run_smoke(smoke_test_costing, rollback=False)
        self.assertGreaterEqual(len(rows), 45, 'costing smoke test lost checks')
