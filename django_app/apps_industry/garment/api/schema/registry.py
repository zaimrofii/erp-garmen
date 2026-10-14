"""Registry resource -> schema builder (Kontrak §1).

Menambah resource baru = tambah satu entri di sini + builder-nya di
`api/resources/`. Frontend hanya menyebut nama resource ("bundles"), tidak perlu
tahu model Django mana yang dipakai — itu inti prinsip "backend = otak".
"""

from __future__ import annotations

from apps_industry.garment.api.resources.bundle import BundleSchemaBuilder
from apps_industry.garment.api.resources.order_line import OrderLineSchemaBuilder
from apps_industry.garment.api.resources.qc import QCSchemaBuilder
from apps_industry.garment.api.resources.work_order import WorkOrderSchemaBuilder
from apps_industry.garment.api.schema.builder import BaseSchemaBuilder

#: Nama resource (dipakai di URL & metadata) -> builder class.
#: Catatan: nama resource di sini juga membatasi pola URL `list` (lihat
#: `api/urls.py`) supaya tidak men-shadows path core lain di `/api/v1/`.
SCHEMA_BUILDERS: dict[str, type[BaseSchemaBuilder]] = {
    "work-orders": WorkOrderSchemaBuilder,
    "bundles": BundleSchemaBuilder,
    "qc": QCSchemaBuilder,
    # FASE 3.4 (P1) — OrderLine bisa dibaca lewat HTTP (dipakai jalur
    # "order baru → WO → bundle"); bukan resource aksi (tanpa state machine).
    "order-lines": OrderLineSchemaBuilder,
}


def get_builder(resource_name: str | None) -> type[BaseSchemaBuilder] | None:
    """Builder class untuk `resource_name` (case-insensitive); `None` kalau tak dikenal."""
    if not resource_name:
        return None
    return SCHEMA_BUILDERS.get(str(resource_name).strip().lower())
