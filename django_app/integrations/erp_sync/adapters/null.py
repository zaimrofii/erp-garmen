"""Adapter no-op (`NullAdapter`).

Dipakai untuk development/testing tanpa instance Odoo: semua panggilan dicatat
ke log dan mengembalikan nilai dummy yang aman (tidak ada request jaringan).

`NullAdapter` mengimplementasikan **dua** interface:

* :class:`ERPAdapter` — kontrak bisnis two-stage sync (WIP issue + FG receipt)
  dengan ``erp_id`` unik per push supaya alur idempotensi (`SyncRecord`) bisa
  diuji end-to-end tanpa ERP nyata;
* :class:`ERPTransport` — transport no-op lama (login/search_read/create/write/
  call) yang masih dipakai task diagnosa ``erp_sync.ping``.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .base import STAGE_FG, STAGE_WIP, ERPAdapter, ERPResponse, ERPTransport

logger = logging.getLogger(__name__)

#: Stage label kontrak **tambahan** (TX-SCRAP & TX-INVOICE) — nilainya sejajar
#: dengan ``STAGE_SCRAP``/``STAGE_INVOICE`` di ``odoo.py``; didefinisikan lokal
#: supaya modul ini tidak perlu mengimpor adapter vendor.
STAGE_SCRAP = "SCRAP"
STAGE_INVOICE = "INVOICE"
#: H2.5 — stage inventory adjustment (sejajar `STAGE_INVENTORY_ADJUST` di ``odoo.py``).
STAGE_INVENTORY_ADJUST = "INVENTORY_ADJUST"
#: H2.6 — stage stock transfer (sejajar `STAGE_STOCK_TRANSFER` di ``odoo.py``).
STAGE_STOCK_TRANSFER = "STOCK_TRANSFER"
#: H3.2 — stage vendor bill (sejajar `STAGE_VENDOR_BILL` di ``odoo.py``/``models.py``).
STAGE_VENDOR_BILL = "VENDOR_BILL"
#: H3.3 — stage payment (`account.payment`; sejajar `STAGE_PAYMENT` di ``odoo.py``).
STAGE_PAYMENT = "PAYMENT"
#: H3.4 — stage journal entry manual (`account.move` entry; sejajar di ``odoo.py``).
STAGE_JOURNAL_ENTRY = "JOURNAL_ENTRY"


class NullAdapter(ERPAdapter, ERPTransport):
    """Implementasi palsu: tidak melakukan request apa pun ke ERP."""

    #: Nama vendor (dipakai log & factory).
    name = "null"

    def __init__(self, uid: int = 1) -> None:
        self.uid = uid
        #: Riwayat push (untuk diagnosa & assertion test).
        self.pushed: list[ERPResponse] = []

    # ------------------------------------------------------------------
    # ERPAdapter — two-stage sync
    # ------------------------------------------------------------------
    def push_wip_issue(self, payload: dict) -> ERPResponse:
        """Catat WIP issue ke log; selalu sukses dengan erp_id unik."""
        return self._push(STAGE_WIP, payload)

    def push_fg_receipt(self, payload: dict) -> ERPResponse:
        """Catat FG receipt ke log; selalu sukses dengan erp_id unik."""
        return self._push(STAGE_FG, payload)

    # ------------------------------------------------------------------
    # Kontrak tambahan TX-SCRAP & TX-INVOICE (I4/I5)
    # ------------------------------------------------------------------
    def push_scrap_wo(self, wo: dict) -> ERPResponse:
        """Catat scrap ke log; selalu sukses dengan erp_id unik.

        ``push_scrap_wo``/``push_customer_invoice_wo`` tidak dideklarasikan di
        ``ERPAdapter`` (kontraknya ditambahkan langsung di ``OdooAdapter`` pada
        I4/I5), sehingga **tanpa** method ini ``ERP_ADAPTER=null`` melempar
        ``AttributeError`` dan task scrap/invoice selalu berakhir FAILED —
        ketahuan saat menulis test fail-safe end-to-end I8.10. Implementasi
        bisnis di ``OdooAdapter`` **tidak** disentuh.
        """
        return self._push(STAGE_SCRAP, wo)

    def push_customer_invoice_wo(self, wo: dict) -> ERPResponse:
        """Catat customer invoice ke log; selalu sukses dengan erp_id unik (I8.10)."""
        return self._push(STAGE_INVOICE, wo)

    def push_inventory_adjustment(self, payload: dict) -> ERPResponse:
        """Catat inventory adjustment ke log; selalu sukses dengan erp_id unik (H2.5).

        Tanpa method ini ``ERP_ADAPTER=null`` melempar ``AttributeError`` dan task
        adjustment selalu berakhir FAILED (pola yang sama dengan
        ``push_scrap_wo``/``push_customer_invoice_wo`` — lihat catatan di method itu).
        """
        return self._push(STAGE_INVENTORY_ADJUST, payload)

    def push_stock_transfer_wo(self, transfer: dict) -> ERPResponse:
        """Catat stock transfer ke log; selalu sukses dengan erp_id unik (H2.6).

        Tanpa method ini ``ERP_ADAPTER=null`` melempar ``AttributeError`` dan task
        transfer selalu berakhir FAILED (pola I8.10/H2.5).
        """
        return self._push(STAGE_STOCK_TRANSFER, transfer)

    def push_customer_invoice(self, payload: dict) -> ERPResponse:
        """Catat customer invoice **harga nyata** ke log; selalu sukses (H3.1).

        Sejajar ``push_customer_invoice_wo`` (I5) tetapi menerima payload baris
        eksplisit dari model ``CustomerInvoice``; stage ledger yang dipakai tetap
        ``INVOICE`` (di-reuse, bukan stage baru).
        """
        return self._push(STAGE_INVOICE, payload)

    def cancel_customer_invoice(self, erp_id: str) -> ERPResponse:
        """Catat pembatalan customer invoice ke log; selalu sukses (H3.1)."""
        return self._push(STAGE_INVOICE, {"ref": str(erp_id or ""), "action": "cancel"})

    def push_vendor_bill(self, payload: dict) -> ERPResponse:
        """Catat vendor bill (`account.move` in_invoice) ke log; selalu sukses (H3.2).

        Sejajar ``push_customer_invoice`` (H3.1) tetapi stage ledger-nya
        ``VENDOR_BILL`` (baru) — tanpa method ini ``ERP_ADAPTER=null`` melempar
        ``AttributeError`` dan task push bill selalu FAILED (pola I8.10).
        """
        return self._push(STAGE_VENDOR_BILL, payload)

    def cancel_vendor_bill(self, erp_id: str) -> ERPResponse:
        """Catat pembatalan vendor bill ke log; selalu sukses (H3.2)."""
        return self._push(STAGE_VENDOR_BILL, {"ref": str(erp_id or ""), "action": "cancel"})

    def push_payment(self, payload: dict) -> ERPResponse:
        """Catat payment (`account.payment`) ke log; selalu sukses (H3.3).

        Sejajar ``push_vendor_bill`` (H3.2) tetapi stage ledger-nya ``PAYMENT`` (baru) —
        tanpa method ini ``ERP_ADAPTER=null`` melempar ``AttributeError`` dan task push
        payment selalu FAILED (pola I8.10/H2.5/H3.2).
        """
        return self._push(STAGE_PAYMENT, payload)

    def push_journal_entry(self, payload: dict) -> ERPResponse:
        """Catat journal entry (`account.move` ``move_type='entry'``) ke log (H3.4).

        Tanpa method ini ``ERP_ADAPTER=null`` melempar ``AttributeError`` dan task push
        journal entry selalu FAILED (pola I8.10/H2.5/H3.2/H3.3).
        """
        return self._push(STAGE_JOURNAL_ENTRY, payload)

    def cancel_journal_entry(self, erp_id: str) -> ERPResponse:
        """Catat pembatalan journal entry ke log; selalu sukses (H3.4)."""
        return self._push(
            STAGE_JOURNAL_ENTRY, {"ref": str(erp_id or ""), "action": "cancel"}
        )

    def cancel_payment(self, erp_id: str) -> ERPResponse:
        """Catat pembatalan payment ke log; selalu sukses (H3.3)."""
        return self._push(STAGE_PAYMENT, {"ref": str(erp_id or ""), "action": "cancel"})

    def health_check(self) -> bool:
        """NullAdapter selalu siap (tidak ada dependensi eksternal)."""
        logger.info("[NullAdapter] health_check() -> True")
        return True

    # ------------------------------------------------------------------
    # ERPTransport — transport no-op (legacy)
    # ------------------------------------------------------------------
    def login(self) -> int:
        logger.info("[NullAdapter] login() -> uid=%s", self.uid)
        return self.uid

    def search_read(
        self,
        model: str,
        domain: Sequence | None = None,
        fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        logger.info(
            "[NullAdapter] search_read(model=%s, domain=%s, fields=%s, limit=%s, offset=%s, order=%s) -> []",
            model,
            list(domain or []),
            list(fields or []),
            limit,
            offset,
            order,
        )
        return []

    def create(self, model: str, values: Mapping[str, Any]) -> int:
        logger.info("[NullAdapter] create(model=%s, values=%s) -> 999", model, dict(values))
        return 999

    def write(self, model: str, ids: Sequence[int], values: Mapping[str, Any]) -> bool:
        logger.info(
            "[NullAdapter] write(model=%s, ids=%s, values=%s) -> True",
            model,
            list(ids),
            dict(values),
        )
        return True

    def call(
        self,
        model: str,
        method: str,
        args: Sequence | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        logger.info(
            "[NullAdapter] call(model=%s, method=%s, args=%s, kwargs=%s) -> None",
            model,
            method,
            list(args or []),
            dict(kwargs or {}),
        )
        return None

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------
    def _push(self, stage: str, payload: dict) -> ERPResponse:
        """Bangun ERPResponse sukses dengan ``erp_id`` unik (``NULL-<uuid4>``)."""
        data = dict(payload or {})
        response = ERPResponse(
            ok=True,
            erp_id=f"NULL-{uuid4()}",
            raw={"payload": data},
            error=None,
            stage=stage,
            ref=str(data.get("ref") or ""),
        )
        self.pushed.append(response)
        logger.info(
            "[NullAdapter] push %s ref=%s qty=%s -> %s",
            stage,
            response.ref or "-",
            data.get("qty"),
            response.erp_id,
        )
        return response
