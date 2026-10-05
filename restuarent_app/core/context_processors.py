from django.conf import settings

from core.countries import active_country
from core.navigation import build_sidebar, active_url_name
from core.permissions import areas_for

# Branding shown across the UI (header, page titles). Kept in one place so the
# name only ever has to be changed in settings.py (RESTAURANT_NAME).
DEFAULT_RESTAURANT_NAME = 'RestroPOS'


def app_branding(request):
    """Expose RESTAURANT_NAME from settings.py to every template."""
    return {
        'RESTAURANT_NAME': getattr(settings, 'RESTAURANT_NAME', DEFAULT_RESTAURANT_NAME),
    }


def navigation(request):
    """
    Expose the sidebar to every template, with the link for the current page
    already flagged (templates cannot call functions with arguments) and with
    links the signed-in user may not open removed.
    """
    user = getattr(request, 'user', None)
    current = active_url_name(request)
    signed_in = getattr(user, 'is_authenticated', False)
    return {
        'sidebar_sections': build_sidebar(current, areas_for(user) if signed_in else None),
        'current_url_name': current,
        'user_role': user.get_role_display() if signed_in else '',
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
