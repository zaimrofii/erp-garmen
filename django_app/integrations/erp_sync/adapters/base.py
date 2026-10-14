"""Interface adapter ERP (Fase 4 — Two-Stage Sync WIP + FG).

Ada **dua level** abstraksi di paket `integrations.erp_sync.adapters`:

* :class:`ERPTransport` — transport tingkat rendah (`login`, `search_read`,
  `create`, `write`, `call`). Dipakai untuk eksplorasi master data dan task
  diagnosa ``erp_sync.ping``; implementasi nyatanya
  :class:`~integrations.erp_sync.adapters.odoo.OdooJSONRPCAdapter`.
* :class:`ERPAdapter` — kontrak **bisnis** sinkronisasi stok dua tahap
  (WIP issue + FG receipt) + ``health_check``. Setiap vendor ERP
  (Null/Odoo/Accurate/SAP) mengimplementasikan interface ini supaya kode
  pemanggil (Celery task, endpoint sync) tidak perlu tahu vendor mana pun.

Method bisnis **selalu** mengembalikan :class:`ERPResponse` (tidak melempar
exception untuk kegagalan ERP biasa) supaya kegagalan bisa dicatat ke
``SyncRecord`` tanpa membatalkan alur produksi di lantai.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

#: Nama stage two-stage sync (satu-satunya sumber kebenaran di paket ini).
STAGE_WIP = "WIP"
STAGE_FG = "FG"


@dataclass
class ERPResponse:
    """Hasil satu panggilan push ke ERP (WIP issue atau FG receipt)."""

    ok: bool
    erp_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    stage: str = ""
    ref: str = ""

    def as_dict(self) -> dict[str, Any]:
        """Bentuk JSON-safe (untuk log, ``SyncRecord``, atau respons API)."""
        return {
            "ok": self.ok,
            "erp_id": self.erp_id,
            "error": self.error,
            "stage": self.stage,
            "ref": self.ref,
            "raw": dict(self.raw),
        }

    def __str__(self) -> str:
        status = "ok" if self.ok else f"gagal: {self.error}"
        return f"ERPResponse[{self.stage or '?'} {self.ref or '-'}] {status}"


class ERPAdapterError(Exception):
    """Error adapter ERP yang harus menghentikan alur (mis. salah konfigurasi)."""


class ERPAdapter(ABC):
    """Kontrak adapter sinkronisasi stok dua tahap (WIP + FG)."""

    #: Nama vendor untuk log/diagnosa (di-override subclass).
    name: str = "erp"

    @abstractmethod
    def push_wip_issue(self, payload: dict) -> ERPResponse:
        """Kirim pemakaian bahan (WIP issue) ke ERP."""

    @abstractmethod
    def push_fg_receipt(self, payload: dict) -> ERPResponse:
        """Kirim penerimaan barang jadi (FG receipt) ke ERP."""

    @abstractmethod
    def health_check(self) -> bool:
        """True kalau ERP siap menerima push (tanpa efek samping)."""

    def close(self) -> None:
        """Tutup resource yang dipakai adapter (opsional, default no-op)."""
        return None

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name}>"


class ERPTransport(ABC):
    """Transport tingkat rendah ke ERP (dipakai ``erp_sync.ping`` & master data).

    Interface ini adalah kontrak lama yang **dipertahankan** agar
    ``OdooJSONRPCAdapter`` (JSON-RPC) dan ``NullAdapter`` tetap bisa dipakai
    untuk membaca/menulis record ERP secara bebas, terpisah dari kontrak bisnis
    :class:`ERPAdapter` (two-stage sync).
    """

    @abstractmethod
    def login(self) -> int:
        """Autentikasi ke ERP, kembalikan user id (uid)."""

    @abstractmethod
    def search_read(
        self,
        model: str,
        domain: Sequence | None = None,
        fields: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Baca beberapa record sekaligus (`search_read`)."""

    @abstractmethod
    def create(self, model: str, values: Mapping[str, Any]) -> int:
        """Buat satu record baru dan kembalikan id-nya."""

    @abstractmethod
    def write(self, model: str, ids: Sequence[int], values: Mapping[str, Any]) -> bool:
        """Update record yang sudah ada; True kalau sukses."""

    @abstractmethod
    def call(
        self,
        model: str,
        method: str,
        args: Sequence | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        """Panggil method bebas pada model ERP (`execute_kw`)."""

    def close(self) -> None:
        """Tutup resource yang dipakai transport (opsional, default no-op)."""
        return None


__all__ = (
    "ERPAdapter",
    "ERPAdapterError",
    "ERPResponse",
    "ERPTransport",
    "STAGE_FG",
    "STAGE_WIP",
)
