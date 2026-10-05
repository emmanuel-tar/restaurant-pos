"""
Country / currency configuration for the POS.

Everything currency- and locale-related is driven from here so the same codebase
can run in any country. Set the active country with a single line in settings.py:

    COUNTRY = 'NG'   # Nigeria (default)

Add a country by copying an entry in COUNTRIES - nothing else needs changing.
"""

from decimal import Decimal, InvalidOperation
from django.conf import settings

# Used when settings.COUNTRY is missing or unknown.
DEFAULT_COUNTRY = 'NG'


def _c(code, name, currency_code, symbol, *, position='left', space=False,
       dp=2, thousands=',', decimal_point='.', locale='en-US',
       timezone='UTC', language='en-us', phone='+1', vat='0',
       receipt_symbol=None):
    return {
        'code': code,
        'name': name,
        'currency_code': currency_code,
        'currency_symbol': symbol,
        'symbol_position': position,          # 'left' or 'right'
        'space_after_symbol': space,          # "US$ 10" vs "$10"
        'decimal_places': dp,
        'thousands_separator': thousands,
        'decimal_separator': decimal_point,
        'locale': locale,                     # for JS Number.toLocaleString()
        'timezone': timezone,
        'language_code': language,
        'phone_code': phone,
        'vat_rate': vat,                      # standard VAT rate, percent
        # Thermal receipt printers are usually ASCII-only, so they get a safe
        # fallback (the ISO code, or a plain letter) instead of e.g. the Naira sign.
        'receipt_symbol': receipt_symbol or currency_code,
    }


COUNTRIES = {
    # ---- West Africa ----
    'NG': _c('NG', 'Nigeria', 'NGN', '\u20a6', locale='en-NG', timezone='Africa/Lagos',
             phone='+234', vat='7.5', receipt_symbol='N'),
    'GH': _c('GH', 'Ghana', 'GHS', '\u20b5', locale='en-GH', timezone='Africa/Accra',
             phone='+233', vat='15', receipt_symbol='GHS'),
    'CI': _c('CI', "Cote d'Ivoire", 'XOF', 'FCFA', space=True, locale='fr-CI',
             timezone='Africa/Abidjan', language='fr', phone='+225', vat='18',
             receipt_symbol='FCFA'),
    'SN': _c('SN', 'Senegal', 'XOF', 'FCFA', space=True, locale='fr-SN',
             timezone='Africa/Dakar', language='fr', phone='+221', vat='18',
             receipt_symbol='FCFA'),

    # ---- East & Southern Africa ----
    'KE': _c('KE', 'Kenya', 'KES', 'KSh', space=True, locale='en-KE',
             timezone='Africa/Nairobi', phone='+254', vat='16', receipt_symbol='KSh'),
    'ZA': _c('ZA', 'South Africa', 'ZAR', 'R', space=True, locale='en-ZA',
             timezone='Africa/Johannesburg', phone='+27', vat='15', receipt_symbol='R'),
    'EG': _c('EG', 'Egypt', 'EGP', 'E\u00a3', space=True, locale='ar-EG',
             timezone='Africa/Cairo', language='ar', phone='+20', vat='14',
             receipt_symbol='EGP'),

    # ---- Middle East ----
    'AE': _c('AE', 'United Arab Emirates', 'AED', 'AED', space=True, locale='ar-AE',
             timezone='Asia/Dubai', language='ar', phone='+971', vat='5',
             receipt_symbol='AED'),
    'SA': _c('SA', 'Saudi Arabia', 'SAR', 'SAR', space=True, locale='ar-SA',
             timezone='Asia/Riyadh', language='ar', phone='+966', vat='15',
             receipt_symbol='SAR'),

    # ---- Europe ----
    'GB': _c('GB', 'United Kingdom', 'GBP', '\u00a3', locale='en-GB',
             timezone='Europe/London', phone='+44', vat='20', receipt_symbol='GBP'),
    'FR': _c('FR', 'France', 'EUR', '\u20ac', space=True, locale='fr-FR',
             timezone='Europe/Paris', language='fr', phone='+33', vat='20',
             receipt_symbol='EUR'),
    'DE': _c('DE', 'Germany', 'EUR', '\u20ac', space=True, locale='de-DE',
             timezone='Europe/Berlin', language='de', phone='+49', vat='19',
             receipt_symbol='EUR'),

    # ---- Americas & Asia ----
    'US': _c('US', 'United States', 'USD', '$', locale='en-US',
             timezone='America/New_York', phone='+1', vat='0', receipt_symbol='$'),
    'BR': _c('BR', 'Brazil', 'BRL', 'R$', space=True, locale='pt-BR',
             timezone='America/Sao_Paulo', language='pt', phone='+55', vat='17',
             receipt_symbol='R$'),
    'IN': _c('IN', 'India', 'INR', '\u20b9', locale='en-IN', timezone='Asia/Kolkata',
             phone='+91', vat='18', receipt_symbol='Rs'),
    'PK': _c('PK', 'Pakistan', 'PKR', '\u20a8', space=True, locale='en-PK',
             timezone='Asia/Karachi', phone='+92', vat='18', receipt_symbol='Rs'),
    'ID': _c('ID', 'Indonesia', 'IDR', 'Rp', locale='id-ID', timezone='Asia/Jakarta',
             language='id', phone='+62', vat='11', receipt_symbol='Rp'),
    'CN': _c('CN', 'China', 'CNY', '\u00a5', space=True, locale='zh-CN',
             timezone='Asia/Shanghai', phone='+86', vat='13', receipt_symbol='CNY'),
}


def get_country(code=None):
    """Config for a country code; falls back to the default when unknown."""
    code = (code or getattr(settings, 'COUNTRY', DEFAULT_COUNTRY) or DEFAULT_COUNTRY)
    return COUNTRIES.get(str(code).upper(), COUNTRIES[DEFAULT_COUNTRY])


def active_country():
    """The country this install is configured for."""
    return get_country()
def format_number(value, country=None, with_symbol=True):
    """
    Format an amount for a country. For Nigeria:
        1234567.5  ->  '\u20a61,234,567.50'
    """
    cfg = country or active_country()

    try:
        amount = Decimal(str(value if value not in (None, '') else 0))
    except (InvalidOperation, ValueError, TypeError):
        amount = Decimal('0')

    amount = amount.quantize(Decimal(1).scaleb(-cfg['decimal_places']))
    negative = amount < 0
    amount = abs(amount)

    fixed = f"{amount:.{cfg['decimal_places']}f}"
    if cfg['decimal_separator'] != '.':
        fixed = fixed.replace('.', cfg['decimal_separator'])

    whole, _, frac = fixed.partition(cfg['decimal_separator'])
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    number = cfg['thousands_separator'].join(groups)
    if frac:
        number += cfg['decimal_separator'] + frac

    sign = '-' if negative else ''
    if not with_symbol:
        return sign + number

    symbol = cfg['currency_symbol']
    space = ' ' if cfg['space_after_symbol'] else ''
    if cfg['symbol_position'] == 'right':
        return f"{sign}{number}{space}{symbol}"
    return f"{sign}{symbol}{space}{number}"


def receipt_amount(value, country=None):
    """
    Printer-safe, ASCII-only amount. Thermal printers generally cannot render
    symbols such as the Naira sign, so Nigeria prints e.g. 'N1,500.00'.
    """
    cfg = country or active_country()
    number = format_number(value, cfg, with_symbol=False)
    negative = number.startswith('-')
    number = number.lstrip('-')
    out = f"{cfg['receipt_symbol']}{number}"
    return f"-{out}" if negative else out