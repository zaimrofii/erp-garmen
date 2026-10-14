"""Client ERP: factory transport lama + klien JSON-RPC Odoo (`OdooClient`).

Dua lapis di modul ini:

* :func:`get_odoo_client` — factory **transport** (`OdooJSONRPCAdapter` /
  `NullAdapter`) yang dipakai task diagnosa ``erp_sync.ping``. Perilaku lama
  dipertahankan apa adanya.
* :class:`OdooClient` + :func:`get_odoo_rpc_client` — klien JSON-RPC tingkat
  rendah dengan API ``authenticate()`` / ``execute_kw()`` / ``ping()`` yang
  dipakai :class:`~integrations.erp_sync.adapters.odoo.OdooAdapter` (Sprint 4.2)
  dan endpoint cek koneksi.

Semua kredensial dibaca dari settings (``ODOO_URL``/``ODOO_DB``/``ODOO_USER``/
``ODOO_API_KEY``/``ODOO_TIMEOUT``) — **tidak ada kredensial hardcode**.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .adapters.base import ERPTransport
from .adapters.null import NullAdapter
from .adapters.odoo import OdooJSONRPCAdapter

logger = logging.getLogger(__name__)

ODOO_CREDENTIAL_KEYS = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY")


def _missing_odoo_settings() -> list[str]:
    """Nama setting Odoo yang masih kosong (urutan tetap sesuai konstanta)."""
    return [key for key in ODOO_CREDENTIAL_KEYS if not getattr(settings, key, "")]


def get_odoo_client(adapter: str | None = None) -> ERPTransport:
    """Buat instance transport ERP sesuai `settings.ERP_ADAPTER`.

    * ``adapter="odoo"`` (default) → :class:`OdooJSONRPCAdapter`
    * ``adapter="null"``           → :class:`NullAdapter` (testing tanpa Odoo)

    Instance dikembalikan baru setiap panggilan (tidak di-cache) supaya aman
    dipakai di proses worker Celery; panggil ``client.close()`` setelah selesai
    atau pakai adapter sebagai context manager.
    """
    name = (adapter or getattr(settings, "ERP_ADAPTER", "odoo") or "odoo").lower()

    if name == "null":
        logger.info("Memakai NullAdapter (ERP_ADAPTER=null).")
        return NullAdapter()

    if name != "odoo":
        raise ImproperlyConfigured(
            f"ERP_ADAPTER tidak dikenal: {name!r}. Pilihan yang valid: 'odoo', 'null'."
        )

    missing = _missing_odoo_settings()
    if missing:
        raise ImproperlyConfigured(
            "Konfigurasi Odoo belum lengkap, environment variable berikut kosong: "
            + ", ".join(missing)
        )

    logger.info("Memakai OdooJSONRPCAdapter (url=%s, db=%s).", settings.ODOO_URL, settings.ODOO_DB)
    return OdooJSONRPCAdapter(
        url=settings.ODOO_URL,
        db=settings.ODOO_DB,
        user=settings.ODOO_USER,
        api_key=settings.ODOO_API_KEY,
        timeout=getattr(settings, "ODOO_TIMEOUT", 30.0),
    )


class OdooClient:
    """Klien JSON-RPC Odoo 17 (`authenticate` / `execute_kw` / `ping`).

    Semua parameter keyword opsional; kalau tidak diisi nilainya dibaca dari
    settings. ``transport`` / ``http_client`` bisa di-inject untuk test (mis.
    ``httpx.Client(transport=httpx.MockTransport(...))``) sehingga test tidak
    pernah memanggil Odoo sungguhan.

    ``api_key`` sengaja **tidak** ditampilkan di ``__repr__``.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        db: str | None = None,
        user: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        transport: ERPTransport | None = None,
        http_client: Any | None = None,
    ) -> None:
        self.url = (
            url if url is not None else getattr(settings, "ODOO_URL", "") or ""
        ).rstrip("/")
        self.db = db if db is not None else getattr(settings, "ODOO_DB", "")
        self.user = user if user is not None else getattr(settings, "ODOO_USER", "")
        self.api_key = api_key if api_key is not None else getattr(settings, "ODOO_API_KEY", "")
        if timeout is None:
            timeout = getattr(settings, "ODOO_TIMEOUT", 30.0)
        self.timeout = float(timeout)
        self._transport = transport or OdooJSONRPCAdapter(
            url=self.url,
            db=self.db,
            user=self.user,
            api_key=self.api_key,
            timeout=self.timeout,
            client=http_client,
        )

    @property
    def transport(self) -> ERPTransport:
        """Transport JSON-RPC di balik klien (bisa di-swap untuk test)."""
        return self._transport

    @property
    def uid(self) -> int | None:
        """uid hasil autentikasi (None kalau belum login)."""
        return getattr(self._transport, "uid", None)

    def authenticate(self) -> int:
        """Login ke Odoo (`common.login`) dan kembalikan uid."""
        uid = self._transport.login()
        logger.info(
            "OdooClient.authenticate() sukses: db=%s user=%s uid=%s", self.db, self.user, uid
        )
        return uid

    def execute_kw(
        self,
        model: str,
        method: str,
        args: Sequence | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        """Panggil ``object.execute_kw`` (login otomatis kalau uid belum ada)."""
        return self._transport.call(model, method, args, kwargs)

    def ping(self) -> bool:
        """Health check murah (`common.version`, tanpa autentikasi)."""
        try:
            transport = self._transport
            if hasattr(transport, "ping"):
                return bool(transport.ping())
            if hasattr(transport, "version"):
                return bool(transport.version())
        except Exception as exc:  # noqa: BLE001 - semua kegagalan = tidak sehat
            logger.warning("OdooClient.ping() gagal ke %s: %s", self.url, exc)
            return False
        logger.warning("OdooClient.ping(): transport %r tidak punya ping/version.", transport)
        return False

    def close(self) -> None:
        """Tutup koneksi HTTP di transport."""
        self._transport.close()

    def __enter__(self) -> "OdooClient":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<OdooClient url={self.url} db={self.db} user={self.user} uid={self.uid}>"


def get_odoo_rpc_client(**overrides: Any) -> OdooClient:
    """Klien JSON-RPC dari settings.

    Raise :class:`~django.core.exceptions.ImproperlyConfigured` kalau salah satu
    kredensial belum diisi supaya tidak diam-diam gagal di tengah produksi.
    """
    missing = _missing_odoo_settings()
    if missing:
        raise ImproperlyConfigured(
            "Konfigurasi Odoo belum lengkap, environment variable berikut kosong: "
            + ", ".join(missing)
        )
    return OdooClient(**overrides)


__all__ = ("ODOO_CREDENTIAL_KEYS", "OdooClient", "get_odoo_client", "get_odoo_rpc_client")

