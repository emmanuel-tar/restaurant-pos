from django.db import migrations


UNIT_SYMBOLS = ['kg', 'g', 'mg', 'lb', 'oz', 'l', 'ml', 'tbsp', 'tsp', 'cup', 'floz', 'pc', 'doz', 'pack', 'box', 'bag', 'bottle', 'can', 'pcs', 'gal']


def seed_units_and_backfill(apps, schema_editor):
    Unit = apps.get_model('core', 'Unit')
    RawMaterial = apps.get_model('core', 'RawMaterial')
    PurchaseOrderItem = apps.get_model('core', 'PurchaseOrderItem')

    defaults = [
        ('Kilogram', 'kg', 'mass'), ('Gram', 'g', 'mass'),
        ('Milligram', 'mg', 'mass'), ('Pound', 'lb', 'mass'), ('Ounce', 'oz', 'mass'),
        ('Litre', 'l', 'volume'), ('Millilitre', 'ml', 'volume'),
        ('Tablespoon', 'tbsp', 'volume'), ('Teaspoon', 'tsp', 'volume'),
        ('Cup', 'cup', 'volume'), ('Fluid Ounce', 'floz', 'volume'),
        ('Gallon', 'gal', 'volume'),
        ('Piece', 'pc', 'count'), ('Pieces', 'pcs', 'count'), ('Dozen', 'doz', 'count'),
        ('Pack', 'pack', 'count'), ('Box', 'box', 'count'),
        ('Bag', 'bag', 'count'), ('Bottle', 'bottle', 'count'), ('Can', 'can', 'count'),
    ]
    for name, symbol, typ in defaults:
        Unit.objects.get_or_create(symbol=symbol, defaults={'name': name, 'unit_type': typ})

    by_symbol = {u.symbol.lower(): u.id for u in Unit.objects.all()}

    # Map legacy free-text units onto the Unit master.
    legacy_map = {
        'kilogram': 'kg', 'kilograms': 'kg', 'kilo': 'kg', 'kilos': 'kg',
        'gram': 'g', 'grams': 'g', 'gm': 'g', 'gms': 'g',
        'milligram': 'mg', 'litre': 'l', 'liter': 'l', 'litres': 'l', 'liters': 'l',
        'millilitre': 'ml', 'milliliter': 'ml',
        'tablespoon': 'tbsp', 'teaspoon': 'tsp', 'piece': 'pc', 'pieces': 'pc',
        'nos': 'pc', 'no': 'pc', 'pkt': 'pack', 'packet': 'pack', 'packets': 'pack',
    }
    for rm in RawMaterial.objects.all():
        raw = (rm.unit or '').strip()
        key = raw.lower()
        symbol = legacy_map.get(key, key)
        uid = by_symbol.get(symbol)
        if not uid:
            continue
        updates = {}
        if not rm.stock_unit_id:
            updates['stock_unit_id'] = uid
        if not rm.purchase_unit_id:
            updates['purchase_unit_id'] = uid
        if updates:
            RawMaterial.objects.filter(pk=rm.pk).update(**updates)

    # PO lines inherit the material's purchase unit when blank.
    for item in PurchaseOrderItem.objects.filter(purchase_unit__isnull=True).select_related('raw_material'):
        pu = getattr(item.raw_material, 'purchase_unit_id', None) or getattr(item.raw_material, 'stock_unit_id', None)
        if pu:
            PurchaseOrderItem.objects.filter(pk=item.pk).update(purchase_unit_id=pu)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0045_purchaseorderitem_purchase_unit_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_units_and_backfill, noop),
    ]
