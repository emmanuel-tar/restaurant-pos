import getpass

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Category, MenuItem, POSSettings, PrintStation, Unit


class Command(BaseCommand):
    help = (
        'Seeds the essential reference data the POS needs to run: POS settings, '
        'the main print station, and measurement units. Safe to run repeatedly.'
    )

    # (name, symbol, unit_type) - generic, non-business-specific reference data.
    DEFAULT_UNITS = [
        ('Kilogram', 'kg', 'mass'),
        ('Gram', 'g', 'mass'),
        ('Litre', 'l', 'volume'),
        ('Millilitre', 'ml', 'volume'),
        ('Piece', 'pc', 'count'),
        ('Dozen', 'doz', 'count'),
    ]

    # Generic placeholder menu used by --demo-menu. Replace with your real menu,
    # and remove it again with:  python manage.py seed_pos --remove-demo-menu
    DEMO_MENU = {
        'Grills': [
            ('Chicken Suya', '2500'),
            ('Beef Suya', '2800'),
            ('Grilled Chicken', '3500'),
            ('Grilled Fish', '4500'),
            ('Fried Plantain', '1000'),
        ],
        'Rice & Meals': [
            ('Jollof Rice', '2000'),
            ('Fried Rice', '2200'),
            ('Chicken Fried Rice', '2800'),
            ('Beef Stew & Rice', '3200'),
            ('White Stew & Rice', '3000'),
        ],
        'Snacks': [
            ('Spring Roll', '1200'),
            ('Samosa', '800'),
            ('Chips & Chicken', '2000'),
        ],
        'Drinks': [
            ('Bottled Water', '200'),
            ('Soft Drink (500ml)', '500'),
            ('Malt Drink', '800'),
            ('Orange Juice', '1500'),
        ],
    }

    def add_arguments(self, parser):
        parser.add_argument(
            '--demo-menu',
            action='store_true',
            help='Also create a small placeholder menu (categories + items) to get started.',
        )
        parser.add_argument(
            '--remove-demo-menu',
            action='store_true',
            help='Remove the placeholder menu created by --demo-menu.',
        )
        parser.add_argument(
            '--staff',
            action='store_true',
            help='Also create a cashier and a kitchen staff account (prompts for passwords).',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0

        # --- POS settings (singleton, id=1 - matches POSSettingsUpdateView) ---
        pos_settings, created = POSSettings.objects.get_or_create(
            id=1,
            defaults={'restaurant_name': getattr(settings, 'RESTAURANT_NAME', 'My Restaurant')},
        )
        if created:
            created_count += 1
            self.stdout.write(self.style.SUCCESS(f'  + POS settings: "{pos_settings.restaurant_name}"'))
        else:
            self.stdout.write(f'  = POS settings already present: "{pos_settings.restaurant_name}"')

        # --- Print station (kitchen/token printing iterates over these) ---
        # Only create a default when the install has none at all, so we never
        # add a duplicate station alongside one the restaurant already configured.
        if PrintStation.objects.exists():
            self.stdout.write(
                f'  = Print station(s) already configured: '
                f'{", ".join(PrintStation.objects.values_list("name", flat=True))}'
            )
        else:
            PrintStation.objects.create(
                name='Main Kitchen',
                print_separate_slip=True,
                use_separate_sequence=False,
            )
            created_count += 1
            self.stdout.write(self.style.SUCCESS('  + Print station: "Main Kitchen"'))

        # --- Units (required by raw materials / inventory) ---
        for name, symbol, unit_type in self.DEFAULT_UNITS:
            _, created = Unit.objects.get_or_create(
                symbol=symbol,
                defaults={'name': name, 'unit_type': unit_type},
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f'  + Units seeded ({len(self.DEFAULT_UNITS)} total)'))

        if options['remove_demo_menu']:
            self._remove_demo_menu()
            return

        if options['demo_menu']:
            created_count += self._create_demo_menu()

        if options['staff']:
            created_count += self._create_staff()

        self.stdout.write('')
        if created_count:
            self.stdout.write(self.style.SUCCESS(f'Seeding complete - {created_count} item(s) created.'))
        else:
            self.stdout.write(self.style.SUCCESS('Seeding complete - nothing new to create.'))
        self.stdout.write('Next: add your menu items, then run  python manage.py runserver')

    def _create_demo_menu(self):
        """Creates a small placeholder menu so the POS can take orders immediately."""
        created_count = 0
        station = PrintStation.objects.first()

        for category_name, items in self.DEMO_MENU.items():
            category, cat_created = Category.objects.get_or_create(
                name=category_name,
                defaults={'default_station': station},
            )
            if cat_created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f'  + Category: "{category_name}"'))

            for item_name, price in items:
                _, item_created = MenuItem.objects.get_or_create(
                    category=category,
                    name=item_name,
                    defaults={'price': price},
                )
                if item_created:
                    created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'  + Demo menu created ({sum(len(v) for v in self.DEMO_MENU.values())} items '
                f'across {len(self.DEMO_MENU)} categories)'
            )
        )
        return created_count

    def _remove_demo_menu(self):
        """Deletes only the placeholder categories/items created by --demo-menu."""
        removed = 0
        for category_name in self.DEMO_MENU:
            category = Category.objects.filter(name=category_name).first()
            if not category:
                continue
            item_count = category.items.count()
            removed += item_count
            # Delete items first: MenuItem.category is on_delete=PROTECT.
            category.items.all().delete()
            category.delete()
            self.stdout.write(f'  - Removed "{category_name}" ({item_count} items)')

        if removed:
            self.stdout.write(self.style.SUCCESS(f'Removed {removed} demo menu item(s).'))
        else:
            self.stdout.write(self.style.WARNING('No demo menu found - nothing removed.'))

    def _create_staff(self):
        """Creates a cashier and a kitchen account, prompting for passwords."""
        User = get_user_model()
        created_count = 0

        for username, role in (('cashier', 'cashier'), ('kitchen', 'kitchen')):
            if User.objects.filter(username=username).exists():
                self.stdout.write(f'  = Staff account "{username}" already exists')
                continue

            password = getpass.getpass(f'  Password for "{username}" ({role}): ')
            if len(password) < 8:
                self.stdout.write(self.style.ERROR(f'  ! Skipped "{username}" - password must be 8+ characters.'))
                continue

            User.objects.create_user(
                username=username,
                email=f'{username}@restropos.local',
                password=password,
                role=role,
                is_staff=True,
            )
            created_count += 1
            self.stdout.write(self.style.SUCCESS(f'  + Staff account: "{username}" (role: {role})'))

        return created_count