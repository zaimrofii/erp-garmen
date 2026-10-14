"""Builder schema resource `qc` — mapping ke `ScrapAccumulator` (Sprint 3.2).

Resource `qc` bukan tabel baru: ia adalah **catatan** scrap/rework/end-loss per
work center (`ScrapAccumulator`, Sprint 2.1). Karena itu:

  * `version` dihitung on-the-fly (tidak ada kolom `version`);
  * state machine minimal (`RECORDED`) — scrap adalah hasil pencatatan, bukan
    alur; definisi DB baru dibuat bila rework perlu alur sendiri;
  * chatter kosong (belum ada event log untuk scrap).
"""

from __future__ import annotations

from apps_industry.garment.api.schema.builder import BaseSchemaBuilder
from apps_industry.garment.models import ScrapAccumulator

RECORDED_STATE = "RECORDED"


class QCSchemaBuilder(BaseSchemaBuilder):
    """Metadata halaman QC (view_type `form`)."""

    MODEL = ScrapAccumulator
    RESOURCE_NAME = "qc"
    RESOURCE_LABEL = "Catatan QC"
    # QC diisi dari tablet kios di lantai produksi. Nilai ini HARUS salah satu enum
    # frontend (`DEVICE_HINTS` di `metadata.schema.ts`); catatan: kode `DeviceProfile`
    # di DB masih "KIOS" (seed `0002_seed_default_profiles`) — selisih penamaan itu
    # dicatat untuk fase pembersihan berikutnya, tidak diubah di B.1 (larangan
    # menyentuh migration).
    DEVICE_HINT = "KIOSK_TABLET"
    SELECT_RELATED = ("work_center", "bundle")

    def get_resource_name(self) -> str:
        return self.RESOURCE_NAME

    def get_title(self) -> str:
        return f"QC #{self.instance.pk}"

    def get_version(self) -> str:
        """Hash state kritis catatan QC (tidak ada kolom `version`)."""
        instance = self.instance
        return self.hash_state(
            instance.pk,
            instance.work_center_id,
            instance.bundle_id,
            instance.qty,
            instance.rework_qty,
            instance.end_loss_qty,
            instance.updated_at.isoformat() if instance.updated_at else "",
        )

    def get_device_hint(self) -> str:
        return self.DEVICE_HINT

    def get_state_machine(self) -> dict:
        """State machine minimal: `RECORDED` tanpa aksi (scrap = hasil, bukan alur).

        Bentuk kontrak §5.1 Fase B.1.2: `possible_states[]` = `{id, label, kind}`;
        karena `RECORDED` adalah state aktif, `kind`-nya `current`.
        """
        return {
            "current_state": RECORDED_STATE,
            "possible_states": [
                {"id": RECORDED_STATE, "label": "Recorded", "kind": "current"}
            ],
            "allowed_actions": [],
        }

    def get_layout_sections(self) -> list[dict]:
        instance = self.instance
        return [
            {
                "section": "Info QC",
                "fields": [
                    self.field(
                        "work_center",
                        "text",
                        "Work Center",
                        instance.work_center.code if instance.work_center_id else None,
                    ),
                    self.field("qty", "number", "Qty Scrap", instance.qty),
                    self.field("rework_qty", "number", "Qty Rework", instance.rework_qty),
                    self.field(
                        "end_loss_qty", "number", "Qty End-Loss", instance.end_loss_qty
                    ),
                    self.field("reason", "text", "Alasan", instance.reason),
                ],
            }
        ]

    def get_chatter(self) -> dict:
        """Belum ada event log untuk catatan QC."""
        return self.empty_chatter()
