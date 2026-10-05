"""Verify every URL name referenced in code/templates resolves.

Run with:  .venv\\Scripts\\python.exe url_audit.py
Exits 1 when a referenced name is missing from the URLconf.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restuarent_app.settings')

import django  # noqa: E402

django.setup()

from django.urls import get_resolver, NoReverseMatch, reverse  # noqa: E402

resolver = get_resolver()
known = set(resolver.reverse_dict.keys())

# Collect url_name / reverse('...') / {% url '...' %} references from the app
# so the audit matches real usage.
root = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'core')
used = set()
pattern = re.compile(
    r"""(?:url_name['"]\s*:\s*['"]|reverse\(\s*['"]|{% url ['"]|url ['"])"""
    r"""([a-zA-Z0-9_]+)"""
)
for base, _dirs, files in os.walk(root):
    if '__pycache__' in base:
        continue
    for fname in files:
        if not fname.endswith(('.py', '.html')):
            continue
        path = os.path.join(base, fname)
        try:
            with open(path, encoding='utf-8', errors='ignore') as fh:
                for match in pattern.finditer(fh.read()):
                    used.add(match.group(1))
        except OSError:
            continue

missing = sorted(name for name in used if name not in known)
print(f'URL names referenced : {len(used)}')
print(f'Resolver names       : {len(known)}')
if missing:
    print(f'DOES NOT RESOLVE ({len(missing)}):')
    for name in missing:
        print('    ' + name)
else:
    print('All referenced URL names resolve.')

# Smoke-resolve every known name that takes no args to catch broken patterns.
broken = []
for name in sorted((n for n in known if isinstance(n, str)), key=str):
    if str(name).startswith('admin:'):
        continue
    try:
        reverse(name)
    except NoReverseMatch:
        continue  # requires args
    except Exception as exc:  # noqa: BLE001
        broken.append((name, repr(exc)))
if broken:
    print('BROKEN:')
    for name, err in broken:
        print(f'    {name}: {err}')

sys.exit(1 if missing or broken else 0)
