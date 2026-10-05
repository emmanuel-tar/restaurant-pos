"""Every URL name referenced in code or templates must reverse cleanly.

Catches renamed routes before they surface as NoReverseMatch in production.
"""
from django.test import SimpleTestCase

from .base import PROJECT_ROOT  # noqa: F401  (puts restuarent_app on sys.path)

import url_audit


class UrlAuditTests(SimpleTestCase):

    def test_audit_finds_references(self):
        """The scan pattern still matches real code (guards against staleness)."""
        used = url_audit.referenced_names()
        self.assertGreater(len(used), 50, 'URL reference scan found suspiciously little')

    def test_every_referenced_url_name_resolves(self):
        used, _known, missing, broken = url_audit.audit()
        self.assertEqual(
            missing, [],
            'Referenced URL names with no route:\n  ' + '\n  '.join(missing),
        )
        self.assertEqual(
            broken,
            [],
            'Routes that fail to reverse:\n  '
            + '\n  '.join(f'{name}: {err}' for name, err in broken),
        )

    def test_sidebar_url_names_resolve(self):
        """The sidebar config must agree with the URLconf."""
        from core.navigation import SIDEBAR

        _used, known, _missing, _broken = url_audit.audit()

        for section in SIDEBAR:
            for item in section.get('items', []):
                self.assertIn(
                    item['url_name'], known,
                    f"sidebar link '{item['label']}' points at a missing route "
                    f"{item['url_name']!r}",
                )
