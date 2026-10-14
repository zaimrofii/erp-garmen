"""Builder schema resource `order-lines` (Kontrak §1) — FASE 3.4 (P1).

`OrderLine` adalah **input** produksi (baris pesanan: produk + qty + tag +
kupon). Ia **tidak punya state machine** — alur hidup produksi ada di
`WorkOrder`/`Bundle` — jadi:

* `get_state_machine()` mengembalikan blok **kosong** `{current_state: "N/A",
  possible_states: [], allowed_actions: []}` supaya kontrak §1 tetap terpenuhi
  tanpa memaksakan state yang tidak ada (tidak ada baris di DB yang perlu
  di-seed, tidak ada aksi yang bisa di-POST);
* `version` dihitung **on-the-fly** (SHA-256 state kritis) seperti
  `WorkOrderSchemaBuilder` — model `OrderLine` tidak punya field `version`.

Kenapa resource ini ditambahkan: jalur "order baru → WorkOrder → Bundle" (FASE
3.4) butuh cara **menemukan OrderLine lewat HTTP**; sebelumnya registry hanya
punya `work-orders`/`bundles`/`qc` sehingga `GET /garmen/order-lines/` → 404.
"""

from __future__ import annotations

from apps_industry.garment.api.schema.builder import BaseSchemaBuilder
from apps_industry.garment.models import OrderLine

#: OrderLine tidak punya state machine → nilai `current_state` penanda "N/A".
NO_STATE_MACHINE = "N/A"


class OrderLineSchemaBuilder(BaseSchemaBuilder):
    """Metadata halaman Order Line (view_type `form`)."""

    MODEL = OrderLine
    RESOURCE_NAME = "order-lines"
    RESOURCE_LABEL = "Order Line"
    DEVICE_HINT = "OPERATOR_HP"  # dibaca supervisor/PPIC di HP
    SELECT_RELATED = ("order", "product")

    def get_resource_name(self) -> str:
        return self.RESOURCE_NAME

    def get_title(self) -> str:
        return f"Order Line #{self.instance.pk}"

    def get_version(self) -> str:
        """SHA-256 dari `order|product|qty|updated_at` (OrderLine tanpa `version`)."""

        instance = self.instance
        return self.hash_state(
            instance.order_id,
            getattr(instance.product, "code", None),
            instance.qty,
            instance.updated_at.isoformat() if instance.updated_at else "",
        )

    def get_device_hint(self) -> str:
        return self.DEVICE_HINT

    def get_state_machine(self) -> dict:
        """OrderLine bukan entitas ber-state → blok kosong tanpa aksi."""

        return {
            "current_state": NO_STATE_MACHINE,
            "possible_states": [],
            "allowed_actions": [],
        }

    def get_layout_sections(self) -> list[dict]:
        instance = self.instance
        return [
            {
                "section": "Info Order Line",
                "fields": [
                    self.field("order_code", "text", "Kode Order", instance.order.code),
                    self.field(
                        "product_code",
                        "text",
                        "Produk",
                        getattr(instance.product, "code", None),
                    ),
                    self.field("qty", "number", "Qty", instance.qty),
                    self.field("tag", "text", "Tag", instance.tag),
                ],
            }
        ]

    def get_chatter(self) -> dict:
        """Belum ada event log untuk OrderLine (chatter kosong)."""

        return self.empty_chatter()
