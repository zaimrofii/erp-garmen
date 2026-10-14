"""Service **rekonsiliasi stok** MES vs Odoo (fase I7).

Membandingkan stok yang dicatat MES dengan on-hand Odoo **per produk**
(``Product.odoo_id`` ↔ ``product.product``):

1. **Sisi MES** — WIP + FG dihitung dari bundle yang sudah ada di lantai
   produksi memakai
   :class:`~apps_industry.garment.services.TwoStageAggregator`
   (WIP → ``bundle.qty``, FG → ``bundle.qty_done``; FG kalau WC bundle adalah
   step routing terminal). Bundle ``state="DRAFT"`` **dilewati** karena belum
   dirilis ke lantai. ``BundleEvent`` **tidak** dipakai untuk qty: event tidak
   menyimpan qty (jumlah material ada di kolom bundle) — lihat laporan.
2. **Sisi Odoo** — daftar lokasi diambil **live** dari Odoo
   (``fetch_internal_locations`` → ``usage='internal'``, anti-hardcode; MES
   ``master.Location`` tidak menyimpan ``usage``/hierarki), lalu on-hand diambil
   **sekali** lewat ``fetch_stock_quants(..., child_of=True)`` supaya lokasi
   **anak** (mis. ``WH/Stok/Shelf 1``, ``…/Gate A``) ikut terhitung, dan
   diagregasi per ``product_id``. Total 2 RPC per run (bukan per produk).
3. **Filter produk** — hanya produk yang ada di ``master.Product`` (``odoo_id``
   terisi) yang dibandingkan; produk demo Furniture di Odoo (tanpa master)
   diabaikan.
4. **Toleransi** — ``is_alert`` = ``|diff| > max(TOLERANCE_UNITS,
   TOLERANCE_PCT × mes_qty)`` dari settings (default 5 unit / 1%).
5. Hasil ditulis sebagai baris
   :class:`~apps_industry.garment.models.StockReconciliation` (append-only per
   run) dan diringkas ``{"total_products", "alert_count", "alerts": [top 5]}``.

Kalau Odoo tidak mengembalikan lokasi internal sama sekali (anomali/config),
``compare`` **tidak** menulis baris (menghindari alert palsu ``odoo_qty=0``) dan
mengembalikan hasil kosong + ``logger.warning``.

Murni service: tanpa Celery, dan **tidak** memanggil Odoo langsung (selalu lewat
transport).
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps_industry.garment.models import Bundle, StockReconciliation
from apps_industry.garment.services.two_stage_aggregator import TwoStageAggregator
from master.models import Product

from ..transport import get_transport

logger = logging.getLogger(__name__)

__all__ = ("ReconciliationService",)

#: Toleransi fallback kalau settings tidak tersedia (nilai produksi = settings).
DEFAULT_TOLERANCE_UNITS = 5
DEFAULT_TOLERANCE_PCT = 0.01

#: State bundle yang **belum** dirilis ke lantai (tidak dihitung sebagai stok).
SKIPPED_BUNDLE_STATES = ("DRAFT",)

#: State bundle "selesai". Dikombinasikan dengan ``qty_done == 0`` untuk mengenali
#: bundle yang berakhir **tanpa produksi** — mis. hasil ``BUNDLE_SCRAP`` yang
#: memindahkan bundle ke ``DONE`` walau tidak ada barang jadi. Kalau ikut dihitung
#: WIP, material yang sudah dibuang tetap terlihat sebagai stok MES (I8.7).
DONE_STATE = "DONE"


def _first_id(value):
    """Ambil id dari field many2one Odoo (``[id, name]`` → ``id``).

    Disalin (bukan impor dari :mod:`material_readiness`) karena helper di sana
    privat — pola yang sama dipakai lintas service.
    """
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value or None


def _to_float(value):
    """Nilai Odoo → float (tahan ``None``/string tak terduga)."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


class ReconciliationService:
    """Bandingkan stok MES (WIP + FG) dengan on-hand Odoo per produk."""

    def __init__(self, transport=None):
        """``transport`` opsional (untuk test); ``None`` → :func:`get_transport`."""
        self.transport = transport

    # ------------------------------------------------------------------- public
    def compare(self) -> dict:
        """Jalankan rekonsiliasi: simpan baris + ringkas hasil.

        Return ``{"total_products", "alert_count", "alerts"}`` dengan
        ``alerts`` = maksimal 5 produk berselisih terbesar (urut ``|diff|`` turun).
        """
        transport = self.transport if self.transport is not None else get_transport()
        try:
            return self._compare(transport)
        finally:
            if self.transport is None:  # tutup hanya kalau kita yang membangunnya
                transport.close()

    def report(self, days=7) -> list[dict]:
        """Riwayat rekonsiliasi ``days`` hari terakhir (untuk endpoint)."""
        try:
            days_int = int(days)
        except (TypeError, ValueError):
            days_int = 7
        since = timezone.now() - timedelta(days=max(days_int, 0))
        rows = (
            StockReconciliation.objects.filter(run_at__gte=since)
            .select_related("product")
            .order_by("-run_at", "product_odoo_id")
        )
        return [
            {
                "run_at": row.run_at,
                "product_code": row.product.code if row.product_id else None,
                "product_odoo_id": row.product_odoo_id,
                "mes_qty": row.mes_qty,
                "odoo_qty": row.odoo_qty,
                "diff": row.diff,
                "is_alert": row.is_alert,
                "notes": row.notes,
            }
            for row in rows
        ]

    # ---------------------------------------------------------------- internal
    def _compare(self, transport) -> dict:
        """Inti ``compare`` dengan transport yang sudah pasti ada."""
        # a. stok MES per Product.odoo_id (WIP + FG dari bundle di lantai)
        mes_qty = self._mes_stock_by_odoo_id()

        # b. lokasi internal — enumerasi live dari Odoo (anti-hardcode)
        locations = transport.fetch_internal_locations() or []
        location_ids = [
            row["id"]
            for row in locations
            if isinstance(row, dict) and row.get("id") is not None
        ]
        if not location_ids:
            logger.warning(
                "reconciliation: Odoo tidak mengembalikan lokasi usage='internal' "
                "-> run dilewati (tidak ada baris ditulis)."
            )
            return {"total_products": 0, "alert_count": 0, "alerts": []}

        # c. on-hand SEKALI untuk semua lokasi internal (termasuk anak)
        quants = transport.fetch_stock_quants(location_ids, child_of=True) or []

        # d. agregat Odoo per product_id + produk master sebagai filter
        odoo_qty = self._odoo_stock_by_product_id(quants)
        products = self._master_products_by_odoo_id()

        # e. bandingkan + flag produk di luar toleransi
        rows = self._build_rows(mes_qty, odoo_qty, products)

        # f. simpan (append-only per run)
        if rows:
            StockReconciliation.objects.bulk_create(rows)

        # g. ringkasan
        alert_rows = [row for row in rows if row.is_alert]
        top_alerts = sorted(alert_rows, key=lambda row: abs(row.diff), reverse=True)[:5]
        return {
            "total_products": len(rows),
            "alert_count": len(alert_rows),
            "alerts": [self._alert_payload(row, products) for row in top_alerts],
        }

    # -------------------------------------------------------------- toleransi
    @staticmethod
    def _tolerance() -> tuple:
        """``(units, pct)`` toleransi dari settings (dengan fallback aman)."""
        units = getattr(settings, "RECONCILIATION_TOLERANCE_UNITS", DEFAULT_TOLERANCE_UNITS)
        pct = getattr(settings, "RECONCILIATION_TOLERANCE_PCT", DEFAULT_TOLERANCE_PCT)
        try:
            return float(units), float(pct)
        except (TypeError, ValueError):
            return DEFAULT_TOLERANCE_UNITS, DEFAULT_TOLERANCE_PCT

    @staticmethod
    def _build_rows(mes_qty, odoo_qty, products) -> list:
        """Bentuk baris per produk: ``(mes ∪ odoo) ∩ master`` (tanpa simpan).

        Produk yang tidak ada di ``master.Product`` (mis. data demo Odoo)
        diabaikan. ``is_alert`` = ``|diff| > max(units, pct × |mes_qty|)``.
        """
        tolerance_units, tolerance_pct = ReconciliationService._tolerance()
        rows = []
        for odoo_id in sorted(set(mes_qty) | set(odoo_qty)):
            product = products.get(odoo_id)
            if product is None:
                continue
            mes = float(mes_qty.get(odoo_id, 0.0))
            odoo = float(odoo_qty.get(odoo_id, 0.0))
            diff = mes - odoo
            threshold = max(tolerance_units, tolerance_pct * abs(mes))
            rows.append(
                StockReconciliation(
                    product=product,
                    product_odoo_id=int(odoo_id),
                    mes_qty=mes,
                    odoo_qty=odoo,
                    diff=diff,
                    is_alert=abs(diff) > threshold,
                    notes=f"toleransi={threshold:g}",
                )
            )
        return rows

    @staticmethod
    def _alert_payload(row, products) -> dict:
        """Satu entri ``alerts`` (produk + qty + selisih)."""
        product = products.get(row.product_odoo_id)
        return {
            "product_odoo_id": row.product_odoo_id,
            "product_code": product.code if product is not None else None,
            "mes_qty": row.mes_qty,
            "odoo_qty": row.odoo_qty,
            "diff": row.diff,
        }

    @staticmethod
    def _mes_bundles():
        """QuerySet bundle yang dihitung sebagai **stok MES** (WIP + FG).

        Dikecualikan:

          * ``state`` di :data:`SKIPPED_BUNDLE_STATES` (``DRAFT`` — belum dirilis
            ke lantai);
          * ``state="DONE"`` **dan** ``qty_done=0`` — bundle berakhir tanpa
            produksi (mis. hasil ``BUNDLE_SCRAP``) sehingga tidak boleh lagi
            dihitung sebagai WIP (I8.7).

        Satu-satunya tempat filter ini hidup supaya aturan "apa yang dianggap
        stok MES" tidak tersebar. ``TwoStageAggregator`` **tidak** diubah: ia
        penyusun payload two-stage (dipanggil per bundle saat event sync), bukan
        pembaca agregat — semantik stage-nya terkunci kontrak TX-WIP-ISSUE/FG.
        """
        return (
            Bundle.objects.exclude(state__in=SKIPPED_BUNDLE_STATES)
            .exclude(state=DONE_STATE, qty_done=0)
            .select_related("work_order__order_line__product", "current_work_center")
            .order_by("code")
        )

    @staticmethod
    def _mes_stock_by_odoo_id() -> dict:
        """Stok MES per ``Product.odoo_id``: Σ qty WIP + FG bundle di lantai.

        Stage/qty ditentukan :class:`TwoStageAggregator` (WIP → ``bundle.qty``,
        FG → ``bundle.qty_done``). Bundle yang dikecualikan (DRAFT, serta DONE
        tanpa produksi) lihat :meth:`_mes_bundles`. Satu instance aggregator
        dipakai ulang supaya routing hanya di-query sekali (pola batch
        ``_fetch_po_data``).
        """
        aggregator = TwoStageAggregator()
        bundles = ReconciliationService._mes_bundles()
        totals: dict = {}
        for bundle in bundles:
            order_line = bundle.work_order.order_line
            product = order_line.product if order_line is not None else None
            odoo_id = getattr(product, "odoo_id", None)
            if not odoo_id:
                continue  # produk belum tersinkron → tidak bisa dibandingkan
            move = aggregator.build_payload(bundle)
            key = int(odoo_id)
            totals[key] = totals.get(key, 0.0) + float(move.qty or 0)
        return totals

    @staticmethod
    def _odoo_stock_by_product_id(quants) -> dict:
        """Agregat ``quantity`` Odoo per id ``product.product`` (semua lokasi)."""
        totals: dict = {}
        for row in quants or []:
            if not isinstance(row, dict):
                continue
            product_id = _first_id(row.get("product_id"))
            if product_id is None:
                continue
            key = int(product_id)
            totals[key] = totals.get(key, 0.0) + _to_float(row.get("quantity"))
        return totals

    @staticmethod
    def _master_products_by_odoo_id() -> dict:
        """``{odoo_id: Product}`` — HANYA produk master (demo Odoo diabaikan)."""
        return {
            int(product.odoo_id): product
            for product in Product.objects.filter(odoo_id__isnull=False)
        }
