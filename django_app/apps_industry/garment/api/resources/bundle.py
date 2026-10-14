"""Builder schema resource `bundles` (Kontrak §1).

Bundle adalah resource utama operator: ia punya `version` (SHA-256 state kritis
dari Sprint 2.1), widget QR (`field.widget = "garmen-qr-bundle"`, Fase B.1.4),
dan chatter dari `BundleEvent` (preview 5 event terbaru + cursor — kontrak §8:
jangan kirim semua event).
"""

from __future__ import annotations

from apps_industry.garment.api.chatter.paginator import chatter_page_payload
from apps_industry.garment.api.schema.builder import (
    BaseSchemaBuilder,
    build_state_machine_payload,
)
from apps_industry.garment.models import Bundle, BundleEvent

#: Kode state machine bundle (di-seed migration `0002_seed_state_machines`).
MACHINE_CODE = "garment.bundle"


class BundleSchemaBuilder(BaseSchemaBuilder):
    """Metadata halaman Bundle (view_type `form`)."""

    MODEL = Bundle
    RESOURCE_NAME = "bundles"
    RESOURCE_LABEL = "Bundle"
    DEVICE_HINT = "SCANNER_USB"  # bundle di-scan di lantai produksi
    SELECT_RELATED = (
        "work_order",
        "work_order__order_line",
        "work_order__order_line__order",
        "work_order__order_line__product",
        "current_work_center",
        "production_line",
    )
    CHATTER_PREVIEW_LIMIT = 5

    def get_resource_name(self) -> str:
        return self.RESOURCE_NAME

    def get_title(self) -> str:
        return f"Bundle #{self.instance.code}"

    def get_version(self) -> str:
        """`Bundle.version` (sudah dihitung model); fallback hitung ulang."""
        return self.instance.version or self.instance.compute_version()

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
        work_center = (
            instance.current_work_center.code
            if instance.current_work_center_id
            else None
        )
        return [
            {
                "section": "Info Bundle",
                "fields": [
                    self.field("code", "text", "Kode", instance.code),
                    self.field("size", "text", "Ukuran", instance.size),
                    self.field("qty", "number", "Qty", instance.qty),
                    self.field("qty_done", "number", "Qty Selesai", instance.qty_done),
                    self.field(
                        "current_work_center", "text", "Work Center", work_center
                    ),
                    # Widget khusus garmen (blueprint §9: plugin industri).
                    # Fase B.1.4: `type` = enum kontrak; nama widget dipisah ke
                    # `widget` dan HARUS sama dengan `registerWidget()` frontend
                    # (`modules/garmen/register.ts` -> "garmen-qr-bundle").
                    self.field(
                        "qr_scan",
                        "string",
                        "Scan QR Bundle",
                        instance.code,
                        widget="garmen-qr-bundle",
                    ),
                ],
            }
        ]

    def get_chatter(self) -> dict:
        """Preview 5 event terbaru + `total_count` + cursor halaman berikutnya.

        Memakai helper yang SAMA dengan endpoint chatter
        (`chatter_page_payload`, kontrak §8 / Fase B.2) supaya metadata dan
        `GET /chatter/bundles/<id>` tidak mungkin berbeda bentuk.
        """
        return chatter_page_payload(
            BundleEvent.objects.filter(bundle=self.instance),
            limit=self.CHATTER_PREVIEW_LIMIT,
        )
