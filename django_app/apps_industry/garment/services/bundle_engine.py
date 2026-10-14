"""BundleEngine — pembentukan bundle dari matriks ukuran (Sprint 2.2).

Bundle = unit pelacakan terkecil di lantai produksi. Satu `OrderLine` dipecah
per **size**; setiap size dipecah lagi per `bundle_size`, dan sisanya menjadi
bundle terakhir yang lebih kecil.

Contoh: ``size_matrix={"L": 7, "M": 3}``, ``bundle_size=5`` ->
  * L -> 2 bundle (5 + 2)
  * M -> 1 bundle (3)

Kode bundle: ``f"{order_line.id}-{size}-{seq:03d}"`` dengan ``seq`` mulai dari 1
dan **reset per size**, mis. ``12-L-001``, ``12-L-002``, ``12-M-001``.

Urutan pembuatan mengikuti urutan key `size_matrix` (dict Python mempertahankan
urutan input) supaya hasilnya deterministik. Service ini sinkron murni: tidak
mengubah state order/line dan tidak menerbitkan event.
"""

from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from apps_industry.garment.models import Bundle, OrderLine, WorkOrder
from apps_industry.garment.services.exceptions import BundleEngineError

logger = logging.getLogger(__name__)


class BundleEngine:
    """Pembentukan bundle dari matriks ukuran (stateless)."""

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _validate_bundle_size(bundle_size: Any) -> int:
        """`bundle_size` harus bilangan bulat > 0."""
        try:
            size = int(bundle_size)
        except (TypeError, ValueError) as exc:
            raise BundleEngineError("bundle_size harus bilangan bulat > 0.") from exc
        if size <= 0:
            raise BundleEngineError("bundle_size harus bilangan bulat > 0.")
        return size

    @staticmethod
    def _normalize(size_matrix: Any) -> dict[str, int]:
        """Validasi matriks ukuran -> dict {size: qty} yang sudah dinormalkan."""
        if not size_matrix:
            raise BundleEngineError("size_matrix tidak boleh kosong.")

        normalized: dict[str, int] = {}
        for size, qty in size_matrix.items():
            size_code = str(size).strip().upper()
            if not size_code:
                raise BundleEngineError("kode size tidak boleh kosong.")
            try:
                qty_int = int(qty)
            except (TypeError, ValueError) as exc:
                raise BundleEngineError(
                    f"qty untuk size '{size}' harus angka bulat."
                ) from exc
            if qty_int < 0:
                raise BundleEngineError(f"qty untuk size '{size}' tidak boleh negatif.")
            # Size yang sama (beda kapitalisasi) digabung.
            normalized[size_code] = normalized.get(size_code, 0) + qty_int

        # Total qty = sum(size_matrix.values()) harus > 0.
        if sum(normalized.values()) <= 0:
            raise BundleEngineError("total qty (sum size_matrix) harus > 0.")
        return normalized

    @staticmethod
    def _require_saved(order_line: OrderLine) -> OrderLine:
        if order_line is None:
            raise BundleEngineError("order_line wajib diisi.")
        if order_line.pk is None:
            raise BundleEngineError("order_line harus sudah tersimpan (punya id).")
        return order_line

    @staticmethod
    def _resolve_work_order(order_line: OrderLine) -> WorkOrder:
        """WorkOrder pertama dari order line (deterministik: id terkecil)."""
        work_order = order_line.work_orders.order_by("id").first()
        if work_order is None:
            raise BundleEngineError(
                f"order line {order_line.pk} belum punya WorkOrder; "
                "buat work order dulu sebelum membentuk bundle."
            )
        return work_order

    @staticmethod
    def _plan(
        order_line: OrderLine, size_matrix: dict[str, int], bundle_size: int
    ) -> list[dict]:
        """Rencana bundle (belum disimpan) untuk semua size."""
        plan: list[dict] = []
        for size, total_qty in size_matrix.items():
            remaining = total_qty
            seq = 1
            while remaining > 0:
                qty = min(bundle_size, remaining)
                plan.append(
                    {
                        "code": f"{order_line.id}-{size}-{seq:03d}",
                        "size": size,
                        "sku_variant": "",
                        "qty": qty,
                    }
                )
                remaining -= qty
                seq += 1
        return plan

    # ------------------------------------------------------------------- public
    @classmethod
    def preview_bundles(
        cls, order_line: OrderLine, size_matrix: Any, bundle_size: Any
    ) -> list[dict]:
        """Rencana bundle **tanpa menyimpan** (untuk preview UI di Fase 3)."""
        order_line = cls._require_saved(order_line)
        size = cls._validate_bundle_size(bundle_size)
        normalized = cls._normalize(size_matrix)
        return cls._plan(order_line, normalized, size)

    @classmethod
    def create_bundles(
        cls, order_line: OrderLine, size_matrix: Any, bundle_size: Any
    ) -> list[Bundle]:
        """Buat bundle (bulk create) dan kembalikan Bundle yang sudah tersimpan.

        Catatan: `bulk_create()` tidak memanggil `save()`, jadi `version`
        (SHA-256 state kritis) dihitung manual di sini — hasilnya identik dengan
        yang akan ditulis `Bundle.save()`.
        """
        order_line = cls._require_saved(order_line)
        size = cls._validate_bundle_size(bundle_size)
        normalized = cls._normalize(size_matrix)
        work_order = cls._resolve_work_order(order_line)
        plan = cls._plan(order_line, normalized, size)
        if not plan:
            return []

        timestamp = timezone.now()
        bundles: list[Bundle] = []
        for item in plan:
            bundle = Bundle(
                code=item["code"],
                work_order=work_order,
                size=item["size"],
                sku_variant=item["sku_variant"],
                qty=item["qty"],
            )
            bundle.version = bundle.compute_version(timestamp)
            # Penanda state kritis (dipakai save()) di-set manual karena
            # bulk_create() melewati save().
            bundle._loaded_critical = {
                field: getattr(bundle, field) for field in Bundle.CRITICAL_FIELDS
            }
            bundles.append(bundle)

        Bundle.objects.bulk_create(bundles)
        logger.info(
            "bundle engine: %d bundle dibuat untuk order line %s",
            len(bundles),
            order_line.pk,
        )
        return bundles
