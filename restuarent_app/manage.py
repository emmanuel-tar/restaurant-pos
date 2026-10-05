#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Packages that only exist inside this project's virtualenv. If any of them is
# missing, the wrong interpreter is being used.
PROJECT_PACKAGES = ('django', 'crispy_forms', 'win32print')


def _project_venv_python():
    """Path of the interpreter inside this project's .venv (Windows layout)."""
    return os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')


def _guard_virtualenv():
    """
    Stop with a clear message when manage.py is run with the wrong Python.

    This machine has a system-wide Django (installed with --user) that is
    missing this project's packages, so the usual "ModuleNotFoundError" for
    crispy_forms / win32print is very confusing. Say what to do instead.
    """
    venv_python = _project_venv_python()
    if not os.path.isfile(venv_python):
        return  # no project venv here; nothing to point the user at

    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(venv_python):
        return  # already running the project interpreter

    try:
        import importlib.util
        for package in PROJECT_PACKAGES:
            if importlib.util.find_spec(package) is None:
                raise ImportError(package)
    except ImportError:
        sys.stderr.write(
            "\n"
            "  Wrong Python: this project must run with its own virtualenv.\n"
            f"  You are running : {sys.executable}\n"
            f"  Required        : {venv_python}\n"
            "\n"
            "  Fix it with either of these:\n"
            "      .\\.venv\\Scripts\\Activate.ps1\n"
            "      .\\.venv\\Scripts\\python.exe manage.py runserver\n"
            "\n"
            "  (Or just double-click start_server.bat)\n\n"
        )
        sys.exit(1)


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restuarent_app.settings')
    _guard_virtualenv()
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
