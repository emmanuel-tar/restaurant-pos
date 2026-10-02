import getpass
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.contrib.auth import authenticate, get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Wipes all data from the DB after superuser confirmation.'

    def handle(self, *args, **options):
        # 1) Ask for credentials
        username = input('Superuser username: ')
        password = getpass.getpass('Password: ')

        user = authenticate(username=username, password=password)
        if user is None or not user.is_superuser:
            self.stdout.write(self.style.ERROR(
                'Authentication failed or user is not a superuser.'
            ))
            return

        # 2) Final confirmation
        confirm = input(
            '⚠️  This will DELETE ALL DATA from your database!  ⚠️\n'
            'Type "YES" to proceed: '
        )
        if confirm != 'YES':
            self.stdout.write(self.style.WARNING('Aborted. No changes made.'))
            return

        # 3) Flush the database
        call_command('flush', interactive=False)
        self.stdout.write(self.style.SUCCESS('✅  Database has been cleaned.'))
