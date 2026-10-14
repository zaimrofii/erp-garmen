"""Builder schema per resource garmen (Kontrak §1).

Satu file = satu resource. Resource baru cukup ditambah di sini lalu didaftarkan
di `api/schema/registry.py` — frontend tidak perlu tahu model Django-nya.
"""

from __future__ import annotations

from .bundle import BundleSchemaBuilder
from .work_order import WorkOrderSchemaBuilder

__all__ = [
    "BundleSchemaBuilder",
    "WorkOrderSchemaBuilder",
]
