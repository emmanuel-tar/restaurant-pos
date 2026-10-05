"""
Currency helpers for templates.

Usage:
    {% load currency %}
    {{ order.total|money }}        ->  ₦12,500.00   (Nigeria)
    {{ order.total|money:False }}   ->  12,500.00    (no symbol)
    {{ order.total|receipt_money }} ->  N12,500.00   (ASCII-safe, for printers)
"""
from django import template
from django.template.defaultfilters import stringfilter

from core.countries import active_country, format_number, receipt_amount

register = template.Library()


@register.filter(name='money')
@stringfilter
def money(value, with_symbol=True):
    """Format an amount using the active country's currency symbol."""
    return format_number(value, active_country(), with_symbol=str(with_symbol).lower() != 'false')


@register.filter(name='money_code')
@stringfilter
def money_code(value):
    """Format an amount with the ISO code, e.g. 'NGN 12,500.00'."""
    cfg = active_country()
    number = format_number(value, cfg, with_symbol=False)
    space = ' ' if cfg['space_after_symbol'] else ''
    return f"{cfg['currency_code']}{space}{number}"


@register.filter(name='receipt_money')
@stringfilter
def receipt_money(value):
    """ASCII-only amount for thermal receipt printers."""
    return receipt_amount(value, active_country())