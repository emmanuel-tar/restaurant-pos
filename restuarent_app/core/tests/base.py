"""Shared harness for running the standalone smoke scripts under `manage.py test`.

The smoke scripts (`smoke_test_taxes.py`, `smoke_test_costing.py`) still work on
their own from the command line, but they are plain functions that record
`(label, got, want, ok)` rows. This base class runs one of them inside a Django
`TestCase`, captures its output, and turns any failed row into a real assertion
failure that names the check.
"""
import io
import os
import sys
from contextlib import redirect_stdout

from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()

# The smoke scripts live next to manage.py (restuarent_app/), not inside core/.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class SmokeTestCase(TestCase):
    """Runs one of the standalone smoke scripts inside Django's test runner."""

    #: printed output kept for debugging when a run fails
    captured_output = ''

    def ensure_base_data(self):
        """The scripts assume at least one signed-in user exists."""
        if not User.objects.exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin-pass-123')

    def run_smoke(self, module, *args, **kwargs):
        """Run `module.run(...)` with rollback/verbose off, assert every check.

        Returns the rows so a test can make extra assertions about them.
        """
        self.ensure_base_data()
        if hasattr(module, 'CHECKS'):
            module.CHECKS.clear()

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rows = module.run(*args, **kwargs)
        self.captured_output = buffer.getvalue()

        failures = [(label, got, want) for label, got, want, ok in rows if not ok]
        if failures:
            detail = '\n'.join(
                f'  {label}: got={got!r} expected={want!r}'
                for label, got, want in failures
            )
            self.fail(
                f'{len(failures)}/{len(rows)} checks failed\n{detail}\n'
                f'--- captured smoke output (tail) ---\n'
                f'{self.captured_output[-4000:]}'
            )
        self.assertTrue(rows, f'{module.__name__} recorded no checks at all')
        return rows
