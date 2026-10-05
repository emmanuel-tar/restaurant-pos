import os
from pathlib import Path

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

SITE_ID = 1

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = 'replace-with-secure-key'
DEBUG = True
ALLOWED_HOSTS = ['*', '192.168.0.2']

RESTAURANT_NAME = "RestroPOS"

# Country the POS operates in. One line controls currency symbol/code, number and
# date formats, timezone, language and the standard VAT rate.
# Options: NG (default), GH, CI, SN, KE, ZA, EG, AE, SA, GB, FR, DE, US, BR, IN, PK, ID, CN
# Add new ones in core/countries.py.
COUNTRY = 'NG'
# Optionally:
LOGO_PATH = os.path.join(BASE_DIR, "staticfiles", "images", "logo.png")

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
    'django.contrib.sites',
    'crispy_forms',
    'crispy_bootstrap5',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'restuarent_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'core' / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.app_branding',
                'core.context_processors.localization',
                'core.context_processors.navigation',
            ],
        },
    },
]

WSGI_APPLICATION = 'restuarent_app.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',

    }
}

CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

AUTH_USER_MODEL = 'core.User'

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True


STATIC_ROOT = BASE_DIR / 'staticfiles'

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']


MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')


LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'