"""Role-based access control (`core.permissions`).

The rules are the app's security boundary: a cashier must never reach the tax
screens, the accounts screens or a delete button. Keeping them as focused unit
tests means a matrix change is caught immediately instead of by a 403 in
production.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase

from core.models import Staff
from core.permissions import can, can_access_route, areas_for

User = get_user_model()

# area -> expected for each role (staff flags are covered separately)
MATRIX = {
    'admin':    {'sales', 'menu', 'inventory', 'accounts', 'settings', 'staff', 'reports'},
    'manager':  {'sales', 'menu', 'inventory', 'accounts', 'settings', 'reports'},
    'cashier':  {'sales', 'reports'},
    'kitchen':  set(),
}


class RoleMatrixTests(TestCase):

    def _user(self, role):
        return User.objects.create_user(f'perm_{role}', password='x', role=role)

    def test_each_role_gets_exactly_its_areas(self):
        for role, expected in MATRIX.items():
            with self.subTest(role=role):
                self.assertEqual(areas_for(self._user(role)), expected)

    def test_superuser_always_gets_everything(self):
        su = User.objects.create_superuser('perm_admin', 'a@example.com', 'x')
        self.assertEqual(areas_for(su), MATRIX['admin'])

    def test_anonymous_user_gets_nothing(self):
        self.assertEqual(areas_for(AnonymousUser()), set())
        self.assertFalse(can(AnonymousUser(), 'sales'))

    def test_can_reports_true_only_for_granted_areas(self):
        cashier = self._user('cashier')
        self.assertTrue(can(cashier, 'sales'))
        for area in ('menu', 'inventory', 'accounts', 'settings', 'staff'):
            with self.subTest(area=area):
                self.assertFalse(can(cashier, area))


class StaffFlagTests(TestCase):
    """A Staff record may widen a role's access, but must never narrow it."""

    def test_flag_widens_access(self):
        cashier = User.objects.create_user('perm_widen', password='x', role='cashier')
        Staff.objects.create(full_name='Widen', role='cashier', user=cashier,
                             access_inventory=True)
        self.assertTrue(can(cashier, 'inventory'))
        # Widening is per-area: accounts must stay locked.
        self.assertFalse(can(cashier, 'accounts'))

    def test_flag_never_narrows_role(self):
        manager = User.objects.create_user('perm_narrow', password='x', role='manager')
        Staff.objects.create(full_name='Narrow', role='manager', user=manager,
                             access_accounts=False, access_sales=False)
        self.assertTrue(can(manager, 'accounts'))
        self.assertTrue(can(manager, 'sales'))

    def test_software_access_grants_menu_and_reports(self):
        user = User.objects.create_user('perm_sw', password='x', role='cashier')
        Staff.objects.create(full_name='Sw', role='cashier', user=user,
                             has_software_access=True)
        self.assertTrue(can(user, 'menu'))
        self.assertTrue(can(user, 'reports'))
        self.assertTrue(can(user, 'staff'))


class RouteGuardTests(TestCase):

    def test_cashier_is_blocked_from_admin_routes(self):
        cashier = User.objects.create_user('perm_route', password='x', role='cashier')
        for route in ('taxrate_list', 'expense_list', 'configuration', 'raw_material_list'):
            with self.subTest(route=route):
                self.assertFalse(can_access_route(cashier, route))

    def test_cashier_may_use_sales_routes(self):
        cashier = User.objects.create_user('perm_route2', password='x', role='cashier')
        for route in ('dashboard', 'order_create', 'order_list', 'table_list'):
            with self.subTest(route=route):
                self.assertTrue(can_access_route(cashier, route))

    def test_superuser_bypasses_route_guards(self):
        su = User.objects.create_superuser('perm_route3', 'a@example.com', 'x')
        self.assertTrue(can_access_route(su, 'taxrate_list'))

    def test_unmapped_route_is_left_alone(self):
        """Routes with no area mapping are not silently hidden."""
        cashier = User.objects.create_user('perm_route4', password='x', role='cashier')
        self.assertTrue(can_access_route(cashier, 'a_route_that_is_not_mapped'))

    def test_empty_route_name_is_denied(self):
        cashier = User.objects.create_user('perm_route5', password='x', role='cashier')
        self.assertFalse(can_access_route(cashier, ''))
