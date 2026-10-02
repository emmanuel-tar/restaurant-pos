from django.conf import settings

# Branding shown across the UI (header, page titles). Kept in one place so the
# name only ever has to be changed in settings.py (RESTAURANT_NAME).
DEFAULT_RESTAURANT_NAME = 'RestroPOS'


def app_branding(request):
    """Expose RESTAURANT_NAME from settings.py to every template."""
    return {
        'RESTAURANT_NAME': getattr(settings, 'RESTAURANT_NAME', DEFAULT_RESTAURANT_NAME),
    }