"""Service **Integration Config** (H5.6) — profil config MES ↔ Odoo, **singleton**.

Keputusan STEP 0 — **Opsi B ("tersimpan + viewer efektif")**:

  * baris DB menyimpan **profil config** yang bisa diisi/diedit dari UI (ledger
    ``SyncRecord`` ``master.integration_config``/``MASTER_PUSH`` ber-status **``SKIPPED``**
    + ``AuditLog``);
  * **konsumen TIDAK membaca baris ini** — kedelapan konsumen tetap membaca
    ``django.conf.settings.*`` (dari ``.env``), jadi **nol risiko regresi**
    (8 konsumen + 113 referensi setting di test). Opsi C (DB meng-override ``.env``)
    **ditolak**: risiko >> manfaat;
  * ``GET`` melaporkan tiga hal tambahan supaya UI jujur: ``effective`` (nilai ``.env``
    yang **benar-benar aktif** sekarang), ``diverges`` (field yang beda DB vs ``.env``)
    dan ``needs_restart`` (``bool(diverges)``). Aktivasi = salin ke ``.env`` + restart
    ``django``/``celery_worker``/``celery_beat``.

Rahasia: ``odoo_api_key`` disimpan **plaintext** + **selalu di-mask** ``***`` di
response (PUT ``***`` = tidak mengubah; PUT nilai baru = update; PUT ``""`` = hapus).
Enkripsi (Fernet) = V2 (butuh dependency ``cryptography`` + key env tersendiri).

``POST …/test-connection/`` → :func:`test_connection` (read-only; memakai
``adapters.factory.get_adapter().health_check()`` yang tidak butuh login).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.conf import settings

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.adapters.factory import get_adapter
from integrations.erp_sync.client import ODOO_CREDENTIAL_KEYS
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .models import IntegrationConfig
from .services import ACTION_CREATE, ACTION_UPDATE, parse_bool

logger = logging.getLogger(__name__)

__all__ = (
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

#: Kunci sync Integration Config (jangan diganti string literal di view).
CONFIG_RESOURCE = SyncResource.MASTER_INTEGRATION_CONFIG.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: profil config hanya disimpan di MES (Opsi B) — konsumen tetap membaca "
    "`.env`; aktivasi = salin ke `.env` + restart django/celery. DB TIDAK meng-override "
    "settings (8 konsumen + 113 referensi test)."
)

#: Perintah aktivasi yang ditampilkan UI (bukan dijalankan server).
RESTART_COMMAND = (
    "docker compose restart django celery_worker celery_beat"
)

#: Field rahasia — selalu di-mask di response (dan di ``diverges``).
SENSITIVE_FIELDS = ("odoo_api_key",)
MASK = "***"

#: Batas panjang teks (selaras kolom model → beda dari DB = 400, bukan 500).
MAX_URL_LENGTH = 200
MAX_DB_LENGTH = 64
MAX_USER_LENGTH = 64
MAX_API_KEY_LENGTH = 255
MAX_ADAPTER_LENGTH = 16

#: Batas numerik (biar tidak ada nilai tak masuk akal).
MIN_TIMEOUT = Decimal("1")
MAX_TIMEOUT = Decimal("600")
MAX_TOLERANCE_PCT = Decimal("1")

#: Field ``master.IntegrationConfig`` → nama env (``.env``) yang setara.
ENV_KEYS: dict[str, str] = {
    "erp_adapter": "ERP_ADAPTER",
    "odoo_url": "ODOO_URL",
    "odoo_db": "ODOO_DB",
    "odoo_user": "ODOO_USER",
    "odoo_api_key": "ODOO_API_KEY",
    "odoo_timeout": "ODOO_TIMEOUT",
    "odoo_location_wip_id": "ODOO_LOCATION_WIP_ID",
    "odoo_location_production_id": "ODOO_LOCATION_PRODUCTION_ID",
    "odoo_location_fg_id": "ODOO_LOCATION_FG_ID",
    "odoo_location_scrap_id": "ODOO_LOCATION_SCRAP_ID",
    "odoo_uom_id": "ODOO_UOM_ID",
    "odoo_payment_journal_id": "ODOO_PAYMENT_JOURNAL_ID",
    "odoo_picking_type_internal_id": "ODOO_PICKING_TYPE_INTERNAL_ID",
    "reconciliation_tolerance_units": "RECONCILIATION_TOLERANCE_UNITS",
    "reconciliation_tolerance_pct": "RECONCILIATION_TOLERANCE_PCT",
    "reconciliation_alert_wa_to": "RECONCILIATION_ALERT_WA_TO",
}

#: Field id Odoo (int/null) — dipakai normalisasi nilai env & DB.
ID_FIELDS = (
    "odoo_location_wip_id",
    "odoo_location_production_id",
    "odoo_location_fg_id",
    "odoo_location_scrap_id",
    "odoo_uom_id",
    "odoo_payment_journal_id",
    "odoo_picking_type_internal_id",
)

#: Field angka (float di response).
FLOAT_FIELDS = (
    "odoo_timeout",
    "reconciliation_tolerance_units",
    "reconciliation_tolerance_pct",
)

#: Urutan field untuk baris config (dipakai ``config_row`` & ``effective_row``).
CONFIG_FIELDS = tuple(ENV_KEYS)


@dataclass
class ConfigWriteResult:
    """Hasil satu operasi tulis Integration Config (dipakai view).

    **Tanpa** ``task_id``/``queued``: H5.6 Opsi B → tidak ada push ke Odoo.
    """

    config: IntegrationConfig | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def _is_http_url(value: str) -> bool:
    """True kalau URL **http/https dengan host**.

    **Tidak** memakai ``URLValidator`` Django karena validator itu menuntut TLD/
    ``localhost``, sedangkan MES memakai hostname internal Docker **tanpa TLD**
    (``ODOO_URL=http://odoo:8069`` — nilai default project ini sendiri).
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
    if field in ID_FIELDS:
        try:
            return int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            return None
    if field in FLOAT_FIELDS:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    if field == "reconciliation_alert_wa_to":
        return [str(item).strip() for item in (raw or []) if str(item).strip()]

    return str(raw or "")


def _db_value(config: IntegrationConfig, field: str, *, mask: bool = True):
    """Nilai field dari baris DB — dinormalisasi (rahasia di-mask bila ``mask=True``)."""
    return _normalize(field, getattr(config, field, None), mask=mask)


def _env_value(field: str, *, mask: bool = True):
    """Nilai field dari ``.env`` (settings) — dinormalisasi (rahasia di-mask)."""
    return _normalize(field, getattr(settings, ENV_KEYS[field], None), mask=mask)


def effective_row() -> dict:
    """Config yang **benar-benar aktif** sekarang (dibaca dari ``.env``/settings).

    Read-only — dipakai UI untuk membandingkan profil tersimpan vs yang berjalan.
    """
    return {field: _env_value(field) for field in CONFIG_FIELDS}


def config_row(config: IntegrationConfig) -> dict:
    """Baris profil config untuk API — ``odoo_api_key`` **selalu** di-mask (``***``)."""
    return {
        "id": config.pk,
        **{field: _db_value(config, field) for field in CONFIG_FIELDS},
        "is_active": bool(config.is_active),
        "created_at": _iso(config.created_at),
        "updated_at": _iso(config.updated_at),
    }


def divergences(config: IntegrationConfig | None) -> dict:
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


def needs_restart(config: IntegrationConfig | None) -> bool:
    """True kalau ada perbedaan DB vs ``.env`` (aktivasi = salin ke ``.env`` + restart)."""
    return bool(divergences(config))


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H5.1/H5.2
# ---------------------------------------------------------------------------
def _config_payload(config: IntegrationConfig) -> dict:
    """Payload ledger — memakai baris profil (rahasia sudah di-mask)."""
    row = config_row(config)
    row.pop("id", None)
    row.pop("created_at", None)
    row.pop("updated_at", None)

    return row


def _record_mes_only(config: IntegrationConfig) -> int:
    """Tulis/segarkan ``SyncRecord`` integration config lalu tandai ``SKIPPED``."""
    payload = _config_payload(config)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(CONFIG_RESOURCE, config.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(action: str, config: IntegrationConfig, request, metadata: dict | None = None) -> None:
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
            "master.integration_config: gagal menulis audit (%s, config %s).",
            action,
            config.pk,
        )


def _record_and_audit(
    config: IntegrationConfig,
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


def _parse_decimal(value, label: str, *, minimum, maximum=None):
    """``(Decimal|None, error)`` untuk angka dalam rentang (``None`` = kosong)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, f"Field '{label}' harus berupa angka."

    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None, f"Field '{label}' harus berupa angka."

    if not number.is_finite():
        return None, f"Field '{label}' harus berupa angka."
    if number < minimum:
        return None, f"Field '{label}' minimal {minimum}."
    if maximum is not None and number > maximum:
        return None, f"Field '{label}' maksimal {maximum}."

    return number, None


def _parse_id(value, label: str):
    """``(int|None, error)`` untuk id Odoo positif (kosong → ``None``)."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return None, f"Field '{label}' harus berupa id angka."

    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, f"Field '{label}' harus berupa id angka."

    if number < 1:
        return None, f"Field '{label}' harus id positif (≥ 1)."

    return number, None


def _parse_wa_list(value, label: str):
    """``(list[str], error)`` dari array / string dipisah koma (item kosong dibuang)."""
    if value in (None, ""):
        return [], None

    if isinstance(value, str):
        items = value.split(",")
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        return None, f"Field '{label}' harus daftar nomor (array atau string dipisah koma)."

    numbers: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        if len(text) > 32:
            return None, f"Field '{label}': nomor maksimal 32 karakter."
        numbers.append(text)

    return numbers, None


def validate_config_payload(data, instance: IntegrationConfig | None = None):
    """Validasi body PUT Integration Config → ``(values, error)``.

    **Create-on-first-PUT**: saat ``instance is None`` nilai default model dipakai
    (``erp_adapter='odoo'``, ``odoo_timeout=30``, toleransi 5/0.01). Field yang **tidak**
    dikirim tidak diubah. ``odoo_api_key="***"`` (mask) **diabaikan** ⇒ nilai lama
    dipertahankan; ``""`` menghapus.

    **Guard adapter**: ``erp_adapter='odoo'`` ⇒ ``odoo_url`` + ``odoo_db`` + ``odoo_user``
    wajib terisi (nilai efektif: payload menang, kalau tidak ada pakai baris lama).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "erp_adapter" in payload:
        adapter = str(payload.get("erp_adapter") or "").strip().lower()
        if not adapter:
            adapter = (
                instance.erp_adapter
                if instance is not None
                else IntegrationConfig.Adapter.ODOO
            )
        if adapter not in IntegrationConfig.Adapter.values:
            return None, (
                "Field 'erp_adapter' harus salah satu dari "
                f"{', '.join(IntegrationConfig.Adapter.values)}."
            )
        values["erp_adapter"] = adapter

    if "odoo_url" in payload:
        url, error = _text(payload.get("odoo_url"), "odoo_url", MAX_URL_LENGTH)
        if error:
            return None, error
        if url:
            try:
                valid_url = _is_http_url(url)
            except (TypeError, ValueError):
                valid_url = False
            if not valid_url:
                return None, f"Field 'odoo_url' bukan URL valid: {url!r}."
        values["odoo_url"] = url

    for field, max_length in (("odoo_db", MAX_DB_LENGTH), ("odoo_user", MAX_USER_LENGTH)):
        if field in payload:
            text, error = _text(payload.get(field), field, max_length)
            if error:
                return None, error
            values[field] = text

    if "odoo_api_key" in payload:
        text, error = _text(
            payload.get("odoo_api_key"), "odoo_api_key", MAX_API_KEY_LENGTH
        )
        if error:
            return None, error
        if text != MASK:
            # "***" = nilai lama dibiarkan; nilai baru/kosong = ganti/hapus.
            values["odoo_api_key"] = text

    if "odoo_timeout" in payload:
        timeout, error = _parse_decimal(
            payload.get("odoo_timeout"),
            "odoo_timeout",
            minimum=MIN_TIMEOUT,
            maximum=MAX_TIMEOUT,
        )
        if error:
            return None, error
        if timeout is None:
            return None, "Field 'odoo_timeout' wajib diisi (detik)."
        values["odoo_timeout"] = timeout

    for field in ID_FIELDS:
        if field in payload:
            number, error = _parse_id(payload.get(field), field)
            if error:
                return None, error
            values[field] = number

    if "reconciliation_tolerance_units" in payload:
        units, error = _parse_decimal(
            payload.get("reconciliation_tolerance_units"),
            "reconciliation_tolerance_units",
            minimum=Decimal("0"),
        )
        if error:
            return None, error
        if units is None:
            return None, "Field 'reconciliation_tolerance_units' wajib diisi."
        values["reconciliation_tolerance_units"] = units

    if "reconciliation_tolerance_pct" in payload:
        pct, error = _parse_decimal(
            payload.get("reconciliation_tolerance_pct"),
            "reconciliation_tolerance_pct",
            minimum=Decimal("0"),
            maximum=MAX_TOLERANCE_PCT,
        )
        if error:
            return None, error
        if pct is None:
            return None, "Field 'reconciliation_tolerance_pct' wajib diisi (rasio 0..1)."
        values["reconciliation_tolerance_pct"] = pct

    if "reconciliation_alert_wa_to" in payload:
        numbers, error = _parse_wa_list(
            payload.get("reconciliation_alert_wa_to"), "reconciliation_alert_wa_to"
        )
        if error:
            return None, error
        values["reconciliation_alert_wa_to"] = numbers

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    adapter = values.get(
        "erp_adapter", getattr(instance, "erp_adapter", IntegrationConfig.Adapter.ODOO)
    )
    if adapter == IntegrationConfig.Adapter.ODOO:
        url = values.get("odoo_url", getattr(instance, "odoo_url", ""))
        db = values.get("odoo_db", getattr(instance, "odoo_db", ""))
        user = values.get("odoo_user", getattr(instance, "odoo_user", ""))
        if not (url and db and user):
            return None, (
                "Adapter 'odoo' membutuhkan 'odoo_url', 'odoo_db', dan 'odoo_user' — "
                "atau ubah 'erp_adapter' ke 'null' bila MES berjalan tanpa Odoo."
            )

    return values, None


# ---------------------------------------------------------------------------
# Singleton + tulis + test koneksi
# ---------------------------------------------------------------------------
def get_config() -> IntegrationConfig | None:
    """Baris config (baris pertama, ``ordering=("pk",)``) atau ``None``.

    **Tanpa efek samping** — GET memakai ini supaya tidak membuat baris.
    """
    return IntegrationConfig.objects.order_by("pk").first()


def get_or_create_config() -> tuple[IntegrationConfig, bool]:
    """``(config, created)`` — baris **pasti ada** (dibuat dengan default model bila kosong).

    Dipakai konsumen internal yang butuh profil config tanpa payload; view GET
    **tidak** memakainya (GET tidak boleh membuat baris).
    """
    config = get_config()
    if config is not None:
        return config, False

    return IntegrationConfig.objects.create(), True


def update_config(data, request=None) -> ConfigWriteResult:
    """PUT profil config — **create-on-first-PUT** + ledger ``SKIPPED`` + audit.

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
        config = IntegrationConfig.objects.create(**values)
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
        "master.integration_config: profil %s %s (ledger=%s, MES-only).",
        config.pk,
        "dibuat" if created else "diubah",
        record_id,
    )
    return ConfigWriteResult(config=config, sync_record_id=record_id)


def test_connection() -> dict:
    """Uji koneksi Odoo (read-only, tanpa efek samping) → ``{ok, …}``.

    Urutan cek (semua **tanpa** mengubah apa pun):

      1. ``ERP_ADAPTER`` bukan ``odoo`` → ``ok=false`` (mode tanpa ERP);
      2. kredensial ``ODOO_*`` kurang (``ODOO_CREDENTIAL_KEYS`` — cek kanonik milik
         ``erp_sync/client.py``) → ``ok=false`` + daftar key yang hilang;
      3. ``get_adapter("odoo").health_check()`` (ping ``common.version``, tidak butuh
         login) → ``ok`` + ``server_version`` bila tersedia.

    Memakai kredensial **dari ``.env``** (bukan baris DB) — konsisten Opsi B.
    """
    adapter_name = str(getattr(settings, "ERP_ADAPTER", "") or "").strip().lower()
    url = str(getattr(settings, "ODOO_URL", "") or "")

    if adapter_name != "odoo":
        return {
            "ok": False,
            "adapter": adapter_name or "null",
            "url": None,
            "server_version": None,
            "message": "ERP_ADAPTER bukan 'odoo' (mode tanpa ERP) — tidak ada koneksi untuk diuji.",
        }

    missing = [key for key in ODOO_CREDENTIAL_KEYS if not getattr(settings, key, "")]
    if missing:
        return {
            "ok": False,
            "adapter": "odoo",
            "url": url or None,
            "server_version": None,
            "message": "Kredensial Odoo belum lengkap: " + ", ".join(missing) + " (cek .env).",
        }

    adapter = get_adapter("odoo")
    try:
        healthy = bool(adapter.health_check())
        version = None
        version_getter = getattr(adapter, "version", None)
        if healthy and callable(version_getter):
            try:
                version = (version_getter() or {}).get("server_version")
            except Exception:  # noqa: BLE001 - ping sukses; versi opsional
                logger.debug("master.integration_config: gagal membaca versi Odoo.")

        return {
            "ok": healthy,
            "adapter": "odoo",
            "url": url,
            "server_version": version,
            "message": (
                "Koneksi Odoo OK."
                if healthy
                else "Odoo tidak menjawab (cek URL/jaringan/database Odoo)."
            ),
        }
    finally:
        closer = getattr(adapter, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:  # noqa: BLE001 - penutupan koneksi best-effort
                logger.debug("master.integration_config: gagal menutup adapter Odoo.")
