"""
Role-based permissions.

Right now any signed-in user can delete a menu item or void money, which is the
normal state of affairs in a small POS but not something a restaurant can live
with once there is more than one cashier.

Two sources of truth are combined:

  User.role        admin / cashier / kitchen      (AUTH_USER_MODEL.role)
  Staff.access_*   sales / inventory / accounts   (per-person overrides)

A Staff record linked to the user can *widen* what the role allows, never
narrow it, so adding a staff member can never accidentally lock someone out of
their own account.
"""
import logging

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# What each role may do.
# ---------------------------------------------------------------------------
PERMISSIONS = {
    'admin': {
        'sales', 'menu', 'inventory', 'accounts', 'settings', 'staff', 'reports',
    },
    'manager': {
        'sales', 'menu', 'inventory', 'accounts', 'settings', 'reports',
    },
    'cashier': {
        'sales', 'reports',
    },
    'kitchen': set(),
}

# Staff.access_* flag that grants each area (used to widen a role's access).
STAFF_FLAG_FOR_AREA = {
    'sales': 'access_sales',
    'inventory': 'access_inventory',
    'accounts': 'access_accounts',
}

# Maps a view's permission area onto the sidebar sections it should reveal.
SIDEBAR_AREA = {
    'dashboard': 'sales',
    'order_create': 'sales',
    'order_list': 'sales',
    'table_list': 'sales',
    'category_list': 'menu',
    'menuitem_list': 'menu',
    'deal_list': 'menu',
    'modifiergroup_list': 'menu',
    'taxrate_list': 'menu',
    'kitchen_voucher_list': 'inventory',
    'kitchen_stock_summary': 'inventory',
    'raw_material_list': 'inventory',
    'recipe_list': 'inventory',
    'purchase_order_list': 'inventory',
    'supplier_list': 'inventory',
    'low_stock': 'inventory',
    'unit_list': 'inventory',
    'expense_list': 'accounts',
    'payment_received_list': 'accounts',
    'bankaccount_list': 'accounts',
    'bankmovement_list': 'accounts',
    'ledger_home': 'accounts',
    'waiter_list': 'staff',
    'staff_list': 'staff',
    'customer_list': 'sales',
    'reports': 'reports',
    'cost_report': 'reports',
    'overview_report': 'reports',
    'market_list': 'inventory',
    'market_list_print': 'inventory',
    'stock_summary': 'inventory',
    'configuration': 'settings',
    'station_create': 'settings',
}


def staff_for(user):
    """
    The Staff record linked to this user, if any.

    Staff.user has no related_name, so the reverse accessor is `staff_set`;
    querying explicitly keeps this working if a related_name is added later.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    from .models import Staff
    return Staff.objects.filter(user=user).first()


def areas_for(user):
    """The set of areas this user may work in."""
    if isinstance(user, AnonymousUser) or not getattr(user, 'is_authenticated', False):
        return set()

    if user.is_superuser:
        return set(PERMISSIONS['admin'])

    areas = set(PERMISSIONS.get(getattr(user, 'role', 'cashier'), set()))

    staff = staff_for(user)
    if staff is not None:
        for area, flag in STAFF_FLAG_FOR_AREA.items():
            if getattr(staff, flag, False):
                areas.add(area)
        # Staff marked as having software access are treated as staff-level.
        if getattr(staff, 'has_software_access', False) and 'staff' not in areas:
            areas.add('staff')
            areas.add('menu')
            areas.add('reports')
    return areas


def can(user, area):
    """True when this user may work in the given area ('sales', 'menu', ...)."""
    return area in areas_for(user)


def can_access_route(user, url_name):
    """True when this user may see a route that maps to a permission area."""
    if not url_name:
        return False
    if not isinstance(user, AnonymousUser) and getattr(user, 'is_superuser', False):
        return True
    area = SIDEBAR_AREA.get(url_name)
    if area is None:
        return True                      # unknown route: leave it alone
    return can(user, area)


def require_permission(area):
    """
    Class/function decorator guarding a view behind a permission area.

    Anonymous users are sent to the login page (the view still has to sit behind
    LoginRequiredMixin); signed-in users without permission get a 403.
    """
    def decorator(view):
        def _wrapped(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            if user is None or not getattr(user, 'is_authenticated', False):
                return _login_redirect(request)
            if not can(user, area):
                logger.info(
                    'Permission denied: %s tried to use "%s" (area=%s, role=%s)',
                    user.get_username(), request.path, area,
                    getattr(user, 'role', '?'),
                )
                raise PermissionDenied(
                    'Your role does not have access to this screen.'
                )
            return view(request, *args, **kwargs)

        _wrapped.__name__ = getattr(view, '__name__', 'view')
        _wrapped.__doc__ = view.__doc__
        return _wrapped
    return decorator


def _login_redirect(request):
    """Send anonymous users to login, falling back to '/' if there is no route."""
    try:
        login_url = reverse('login')
    except NoReverseMatch:
        login_url = '/'
    return redirect(f'{login_url}?next={request.get_full_path()}')