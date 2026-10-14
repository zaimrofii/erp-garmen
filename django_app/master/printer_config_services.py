"""Service **Printer Config** (H5.7) — profil printer thermal ESC/POS, **singleton**.

Pola **sama persis** dengan H5.6 (``integration_config_services``) & H5.8
(``wa_config_services``) — keputusan STEP 0 **Opsi B ("tersimpan + viewer efektif")**:

  * baris DB menyimpan **profil printer** yang bisa diisi/diedit dari UI (ledger
    ``SyncRecord`` ``master.printer_config``/``MASTER_PUSH`` ber-status **``SKIPPED``**
    + ``AuditLog``);
  * **konsumen TIDAK membaca baris ini** — ``integrations/printing``
    (``backends/__init__.get_backend()`` yang dipakai ``printing/api.py``:
    ``PrintBundleTagView``/``PrintCouponView``) tetap membaca
    ``django.conf.settings.PRINTER_*`` dari ``.env`` ⇒ **nol risiko regresi**;
    aktivasi = salin ke ``.env`` + restart ``django``/``celery_worker``/``celery_beat``;
  * ``GET`` melaporkan ``effective`` (nilai ``.env`` yang **benar-benar aktif**),
    ``diverges`` (field yang beda DB vs ``.env``) dan ``needs_restart``.

**Tanpa mask**: host/port/USB id/folder printer **bukan** kredensial (beda dari
``odoo_api_key`` H5.6 & ``wa_api_key`` H5.8).

``POST …/test-connection/`` → :func:`test_connection` — **TIDAK PERNAH mencetak**:

  * ``mock`` → ``os.makedirs(mock_dir, exist_ok=True)`` (folder siap/tidak);
  * ``usb`` → ``ok=false`` + pesan stub (backend USB belum diimplementasi:
    butuh ``python-escpos`` + ``libusb``) + vendor/product terbaca;
  * ``network`` → **TCP connect** ``host:port`` (timeout 5 s) **tanpa** mengirim
    bytes ESC/POS (mengirim bytes = mencetak kertas nyata).
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass

from django.conf import settings

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .models import PrinterConfig
from .services import ACTION_CREATE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "BACKENDS",
    "CONFIG_FIELDS",
    "CONFIG_RESOURCE",
    "ENV_KEYS",
    "MES_ONLY_REASON",
    "RESTART_COMMAND",
    "USB_STUB_MESSAGE",
    "ConfigWriteResult",
    "config_row",
    "divergences",
    "effective_row",
    "get_config",
    "get_or_create_config",
    "needs_restart",
    "test_connection",
    "update_config",
    "validate_config_payload",
)

#: Kunci sync Printer Config (jangan diganti string literal di view).
CONFIG_RESOURCE = SyncResource.MASTER_PRINTER_CONFIG.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: profil printer hanya disimpan di MES (Opsi B) — konsumen "
    "(`integrations/printing.backends.get_backend`) tetap membaca `.env`; aktivasi = "
    "salin ke `.env` + restart django/celery. DB TIDAK meng-override settings."
)

#: Perintah aktivasi yang ditampilkan UI (bukan dijalankan server).
RESTART_COMMAND = "docker compose restart django celery_worker celery_beat"

#: Backend printer yang boleh diketik (selaras ``PrinterConfig.Backend`` & env).
BACKENDS = tuple(PrinterConfig.Backend.values)

#: Pesan stub backend USB (dipakai juga oleh ``backends/usb.py``).
USB_STUB_MESSAGE = "USB backend stub — butuh python-escpos + libusb (belum diimplementasi)."

#: Batas panjang teks (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_VENDOR_LENGTH = 32
MAX_PRODUCT_LENGTH = 32
MAX_HOST_LENGTH = 200
MAX_DIR_LENGTH = 200
MAX_BACKEND_LENGTH = 16

#: Rentang port TCP yang sah.
PORT_MIN = 1
PORT_MAX = 65535

#: Timeout probe TCP ``test-connection`` (detik) — cek konektivitas saja.
TCP_TIMEOUT_SECONDS = 5.0

#: Folder default hasil "cetak" mock (sama dengan ``backends/mock.DEFAULT_DIRECTORY``).
DEFAULT_MOCK_DIR = "/tmp/print_mock"

#: Field ``master.PrinterConfig`` → nama env (``.env``) yang setara.
ENV_KEYS: dict[str, str] = {
    "printer_backend": "PRINTER_BACKEND",
    "printer_usb_vendor_id": "PRINTER_USB_VENDOR_ID",
    "printer_usb_product_id": "PRINTER_USB_PRODUCT_ID",
    "printer_network_host": "PRINTER_NETWORK_HOST",
    "printer_network_port": "PRINTER_NETWORK_PORT",
    "printer_mock_dir": "PRINTER_MOCK_DIR",
}

#: Field angka (int/null) — dipakai normalisasi nilai env & DB.
INT_FIELDS = ("printer_network_port",)

#: Urutan field untuk baris config (dipakai ``config_row`` & ``effective_row``).
CONFIG_FIELDS = tuple(ENV_KEYS)


@dataclass
class ConfigWriteResult:
    """Hasil satu operasi tulis Printer Config (dipakai view).

    **Tanpa** ``task_id``/``queued``: H5.7 Opsi B → tidak ada push ke printer/Odoo.
    """

    config: PrinterConfig | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Baris response: profil (DB) + effective (.env) + divergences
# ---------------------------------------------------------------------------
def _normalize(field: str, raw):
    """Normalisasi nilai field → JSON-safe (angka → int/None, teks → ``str`` ter-trim).

    Tanpa mask: tidak ada field rahasia di Printer Config (H5.7).
    """
    if field in INT_FIELDS:
        if raw in (None, ""):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return str(raw or "").strip()


def _db_value(config: PrinterConfig, field: str):
    """Nilai field dari baris DB — dinormalisasi."""
    return _normalize(field, getattr(config, field, None))


def _env_value(field: str):
    """Nilai field dari ``.env`` (settings) — dinormalisasi."""
    return _normalize(field, getattr(settings, ENV_KEYS[field], None))


def effective_row() -> dict:
    """Printer yang **benar-benar aktif** sekarang (dibaca dari ``.env``/settings).

    Read-only — dipakai UI untuk membandingkan profil tersimpan vs yang berjalan.
    """
    return {field: _env_value(field) for field in CONFIG_FIELDS}


def config_row(config: PrinterConfig) -> dict:
    """Baris profil printer untuk API (tanpa mask — tidak ada field rahasia)."""
    return {
        "id": config.pk,
        **{field: _db_value(config, field) for field in CONFIG_FIELDS},
        "is_active": bool(config.is_active),
        "created_at": _iso(config.created_at),
        "updated_at": _iso(config.updated_at),
    }


def divergences(config: PrinterConfig | None) -> dict:
    """``{field: {db, env}}`` untuk field yang **beda** DB vs ``.env``.

    Nilai dilaporkan apa adanya (tanpa mask — bukan rahasia).
    """
    if config is None:
        return {}

    found: dict = {}
    for field in CONFIG_FIELDS:
        if _db_value(config, field) != _env_value(field):
            found[field] = {"db": _db_value(config, field), "env": _env_value(field)}

    return found


def needs_restart(config: PrinterConfig | None) -> bool:
    """True kalau ada perbedaan DB vs ``.env`` (aktivasi = salin ke ``.env`` + restart)."""
    return bool(divergences(config))


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H5.1/H5.2/H5.6/H5.8
# ---------------------------------------------------------------------------
def _config_payload(config: PrinterConfig) -> dict:
    """Payload ledger — memakai baris profil (tanpa mask; bukan data rahasia)."""
    row = config_row(config)
    row.pop("id", None)
    row.pop("created_at", None)
    row.pop("updated_at", None)

    return row


def _record_mes_only(config: PrinterConfig) -> int:
    """Tulis/segarkan ``SyncRecord`` printer config lalu tandai ``SKIPPED``."""
    payload = _config_payload(config)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(CONFIG_RESOURCE, config.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(action: str, config: PrinterConfig, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=CONFIG_RESOURCE,
            resource_id=config.pk,
            request=request,
            payload=_config_payload(config),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD
        logger.exception(
            "master.printer_config: gagal menulis audit (%s, config %s).",
            action,
            config.pk,
        )


def _record_and_audit(
    config: PrinterConfig,
    request,
    *,
    metadata: dict | None = None,
    action: str = ACTION_UPDATE,
) -> int:
    """Tulis ledger ``SKIPPED`` + audit lalu kembalikan id ``SyncRecord``."""
    record_id = _record_mes_only(config)
    _audit(action, config, request, metadata)

    return record_id


# ---------------------------------------------------------------------------
# Validasi (PUT — create-on-first-PUT)
# ---------------------------------------------------------------------------
def _text(value, label: str, max_length: int):
    """``(str, error)`` untuk teks opsional dengan batas panjang (di-trim)."""
    text = "" if value is None else str(value).strip()
    if len(text) > max_length:
        return "", f"Field '{label}' maksimal {max_length} karakter."

    return text, None


def _parse_port(value):
    """``(int|None, error)`` untuk port TCP ``1..65535`` (kosong → ``None``)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, f"Field 'printer_network_port' harus angka port ({PORT_MIN}..{PORT_MAX})."

    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None, f"Field 'printer_network_port' harus angka port ({PORT_MIN}..{PORT_MAX})."

    if number < PORT_MIN or number > PORT_MAX:
        return None, (
            f"Field 'printer_network_port' harus antara {PORT_MIN} dan {PORT_MAX}."
        )

    return number, None


def validate_config_payload(data, instance: PrinterConfig | None = None):
    """Validasi body PUT Printer Config → ``(values, error)``.

    **Create-on-first-PUT**: saat ``instance is None`` nilai default model dipakai
    (``printer_backend='mock'``). Field yang **tidak** dikirim tidak diubah.

    **Guard kondisional** (nilai efektif: payload menang, kalau tidak pakai baris lama):

      * ``printer_backend='usb'`` ⇒ ``printer_usb_vendor_id`` + ``printer_usb_product_id``
        wajib terisi;
      * ``printer_backend='network'`` ⇒ ``printer_network_host`` + ``printer_network_port``
        (1..65535) wajib terisi;
      * ``printer_backend='mock'`` ⇒ ``printer_mock_dir`` opsional (kosong = default server).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "printer_backend" in payload:
        backend = str(payload.get("printer_backend") or "").strip().lower()
        if not backend:
            backend = (
                instance.printer_backend
                if instance is not None
                else PrinterConfig.Backend.MOCK
            )
        if backend not in BACKENDS:
            return None, (
                "Field 'printer_backend' harus salah satu dari "
                + ", ".join(BACKENDS)
                + "."
            )
        values["printer_backend"] = backend

    for field, max_length in (
        ("printer_usb_vendor_id", MAX_VENDOR_LENGTH),
        ("printer_usb_product_id", MAX_PRODUCT_LENGTH),
        ("printer_network_host", MAX_HOST_LENGTH),
        ("printer_mock_dir", MAX_DIR_LENGTH),
    ):
        if field in payload:
            text, error = _text(payload.get(field), field, max_length)
            if error:
                return None, error
            values[field] = text

    if "printer_network_port" in payload:
        port, error = _parse_port(payload.get("printer_network_port"))
        if error:
            return None, error
        values["printer_network_port"] = port

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    backend = values.get(
        "printer_backend", getattr(instance, "printer_backend", PrinterConfig.Backend.MOCK)
    )
    if backend == PrinterConfig.Backend.USB:
        vendor = values.get(
            "printer_usb_vendor_id", getattr(instance, "printer_usb_vendor_id", "")
        )
        product = values.get(
            "printer_usb_product_id", getattr(instance, "printer_usb_product_id", "")
        )
        if not (vendor and product):
            return None, (
                "Backend 'usb' membutuhkan 'printer_usb_vendor_id' dan "
                "'printer_usb_product_id' — atau pilih 'mock'/'network'."
            )
    elif backend == PrinterConfig.Backend.NETWORK:
        host = values.get(
            "printer_network_host", getattr(instance, "printer_network_host", "")
        )
        port = values.get(
            "printer_network_port", getattr(instance, "printer_network_port", None)
        )
        if not (host and port):
            return None, (
                "Backend 'network' membutuhkan 'printer_network_host' dan "
                "'printer_network_port' — atau pilih 'mock'."
            )

    return values, None


# ---------------------------------------------------------------------------
# Singleton + tulis + test koneksi
# ---------------------------------------------------------------------------
def get_config() -> PrinterConfig | None:
    """Baris config (baris pertama, ``ordering=("pk",)``) atau ``None``.

    **Tanpa efek samping** — GET memakai ini supaya tidak membuat baris.
    """
    return PrinterConfig.objects.order_by("pk").first()


def get_or_create_config() -> tuple[PrinterConfig, bool]:
    """``(config, created)`` — baris **pasti ada** (dibuat default model bila kosong).

    Dipakai konsumen internal yang butuh profil printer tanpa payload; view GET
    **tidak** memakainya (GET tidak boleh membuat baris).
    """
    config = get_config()
    if config is not None:
        return config, False

    return PrinterConfig.objects.create(), True


def update_config(data, request=None) -> ConfigWriteResult:
    """PUT profil printer — **create-on-first-PUT** + ledger ``SKIPPED`` + audit.

    Baris pertama di-update; kalau belum ada baris sama sekali, baris **dibuat**
    (default model + payload) ⇒ 2× PUT tetap **1 baris** (singleton). PUT tanpa
    perubahan apa pun → 200 tanpa ledger/audit baru.
    """
    config = get_config()
    values, error = validate_config_payload(data, instance=config)
    if error:
        return ConfigWriteResult(config=config, error=error)

    created = config is None
    if created:
        config = PrinterConfig.objects.create(**values)
    elif values:
        for field, value in values.items():
            setattr(config, field, value)
        config.save()
    else:
        # Tidak ada perubahan -> tidak ada audit/ledger.
        return ConfigWriteResult(config=config)

    record_id = _record_and_audit(
        config,
        request,
        metadata={"fields": sorted(values), "create": created},
        action=ACTION_CREATE if created else ACTION_UPDATE,
    )

    logger.info(
        "master.printer_config: profil %s %s (ledger=%s, MES-only).",
        config.pk,
        "dibuat" if created else "diubah",
        record_id,
    )
    return ConfigWriteResult(config=config, sync_record_id=record_id)


def _hex_or_text(value) -> str:
    """Tampilkan USB id sebagai hex (``0x04B8``) bila angka; selain itu apa adanya."""
    text = str(value or "").strip()
    if text == "":
        return "-"

    try:
        number = int(text, 0)
    except (TypeError, ValueError):
        return text

    return f"0x{number:04X}"


def _test_mock(directory: str) -> dict:
    """Cek backend mock: folder hasil cetak bisa dibuat/dipakai (tanpa mencetak)."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        return {
            "ok": False,
            "backend": PrinterConfig.Backend.MOCK,
            "message": f"Mock dir tidak bisa dibuat: {exc}",
        }

    return {
        "ok": True,
        "backend": PrinterConfig.Backend.MOCK,
        "message": f"Mock dir siap: {directory}",
    }


def _test_usb(vendor, product) -> dict:
    """Backend USB = **stub**: laporkan jelas (``ok=false``), bukan exception."""
    return {
        "ok": False,
        "backend": PrinterConfig.Backend.USB,
        "message": (
            f"{USB_STUB_MESSAGE} Vendor: {_hex_or_text(vendor)}, "
            f"Product: {_hex_or_text(product)}"
        ),
    }


def _test_network(host, port) -> dict:
    """Uji jaringan: **TCP connect** ``host:port`` tanpa mengirim bytes ESC/POS."""
    if not host or not port:
        return {
            "ok": False,
            "backend": PrinterConfig.Backend.NETWORK,
            "message": "PRINTER_NETWORK_HOST/PORT belum dikonfigurasi.",
        }

    target = f"{host}:{int(port)}"
    try:
        with socket.create_connection((str(host), int(port)), timeout=TCP_TIMEOUT_SECONDS):
            pass
    except (OSError, ValueError) as exc:
        return {
            "ok": False,
            "backend": PrinterConfig.Backend.NETWORK,
            "message": f"TCP connect gagal: {exc}",
        }

    return {
        "ok": True,
        "backend": PrinterConfig.Backend.NETWORK,
        "message": f"TCP connect ke {target} sukses (tanpa mengirim bytes ESC/POS).",
    }


def test_connection() -> dict:
    """Uji printer (read-only, **TIDAK PERNAH mencetak**) → ``{ok, backend, message}``.

    Memakai nilai **dari ``.env``** (bukan baris DB) — konsisten Opsi B:

      * ``mock`` → folder ``PRINTER_MOCK_DIR`` bisa dibuat/dipakai;
      * ``usb`` → ``ok=false`` + pesan stub (butuh python-escpos + libusb) + USB id;
      * ``network`` → TCP connect ``host:port`` (timeout 5 s), **tanpa** bytes;
      * nilai tak dikenal → dicek sebagai ``mock`` (perilaku fail-safe factory) dan
        pesannya menyebut fallback itu.

    Tidak pernah melempar exception: kegagalan apa pun dilaporkan ``ok=false``.
    """
    requested = (
        str(getattr(settings, "PRINTER_BACKEND", "") or "").strip().lower()
        or PrinterConfig.Backend.MOCK
    )

    if requested == PrinterConfig.Backend.MOCK:
        return _test_mock(
            str(getattr(settings, "PRINTER_MOCK_DIR", "") or DEFAULT_MOCK_DIR)
        )

    if requested == PrinterConfig.Backend.USB:
        return _test_usb(
            getattr(settings, "PRINTER_USB_VENDOR_ID", None),
            getattr(settings, "PRINTER_USB_PRODUCT_ID", None),
        )

    if requested == PrinterConfig.Backend.NETWORK:
        return _test_network(
            getattr(settings, "PRINTER_NETWORK_HOST", None),
            getattr(settings, "PRINTER_NETWORK_PORT", None),
        )

    # Backend tak dikenal: factory `get_backend()` fallback ke mock (fail-safe).
    result = _test_mock(
        str(getattr(settings, "PRINTER_MOCK_DIR", "") or DEFAULT_MOCK_DIR)
    )

    return {
        **result,
        "backend": requested,
        "message": (
            f"PRINTER_BACKEND {requested!r} tidak dikenal — fallback mock (fail-safe). "
            + str(result["message"])
        ),
    }




