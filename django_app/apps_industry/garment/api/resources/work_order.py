"""Builder schema resource `work-orders` (Kontrak §1).

WorkOrder belum punya field `version` (beda dengan Bundle), jadi `version`
dihitung **on-the-fly** sebagai SHA-256 dari state kritis — perilaku ini sama
dengan `Bundle.version` sehingga frontend bisa memakai mekanisme conflict yang
sama (`base_version` + `X-Base-Version`, kontrak §2.3).

Chatter WorkOrder masih kosong: `BundleEvent` hanya menempel ke Bundle; event
tingkat WO menyusul di Sprint 3.2.
"""

from __future__ import annotations

from apps_industry.garment.api.schema.builder import (
    BaseSchemaBuilder,
    build_state_machine_payload,
)
from apps_industry.garment.models import WorkOrder

#: Kode state machine WO (di-seed migration `0002_seed_state_machines`).
MACHINE_CODE = "garment.work_order"


class WorkOrderSchemaBuilder(BaseSchemaBuilder):
    """Metadata halaman Work Order (view_type `form`)."""

    MODEL = WorkOrder
    RESOURCE_NAME = "work-orders"
    RESOURCE_LABEL = "Work Order"
    DEVICE_HINT = "OPERATOR_HP"  # supervisor/operator HP
    SELECT_RELATED = (
        "order_line",
        "order_line__order",
        "order_line__product",
    )

    def get_resource_name(self) -> str:
        return self.RESOURCE_NAME

    def get_title(self) -> str:
        return f"Work Order #{self.instance.code}"

    def get_version(self) -> str:
        """SHA-256 dari `code|state|qty_done|updated_at` (WorkOrder tanpa field version)."""
        instance = self.instance
        return self.hash_state(
            instance.code,
            instance.state,
            instance.qty_done,
            instance.updated_at.isoformat() if instance.updated_at else "",
        )

    def get_device_hint(self) -> str:
        return self.DEVICE_HINT

    def get_state_machine(self) -> dict:
        return build_state_machine_payload(
            MACHINE_CODE,
            self.instance.state,
            endpoint_prefix=self.action_endpoint_prefix(),
        )

    def get_layout_sections(self) -> list[dict]:
        instance = self.instance
        return [
            {
                "section": "Info WO",
                "fields": [
                    self.field("code", "text", "Kode", instance.code),
                    self.field("state", "text", "Status", instance.state),
                    self.field(
                        "qty_planned", "number", "Qty Rencana", instance.qty_planned
                    ),
                    self.field("qty_done", "number", "Qty Selesai", instance.qty_done),
                ],
            }
        ]

    def get_chatter(self) -> dict:
        """Belum ada event log untuk WO (Sprint 3.2 akan menambahkannya)."""
        return self.empty_chatter()
