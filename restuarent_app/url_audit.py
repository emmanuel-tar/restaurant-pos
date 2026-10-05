"""Verify every URL name referenced in code/templates resolves.

Usable two ways:
  * CLI   : .venv\\Scripts\\python.exe url_audit.py   (exits 1 on any miss)
  * Tests : see core.tests.test_urls.UrlAuditTests

The scan covers `reverse('name')`, `{% url 'name' %}`, `url 'name'` and the
`'url_name': 'name'` entries used by navigation.py / permissions.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restuarent_app.settings')

# Under `manage.py test` the app registry is already populated; only bootstrap
# when this file is executed directly as a script.
import django  # noqa: E402
from django.apps import apps  # noqa: E402

if not apps.ready:
    django.setup()

APP_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core')

REFERENCE_PATTERN = re.compile(
    r"""(?:url_name['"]\s*:\s*['"]|reverse\(\s*['"]|{% url ['"]|url ['"])"""
    r"""([a-zA-Z0-9_]+)"""
)


def referenced_names(root=APP_ROOT):
    """Every URL name referenced anywhere in the app's .py / .html sources."""
    used = set()
    for base, _dirs, files in os.walk(root):
        if '__pycache__' in base:
            continue
        for fname in files:
            if not fname.endswith(('.py', '.html')):
                continue
            path = os.path.join(base, fname)
            try:
                with open(path, encoding='utf-8', errors='ignore') as fh:
                    for match in REFERENCE_PATTERN.finditer(fh.read()):
                        used.add(match.group(1))
            except OSError:
                continue
    return used


def audit():
    """Return (referenced, known, missing, broken).

    missing : referenced names with no matching route
    broken  : (name, error) for routes that raise for reasons other than
              needing positional args
    """
    from django.urls import NoReverseMatch, get_resolver, reverse

    known = {name for name in get_resolver().reverse_dict.keys() if isinstance(name, str)}
    used = referenced_names()

    missing = sorted(used - known)

    broken = []
    for name in sorted(known):
        if name.startswith('admin:'):
            continue
        try:
            reverse(name)
        except NoReverseMatch:
            continue  # pattern requires args we do not have here
        except Exception as exc:  # noqa: BLE001
            broken.append((name, repr(exc)))

    return used, known, missing, broken


def main():
    used, known, missing, broken = audit()

    print(f'URL names referenced : {len(used)}')
    print(f'Resolver names       : {len(known)}')
    if missing:
        print(f'DOES NOT RESOLVE ({len(missing)}):')
        for name in missing:
            print('    ' + name)
    else:
        print('All referenced URL names resolve.')
    if broken:
        print('BROKEN:')
        for name, err in broken:
            print(f'    {name}: {err}')

    return 1 if missing or broken else 0


if __name__ == '__main__':
    sys.exit(main())
