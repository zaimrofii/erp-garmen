"""Service **WA Gateway Config** (H5.8) — profil gateway WhatsApp, **singleton**.

Pola **sama persis** dengan H5.6 (``master/integration_config_services.py``) —
keputusan STEP 0 **Opsi B ("tersimpan + viewer efektif")**:

  * baris DB menyimpan **profil gateway** yang bisa diisi/diedit dari UI (ledger
    ``SyncRecord`` ``master.wa_config``/``MASTER_PUSH`` ber-status **``SKIPPED``** +
    ``AuditLog``);
  * **konsumen TIDAK membaca baris ini** — ``integrations/wa_bot/services.py``
    (:func:`get_wa_gateway`, dibaca ``api.py`` WA + ``tasks_reconciliation.py`` +
    ``ai/hitl_views.py``) tetap membaca ``django.conf.settings.WA_*`` dari ``.env``
    ⇒ **nol risiko regresi**. Aktivasi = salin ke ``.env`` + restart
    ``django``/``celery_worker``/``celery_beat``;
  * ``GET`` melaporkan ``effective`` (nilai ``.env`` yang **benar-benar aktif**),
    ``diverges`` (field yang beda DB vs ``.env``) dan ``needs_restart``.

**Model terpisah** dari ``IntegrationConfig`` (H5.6) atas dasar SRP; nomor penerima
alert (``RECONCILIATION_ALERT_WA_TO``) tetap milik H5.6 — tidak diduplikasi.

Rahasia: ``wa_api_key`` disimpan **plaintext** + **selalu di-mask** ``***`` di response
(PUT ``***`` = tidak mengubah; PUT nilai baru = update; PUT ``""`` = hapus). ``diverges``
membandingkan nilai **mentah** tetapi **melaporkan** yang ter-mask ⇒ tidak ada rahasia
yang bocor.

``POST …/test-connection/`` → :func:`test_connection` (read-only; memakai
``integrations.wa_bot.services.get_wa_gateway().health_check()`` — **tidak** mengirim
pesan).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus
from integrations.wa_bot.services import get_wa_gateway

from .models import WAConfig
from .services import ACTION_CREATE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
    "BACKENDS",
    "CONFIG_FIELDS",
    "CONFIG_RESOURCE",
    "ENV_KEYS",
    "MASK",
    "MES_ONLY_REASON",
    "RESTART_COMMAND",
    "SENSITIVE_FIELDS",
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

#: Kunci sync WA config (jangan diganti string literal di view).
CONFIG_RESOURCE = SyncResource.MASTER_WA_CONFIG.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: profil gateway WA hanya disimpan di MES (Opsi B) — konsumen "
    "(`get_wa_gateway`) tetap membaca `.env`; aktivasi = salin ke `.env` + restart "
    "django/celery. DB TIDAK meng-override settings (3 konsumen + test gateway)."
)

#: Perintah aktivasi yang ditampilkan UI (bukan dijalankan server).
RESTART_COMMAND = "docker compose restart django celery_worker celery_beat"

#: Field rahasia — selalu di-mask di response (dan di ``diverges``).
SENSITIVE_FIELDS = ("wa_api_key",)
MASK = "***"

#: Backend WA yang boleh diketik (selaras ``WAConfig.Backend`` & env ``WA_BACKEND``).
BACKENDS = tuple(WAConfig.Backend.values)

#: Batas panjang teks (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_URL_LENGTH = 200
MAX_API_KEY_LENGTH = 255
MAX_BACKEND_LENGTH = 16

#: Field ``master.WAConfig`` → nama env (``.env``) yang setara.
ENV_KEYS: dict[str, str] = {
    "wa_backend": "WA_BACKEND",
    "wa_api_url": "WA_API_URL",
    "wa_api_key": "WA_API_KEY",
}

#: Urutan field untuk baris config (dipakai ``config_row`` & ``effective_row``).
CONFIG_FIELDS = tuple(ENV_KEYS)

#: Env yang wajib terisi bila backend bukan ``mock`` (guard kredensial).
CREDENTIAL_ENV_KEYS = ("WA_API_URL", "WA_API_KEY")


@dataclass
class ConfigWriteResult:
    """Hasil satu operasi tulis WA Config (dipakai view).

    **Tanpa** ``task_id``/``queued``: H5.8 Opsi B → tidak ada push ke vendor WA.
    """

    config: WAConfig | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def _is_http_url(value: str) -> bool:
    """True kalau URL **http/https dengan host** (mirror H5.6).

    **Tidak** memakai ``URLValidator`` Django karena validator itu menuntut TLD/
    ``localhost``, sedangkan MES memakai hostname internal Docker **tanpa TLD**
    (``http://wa-gateway:8080``). Pola sama dengan ``integration_config_services``.
    """
    try:
        parts = urlsplit(value)
    except ValueError:
        return False

    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Baris response: profil (DB) + effective (.env) + divergences
# ---------------------------------------------------------------------------
def _normalize(field: str, raw, *, mask: bool = True):
    """Normalisasi nilai field → JSON-safe; field rahasia di-mask kecuali ``mask=False``."""
    if field in SENSITIVE_FIELDS:
        text = str(raw or "").strip()

        return MASK if (mask and text) else text

    return str(raw or "").strip()


def _db_value(config: WAConfig, field: str, *, mask: bool = True):
    """Nilai field dari baris DB — dinormalisasi (rahasia di-mask bila ``mask=True``)."""
    return _normalize(field, getattr(config, field, None), mask=mask)


def _env_value(field: str, *, mask: bool = True):
    """Nilai field dari ``.env`` (settings) — dinormalisasi (rahasia di-mask)."""
    return _normalize(field, getattr(settings, ENV_KEYS[field], None), mask=mask)


def effective_row() -> dict:
    """Gateway yang **benar-benar aktif** sekarang (dibaca dari ``.env``/settings).

    Read-only — dipakai UI untuk membandingkan profil tersimpan vs yang berjalan.
    """
    return {field: _env_value(field) for field in CONFIG_FIELDS}


def config_row(config: WAConfig) -> dict:
    """Baris profil gateway untuk API — ``wa_api_key`` **selalu** di-mask (``***``)."""
    return {
        "id": config.pk,
        **{field: _db_value(config, field) for field in CONFIG_FIELDS},
        "is_active": bool(config.is_active),
        "created_at": _iso(config.created_at),
        "updated_at": _iso(config.updated_at),
    }


def divergences(config: WAConfig | None) -> dict:
    """``{field: {db, env}}`` untuk field yang **beda** DB vs ``.env``.

    Perbandingan memakai nilai **mentah** (supaya beda API key tetap terdeteksi),
    tetapi nilai yang **dilaporkan** sudah di-mask untuk field rahasia (``***``) —
    tidak ada rahasia yang bocor ke response.
    """
    if config is None:
        return {}

    found: dict = {}
    for field in CONFIG_FIELDS:
        if _db_value(config, field, mask=False) != _env_value(field, mask=False):
            found[field] = {"db": _db_value(config, field), "env": _env_value(field)}

    return found


def needs_restart(config: WAConfig | None) -> bool:
    """True kalau ada perbedaan DB vs ``.env`` (aktivasi = salin ke ``.env`` + restart)."""
    return bool(divergences(config))


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H5.1/H5.2/H5.6
# ---------------------------------------------------------------------------
def _config_payload(config: WAConfig) -> dict:
    """Payload ledger — memakai baris profil (rahasia sudah di-mask)."""
    row = config_row(config)
    row.pop("id", None)
    row.pop("created_at", None)
    row.pop("updated_at", None)

    return row


def _record_mes_only(config: WAConfig) -> int:
    """Tulis/segarkan ``SyncRecord`` WA config lalu tandai ``SKIPPED``."""
    payload = _config_payload(config)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(CONFIG_RESOURCE, config.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(action: str, config: WAConfig, request, metadata: dict | None = None) -> None:
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
            "master.wa_config: gagal menulis audit (%s, config %s).", action, config.pk
        )


def _record_and_audit(
    config: WAConfig,
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


def validate_config_payload(data, instance: WAConfig | None = None):
    """Validasi body PUT WA Config → ``(values, error)``.

    **Create-on-first-PUT**: saat ``instance is None`` nilai default model dipakai
    (``wa_backend='mock'``). Field yang **tidak** dikirim tidak diubah.
    ``wa_api_key="***"`` (mask) **diabaikan** ⇒ nilai lama dipertahankan; ``""`` menghapus.

    **Guard backend**: ``wa_backend`` ``real``/``api`` ⇒ ``wa_api_url`` + ``wa_api_key``
    wajib terisi (nilai efektif: payload menang, kalau tidak pakai baris lama).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "wa_backend" in payload:
        backend = str(payload.get("wa_backend") or "").strip().lower()
        if not backend:
            backend = (
                instance.wa_backend if instance is not None else WAConfig.Backend.MOCK
            )
        if backend not in BACKENDS:
            return None, (
                "Field 'wa_backend' harus salah satu dari " + ", ".join(BACKENDS) + "."
            )
        values["wa_backend"] = backend

    if "wa_api_url" in payload:
        url, error = _text(payload.get("wa_api_url"), "wa_api_url", MAX_URL_LENGTH)
        if error:
            return None, error
        if url:
            try:
                valid_url = _is_http_url(url)
            except (TypeError, ValueError):
                valid_url = False
            if not valid_url:
                return None, f"Field 'wa_api_url' bukan URL valid: {url!r}."
        values["wa_api_url"] = url

    if "wa_api_key" in payload:
        text, error = _text(payload.get("wa_api_key"), "wa_api_key", MAX_API_KEY_LENGTH)
        if error:
            return None, error
        if text != MASK:
            # "***" = nilai lama dibiarkan; nilai baru/kosong = ganti/hapus.
            values["wa_api_key"] = text

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    backend = values.get(
        "wa_backend", getattr(instance, "wa_backend", WAConfig.Backend.MOCK)
    )
    if backend in (WAConfig.Backend.REAL, WAConfig.Backend.API):
        url = values.get("wa_api_url", getattr(instance, "wa_api_url", ""))
        key = values.get("wa_api_key", getattr(instance, "wa_api_key", ""))
        if not (url and key):
            return None, (
                "Backend 'real'/'api' membutuhkan 'wa_api_url' dan 'wa_api_key' — "
                "atau pilih 'mock' untuk gateway tanpa jaringan."
            )

    return values, None


# ---------------------------------------------------------------------------
# Singleton + tulis + test koneksi
# ---------------------------------------------------------------------------
def get_config() -> WAConfig | None:
    """Baris config (baris pertama, ``ordering=("pk",)``) atau ``None``.

    **Tanpa efek samping** — GET memakai ini supaya tidak membuat baris.
    """
    return WAConfig.objects.order_by("pk").first()


def get_or_create_config() -> tuple[WAConfig, bool]:
    """``(config, created)`` — baris **pasti ada** (dibuat dengan default model bila kosong).

    Dipakai konsumen internal yang butuh profil gateway tanpa payload; view GET
    **tidak** memakainya (GET tidak boleh membuat baris).
    """
    config = get_config()
    if config is not None:
        return config, False

    return WAConfig.objects.create(), True


def update_config(data, request=None) -> ConfigWriteResult:
    """PUT profil gateway — **create-on-first-PUT** + ledger ``SKIPPED`` + audit.

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
        config = WAConfig.objects.create(**values)
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
        "master.wa_config: profil %s %s (ledger=%s, MES-only).",
        config.pk,
        "dibuat" if created else "diubah",
        record_id,
    )
    return ConfigWriteResult(config=config, sync_record_id=record_id)


def test_connection() -> dict:
    """Uji gateway WA (read-only, **tanpa** mengirim pesan) → ``{ok, …}``.

    Urutan cek (semua **tanpa** efek samping):

      1. backend ``real``/``api`` tapi kredensial ``.env`` kurang (``WA_API_URL``/
         ``WA_API_KEY``) → ``ok=false`` + daftar env yang hilang;
      2. gateway dari factory existing ``get_wa_gateway()`` (bersumber
         ``settings.WA_BACKEND``) lalu ``health_check()`` — mock **selalu** siap dan
         tidak menyentuh jaringan.

    Memakai nilai **dari ``.env``** (bukan baris DB) — konsisten Opsi B. Tidak pernah
    melempar exception: kegagalan apa pun dilaporkan sebagai ``ok=false`` + pesan.
    """
    backend = str(getattr(settings, "WA_BACKEND", "") or "").strip().lower() or "mock"
    url = str(getattr(settings, "WA_API_URL", "") or "")

    if backend in ("real", "api"):
        missing = [key for key in CREDENTIAL_ENV_KEYS if not getattr(settings, key, None)]
        if missing:
            return {
                "ok": False,
                "backend": backend,
                "url": url or None,
                "mock": False,
                "message": "Kredensial WA belum lengkap: "
                + ", ".join(missing)
                + " (cek .env).",
            }

    try:
        gateway = get_wa_gateway()
    except Exception as exc:  # noqa: BLE001 - factory tidak boleh menjatuhkan endpoint
        logger.exception("master.wa_config: gagal membuat gateway WA.")
        return {
            "ok": False,
            "backend": backend,
            "url": url or None,
            "mock": False,
            "message": f"Gateway WA gagal dibuat: {type(exc).__name__}.",
        }

    name = str(getattr(gateway, "name", "") or backend)
    checker = getattr(gateway, "health_check", None)
    if not callable(checker):
        return {
            "ok": False,
            "backend": name,
            "url": url or None,
            "mock": name == "mock",
            "message": "Gateway WA aktif tidak menyediakan health_check().",
        }

    try:
        healthy = bool(checker())
    except Exception as exc:  # noqa: BLE001 - kegagalan ping = ok=false, bukan 500
        logger.warning("master.wa_config: gateway WA %s tidak menjawab: %s", name, exc)
        return {
            "ok": False,
            "backend": name,
            "url": url or None,
            "mock": name == "mock",
            "message": f"Gateway WA tidak menjawab: {type(exc).__name__}.",
        }

    is_mock = name == "mock" or backend == "mock"
    if is_mock:
        message = (
            "Mock gateway aktif (tanpa jaringan) — alur notifikasi WA siap dipakai."
            if healthy
            else "Mock gateway melaporkan tidak siap."
        )
    else:
        message = (
            "Gateway WA menjawab (health check OK)."
            if healthy
            else "Gateway WA tidak siap (cek URL/API key penyedia)."
        )

    return {
        "ok": healthy,
        "backend": name,
        "url": url or None,
        "mock": is_mock,
        "message": message,
    }



