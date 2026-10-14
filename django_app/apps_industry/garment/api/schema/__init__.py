"""Builder & registry metadata schema resource (Kontrak Backend<->Frontend §1).

Catatan penting: `__init__.py` ini sengaja **hanya** mengekspor `builder`.
`registry` mengimpor `api/resources/*`, sementara `api/resources/*` mengimpor
`api/schema/builder`; kalau registry juga di-import di sini, impor jadi sirkular
(`partially initialized module`). Import registry langsung dari modulnya:
`from apps_industry.garment.api.schema.registry import get_builder`.
"""

from __future__ import annotations

from .builder import SCHEMA_VERSION, BaseSchemaBuilder, build_state_machine_payload

__all__ = [
    "SCHEMA_VERSION",
    "BaseSchemaBuilder",
    "build_state_machine_payload",
]
