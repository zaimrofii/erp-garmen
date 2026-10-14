"""TwoStageAggregator — payload stok dua tahap (WIP + FG) untuk Odoo (Sprint 2.3).

Blueprint §4 **Two-Stage Stock Sync**:

  1. **WIP Issue**  — bahan keluar saat bundle dilepas ke lantai produksi;
  2. **FG Receipt** — barang jadi masuk saat bundle selesai (WC step terminal).

Service ini **hanya menyusun payload** (`AggregatedMove`). Pengiriman ke Odoo
dilakukan `integrations.erp_sync` pada Fase 4 — tidak ada JSON-RPC/Odoo call di
sini supaya service tetap sinkron murni dan bisa diuji tanpa Odoo.

Penentuan tahap: bundle dianggap **FG** kalau `bundle.current_work_center`
adalah work center dari step routing dengan `is_terminal=True`; selain itu
**WIP**. Routing yang dipakai = routing aktif pertama (by id), bisa di-inject
lewat konstruktor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from apps_industry.garment.models import Bundle, ProcessRouting, WorkOrder
from apps_industry.garment.services.exceptions import TwoStageAggregatorError

logger = logging.getLogger(__name__)

STAGE_WIP = "WIP"
STAGE_FG = "FG"


@dataclass(frozen=True)
class AggregatedMove:
    """Satu pergerakan stok siap kirim (WIP issue / FG receipt)."""

    stage: Literal["WIP", "FG"]
    product_ref: str
    qty: int
    ref: str
    wc_code: str | None = None
    metadata: dict = field(default_factory=dict)


class TwoStageAggregator:
    """Penyusun payload stok dua tahap (stateless, tanpa I/O eksternal)."""

    def __init__(self, routing: ProcessRouting | None = None):
        """`routing` opsional; default routing aktif pertama (by id)."""
        self._routing = routing

    @property
    def routing(self) -> ProcessRouting | None:
        """Routing yang dipakai untuk menentukan step terminal."""
        if self._routing is not None:
            return self._routing
        return ProcessRouting.objects.filter(is_active=True).order_by("id").first()

    # ------------------------------------------------------------------- stage
    def is_terminal_work_center(self, work_center) -> bool:
        """True kalau `work_center` dipakai step terminal pada routing."""
        routing = self.routing
        if routing is None or work_center is None:
            return False
        return routing.steps.filter(work_center=work_center, is_terminal=True).exists()

    def compute_stage(self, bundle: Bundle) -> str:
        """`"FG"` kalau WC bundle adalah WC step terminal, selain itu `"WIP"`."""
        if bundle is None:
            raise TwoStageAggregatorError("bundle wajib diisi.")
        if bundle.current_work_center_id is None:
            return STAGE_WIP
        if self.is_terminal_work_center(bundle.current_work_center):
            return STAGE_FG
        return STAGE_WIP

    # ----------------------------------------------------------------- payload
    def build_payload(self, bundle: Bundle) -> AggregatedMove:
        """Payload dengan stage otomatis (WIP/FG)."""
        return self._build(bundle, self.compute_stage(bundle))

    def build_wip_payload(self, bundle: Bundle) -> AggregatedMove:
        """Payload WIP Issue (error kalau bundle sudah di WC terminal)."""
        if self.compute_stage(bundle) == STAGE_FG:
            raise TwoStageAggregatorError(
                f"bundle {bundle.code} sudah di work center terminal (FG), bukan WIP."
            )
        return self._build(bundle, STAGE_WIP)

    def build_fg_payload(self, bundle: Bundle) -> AggregatedMove:
        """Payload FG Receipt (error kalau bundle belum di WC terminal)."""
        if self.compute_stage(bundle) != STAGE_FG:
            raise TwoStageAggregatorError(
                f"bundle {bundle.code} belum sampai work center terminal (masih WIP)."
            )
        return self._build(bundle, STAGE_FG)

    def aggregate_for_work_order(self, work_order: WorkOrder) -> list[AggregatedMove]:
        """Agregasi semua bundle satu WorkOrder, dikelompokkan per (stage, produk).

        `ref` diisi kode work order, `wc_code` = None (agregat lintas WC), dan
        detail WC/bundle ditaruh di `metadata`. Urutan hasil: WIP dulu, lalu FG,
        masing-masing urut `product_ref`.
        """
        if work_order is None:
            raise TwoStageAggregatorError("work_order wajib diisi.")

        grouped: dict[tuple[str, str], dict] = {}
        for bundle in work_order.bundles.order_by("code"):
            move = self.build_payload(bundle)
            bucket = grouped.setdefault(
                (move.stage, move.product_ref),
                {"qty": 0, "bundles": [], "wc_codes": set()},
            )
            bucket["qty"] += move.qty
            bucket["bundles"].append(bundle.code)
            if move.wc_code:
                bucket["wc_codes"].add(move.wc_code)

        moves: list[AggregatedMove] = []
        for (stage, product_ref), bucket in sorted(
            grouped.items(), key=lambda item: (item[0][0] != STAGE_WIP, item[0][1])
        ):
            moves.append(
                AggregatedMove(
                    stage=stage,
                    product_ref=product_ref,
                    qty=bucket["qty"],
                    ref=work_order.code,
                    wc_code=None,
                    metadata={
                        "aggregate": True,
                        "work_order": work_order.code,
                        "bundle_count": len(bucket["bundles"]),
                        "bundle_codes": bucket["bundles"],
                        "wc_codes": sorted(bucket["wc_codes"]),
                    },
                )
            )
        return moves

    # ---------------------------------------------------------------- internal
    def _build(self, bundle: Bundle, stage: str) -> AggregatedMove:
        """Susun satu payload dari bundle.

        Qty: WIP memakai `bundle.qty` (qty yang dilepas ke lantai produksi), FG
        memakai `bundle.qty_done` (qty yang benar-benar selesai).
        """
        if bundle is None:
            raise TwoStageAggregatorError("bundle wajib diisi.")

        order_line = bundle.work_order.order_line
        qty = bundle.qty_done if stage == STAGE_FG else bundle.qty

        return AggregatedMove(
            stage=stage,
            product_ref=order_line.product.code,
            qty=qty,
            ref=bundle.code,
            wc_code=(
                bundle.current_work_center.code if bundle.current_work_center_id else None
            ),
            metadata={
                "bundle_id": bundle.pk,
                "bundle_version": bundle.version,
                "work_order": bundle.work_order.code,
                "order_line_id": order_line.pk,
                "order_type": order_line.order.order_type,
                "tag": order_line.tag,
                "size": bundle.size,
                "sku_variant": bundle.sku_variant,
                "state": bundle.state,
            },
        )
