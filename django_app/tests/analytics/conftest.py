"""Fixture test analytics.

Catatan: fixture global (isolasi registry listener event bus) ada di
``django_app/conftest.py`` (PRA-0A.4) dan berlaku untuk folder ini juga.
Registry metrik di-reset per test lewat fixture di ``test_registry.py``.
"""

from __future__ import annotations
