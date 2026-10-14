"""Service **material readiness** — kebutuhan material vs penerimaan PO (fase I3).

Menghitung/menyegarkan satu baris ringkasan per ``OrderLine``
(:class:`~apps_industry.garment.models.MaterialReadiness`):

1. ``required_qty`` = Σ ``BOMLine.product_qty`` (komponen **aktif**) dari BOM
   **aktif** produk OrderLine, dikali ``OrderLine.qty``;
2. ``received_qty`` = Σ ``qty_received`` baris PO Odoo (``purchase``/``done``)
   yang komponennya match BOM — match lewat ``Product.odoo_id`` (id
   ``product.product``/**varian**, sama seperti ``purchase.order.line.product_id``);
3. ``shortage_qty`` = ``max(0, required - received)``;
4. ``status`` = ``WAITING`` (received 0) / ``PARTIAL`` (0 < received < required) /
   ``READY`` (received >= required, atau tidak ada kebutuhan);
5. ``expected_date`` = ``min(date_planned)`` dari baris PO yang match;
6. ``po_ids`` / ``po_line_ids`` = id PO & PO line yang match (jejak saja);
7. disimpan lewat ``update_or_create(order_line=...)`` (idempotensi) +
   ``last_computed_at``.

Keputusan yang disengaja (lihat laporan):

* **Tidak ada model PO di MES** — PO di-fetch *on-demand* dari Odoo lewat
  :class:`~integrations.erp_sync.transport.OdooTransport`; yang disimpan hanya
  **id** PO/line sebagai jejak.
* **Tidak ada** ``OdooMapping``: idempotensi memakai ``OneToOneField`` ke
  ``OrderLine`` (satu ringkasan per baris order).
* BOM tidak ditemukan → ``required_qty = 0`` dan ``status = READY`` (dianggap
  tidak butuh material) **plus** ``logger.warning`` — ``compute`` mengembalikan
  instance ``MaterialReadiness`` sehingga penanda "tanpa BOM" tidak bisa
  ditempelkan di return value (dilaporkan).

Murni service: read-only, tanpa Celery, dan **tidak** memanggil Odoo langsung.
"""

from __future__ import annotations

import logging
from datetime import date

from django.utils import timezone

from apps_industry.garment.models import MaterialReadiness, OrderLine
from master.models import BOM

from ..transport import get_transport

logger = logging.getLogger(__name__)

__all__ = ("MaterialReadinessService",)

#: Status PO Odoo yang dianggap memasok material: confirmed + locked/selesai.
PO_STATES = ("purchase", "done")


def _first_id(value):
    """Ambil id dari field many2one Odoo (``[id, name]`` → ``id``).

    Disalin (bukan impor dari :mod:`sale_order_sync`) karena helper di sana
    **privat** (``_`` dan di luar ``__all__``) — beda dengan ``RETRY_EXCEPTIONS``
    di ``tasks_master`` yang publik sehingga diimpor.
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


def _to_date(value):
    """``date_planned`` Odoo (``"YYYY-MM-DD HH:MM:SS"``) → :class:`datetime.date`."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


#: Peringkat status vendor bill — dipakai mengagregasi "yang tertinggi".
_VENDOR_STATUS_RANK = {
    MaterialReadiness.VendorBillStatus.NONE: 0,
    MaterialReadiness.VendorBillStatus.DRAFT: 1,
    MaterialReadiness.VendorBillStatus.POSTED: 2,
    MaterialReadiness.VendorBillStatus.PAID: 3,
}


def _vendor_bill_status(bill):
    """Status satu vendor bill: ``DRAFT`` / ``POSTED`` / ``PAID`` (selain itu ``NONE``).

    ``account.move.state`` yang **valid** di instance ini: ``draft`` / ``posted``
    / ``cancel`` — ``cancel`` dianggap ``NONE`` (bill batal tidak dihitung).
    ``PAID`` ditentukan dari ``payment_state`` **kalau field itu ada** di payload;
    saat ini ``VENDOR_BILL_FIELDS`` transport belum memuatnya, jadi bill yang sudah
    dibayar masih terbaca ``POSTED`` (lihat laporan).
    """
    state = str(bill.get("state") or "").lower()
    if state == "draft":
        return MaterialReadiness.VendorBillStatus.DRAFT
    if state == "posted":
        if str(bill.get("payment_state") or "").lower() == "paid":
            return MaterialReadiness.VendorBillStatus.PAID
        return MaterialReadiness.VendorBillStatus.POSTED
    return MaterialReadiness.VendorBillStatus.NONE


class MaterialReadinessService:
    """Hitung kesiapan material (BOM × qty order) vs penerimaan PO Odoo."""

    def __init__(self, transport=None):
        """``transport`` opsional (untuk test); ``None`` → :func:`get_transport`."""
        self.transport = transport

    # ------------------------------------------------------------------- public
    def compute(self, order_line: OrderLine) -> MaterialReadiness:
        """Hitung & simpan ``MaterialReadiness`` untuk satu ``OrderLine``."""
        transport = self.transport if self.transport is not None else get_transport()
        try:
            return self._compute(order_line, transport)
        finally:
            if self.transport is None:  # tutup hanya kalau kita yang membangunnya
                transport.close()

    def compute_batch(self, order_line_qs) -> dict:
        """Hitung banyak OrderLine sekaligus (transport dibangun sekali).

        Satu baris gagal (mis. error transport) tidak menghentikan batch: error
        dicatat ke log + dihitung di ``errors``.

        Return ``{"processed", "waiting", "partial", "ready", "errors"}``.
        """
        transport = self.transport if self.transport is not None else get_transport()
        result = {"processed": 0, "waiting": 0, "partial": 0, "ready": 0, "errors": 0}
        try:
            # Fetch PO SEKALI untuk seluruh batch (dulu: 2 RPC × jumlah OrderLine).
            # Kalau fetch batch gagal → po_data=None: tiap baris mencoba sendiri
            # dan error-nya dihitung per baris (perilaku lama tetap utuh).
            try:
                po_data = self._fetch_po_data(transport)
            except Exception:  # noqa: BLE001 - biar error dihitung per OrderLine
                logger.warning(
                    "material_readiness: fetch PO batch gagal -> "
                    "fallback fetch per OrderLine.",
                    exc_info=True,
                )
                po_data = None

            for order_line in order_line_qs:
                try:
                    readiness = self._compute(order_line, transport, po_data=po_data)
                except Exception:  # noqa: BLE001 - satu baris gagal != batch gagal
                    logger.exception(
                        "material_readiness: gagal menghitung OrderLine %s.",
                        order_line.pk,
                    )
                    result["errors"] += 1
                    continue

                result["processed"] += 1
                result[readiness.status.lower()] += 1
        finally:
            if self.transport is None:
                transport.close()

        return result

    # ---------------------------------------------------------------- internal
    def _fetch_po_data(self, transport):
        """Ambil PO + barisnya **dan** vendor bill **sekali** (batch-friendly).

        Return ``(po_headers, po_lines_map, vendor_bills)``:

        * ``po_lines_map`` = ``{id PO: [baris PO, ...]}``;
        * ``vendor_bills`` = daftar ``account.move`` (in_invoice/in_refund) mentah.

        Dipakai ``compute_batch`` supaya Odoo tidak dihit per OrderLine (dulu
        2 RPC × jumlah baris; vendor bill ikut sekali juga). Nama method tetap
        ``_fetch_po_data`` dan parameter ``po_data`` tetap seperti spesifikasi
        I3.3b — isinya sekarang bertambah vendor bill (lihat laporan).
        """
        po_headers = transport.fetch_purchase_orders(states=PO_STATES) or []
        po_ids = [row["id"] for row in po_headers if row.get("id") is not None]
        rows = transport.fetch_purchase_order_lines(po_ids) if po_ids else []
        vendor_bills = transport.fetch_vendor_bills() or []

        po_lines_map = {po_id: [] for po_id in po_ids}
        for row in rows or []:
            po_lines_map.setdefault(_first_id(row.get("order_id")), []).append(row)
        return po_headers, po_lines_map, vendor_bills

    @staticmethod
    def _all_po_lines(po_lines_map):
        """Semua baris PO dari ``po_lines_map`` (urutan stabil: per PO)."""
        return [line for lines in po_lines_map.values() for line in lines]

    @staticmethod
    def _vendor_bills(vendor_bills, po_rows, matched_order_ids):
        """Ringkas vendor bill Odoo yang menaut ke PO OrderLine ini (tanpa I/O).

        Penautan: ``account.move.invoice_origin`` (char, diisi Odoo waktu bill
        dibuat **dari** PO) dicocokkan dengan **nama PO** (``purchase.order.name``,
        mis. ``P00012``) dari ``po_rows`` — MES tidak menyimpan model PO.

        Return ``(ids, status_agregat, total_amount)``; tidak ada yang cocok →
        ``([], VendorBillStatus.NONE, 0.0)``.
        """
        po_names = {
            str(row.get("name") or "")
            for row in po_rows or []
            if row.get("name") and row.get("id") in matched_order_ids
        }
        if not po_names:
            return [], MaterialReadiness.VendorBillStatus.NONE, 0.0

        matched = [
            bill
            for bill in vendor_bills or []
            if str(bill.get("invoice_origin") or "") in po_names
        ]
        # Buang bill yang TIDAK dihitung (mis. ``state="cancel"`` → status NONE)
        # supaya id/amount-nya tidak ikut terbaca sebagai tagihan.
        counted = [(bill, _vendor_bill_status(bill)) for bill in matched]
        counted = [
            (bill, status) for bill, status in counted if _VENDOR_STATUS_RANK[status] > 0
        ]
        if not counted:
            return [], MaterialReadiness.VendorBillStatus.NONE, 0.0

        ids = sorted(
            bill["id"] for bill, _status in counted if bill.get("id") is not None
        )

        status = MaterialReadiness.VendorBillStatus.NONE
        for _bill, candidate in counted:
            if _VENDOR_STATUS_RANK[candidate] > _VENDOR_STATUS_RANK[status]:
                status = candidate

        amount = sum(_to_float(bill.get("amount_total")) for bill, _status in counted)
        return ids, status, amount

    def _compute(self, order_line, transport, po_data=None):
        """Inti perhitungan (transport sudah dibangun oleh pemanggil).

        ``po_data`` = hasil :meth:`_fetch_po_data`; ``None`` → fetch sendiri
        (jalur ``compute`` single, signature-nya tidak berubah). Di batch,
        ``compute_batch`` mengirim satu hasil fetch untuk semua OrderLine.
        """
        bom = self._find_bom(order_line)
        component_odoo_ids = self._component_odoo_ids(bom)
        required_qty = self._required_qty(bom, order_line)

        if po_data is None:
            po_data = self._fetch_po_data(transport)
        po_rows, po_lines_map, vendor_bills = po_data
        po_lines = self._all_po_lines(po_lines_map)
        matched = [
            line
            for line in po_lines or []
            if _first_id(line.get("product_id")) in component_odoo_ids
        ]

        received_qty = sum(_to_float(line.get("qty_received")) for line in matched)
        matched_order_ids = {_first_id(line.get("order_id")) for line in matched}
        matched_line_ids = {
            line["id"] for line in matched if line.get("id") is not None
        }

        # Vendor bill Odoo (TX-INVOICE) yang menaut ke PO yang match di atas.
        bill_ids, bill_status, bill_amount = self._vendor_bills(
            vendor_bills, po_rows, matched_order_ids
        )

        readiness, _ = MaterialReadiness.objects.update_or_create(
            order_line=order_line,
            defaults={
                "required_qty": required_qty,
                "received_qty": received_qty,
                "shortage_qty": max(0.0, required_qty - received_qty),
                "expected_date": self._expected_date(matched),
                "status": self._status(required_qty, received_qty),
                "po_ids": sorted(oid for oid in matched_order_ids if oid is not None),
                "po_line_ids": sorted(matched_line_ids),
                "vendor_bill_ids": bill_ids,
                "vendor_bill_status": bill_status,
                "vendor_bill_amount": bill_amount,
                "last_computed_at": timezone.now(),
            },
        )
        return readiness

    @staticmethod
    def _find_bom(order_line):
        """BOM **aktif** untuk produk OrderLine (``None`` kalau tidak ada).

        ``OrderLine.product`` = ``master.Product`` (varian). Urutan pencarian:

        1. BOM aktif yang ``product``-nya **persis** produk OrderLine;
        2. kalau tidak ada, BOM aktif yang ``product``-nya berbagi
           ``Product.odoo_tmpl_id`` sama (varian lain dari template yang sama);
        3. tidak ketemu → ``None`` + ``logger.warning`` (required 0 / READY).
        """
        product = order_line.product
        if product is None:
            logger.warning(
                "material_readiness: OrderLine %s belum punya product -> "
                "BOM tidak dicari, required_qty=0, status READY.",
                order_line.pk,
            )
            return None

        bom = (
            BOM.objects.filter(is_active=True, product=product).order_by("-id").first()
        )
        if bom is None and product.odoo_tmpl_id:
            bom = (
                BOM.objects.filter(
                    is_active=True, product__odoo_tmpl_id=product.odoo_tmpl_id
                )
                .order_by("-id")
                .first()
            )
        if bom is None:
            logger.warning(
                "material_readiness: BOM aktif untuk product %s tidak ada -> "
                "required_qty=0, status READY.",
                product.code,
            )
        return bom

    @staticmethod
    def _component_odoo_ids(bom):
        """Set ``Product.odoo_id`` komponen BOM aktif (id ``product.product``)."""
        if bom is None:
            return set()

        ids = (
            bom.lines.filter(is_active=True)
            .exclude(product=None)
            .values_list("product__odoo_id", flat=True)
        )
        return {odoo_id for odoo_id in ids if odoo_id is not None}

    @staticmethod
    def _required_qty(bom, order_line):
        """Σ ``BOMLine.product_qty`` (komponen aktif) × ``OrderLine.qty``."""
        if bom is None:
            return 0.0

        per_unit = sum(
            bom.lines.filter(is_active=True).values_list("product_qty", flat=True)
        )
        return _to_float(per_unit) * _to_float(order_line.qty)

    @staticmethod
    def _expected_date(matched_lines):
        """``min(date_planned)`` baris PO yang match (``None`` kalau tak ada)."""
        dates = [
            day
            for day in (_to_date(line.get("date_planned")) for line in matched_lines)
            if day is not None
        ]
        return min(dates) if dates else None

    @staticmethod
    def _status(required_qty, received_qty):
        """``WAITING`` / ``PARTIAL`` / ``READY`` (lihat docstring modul)."""
        if required_qty <= 0:
            return MaterialReadiness.Status.READY
        if received_qty <= 0:
            return MaterialReadiness.Status.WAITING
        if received_qty < required_qty:
            return MaterialReadiness.Status.PARTIAL
        return MaterialReadiness.Status.READY
