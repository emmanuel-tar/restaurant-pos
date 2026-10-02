# setup.py (excerpt)

from setuptools import setup, Extension
from Cython.Build import cythonize

extensions = [
    Extension("core.views", ["core/views.py"]),
    Extension("core.license_check", ["core/license_check.py"]),
    # … any other modules you want compiled
]

setup(
    name="RestroPOS",
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
    zip_safe=False,
)
