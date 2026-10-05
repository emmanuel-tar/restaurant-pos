"""Standard production-costing helpers (single source of truth)."""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP

MONEY = Decimal('0.01')
QTY = Decimal('0.001')

def q_money(x) -> Decimal:
    try:
        return (Decimal(str(x or 0))).quantize(MONEY, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')

def q_qty(x) -> Decimal:
    try:
        return (Decimal(str(x or 0))).quantize(QTY, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.000')

def _sym(u):
    if u is None:
        return ''
    return (getattr(u, 'symbol', None) or str(u)).strip().lower()

def conversion_factor(from_unit, to_unit) -> Decimal:
    """How many to_unit in one from_unit (same unit_type only)."""
    from .models import Unit
    fs, ts = _sym(from_unit), _sym(to_unit)
    if not fs or not ts or fs == ts:
        return Decimal('1')
    def _type(u):
        t = getattr(u, 'unit_type', None)
        if t:
            return str(t)
        try:
            return Unit.objects.filter(symbol__iexact=str(u)).values_list('unit_type', flat=True).first() or ''
        except Exception:
            return ''
    ft, tt = _type(from_unit), _type(to_unit)
    if ft and tt and ft != tt:
        return Decimal('0')
    try:
        f_base = Unit.to_base_factor(fs)
        t_base = Unit.to_base_factor(ts)
        if not t_base:
            return Decimal('0')
        return (Decimal(str(f_base)) / Decimal(str(t_base)))
    except Exception:
        return Decimal('1')

def raw_avg_cost(rm) -> Decimal:
    """Weighted-average cost per STOCK unit across received PO lines."""
    total_cost = Decimal('0')
    total_qty = Decimal('0')
    items = rm.purchaseorderitem_set.select_related('purchase_order').all()
    recvd = [i for i in items if getattr(getattr(i, 'purchase_order', None), 'status', 'received') == 'received']
    for it in recvd or list(items):
        try:
            qty = Decimal(str(it.quantity or 0))
            price = Decimal(str(it.unit_price or 0))
        except Exception:
            continue
        if qty <= 0:
            continue
        f = conversion_factor(getattr(it, 'purchase_unit', None) or rm.stock_unit, rm.stock_unit)
        if not f:
            f = Decimal('1')
        sq = qty * f
        if sq <= 0:
            continue
        total_qty += sq
        total_cost += qty * price
    if total_qty <= 0:
        last = rm.purchaseorderitem_set.order_by('-id').first()
        if not last:
            return Decimal('0')
        try:
            price = Decimal(str(last.unit_price or 0))
        except Exception:
            return Decimal('0')
        f = conversion_factor(getattr(last, 'purchase_unit', None) or rm.stock_unit, rm.stock_unit)
        if not f:
            f = Decimal('1')
        try:
            return q_money(price / f) if f else Decimal('0')
        except Exception:
            return Decimal('0')
    return q_money(total_cost / total_qty)

def latest_price(rm) -> Decimal:
    last = rm.purchaseorderitem_set.order_by('-id').first()
    if not last:
        return Decimal('0')
    try:
        price = Decimal(str(last.unit_price or 0))
    except Exception:
        return Decimal('0')
    f = conversion_factor(getattr(last, 'purchase_unit', None) or rm.stock_unit, rm.stock_unit)
    if not f:
        return Decimal('0')
    try:
        return q_money(price / f)
    except Exception:
        return Decimal('0')

def recipe_breakdown(recipe, _seen=None):
    """Line-by-line cost breakdown for one recipe (sub-recipes expanded)."""
    _seen = set(_seen or [])
    if recipe.pk in _seen:
        raise ValueError('Circular recipe reference detected.')
    _seen = set(_seen) | {recipe.pk}
    lines = []
    total = Decimal('0')
    for ing in recipe.raw_ingredients.select_related('raw_material').all():
        rm = ing.raw_material
        try:
            qty = Decimal(str(ing.quantity or 0))
        except Exception:
            qty = Decimal('0')
        f = conversion_factor(ing.unit, rm.stock_unit)
        if not f:
            raise ValueError(f'Incompatible unit for {rm.name}.')
        sq = q_qty(qty * f)
        uc = raw_avg_cost(rm)
        lc = q_money(sq * uc)
        total += lc
        lines.append({'kind': 'raw', 'raw_material': rm, 'raw_material_id': rm.pk,
                      'name': rm.name, 'quantity': qty, 'unit': str(ing.unit),
                      'stock_unit': str(rm.stock_unit), 'stock_qty': sq,
                      'unit_cost': uc, 'line_cost': lc})
    subs = []
    for sub in recipe.subrecipes.select_related('sub_recipe').all():
        child = sub.sub_recipe
        try:
            portions = Decimal(str(sub.quantity or 0))
        except Exception:
            portions = Decimal('0')
        detail = recipe_breakdown(child, _seen)
        pc = detail['cost_per_portion'] or detail['total_cost']
        lc = q_money(portions * pc)
        total += lc
        nm = child.menu_item.name if getattr(child, 'menu_item_id', None) else (child.name or f'Recipe #{child.pk}')
        subs.append({'kind': 'sub', 'recipe': child, 'sub_recipe_id': child.pk, 'name': nm,
                     'quantity': portions, 'unit': 'portion', 'portion_cost': pc, 'line_cost': lc, 'detail': detail})
    try:
        yld = Decimal(str(getattr(recipe, 'yield_qty', 0) or 0))
    except Exception:
        yld = Decimal('0')
    try:
        wst = Decimal(str(getattr(recipe, 'wastage_percent', 0) or 0))
    except Exception:
        wst = Decimal('0')
    if yld <= 0:
        yld = Decimal('1')
    wst = max(Decimal('0'), min(Decimal('100'), wst))
    gross = q_money(total)
    eff = (Decimal('1') - wst / Decimal('100')) or Decimal('1')
    per = q_money(gross / (yld * eff)) if yld else gross
    return {'lines': lines, 'sub_recipe_lines': subs, 'all_lines': lines + subs,
            'gross_cost': gross, 'total_cost': gross, 'yield_qty': yld,
            'wastage_percent': wst, 'wastage_qty': q_qty(yld * wst / Decimal('100')),
            'cost_per_portion': per, 'estimated_cost': per}

def recipe_cost(recipe) -> Decimal:
    try:
        return recipe_breakdown(recipe)['cost_per_portion']
    except Exception:
        return Decimal('0')

def usage_map(recipe, portions=Decimal('1'), _seen=None):
    """Flatten recipe into {raw_material_id: stock_qty} for portions made."""
    _seen = set(_seen or [])
    if recipe.pk in _seen:
        raise ValueError('Circular recipe reference detected.')
    _seen = set(_seen) | {recipe.pk}
    try:
        portions = Decimal(str(portions or 0))
    except Exception:
        portions = Decimal('0')
    if portions <= 0:
        return {}
    try:
        yld = Decimal(str(getattr(recipe, 'yield_qty', 0) or 0)) or Decimal('1')
    except Exception:
        yld = Decimal('1')
    batches = portions / yld if yld else portions
    usage = {}
    for ing in recipe.raw_ingredients.select_related('raw_material').all():
        rm = ing.raw_material
        try:
            qty = Decimal(str(ing.quantity or 0))
        except Exception:
            qty = Decimal('0')
        f = conversion_factor(ing.unit, rm.stock_unit)
        if not f:
            raise ValueError(f'Incompatible unit for {rm.name}.')
        need = qty * f * batches
        usage[rm.pk] = usage.get(rm.pk, Decimal('0')) + need
    for sub in recipe.subrecipes.select_related('sub_recipe').all():
        try:
            sp = Decimal(str(sub.quantity or 0)) * batches
        except Exception:
            sp = Decimal('0')
        for rid, need in usage_map(sub.sub_recipe, sp, _seen).items():
            usage[rid] = usage.get(rid, Decimal('0')) + need
    return usage

def menu_economics(mi):
    price = Decimal(str(getattr(mi, 'price', 0) or 0))
    try:
        recipe = mi.recipe
    except Exception:
        recipe = None
    if recipe is None:
        return {'has_recipe': False, 'estimated_cost': Decimal('0'),
                'food_cost_percent': None, 'margin_amount': None, 'margin_percent': None}
    cost = recipe_cost(recipe)
    if price > 0:
        fp = (cost / price * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        mg = q_money(price - cost)
        mp = ((price - cost) / price * Decimal('100')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    else:
        fp, mg, mp = None, None, None
    return {'has_recipe': True, 'estimated_cost': cost, 'food_cost_percent': fp,
            'margin_amount': mg, 'margin_percent': mp}

def refresh_cost(mi, save=True):
    try:
        recipe = mi.recipe
    except Exception:
        return Decimal(str(getattr(mi, 'cost_price', 0) or 0))
    cost = recipe_cost(recipe)
    mi.cost_price = cost
    if save:
        mi.save(update_fields=['cost_price'])
    return cost


