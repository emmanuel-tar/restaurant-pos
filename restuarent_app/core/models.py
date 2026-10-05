from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db.models import Max
from django.utils import timezone
from django.db import IntegrityError, transaction
import logging

from django.db import models
from django.db.models import Max
from django.conf import settings
from django.utils import timezone
import datetime

logger = logging.getLogger(__name__)

# ---------- User & Roles (unchanged) ----------
class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('cashier', 'Cashier'),
        ('kitchen', 'Kitchen'),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='cashier')

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, unique=True, help_text="Primary identifier for Udhaar")
    address = models.TextField(blank=True, null=True)
    
    # Positive balance = Customer owes restaurant (Udhaar)
    # Negative balance = Restaurant owes customer (Advance)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.phone})"
    
    @property
    def abs_balance(self):
        """Returns the absolute value of the balance (removes negative sign)."""
        return abs(self.current_balance)
    

class Unit(models.Model):
    UNIT_TYPES = [
        ('mass', 'Mass'),
        ('volume', 'Volume'),
        ('count', 'Count'),
    ]
    name   = models.CharField(max_length=50, unique=True, help_text="e.g. Gram, Teaspoon, Piece")
    symbol = models.CharField(max_length=10, unique=True, help_text="e.g. g, tsp, pc")
    unit_type = models.CharField(max_length=10, choices=UNIT_TYPES)

    def __str__(self):
        return self.symbol

    # Base units per family: everything converts through these.
    # Mass -> gram, Volume -> millilitre, Count -> piece.
    BASE_UNIT = {'mass': 'g', 'volume': 'ml', 'count': 'pc'}
    # to_base_factor: multiply an amount in `symbol` to get base units.
    FACTORS = {
        # mass (base g)
        'kg': 1000, 'g': 1, 'mg': 0.001, 'lb': 453.592, 'oz': 28.3495,
        # volume (base ml)
        'l': 1000, 'ml': 1, 'tbsp': 15, 'tsp': 5, 'cup': 240,
        'floz': 29.5735, 'gal': 3785.41,
        # count (base pc) - pack sizes configured per material via pack_size
        'pc': 1, 'pcs': 1, 'doz': 12, 'box': 1, 'pack': 1, 'bag': 1, 'bottle': 1, 'can': 1,
    }

    @classmethod
    def to_base_factor(cls, symbol) -> float:
        """Multiply an amount in `symbol` to get base units (g/ml/pc)."""
        if symbol is None:
            return 1
        s = (getattr(symbol, 'symbol', None) or str(symbol)).strip().lower()
        if not s:
            return 1
        if s in cls.FACTORS:
            return cls.FACTORS[s]
        try:
            return float(Unit.objects.filter(symbol__iexact=s).values_list('id', flat=True).first() and 1 or 1)
        except Exception:
            return 1

    @classmethod
    def base_symbol_for(cls, unit_type):
        return cls.BASE_UNIT.get(unit_type or '', '')

    @classmethod
    def convert(cls, qty, from_symbol, to_symbol):
        """Convert qty from one symbol to another within the same family."""
        from decimal import Decimal
        fs = (getattr(from_symbol, 'symbol', None) or str(from_symbol or '')).strip().lower()
        ts = (getattr(to_symbol, 'symbol', None) or str(to_symbol or '')).strip().lower()
        if not fs or not ts or fs == ts:
            return Decimal(str(qty or 0))
        f = Decimal(str(cls.to_base_factor(fs)))
        t = Decimal(str(cls.to_base_factor(ts)))
        if not t:
            return Decimal('0')
        return (Decimal(str(qty or 0)) * f / t)

    @classmethod
    def ensure_defaults(cls):
        """Seed the standard restaurant unit master (idempotent)."""
        defaults = [
            ('Kilogram', 'kg', 'mass'), ('Gram', 'g', 'mass'),
            ('Milligram', 'mg', 'mass'), ('Pound', 'lb', 'mass'), ('Ounce', 'oz', 'mass'),
            ('Litre', 'l', 'volume'), ('Millilitre', 'ml', 'volume'),
            ('Tablespoon', 'tbsp', 'volume'), ('Teaspoon', 'tsp', 'volume'),
            ('Cup', 'cup', 'volume'), ('Fluid Ounce', 'floz', 'volume'),
            ('Piece', 'pc', 'count'), ('Dozen', 'doz', 'count'),
            ('Pack', 'pack', 'count'), ('Box', 'box', 'count'),
            ('Bag', 'bag', 'count'), ('Bottle', 'bottle', 'count'), ('Can', 'can', 'count'),
        ]
        for name, symbol, typ in defaults:
            cls.objects.get_or_create(symbol=symbol, defaults={'name': name, 'unit_type': typ})



class PrintStation(models.Model):
    name = models.CharField(max_length=100, unique=True, help_text="e.g. Main Kitchen, BBQ Section, Bar")
    printer_name = models.CharField(max_length=200, blank=True, null=True, help_text="Windows Printer Name (optional)")
    
    # Feature: Separate Token Slip
    print_separate_slip = models.BooleanField(default=True, help_text="If True, items for this station print on a separate paper slip.")
    
    # Feature: Separate Counting Sequence (1, 2, 3...)
    use_separate_sequence = models.BooleanField(default=False, help_text="If True, this station has its own Token #1, #2... independent of Main Kitchen.")

    def __str__(self):
        return self.name
    

class RawMaterialUnitConversion(models.Model):
    raw_material = models.ForeignKey('RawMaterial', on_delete=models.CASCADE, related_name='conversions')
    unit         = models.ForeignKey(Unit, on_delete=models.PROTECT)
    to_base_factor = models.DecimalField(
        max_digits=12, decimal_places=6,
        help_text="Multiply this unit amount by factor to get grams (for mass) or ml (for volume)"
    )

    class Meta:
        unique_together = ('raw_material', 'unit')

    def __str__(self):
        return f"1 {self.unit.symbol} = {self.to_base_factor} base"


class Waiter(models.Model):
    name = models.CharField(max_length=100)
    employee_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.employee_id})"
    
# ---------- Categories & Menu ----------
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    show_in_orders = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    rank = models.IntegerField(null=True, blank=True)
    
    # Default station for items in this category
    default_station = models.ForeignKey(PrintStation, on_delete=models.SET_NULL, null=True, blank=True, related_name="categories")

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name
    

class MenuItem(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    food_panda_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_available = models.BooleanField(default=True)
    image = models.ImageField(upload_to='menu_items/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    rank = models.IntegerField(null=True, blank=True)

    # Inventory tracking fields
    weight = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True, help_text="Weight/quantity of the item")
    
    UNIT_CHOICES = [
        ('kg', 'Kilogram'),
        ('g', 'Gram'),
        ('l', 'Liter'),
        ('ml', 'Milliliter'),
        ('pcs', 'Pieces'),
        ('doz', 'Dozen'),
        ('box', 'Box'),
        ('pack', 'Pack'),
    ]
    unit = models.CharField(max_length=10, choices=UNIT_CHOICES, null=True, blank=True, help_text="Unit of measurement")

    # Allow overriding station per item
    station = models.ForeignKey(PrintStation, on_delete=models.SET_NULL, null=True, blank=True, related_name="menu_items")

    def __str__(self):
        return f"{self.name} â€“ {self.category.name}"

    def get_effective_station(self):
        """Returns item specific station, or falls back to category station."""
        if self.station:
            return self.station
        if self.category.default_station:
            return self.category.default_station
        return None
    
    def get_weight_display(self):
        """Returns formatted weight with unit."""
        if self.weight and self.unit:
            return f"{self.weight} {self.get_unit_display()}"
        return None
    

# ---------- Deals (New) ----------
# ---------- Menu Item Modifiers ----------
class ModifierGroup(models.Model):
    """
    A group of options attached to menu items, e.g. "Size", "Spice Level",
    "Add-ons". A group can be required (must pick), optional, or single-choice.
    """
    name = models.CharField(max_length=100, unique=True, help_text="e.g. Size, Add-ons, Spice Level")
    min_select = models.PositiveIntegerField(
        default=0, help_text="How many the cashier must pick. 0 = optional")
    max_select = models.PositiveIntegerField(
        default=1, help_text="Maximum allowed. 1 = single choice, higher = pick several")
    active = models.BooleanField(default=True)
    menu_items = models.ManyToManyField(
        MenuItem, blank=True, related_name='modifier_groups',
        help_text="Menu items that offer this group. Leave empty to apply to every item.")
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def is_required(self):
        return self.min_select > 0

    def applies_to(self, menu_item):
        """True when this group should be offered for the given menu item."""
        if not self.active:
            return False
        item_ids = self.menu_items.values_list('id', flat=True)
        return not item_ids.exists() or menu_item.id in item_ids


class Modifier(models.Model):
    """One selectable option inside a ModifierGroup (e.g. Large, Extra Cheese)."""
    group = models.ForeignKey(ModifierGroup, on_delete=models.CASCADE, related_name='options')
    name = models.CharField(max_length=100)
    price = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Added to the item price. Use 0 for no extra cost, negative to reduce.")
    active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        unique_together = [('group', 'name')]

    def __str__(self):
        return f"{self.name} ({self.group.name})"


class Deal(models.Model):
    """
    A Deal bundles multiple MenuItems (with quantities).
    The price is set at creation time and overrides individual item sum.
    """
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2,
                                help_text="Total price for this deal")
    cost_price  = models.DecimalField(
                      max_digits=10,
                      decimal_places=2,
                      default=0,
                      help_text="Sum of ingredients' cost"
                  )
    food_panda_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_available = models.BooleanField(default=True)
    image = models.ImageField(upload_to='deals/', blank=True, null=True)
    items = models.ManyToManyField(
        MenuItem,
        through='DealItem',
        related_name='deals'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    rank = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (Deal)"


class DealItem(models.Model):
    """
    The intermediate table linking a Deal to its MenuItems (with quantity).
    """
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name='deal_items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.quantity} x {self.menu_item.name} in {self.deal.name}"


# ---------- Tables & Orders ----------
class Table(models.Model):
    number = models.PositiveIntegerField(unique=True)
    seats = models.PositiveIntegerField(default=4)
    is_occupied = models.BooleanField(default=False)

    def __str__(self):
        return f"Table {self.number} ({self.seats} seats)"


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),       
        ('in_kitchen', 'In Kitchen'),
        ('served', 'Served'),
        ('paid', 'Paid'),
        ('food_panda', 'Food Panda'),  
    ]
    waiter = models.ForeignKey(
        Waiter,
        on_delete=models.PROTECT,
        related_name="orders",
        null=True, blank=True,
        help_text="Who took this order"
    )
    isHomeDelivery = models.CharField(max_length=10, null=True, blank=True, default="no")
    # Order number is autogenerated on save
    number = models.CharField(max_length=20, unique=True, blank=True)
    table = models.ForeignKey(Table, on_delete=models.PROTECT,
                              related_name='orders', null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                   related_name='orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    customer_name = models.CharField(max_length=50, null=True, blank=True)
    mobile_no = models.CharField(max_length=20, null=True, blank=True)
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")
    customer_address = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Token number resets each day at 12:00 PM
    token_number = models.PositiveIntegerField(default=0, blank=True, null=True)

    source = models.CharField(max_length=20, choices=[('food_panda', 'Food Panda'), ('walk_in','Walk-in')], null=True, blank=True)

    def __str__(self):
        return f"Order #{self.number} â€“ {self.get_status_display()}"

    # ---------- Taxes (multiple, optional) ----------
    def get_subtotal(self):
        """Sum of all line totals, modifiers included."""
        from decimal import Decimal
        return sum((i.line_total() for i in self.items.all()), Decimal('0'))

    def get_tax_lines(self):
        """Tax lines applied to this order (may be empty for orders using the legacy field)."""
        return self.tax_lines.all()

    def get_tax_total(self):
        """
        Total tax charged on this order.

        Prefers the tax_lines table (supports several taxes). Falls back to the
        legacy single tax_percentage field for orders created before this existed,
        so historical bills keep calculating exactly as they always did.
        """
        from decimal import Decimal
        lines = list(self.tax_lines.all())
        if lines:
            return sum((l.amount for l in lines), Decimal('0'))
        base = self.get_subtotal() - (self.discount or Decimal('0'))
        if base < 0:
            base = Decimal('0')
        return ((base * (self.tax_percentage or Decimal('0'))) / Decimal('100')).quantize(Decimal('0.01'))

    def get_total(self):
        """Grand total: subtotal - discount + taxes + service charge."""
        from decimal import Decimal
        base = self.get_subtotal() - (self.discount or Decimal('0'))
        if base < 0:
            base = Decimal('0')
        return base + self.get_tax_total() + (self.service_charge or Decimal('0'))

    def apply_tax(self, tax_rate):
        """
        Add a tax from the TaxRate catalogue to this order, replacing any existing
        line for that same tax (so switching a tax on/off is safe to repeat).
        """
        from decimal import Decimal
        base = self.get_subtotal() - (self.discount or Decimal('0'))
        if base < 0:
            base = Decimal('0')
        line, _ = OrderTax.objects.update_or_create(
            order=self,
            tax_rate=tax_rate,
            defaults={
                'name': tax_rate.name,
                'rate': tax_rate.rate,
                'fixed_amount': tax_rate.fixed_amount,
                'tax_type': tax_rate.tax_type,
                'amount': tax_rate.compute_amount(base),
            },
        )
        # Keep the legacy tax_percentage field in sync so older screens/reports
        # that still read it continue to show the right tax.
        self.recalculate_taxes()
        return line

    def remove_tax(self, tax_rate):
        """Remove a tax line from this order."""
        self.tax_lines.filter(tax_rate=tax_rate).delete()
        self.recalculate_taxes()

    def clear_taxes(self):
        self.tax_lines.all().delete()

    def recalculate_taxes(self):
        """
        Recompute every tax line against the current subtotal/discount, and keep the
        legacy tax_percentage field in sync (sum of percentage taxes) so older
        screens and reports continue to show the correct tax.
        """
        from decimal import Decimal
        base = self.get_subtotal() - (self.discount or Decimal('0'))
        if base < 0:
            base = Decimal('0')

        percent_total = Decimal('0')
        for line in self.tax_lines.select_related('tax_rate').all():
            if line.tax_type == 'fixed':
                line.amount = line.fixed_amount
            else:
                taxable = base if (line.tax_rate and line.tax_rate.applies_after_discount) else self.get_subtotal()
                line.amount = ((taxable * (line.rate or Decimal('0'))) / Decimal('100')).quantize(Decimal('0.01'))
                percent_total += line.rate or Decimal('0')
            line.save(update_fields=['amount'])

        if self.tax_lines.exists():
            self.tax_percentage = percent_total
            super().save(update_fields=['tax_percentage'])
        return self.get_tax_total()

    # ---------- Display helpers (bills, receipts, screens) ----------
    def tax_display_lines(self):
        """
        The tax lines to print on a bill/receipt/detail screen.

        Normally the saved OrderTax rows. Orders created before multi-tax support
        have no rows, so one synthetic line is built from the legacy tax_percentage
        field and old bills keep printing exactly what they always printed.
        """
        from decimal import Decimal
        lines = list(self.tax_lines.all())
        if lines:
            return lines
        percentage = self.tax_percentage or Decimal('0')
        if not percentage:
            return []
        return [OrderTax(
            order=self,
            name='Tax',
            rate=percentage,
            tax_type='percent',
            amount=self.get_tax_total(),
        )]
    
    def save(self, *args, **kwargs):
        import time, random
        from django.db import IntegrityError, transaction
        from django.utils import timezone
        
        # Import the new utilities for dynamic timing and tokens
        # Ensure core/utils.py exists with the code provided in the previous step
        from .utils import get_business_date, get_next_token_number

        logger.debug(f"Order save started for {self.number} at {timezone.now()}")

        # Pin created_at for stable window math (auto_now_add will set DB value; this keeps our logic stable)
        if not self.created_at:
            self.created_at = timezone.localtime(timezone.now())

        # Only auto-generate if missing
        if not self.number:
            # === CHANGED: Use dynamic business date from settings ===
            # This replaces the hardcoded "noon_today" logic to support any start time (e.g. 6AM)
            business_date = get_business_date(self.created_at)

            prefix = f"ORD{business_date:%Y%m%d}"

            # Retry to avoid race on unique(number)
            max_attempts = 25
            backoff = 0.01

            for attempt in range(1, max_attempts + 1):
                try:
                    with transaction.atomic():
                        # Find the last sequence for *this prefix*, ignoring created_at.
                        last_with_prefix = (
                            Order.objects
                            .select_for_update()  # effective on Postgres/MySQL; harmless on SQLite
                            .filter(number__startswith=prefix)
                            .order_by('-number')
                            .first()
                        )

                        if last_with_prefix and '-' in last_with_prefix.number:
                            try:
                                last_seq = int(last_with_prefix.number.rsplit('-', 1)[-1])
                            except ValueError:
                                last_seq = 0
                        else:
                            last_seq = 0

                        # Next order number
                        self.number = f"{prefix}-{last_seq + 1:04d}"

                        # â”€â”€ TOKEN: only if one wasn't pre-supplied (tables pass session token) â”€â”€
                        if not self.token_number:
                            # === CHANGED: Use the centralized token utility ===
                            # This ensures it respects the dynamic day start time and global sequence
                            # station=None means it grabs the "Global/Main" token number
                            self.token_number = get_next_token_number(station=None)
                            
                        logger.debug(f"Attempt {attempt}: number={self.number}, token={self.token_number}")
                        super().save(*args, **kwargs)
                    break  # success
                except IntegrityError as e:
                    # If number collided, back off and try the next sequence
                    if 'core_order.number' in str(e):
                        time.sleep(random.uniform(backoff, backoff * 4))
                        # Exponential-ish backoff cap
                        backoff = min(backoff * 1.5, 0.2)
                        continue
                    raise
            else:
                # Extremely unlikely unless >25 concurrent collisions
                raise IntegrityError("Could not generate a unique Order.number after multiple attempts.")
        else:
            super().save(*args, **kwargs)

        logger.debug(f"Token number set to {self.token_number}")

from decimal import Decimal

class OrderItemModifier(models.Model):
    """
    A modifier chosen for a line on an order. Name/price are snapshotted so that
    later edits to the modifier definition never rewrite past bills.
    """
    order_item = models.ForeignKey('OrderItem', on_delete=models.CASCADE, related_name='modifiers')
    modifier = models.ForeignKey(Modifier, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="order_item_modifiers")
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Order Item Modifier"
        verbose_name_plural = "Order Item Modifiers"

    def __str__(self):
        return self.name


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT, null=True, blank=True)
    deal = models.ForeignKey(Deal, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    token_printed = models.BooleanField(default=False)
    printed_quantity = models.PositiveIntegerField(default=0)

    def modifiers_total(self):
        """Combined price of every modifier chosen on this line."""
        from decimal import Decimal
        return sum((m.price for m in self.modifiers.all()), Decimal('0'))

    def effective_unit_price(self):
        """Unit price including modifiers (modifiers are charged per item)."""
        from decimal import Decimal
        return (self.unit_price or Decimal('0')) + self.modifiers_total()

    def line_total(self):
        return self.quantity * self.effective_unit_price()

    def modifier_summary(self):
        """Readable list of the modifiers chosen on this line, e.g. 'Large + Extra Cheese'."""
        return ' + '.join(m.name for m in self.modifiers.all())

    def update_inventory_usage(self):
        """Deduct raw materials for this line via the standard costing engine.

        Uses costing.usage_map() so yield, wastage, unit conversion and nested
        sub-recipes are honoured. Deals explode into their component menu items.
        Quantity stored on the transaction is in each material's STOCK unit.
        """
        from .costing import usage_map
        targets = []
        if self.menu_item_id:
            targets.append((self.menu_item, self.quantity or 0))
        elif self.deal_id:
            try:
                for di in self.deal.items.through.objects.filter(deal_id=self.deal_id).select_related('menu_item'):
                    targets.append((di.menu_item, (self.quantity or 0) * (di.quantity or 0)))
            except Exception:
                return
        else:
            return
        for menu_item, qty in targets:
            if not menu_item or not qty:
                continue
            try:
                recipe = menu_item.recipe
            except Exception:
                continue
            if recipe is None:
                continue
            try:
                usage = usage_map(recipe, portions=qty)
            except Exception:
                continue
            from decimal import Decimal
            for rm_id, need in usage.items():
                try:
                    rm = RawMaterial.objects.get(pk=rm_id)
                except RawMaterial.DoesNotExist:
                    continue
                used = need.quantize(Decimal('0.01')) if need else Decimal('0')
                if not used:
                    continue
                InventoryTransaction.objects.create(
                    raw_material=rm,
                    transaction_type='out',
                    quantity=used,
                    order_item=self,
                    notes=f"Used in {menu_item.name} (Order #{self.order.number})",
                )

    def reverse_inventory_usage(self):
        """Return previously deducted stock (used when a line is edited/deleted).

        Rows are removed one at a time on purpose: QuerySet.delete() performs a
        bulk delete that *skips* InventoryTransaction.delete(), and that override
        is what actually credits the stock back. Using the queryset here left
        stock permanently short every time a line was edited or voided.
        """
        for txn in list(InventoryTransaction.objects.filter(
                order_item=self, transaction_type='out')):
            txn.delete()

    def save(self, *args, **kwargs):
        # Save the OrderItem first
        super().save(*args, **kwargs)

        # Then update inventory usage
        self.update_inventory_usage()

    def __str__(self):
        if self.deal:
            return f"{self.quantity} x {self.deal.name} (Deal)"
        return f"{self.quantity} x {self.menu_item.name}"

# ---------- Payments & Billing ----------
class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('credit', 'Credit / Udhaar'),
        ('jazz cash', 'Jazz Cash'),
        ('easypaisa', 'Easypaisa'),
        ('bank', 'Bank'),
        ('card', 'Card'),
    ]
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    details = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment for Order #{self.order.number} â€“ {self.get_method_display()}"


# ---------- Settings & Configuration (unchanged) ----------
class TaxRate(models.Model):
    """
    A reusable tax that can be applied to orders (VAT, WHT, Service Levy, ...).
    Several may be active at once; each order keeps its own snapshot of the
    taxes actually charged, so later edits here never rewrite past bills.
    """
    TAX_TYPES = [
        ('percent', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ]

    name = models.CharField(max_length=100, unique=True, help_text="e.g. VAT, WHT, Service Levy")
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                               help_text="Percent, e.g. 7.50 for 7.5% (used when type is Percentage)")
    fixed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                       help_text="Flat amount added to the bill (used when type is Fixed Amount)")
    tax_type = models.CharField(max_length=10, choices=TAX_TYPES, default='percent')
    active = models.BooleanField(default=True, help_text="Uncheck to hide from new orders (existing orders keep it)")
    is_default = models.BooleanField(default=False, help_text="Pre-selected when creating a new order")
    is_optional = models.BooleanField(default=True, help_text="Cashier may switch this tax off for an order")
    applies_after_discount = models.BooleanField(
        default=True, help_text="Calculate on the discounted subtotal instead of the full subtotal")
    sort_order = models.IntegerField(default=0, help_text="Lower numbers are applied/applied first")

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name = "Tax"
        verbose_name_plural = "Taxes"

    def __str__(self):
        if self.tax_type == 'fixed':
            return f"{self.name} (fixed)"
        return f"{self.name} ({self.rate}%)"

    def compute_amount(self, taxable_base):
        """Amount this tax adds to the given base (discounted subtotal)."""
        from decimal import Decimal
        base = Decimal(str(taxable_base or 0))
        if self.tax_type == 'fixed':
            return self.fixed_amount
        return (base * (self.rate or Decimal('0')) / Decimal('100')).quantize(Decimal('0.01'))


class OrderTax(models.Model):
    """
    A tax line applied to one order. Name/rate are snapshotted from TaxRate at the
    time of sale so historical bills never change when a tax is edited later.
    """
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='tax_lines')
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="order_taxes")
    name = models.CharField(max_length=100)
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fixed_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_type = models.CharField(max_length=10, choices=TaxRate.TAX_TYPES, default='percent')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name = "Order Tax Line"
        verbose_name_plural = "Order Tax Lines"

    def __str__(self):
        return f"{self.name} on Order #{self.order.number}: {self.amount}"


class OrderHold(models.Model):
    """
    A parked ("held") order.

    A cashier building a long bill can park it here and start another one, then
    recall it later without losing a single line. The items are stored as a JSON
    snapshot - deliberately *not* a real Order - so a held bill never consumes
    stock, never gets a token number and never shows up in the day's sales.
    """
    label = models.CharField(
        max_length=80,
        help_text='Short name the cashier will recognise, e.g. "Table 5 - Rahim"',
    )
    table = models.ForeignKey(
        Table, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='holds', help_text='Optional table this bill belongs to',
    )
    items = models.JSONField(default=list, help_text='Snapshot of the cart lines')
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_ids = models.JSONField(default=list, help_text='Taxes ticked when the bill was parked')
    is_active = models.BooleanField(
        default=True, help_text='Uncheck once the held bill has been served',
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='order_holds')
    created_at = models.DateTimeField(auto_now_add=True)
    recalled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Held Order'
        verbose_name_plural = 'Held Orders'

    def __str__(self):
        return f'{self.label} ({self.created_at:%d-%b %H:%M})'

    @property
    def item_count(self):
        """How many lines the held bill has, shown in the recall list."""
        return len(self.items or [])

    @property
    def total(self):
        """Snapshot subtotal, recomputed from the parked lines."""
        from decimal import Decimal
        total = Decimal('0')
        for line in self.items or []:
            try:
                unit = Decimal(str(line.get('unit_price', 0) or 0))
                quantity = Decimal(str(line.get('quantity', 1) or 1))
                modifiers = Decimal(str(line.get('modifiers_total', 0) or 0))
            except Exception:
                continue
            total += quantity * (unit + modifiers)
        return total


class DiscountRule(models.Model):
    name = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=10, decimal_places=2,
                                 help_text="Fixed amount or % based on is_percentage")
    is_percentage = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    def __str__(self):
        disc = f"{self.amount}%" if self.is_percentage else f"{self.amount}"
        return f"{self.name} ({disc})"


class POSSettings(models.Model):
    restaurant_name = models.CharField(max_length=200)
    logo = models.ImageField(upload_to='settings/', blank=True, null=True)
    theme_color = models.CharField(max_length=7, default='#ff5722')
    
    # Feature: Configurable Day Start Time
    start_of_day_time = models.TimeField(default=datetime.time(6, 0), help_text="The time a new business day starts (e.g., 06:00 AM or 12:00 PM). Token numbers reset at this time.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.restaurant_name


class PrintStatus(models.Model):
    token = models.BooleanField(default=False)
    bill  = models.BooleanField(default=False)

    def __str__(self):
        return f"PrintStatus(token={self.token}, bill={self.bill})"


class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class RawMaterial(models.Model):
    name = models.CharField(max_length=100, unique=True)
    # Legacy free-text unit (kept for migration compat, synced from stock_unit).
    unit = models.CharField(max_length=50, help_text="E.g. kg, liter, pc")
    # Standard costing units: stock_unit is what inventory is tracked in,
    # purchase_unit is what suppliers sell in (converted via pack_size / Unit factors).
    stock_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='stock_materials', null=True, blank=True)
    purchase_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='purchase_materials', null=True, blank=True)
    pack_size = models.DecimalField(max_digits=12, decimal_places=3, default=1,
        help_text="How many stock units are in one purchase unit (e.g. 1 bag = 25000 g).")
    current_stock = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reorder_level = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="materials")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        sym = getattr(self.stock_unit, 'symbol', None) or self.unit
        return f"{self.name} ({sym})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.stock_unit and self.purchase_unit:
            if self.stock_unit.unit_type != self.purchase_unit.unit_type:
                # Allow count<->mass/volume only via pack_size? No: block mismatched families.
                raise ValidationError('Stock and purchase units must be the same family (mass/volume/count).')
        if (self.pack_size or 0) <= 0:
            raise ValidationError('Pack size must be greater than zero.')

    def save(self, *args, **kwargs):
        # Keep legacy `unit` text in sync so old templates/reports keep working.
        if self.stock_unit_id:
            try:
                sym = Unit.objects.filter(pk=self.stock_unit_id).values_list('symbol', flat=True).first()
                if sym:
                    self.unit = sym
            except Exception:
                pass
        super().save(*args, **kwargs)

    @property
    def stock_symbol(self):
        return getattr(self.stock_unit, 'symbol', None) or self.unit

    @property
    def avg_cost_per_stock_unit(self):
        try:
            from .costing import raw_avg_cost
            return raw_avg_cost(self)
        except Exception:
            from decimal import Decimal as _D
            return _D('0')

    @property
    def latest_cost_per_stock_unit(self):
        try:
            from .costing import latest_price
            return latest_price(self)
        except Exception:
            from decimal import Decimal as _D2
            return _D2('0')

    # ---------- Low stock helpers ----------
    @property
    def is_low_stock(self):
        """True when stock has fallen to (or below) the reorder level."""
        return self.current_stock <= self.reorder_level

    @property
    def is_out_of_stock(self):
        return self.current_stock <= 0

    @property
    def stock_status(self):
        if self.is_out_of_stock:
            return 'out'
        if self.is_low_stock:
            return 'low'
        return 'ok'

    @property
    def shortage(self):
        """How much is missing to get back to the reorder level."""
        from decimal import Decimal
        gap = (self.reorder_level or Decimal('0')) - (self.current_stock or Decimal('0'))
        return gap if gap > 0 else Decimal('0')

    @property
    def suggested_order_qty(self):
        """
        A sensible quantity to order: top the item up to twice its reorder level,
        so there is room before the next delivery.
        """
        from decimal import Decimal
        level = self.reorder_level or Decimal('0')
        if level <= 0:
            return Decimal('0')
        target = level * 2
        gap = target - (self.current_stock or Decimal('0'))
        return gap if gap > 0 else Decimal('0')

    @property
    def estimated_cost(self):
        """Cost of the suggested order using the most recent purchase price."""
        from decimal import Decimal
        last = self.purchaseorderitem_set.order_by('-id').first()
        if not last:
            return Decimal('0')
        return self.suggested_order_qty * (last.unit_price or Decimal('0'))



from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

# core/models.py  (add fields to your existing PurchaseOrder)
class PurchaseOrder(models.Model):
    supplier   = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="purchase_orders")
    created_at = models.DateTimeField(auto_now_add=True)

    # Existing:
    total_cost  = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # treat as Subtotal (sum of lines)
    status      = models.CharField(max_length=20, choices=[('pending','Pending'), ('received','Received')], default='received')

    # NEW (all optional with defaults)
    tax_percent       = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # e.g. 5.00 (%)
    discount_percent  = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # e.g. 10.00 (%)
    net_total         = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # computed subtotal + tax - discount

    def __str__(self):
        return f"PO #{self.id} - {self.supplier.name}"

    def recompute_totals(self):
        """
        Recalculate subtotal (total_cost) from items and recompute net_total
        using % tax and % discount. Keeps compatibility with existing code that
        reads/writes `total_cost`.
        """
        from decimal import Decimal, ROUND_HALF_UP
        subtotal = sum((it.total_cost() for it in self.items.all()), Decimal('0'))
        self.total_cost = subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        tax_amt = (self.total_cost * (self.tax_percent or 0) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        disc_amt = (self.total_cost * (self.discount_percent or 0) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        self.net_total = (self.total_cost + tax_amt - disc_amt).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def calculate_total_cost(self):  # keep your old API intact
        self.recompute_totals()
        self.save(update_fields=['total_cost', 'net_total'])

    def mark_received(self):
        """
        Flag this purchase order as received.

        Stock is already added when each line is first saved, so this only
        updates the status - it must not add stock again or stock is double counted.
        """
        if self.status != 'received':
            self.status = 'received'
            self.save(update_fields=['status'])
        return self

    def delete(self, *args, **kwargs):
        """Delete the PO and hand the stock back.

        Each line has to be deleted individually: Django's cascade collector does
        a bulk delete which skips PurchaseOrderItem.delete(), and that override is
        what writes the 'return' row that removes the stock this PO added.
        Deleting the header alone left stock permanently inflated.
        """
        for item in list(self.items.all()):
            item.delete()
        return super().delete(*args, **kwargs)


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE,
                                       related_name='items')
    raw_material   = models.ForeignKey(RawMaterial, on_delete=models.PROTECT)
    quantity       = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price     = models.DecimalField(max_digits=10, decimal_places=2)
    # Unit the supplier sells in; stock added = quantity x pack/unit conversion.
    purchase_unit  = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name='po_lines', null=True, blank=True)

    def total_cost(self):
        return self.quantity * self.unit_price

    @property
    def stock_qty(self):
        """Quantity converted into the material's stock unit."""
        from decimal import Decimal
        from .costing import conversion_factor
        rm = self.raw_material
        pu = self.purchase_unit or getattr(rm, 'purchase_unit', None) or getattr(rm, 'stock_unit', None)
        f = conversion_factor(pu, rm.stock_unit)
        if not f:
            # purchase_unit and stock_unit in different families: use pack_size.
            try:
                f = Decimal(str(getattr(rm, 'pack_size', 1) or 1))
            except Exception:
                f = Decimal('1')
        return (Decimal(str(self.quantity or 0)) * f)

    @property
    def unit_price_per_stock(self):
        from decimal import Decimal
        sq = self.stock_qty
        if not sq:
            return Decimal('0')
        return (Decimal(str(self.quantity or 0)) * Decimal(str(self.unit_price or 0)) / sq)

    def save(self, *args, **kwargs):
        if not self.purchase_unit_id:
            try:
                rm = RawMaterial.objects.filter(pk=self.raw_material_id).first()
                if rm is not None and rm.purchase_unit_id:
                    self.purchase_unit_id = rm.purchase_unit_id
            except Exception:
                pass
        is_new = self._state.adding
        super().save(*args, **kwargs)
        # Add stock only the FIRST time this line is saved. Without the
        # _state.adding guard every later edit re-added the same quantity
        # and quietly inflated stock levels. Quantity is stored in STOCK units.
        if is_new:
            InventoryTransaction.objects.create(
                raw_material       = self.raw_material,
                transaction_type   = 'in',
                quantity           = self.stock_qty,
                purchase_order_item= self,
                notes              = f"PO #{self.purchase_order_id}"
            )
    def delete(self, *args, **kwargs):
        # Undo the stock this line added. Simply writing a 'return' row is wrong:
        # 'return' ADDS stock while the original 'in' row survives (its FK is
        # SET_NULL, not CASCADE), so the quantity was counted twice and deleting
        # a PO line inflated levels instead of reversing them. Deleting the 'in'
        # row restores the stock exactly - one at a time, because QuerySet.delete()
        # would skip InventoryTransaction.delete() and its F() reversal.
        for txn in list(InventoryTransaction.objects.filter(
                purchase_order_item=self, transaction_type='in')):
            txn.delete()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.quantity} x {self.raw_material.name}"
    

class Recipe(models.Model):
    menu_item  = models.OneToOneField(MenuItem, on_delete=models.CASCADE,
                                      related_name='recipe')
    name       = models.CharField(max_length=150, blank=True)
    # Standard production fields: one recipe batch makes yield_qty portions;
    # wastage_percent inflates the true cost per portion.
    yield_qty = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    yield_unit = models.CharField(max_length=20, default='portion')
    wastage_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    instructions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Recipe for {self.menu_item.name}"

    def cost_breakdown(self):
        from .costing import recipe_breakdown
        return recipe_breakdown(self)

    @property
    def estimated_cost(self):
        from .costing import recipe_cost
        return recipe_cost(self)

    @property
    def cost_per_portion(self):
        return self.estimated_cost

    def refresh_menu_cost(self):
        from .costing import refresh_cost
        return refresh_cost(self.menu_item)

    def total_grams(self):
        """Legacy helper (kept for compat). Use cost_breakdown() instead."""
        try:
            bd = self.cost_breakdown()
            return float(sum((l.get('stock_qty') or 0) for l in bd['lines']))
        except Exception:
            return 0

class RecipeRawMaterial(models.Model):
    recipe       = models.ForeignKey(Recipe, on_delete=models.CASCADE,
                                     related_name='raw_ingredients')
    raw_material = models.ForeignKey(RawMaterial, on_delete=models.PROTECT)
    quantity     = models.DecimalField(max_digits=10, decimal_places=3,
                                       help_text="Use decimals for fractions, e.g. 0.25")
    unit         = models.ForeignKey(Unit, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.quantity} {self.unit.symbol} of {self.raw_material.name}"

class RecipeSubRecipe(models.Model):
    recipe     = models.ForeignKey(Recipe, on_delete=models.CASCADE,
                                   related_name='subrecipes')
    sub_recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT)
    # Quantity is in PORTIONS of the sub-recipe (not a weight unit).
    quantity   = models.DecimalField(max_digits=10, decimal_places=3)
    unit       = models.ForeignKey(Unit, on_delete=models.PROTECT, null=True, blank=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.recipe_id and self.sub_recipe_id and self.recipe_id == self.sub_recipe_id:
            raise ValidationError('A recipe cannot contain itself.')

    def __str__(self):
        return f"{self.quantity} portion(s) of {self.sub_recipe.menu_item.name}"

class InventoryTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('in', 'Stock In'),
        ('out','Stock Out'),
        ('return','Stock Return'),
    ]
    date = models.DateField(default=timezone.localdate, null=True, blank=True)
    raw_material        = models.ForeignKey(RawMaterial, on_delete=models.CASCADE,
                                            related_name='transactions', null=True, blank=True)
    transaction_type    = models.CharField(max_length=6, choices=TRANSACTION_TYPES)
    quantity            = models.DecimalField(max_digits=10, decimal_places=2)
    timestamp           = models.DateTimeField(auto_now_add=True)
    notes               = models.TextField(blank=True)
    # optional backâ€links
    purchase_order_item = models.ForeignKey(PurchaseOrderItem,
                                            on_delete=models.SET_NULL,
                                            null=True, blank=True)
    order_item          = models.ForeignKey(OrderItem,
                                            on_delete=models.SET_NULL,
                                            null=True, blank=True)

    def save(self, *args, **kwargs):
        from decimal import Decimal
        from django.db.models import F
        super().save(*args, **kwargs)
        # Maintain current_stock atomically so parallel sales cannot lose updates.
        qty = self.quantity or Decimal('0')
        if self.transaction_type == 'in':
            RawMaterial.objects.filter(pk=self.raw_material_id).update(current_stock=F('current_stock') + qty)
        elif self.transaction_type in ['out']:
            RawMaterial.objects.filter(pk=self.raw_material_id).update(current_stock=F('current_stock') - qty)
        elif self.transaction_type == 'return':
            RawMaterial.objects.filter(pk=self.raw_material_id).update(current_stock=F('current_stock') + qty)

    def delete(self, *args, **kwargs):
        from decimal import Decimal
        from django.db.models import F
        qty = self.quantity or Decimal('0')
        pk = self.raw_material_id
        super().delete(*args, **kwargs)
        # Deleting an 'out' row returns the stock (used by order-edit reversal).
        if self.transaction_type == 'out':
            RawMaterial.objects.filter(pk=pk).update(current_stock=F('current_stock') + qty)
        elif self.transaction_type in ('in', 'return'):
            RawMaterial.objects.filter(pk=pk).update(current_stock=F('current_stock') - qty)

    def __str__(self):
        return f"{self.get_transaction_type_display()} â€“ {self.raw_material.name}: {self.quantity} {self.raw_material.unit}"


from django.db.models.signals import post_save
from django.dispatch import receiver

# a dictionary of all the units you support, with their
# â€œto baseâ€ factor (base = grams for mass, milliliters for volume).
#    e.g.  1â€¯kg â†’ 1000â€¯g,   1â€¯g â†’ 1â€¯g
#          1â€¯l  â†’ 1000â€¯ml,  1â€¯mlâ†’1â€¯ml
#          1â€¯tbspâ†’15â€¯ml,    1â€¯tspâ†’5â€¯ml,  1â€¯cupâ†’240â€¯ml
DEFAULT_FACTORS = {
  'kg': 1000, 'g': 1,
  'l': 1000, 'ml': 1,
  'tbsp': 15, 'tsp': 5, 'cup': 240,
  # add more if you like: 'oz': 29.5735, etc.
}

@receiver(post_save, sender=RawMaterial)
def seed_unit_conversions(sender, instance, created, **kwargs):
    from .models import Unit, RawMaterialUnitConversion
    # ensure we have Unit objects
    units = {u.symbol: u for u in Unit.objects.filter(symbol__in=DEFAULT_FACTORS)}
    for symb, factor in DEFAULT_FACTORS.items():
        unit = units.get(symb)
        if not unit:
            continue
        RawMaterialUnitConversion.objects.get_or_create(
            raw_material=instance,
            unit=unit,
            defaults={'to_base_factor': factor}
        )



from django.db import models
from django.utils import timezone

class TableSession(models.Model):
    table = models.OneToOneField(
        'Table', on_delete=models.CASCADE, related_name='session'
    )
    waiter = models.ForeignKey(
        'Waiter', on_delete=models.PROTECT, related_name='table_sessions',
        null=True, blank=True
    )
    home_delivery = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    token_number = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"Table {self.table.number} Session"

class TableMenuItem(models.Model):
    TABLE_SOURCE_CHOICES = [
        ('menu', 'MenuItem'),
        ('deal', 'Deal'),
    ]
    session = models.ForeignKey(
        TableSession, on_delete=models.CASCADE, related_name='picked_items', null=True, blank=True
    )
    source_type = models.CharField(max_length=10, choices=TABLE_SOURCE_CHOICES)
    source_id = models.PositiveIntegerField()
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    printed_quantity = models.PositiveIntegerField(default=0, blank=True, null=True)

    created_at = models.DateTimeField(null=True, blank=True)   # when the row was first created
    updated_at = models.DateTimeField(null=True, blank=True)       # every change
    last_added_at = models.DateTimeField(null=True, blank=True)  # when qty was last increased

    def get_source_object(self):
        if self.source_type == 'menu':
            return MenuItem.objects.get(pk=self.source_id)
        return Deal.objects.get(pk=self.source_id)

    class Meta:
        unique_together = ('session', 'source_type', 'source_id')

    def __str__(self):
        label = 'Menu' if self.source_type=='menu' else 'Deal'
        return f"Table {self.session.table.number}: {self.quantity} x {label}({self.source_id})"
    

from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()

class BankAccount(models.Model):
    name           = models.CharField(max_length=100, help_text="e.g. HBL Current A/C")
    bank_name      = models.CharField(max_length=100, blank=True)
    account_number = models.CharField(max_length=50, blank=True)
    branch         = models.CharField(max_length=100, blank=True)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active      = models.BooleanField(default=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        label = self.bank_name or "Bank"
        return f"{label} â€” {self.name}"

    @property
    def current_balance(self):
        from django.db.models import Sum, F, Case, When, DecimalField
        # Sum IN minus OUT for this bank account; opening balance included
        from .models import CashFlow  # avoid circulars if you split files
        agg = (
            CashFlow.objects
            .filter(bank_account=self)
            .aggregate(
                net=Sum(
                    Case(
                        When(flow_type='in',  then=F('amount')),
                        When(flow_type='out', then=-F('amount')),
                        default=0,
                        output_field=DecimalField(max_digits=12, decimal_places=2)
                    )
                )
            )
        )['net'] or 0
        return self.opening_balance + agg


class CashFlow(models.Model):
    IN  = 'in'
    OUT = 'out'
    FLOW_TYPE = [(IN, 'Cash In'), (OUT, 'Cash Out')]

    date         = models.DateField(default=timezone.now)
    flow_type    = models.CharField(max_length=3, choices=FLOW_TYPE)
    amount       = models.DecimalField(max_digits=12, decimal_places=2)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True)
    description  = models.CharField(max_length=255, blank=True)
    created_by   = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        side = "Bank" if self.bank_account else "Cash"
        return f"{self.date} â€” {self.get_flow_type_display()} {self.amount} ({side})"


class BankMovement(models.Model):
    """
    A single logical movement that can touch CASH and/or BANK,
    writing matching rows to CashFlow so reports stay consistent.
    """
    DEPOSIT   = 'deposit'    # cash â†’ bank
    WITHDRAW  = 'withdraw'   # bank â†’ cash
    TRANSFER  = 'transfer'   # bank A â†’ bank B
    FEE       = 'fee'        # bank fee (out)
    INTEREST  = 'interest'   # bank interest (in)
    TYPES = [
        (DEPOSIT,  'Deposit (Cash â†’ Bank)'),
        (WITHDRAW, 'Withdraw (Bank â†’ Cash)'),
        (TRANSFER, 'Transfer (Bank â†’ Bank)'),
        (FEE,      'Bank Fee (Out)'),
        (INTEREST, 'Interest (In)'),
    ]

    date        = models.DateField(default=timezone.now)
    movement_type = models.CharField(max_length=20, choices=TYPES)
    amount      = models.DecimalField(max_digits=12, decimal_places=2)
    # actors
    from_bank   = models.ForeignKey(BankAccount, null=True, blank=True, on_delete=models.PROTECT, related_name='outgoing_movements')
    to_bank     = models.ForeignKey(BankAccount, null=True, blank=True, on_delete=models.PROTECT, related_name='incoming_movements')
    method      = models.CharField(max_length=30, blank=True, help_text="e.g. Cash, Cheque, Online")
    reference_no= models.CharField(max_length=100, blank=True, help_text="Cheque/Txn ref if any")
    notes       = models.CharField(max_length=255, blank=True)
    created_by  = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at  = models.DateTimeField(auto_now_add=True)

    # Link to the actual ledger rows so edits/deletes stay consistent
    cashflow_out = models.OneToOneField(CashFlow, null=True, blank=True, on_delete=models.SET_NULL, related_name='movement_out')
    cashflow_in  = models.OneToOneField(CashFlow, null=True, blank=True, on_delete=models.SET_NULL, related_name='movement_in')

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return f"{self.get_movement_type_display()} â€” {self.amount} on {self.date}"

    def clean(self):
        # basic rule checks
        from django.core.exceptions import ValidationError
        if self.amount <= 0:
            raise ValidationError("Amount must be positive.")

        if self.movement_type == self.DEPOSIT:
            if not self.to_bank:
                raise ValidationError("Deposit requires a destination bank (to_bank).")
        elif self.movement_type == self.WITHDRAW:
            if not self.from_bank:
                raise ValidationError("Withdrawal requires a source bank (from_bank).")
        elif self.movement_type == self.TRANSFER:
            if not self.from_bank or not self.to_bank:
                raise ValidationError("Transfer requires both from_bank and to_bank.")
            if self.from_bank_id == self.to_bank_id:
                raise ValidationError("Cannot transfer to the same bank account.")
        elif self.movement_type in [self.FEE, self.INTEREST]:
            if not (self.from_bank or self.to_bank):
                raise ValidationError("Fee/Interest must reference a bank account.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        """
        Ensure the paired CashFlow entries exist/are updated atomically.
        """
        creating = self.pk is None
        super().save(*args, **kwargs)

        # (1) Figure out the two sides that must exist for this movement
        out_kwargs, in_kwargs = None, None

        if self.movement_type == self.DEPOSIT:
            # cash OUT, bank IN
            out_kwargs = dict(bank_account=None, flow_type=CashFlow.OUT,
                              description=f"Deposit to {self.to_bank}", amount=self.amount)
            in_kwargs  = dict(bank_account=self.to_bank, flow_type=CashFlow.IN,
                              description="Cash deposit", amount=self.amount)

        elif self.movement_type == self.WITHDRAW:
            # bank OUT, cash IN
            out_kwargs = dict(bank_account=self.from_bank, flow_type=CashFlow.OUT,
                              description="Cash withdrawal", amount=self.amount)
            in_kwargs  = dict(bank_account=None, flow_type=CashFlow.IN,
                              description=f"Withdraw from {self.from_bank}", amount=self.amount)

        elif self.movement_type == self.TRANSFER:
            # bank A OUT, bank B IN
            out_kwargs = dict(bank_account=self.from_bank, flow_type=CashFlow.OUT,
                              description=f"Transfer to {self.to_bank}", amount=self.amount)
            in_kwargs  = dict(bank_account=self.to_bank, flow_type=CashFlow.IN,
                              description=f"Transfer from {self.from_bank}", amount=self.amount)

        elif self.movement_type == self.FEE:
            # bank OUT only
            out_kwargs = dict(bank_account=self.from_bank or self.to_bank, flow_type=CashFlow.OUT,
                              description="Bank fee", amount=self.amount)

        elif self.movement_type == self.INTEREST:
            # bank IN only
            in_kwargs  = dict(bank_account=self.to_bank or self.from_bank, flow_type=CashFlow.IN,
                              description="Bank interest", amount=self.amount)

        # (2) Create / update linked CashFlow(s)
        if out_kwargs:
            if self.cashflow_out_id:
                cf = self.cashflow_out
                cf.date = self.date
                cf.amount = out_kwargs['amount']
                cf.flow_type = out_kwargs['flow_type']
                cf.bank_account = out_kwargs['bank_account']
                cf.description = out_kwargs['description']
                cf.save(update_fields=['date','amount','flow_type','bank_account','description'])
            else:
                self.cashflow_out = CashFlow.objects.create(
                    date=self.date,
                    created_by=self.created_by,
                    **out_kwargs
                )
        else:
            # if previously existed but now not needed, remove
            if self.cashflow_out_id:
                self.cashflow_out.delete()
                self.cashflow_out = None

        if in_kwargs:
            if self.cashflow_in_id:
                cf = self.cashflow_in
                cf.date = self.date
                cf.amount = in_kwargs['amount']
                cf.flow_type = in_kwargs['flow_type']
                cf.bank_account = in_kwargs['bank_account']
                cf.description = in_kwargs['description']
                cf.save(update_fields=['date','amount','flow_type','bank_account','description'])
            else:
                self.cashflow_in = CashFlow.objects.create(
                    date=self.date,
                    created_by=self.created_by,
                    **in_kwargs
                )
        else:
            if self.cashflow_in_id:
                self.cashflow_in.delete()
                self.cashflow_in = None

        if creating or 'force_update_links' in kwargs:
            super().save(update_fields=['cashflow_out','cashflow_in'])

from django.db import models
from django.conf import settings

class Role(models.Model):
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name

class Staff(models.Model):
    ROLE_CHOICES = [
        ('super_admin', 'Super Admin'),
        ('manager', 'Manager'),
        ('cashier', 'Cashier'),
        ('waiter', 'Waiter'),
        ('chef', 'Chef'),
        ('security_guard', 'Security Guard'),
        ('it_manager', 'IT Manager'),
        ('helper', 'Helper'),
        ('other', 'Other'),
    ]
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    cnic = models.CharField(max_length=25, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    has_software_access = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)

    access_sales = models.BooleanField(default=False)
    access_inventory = models.BooleanField(default=False)
    access_accounts = models.BooleanField(default=False)

    joined_on = models.DateField(null=True, blank=True, help_text="Staff registry date")
    salary_start = models.DateField(null=True, blank=True, help_text="Salary starts from this date (month-wise)")
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return self.full_name
    
# core/models.py (add/replace these bits)

from django.conf import settings
from django.db import models
from django.utils import timezone

class ExpenseCategory(models.TextChoices):
    SALARY      = 'salary',      'Salary'
    ELECTRICITY = 'electricity', 'Electricity'
    GAS         = 'gas',         'Gas'
    STATIONERY  = 'stationery',  'Stationery'
    MAINTENANCE = 'maintenance', 'Maintenance'
    SOFTWARE    = 'software',    'Software'
    PURCHASE    = 'purchase',    'Purchases/Other Items'
    OTHER       = 'other',       'Other'

class Expense(models.Model):
    PAYMENT_SOURCE = [
        ('cash', 'Cash (Restaurant Cash)'),
        ('bank', 'Bank Account'),
    ]

    date            = models.DateField(default=timezone.now)
    category        = models.CharField(max_length=20, choices=ExpenseCategory.choices)
    amount          = models.DecimalField(max_digits=12, decimal_places=2)
    description     = models.CharField(max_length=255, blank=True)
    reference       = models.CharField(max_length=100, blank=True)  # invoice/bill no (optional)
    attachment      = models.FileField(upload_to='expenses/', null=True, blank=True)

    # Links (nullable; validated by category rules)
    supplier        = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True)
    staff           = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, blank=True)

    # Payment source
    payment_source  = models.CharField(max_length=10, choices=PAYMENT_SOURCE, default='cash')
    bank_account    = models.ForeignKey('BankAccount', on_delete=models.SET_NULL, null=True, blank=True)

    # Audit
    created_by      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at      = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at      = models.DateTimeField(auto_now=True)

    # Link to CashFlow so edits/deletes stay in sync
    cashflow        = models.OneToOneField('CashFlow', on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_expense')

    purchase_order = models.ForeignKey('PurchaseOrder', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')

    def __str__(self):
        return f"{self.date} â€” {self.get_category_display()} â€” â‚¨{self.amount}"

    # --- Validation rules ---
    def clean(self):
        from django.core.exceptions import ValidationError
        # Supplier mandatory for utility bills & purchases
        supplier_required_for = {
            ExpenseCategory.ELECTRICITY,
            ExpenseCategory.GAS,
            ExpenseCategory.PURCHASE,
            ExpenseCategory.STATIONERY,
            ExpenseCategory.MAINTENANCE,
            ExpenseCategory.SOFTWARE,
        }
        if self.category in supplier_required_for and not self.supplier:
            raise ValidationError("Supplier is required for this expense category.")
        # Staff mandatory for Salary
        if self.category == ExpenseCategory.SALARY and not self.staff:
            raise ValidationError("Staff is required for Salary expenses.")
        # Bank account mandatory if payment source is bank
        if self.payment_source == 'bank' and not self.bank_account:
            raise ValidationError("Please choose a Bank Account for bank payments.")
        # Ensure no bank account set for cash payments
        if self.payment_source == 'cash':
            self.bank_account = None

    # --- CashFlow sync ---
    def save(self, *args, **kwargs):
        from .models import CashFlow  # already in your project
        creating = self.pk is None
        super().save(*args, **kwargs)

        # Create/update the CashFlow record
        desc = f"Expense: {self.get_category_display()}"
        if self.description:
            desc += f" â€” {self.description}"

        if not self.cashflow:
            cf = CashFlow.objects.create(
                date=self.date,
                flow_type=CashFlow.OUT,
                amount=self.amount,
                bank_account=self.bank_account if self.payment_source == 'bank' else None,
                description=desc,
                created_by=self.created_by,
            )
            self.cashflow = cf
            super().save(update_fields=['cashflow'])
        else:
            cf = self.cashflow
            cf.date = self.date
            cf.amount = self.amount
            cf.bank_account = self.bank_account if self.payment_source == 'bank' else None
            cf.description = desc
            cf.save()

    def delete(self, *args, **kwargs):
        cf = self.cashflow
        super().delete(*args, **kwargs)
        if cf:
            cf.delete()


# --- KITCHEN ISSUE / RETURN -----------------------------------------------
from django.db import models, transaction
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()

class KitchenVoucher(models.Model):
    ISSUE  = 'issue'
    RETURN = 'return'
    TYPES = [(ISSUE, 'Issue to Kitchen'), (RETURN, 'Return from Kitchen')]

    date        = models.DateField(default=timezone.localdate)
    vtype       = models.CharField(max_length=10, choices=TYPES, default=ISSUE)
    handler     = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, blank=True,
                                    help_text="Kitchen/Store in-charge")
    notes       = models.CharField(max_length=255, blank=True)

    created_by  = models.ForeignKey(User, on_delete=models.PROTECT, related_name='kitchen_vouchers')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['vtype','date'])]

    def __str__(self):
        return f"KV#{self.id} â€” {self.get_vtype_display()} â€” {self.date}"

    @transaction.atomic
    def sync_transactions(self):
        """
        For each item ensure a matching InventoryTransaction exists/updated.
        ISSUE  -> OUT
        RETURN -> IN
        """
        from .models import InventoryTransaction  # avoid cycle

        for it in self.items.select_related('raw_material').all():
            # create/update the attached InventoryTransaction
            if it.transaction_id:
                t = it.transaction
                t.date = self.date  # we add a date field below in InventoryTransaction
                t.timestamp = timezone.now()
                t.transaction_type = 'out' if self.vtype == self.ISSUE else 'in'
                t.quantity = it.quantity
                t.raw_material = it.raw_material
                t.notes = f"{self.get_vtype_display()} KV#{self.id}"
                t.save(update_fields=['date','timestamp','transaction_type','quantity','raw_material','notes'])
            else:
                t = InventoryTransaction.objects.create(
                    raw_material=it.raw_material,
                    transaction_type=('out' if self.vtype == self.ISSUE else 'in'),
                    quantity=it.quantity,
                    notes=f"{self.get_vtype_display()} KV#{self.id}",
                )
                it.transaction = t
                it.save(update_fields=['transaction'])

    def save(self, *args, **kwargs):
        creating = self.pk is None
        super().save(*args, **kwargs)
        # on create/update, (re)sync transactions
        self.sync_transactions()


class KitchenVoucherItem(models.Model):
    voucher      = models.ForeignKey(KitchenVoucher, on_delete=models.CASCADE, related_name='items')
    raw_material = models.ForeignKey('RawMaterial', on_delete=models.PROTECT)
    quantity     = models.DecimalField(max_digits=10, decimal_places=2)

    # Backlink so edits/deletes stay consistent in InventoryTransaction
    transaction  = models.OneToOneField('InventoryTransaction', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='kitchen_item')

    class Meta:
        unique_together = ('voucher','raw_material')  # avoid accidental duplicates

    def __str__(self):
        return f"{self.quantity} {self.raw_material.unit} of {self.raw_material.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.quantity is None or self.quantity <= 0:
            raise ValidationError("Quantity must be > 0")

    def delete(self, *args, **kwargs):
        # remove paired transaction as well
        t = self.transaction
        super().delete(*args, **kwargs)
        if t:
            t.delete()


# models.py
from django.db import models, transaction
from django.utils import timezone

class TokenSequence(models.Model):
    """
    Tracks the last token number for a specific business date.
    Optionally tracks per PrintStation if they need separate sequencing.
    """
    business_date = models.DateField(db_index=True)
    station = models.ForeignKey(PrintStation, on_delete=models.CASCADE, null=True, blank=True, help_text="Null means Global/Main sequence")
    last = models.PositiveIntegerField(default=0)

    class Meta:
        # Unique constraint: One counter per date per station (or one global counter per date)
        unique_together = ('business_date', 'station')

    def __str__(self):
        st_name = self.station.name if self.station else "Global"
        return f"{self.business_date} [{st_name}] -> {self.last}"

def business_date_for(dt):
    ref = timezone.localtime(dt)
    noon = ref.replace(hour=12, minute=0, second=0, microsecond=0)
    return ref.date() if ref >= noon else (ref - timezone.timedelta(days=1)).date()

def next_token_for(dt=None):
    """Atomically returns next token for the business day."""
    ref = dt or timezone.now()
    bday = business_date_for(ref)
    with transaction.atomic():
        row, _ = TokenSequence.objects.select_for_update().get_or_create(
            business_date=bday,
            defaults={'last': 0},
        )
        row.last += 1
        row.save(update_fields=['last'])
        return row.last


class TokenCounter(models.Model):
    service_day = models.DateField(unique=True, db_index=True)
    last        = models.PositiveIntegerField(default=0)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-service_day"]

    def __str__(self):
        return f"{self.service_day}: {self.last}"
    
# core/models.py

class PaymentReceived(models.Model):
    PARTY_Types = [
        ('customer', 'Registered Customer'),
        ('supplier', 'Supplier (Refund/Return)'),
    ]
    PAYMENT_SOURCE = [
        ('cash', 'Cash (Restaurant Cash)'),
        ('bank', 'Bank Account'),
    ]

    date = models.DateField(default=timezone.now)
    party_type = models.CharField(max_length=10, choices=PARTY_Types, default='customer')
    
    # Links (One will be filled, the other null)
    customer = models.ForeignKey('Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name="payments_received")
    supplier = models.ForeignKey('Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name="refunds_received")

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.CharField(max_length=255, blank=True)
    
    # Where is money going?
    payment_method = models.CharField(max_length=10, choices=PAYMENT_SOURCE, default='cash')
    bank_account = models.ForeignKey('BankAccount', on_delete=models.SET_NULL, null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Link to CashFlow so ledger stays in sync
    cashflow = models.OneToOneField('CashFlow', on_delete=models.SET_NULL, null=True, blank=True, related_name='linked_income')

    def __str__(self):
        name = self.customer.name if self.customer else (self.supplier.name if self.supplier else "Unknown")
        return f"Recv {self.amount} from {name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.party_type == 'customer' and not self.customer:
            raise ValidationError("Please select a Customer.")
        if self.party_type == 'supplier' and not self.supplier:
            raise ValidationError("Please select a Supplier.")
        if self.payment_method == 'bank' and not self.bank_account:
            raise ValidationError("Please select a Bank Account.")
        if self.amount <= 0:
            raise ValidationError("Amount must be greater than 0.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_amount = 0
        
        if not is_new:
            # If editing, get the old object to revert balance changes
            old_obj = PaymentReceived.objects.get(pk=self.pk)
            old_amount = old_obj.amount
            # Revert old customer balance change
            if old_obj.customer:
                old_obj.customer.current_balance += old_obj.amount # Add it back (revert payment)
                old_obj.customer.save()

        super().save(*args, **kwargs)

        # 1. Update Customer Balance (Money In = Balance Decreases)
        if self.customer:
            self.customer.current_balance -= self.amount
            self.customer.save()

        # 2. Sync with CashFlow
        from .models import CashFlow
        desc = f"Received from {self.customer.name if self.customer else self.supplier.name}"
        if self.description:
            desc += f" - {self.description}"

        if not self.cashflow:
            cf = CashFlow.objects.create(
                date=self.date,
                flow_type=CashFlow.IN, # Money Coming IN
                amount=self.amount,
                bank_account=self.bank_account if self.payment_method == 'bank' else None,
                description=desc,
                created_by=self.created_by
            )
            self.cashflow = cf
            # Save again to link the ID (avoid recursion by updating queryset)
            PaymentReceived.objects.filter(pk=self.pk).update(cashflow=cf)
        else:
            cf = self.cashflow
            cf.date = self.date
            cf.amount = self.amount
            cf.bank_account = self.bank_account if self.payment_method == 'bank' else None
            cf.description = desc
            cf.save()

    @transaction.atomic
    def delete(self, *args, **kwargs):
        # 1. Revert Customer Balance
        if self.customer:
            self.customer.current_balance += self.amount # Add debt back
            self.customer.save()
        
        # 2. Remove Cashflow
        if self.cashflow:
            self.cashflow.delete()
            
        super().delete(*args, **kwargs)
