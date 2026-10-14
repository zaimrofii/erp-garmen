"""``AuditLogger`` — penulis :class:`~core.audit.models.AuditLog` (Fase 6).

Prinsip:

  * **lengkap tapi aman**: IP (termasuk X-Forwarded-For di belakang proxy),
    user agent, dan request id diambil dari ``request`` kalau tersedia;
  * **tidak boleh gagal karena data aneh**: IP yang tidak valid -> ``None``,
    payload/metadata selalu dibuat JSON-safe (round-trip ``json``);
  * **fail loud**: nilai ``result`` yang tidak dikenal -> ``ValueError``
    (biar ketahuan di test). Pemanggil yang ingin tetap jalan walau audit gagal
    wajib membungkusnya dengan try/except — lihat pola di view action/sync.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from datetime import datetime, time, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from .models import AuditLog

logger = logging.getLogger(__name__)

__all__ = (
    "AuditLogger",
    "audit_detail",
    "audit_row",
    "filter_audit_logs",
    "list_audit_logs",
    "mask_sensitive",
    "metadata_preview",
    "parse_datetime_param",
)

#: Batas panjang user agent yang disimpan (hindari baris audit raksasa).
MAX_USER_AGENT_LENGTH = 500


def _json_safe(data: dict | None) -> dict:
    """Pastikan nilai aman disimpan di ``JSONField`` (round-trip + ``default=str``)."""
    if not data:
        return {}
    return json.loads(json.dumps(dict(data), default=str))


def _valid_ip(value: str | None) -> str | None:
    """IP valid atau ``None`` (GenericIPAddressField menolak string ngawur)."""
    if not value:
        return None
    candidate = str(value).strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        logger.warning("audit: ip tidak valid diabaikan: %r", candidate)
        return None
    return candidate


class AuditLogger:
    """Akses ``AuditLog`` (stateless; seluruh state di DB)."""

    def log(
        self,
        user,
        action: str,
        resource: str,
        resource_id: Any,
        request=None,
        payload: dict | None = None,
        result: str = AuditLog.Result.OK,
        metadata: dict | None = None,
    ) -> AuditLog:
        """Catat satu aksi.

        ``user`` boleh ``None`` (anonim/sistem); kalau ``request`` punya user
        terautentikasi, user itu dipakai. ``result`` harus salah satu
        ``AuditLog.Result`` (nilai lain -> ``ValueError``).
        """
        record = AuditLog.objects.create(
            user=self._resolve_user(user, request),
            action=str(action),
            resource=str(resource),
            resource_id=str(resource_id),
            request_id=str(getattr(request, "request_id", "") or "")[:64],
            ip_address=self._extract_ip(request),
            user_agent=self._extract_user_agent(request),
            payload=_json_safe(payload),
            result=self._validate_result(result),
            metadata=_json_safe(metadata),
        )
        logger.info(
            "audit: %s %s#%s -> %s (user=%s, request_id=%s)",
            record.action,
            record.resource,
            record.resource_id,
            record.result,
            record.user_id or "-",
            record.request_id or "-",
        )
        return record

    # --------------------------------------------------------------- internal
    @staticmethod
    def _resolve_user(user, request):
        """User eksplisit, atau user terautentikasi di request; selain itu None."""
        candidate = user
        if candidate is None and request is not None:
            candidate = getattr(request, "user", None)
        if candidate is None or not getattr(candidate, "is_authenticated", False):
            return None
        if getattr(candidate, "pk", None) is None:
            return None
        return candidate

    @staticmethod
    def _extract_ip(request) -> str | None:
        """IP klien: X-Forwarded-For pertama (kalau di belakang proxy), else REMOTE_ADDR."""
        if request is None:
            return None
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return _valid_ip(forwarded.split(",")[0])
        return _valid_ip(request.META.get("REMOTE_ADDR"))

    @staticmethod
    def _extract_user_agent(request) -> str:
        """User agent dari request (dipotong ``MAX_USER_AGENT_LENGTH``)."""
        if request is None:
            return ""
        return str(request.META.get("HTTP_USER_AGENT", ""))[:MAX_USER_AGENT_LENGTH]

    @staticmethod
    def _validate_result(result: Any) -> str:
        """Pastikan result dikenal (fail-fast daripada data audit ngawur)."""
        value = str(result)
        if value not in AuditLog.Result.values:
            raise ValueError(
                f"result audit tidak dikenal: {result!r}. "
                f"Pilihan: {', '.join(AuditLog.Result.values)}."
            )
        return value


# ---------------------------------------------------------------------------
# Reader **H5.5** — Audit Log Viewer (`/api/v1/settings/audit/`), READ-ONLY
# ---------------------------------------------------------------------------
# Modul ini **tidak pernah** menulis/mengubah ``AuditLog`` (append-only). Yang ada di
# bawah hanya: filter queryset, bentuk baris list (metadata *preview*), bentuk detail
# (payload/metadata lengkap) dan **mask rekursif defensif**.
#
# Kenapa mask: penulis H5.6/H5.8 sudah mengirim payload yang ter-mask, tetapi penulis
# lain (atau sprint berikutnya) bisa saja memasukkan kunci rahasia. Reader mem-mask
# key JSON yang *mengandung* kata sensitif supaya audit viewer tidak pernah menjadi
# jalan bocornya rahasia.

#: Nilai pengganti rahasia di response (konsisten H5.6/H5.8).
MASK_VALUE = "***"

#: Potongan kunci JSON (case-insensitive) yang nilainya WAJIB di-mask.
SENSITIVE_KEY_PARTS = ("api_key", "password", "secret", "token", "key")

#: Panjang maksimum metadata *preview* di daftar (detail = lengkap).
METADATA_PREVIEW_LENGTH = 100

#: Batas panjang kata kunci `?search` (hindari query raksasa).
MAX_SEARCH_LENGTH = 100

#: Batas `?limit` / `?cursor` (selaras endpoint settings lain).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000

#: Pola **strict** tanggal-saja (``YYYY-MM-DD``) — pembeda dari ISO-8601 di atas.
DATE_ONLY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def mask_sensitive(value: Any) -> Any:
    """Kembalikan salinan ``value`` dengan nilai rahasia diganti ``***`` (rekursif).

    Kunci dianggap rahasia bila namanya **mengandung** salah satu frasa di
    :data:`SENSITIVE_KEY_PARTS` (case-insensitive, mis. ``odoo_api_key``,
    ``X-Api-Key``, ``password``, ``access_token``). Berlaku untuk dict/list bersarang;
    tipe lain dikembalikan apa adanya.
    """
    if isinstance(value, dict):
        masked: dict = {}
        for key, item in value.items():
            if isinstance(key, str) and any(
                part in key.lower() for part in SENSITIVE_KEY_PARTS
            ):
                masked[key] = MASK_VALUE if item not in (None, "") else item
            else:
                masked[key] = mask_sensitive(item)
        return masked

    if isinstance(value, (list, tuple)):
        return [mask_sensitive(item) for item in value]

    return value


def metadata_preview(metadata: Any) -> str:
    """Ringkas ``metadata`` untuk daftar: JSON satu baris, dipotong 100 karakter.

    Kosong → ``""`` (bukan ``"{}"``) supaya UI bisa menampilkan sel kosong.
    """
    safe = mask_sensitive(metadata if isinstance(metadata, dict) else {})
    if not safe:
        return ""

    text = json.dumps(safe, ensure_ascii=False, default=str, sort_keys=True)
    if len(text) <= METADATA_PREVIEW_LENGTH:
        return text

    return text[:METADATA_PREVIEW_LENGTH] + "…"


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (kolom waktu kosong)."""
    return value.isoformat() if value else None


def _user_fields(log: AuditLog) -> dict:
    """``{user_id, username, full_name}`` — user NULL (anonim/sistem) → ``None``/``""``."""
    user = getattr(log, "user", None)
    if user is None:
        return {"user_id": None, "username": None, "full_name": ""}

    return {
        "user_id": user.pk,
        "username": user.get_username(),
        "full_name": user.get_full_name(),
    }


def audit_row(log: AuditLog) -> dict:
    """Satu baris **daftar** audit (payload tidak ikut; metadata hanya *preview*)."""
    return {
        "id": log.pk,
        "timestamp": _iso(log.timestamp),
        **_user_fields(log),
        "action": log.action,
        "resource": log.resource,
        "resource_id": log.resource_id,
        "result": log.result,
        "request_id": log.request_id,
        "ip_address": log.ip_address,
        "metadata_preview": metadata_preview(log.metadata),
    }


def audit_detail(log: AuditLog) -> dict:
    """Detail satu audit: baris daftar + ``payload``/``metadata``/``user_agent`` lengkap.

    ``payload`` & ``metadata`` tetap melalui :func:`mask_sensitive` (detail = lengkap,
    bukan berarti rahasia ikut tampil).
    """
    return {
        **audit_row(log),
        "payload": mask_sensitive(log.payload if isinstance(log.payload, dict) else {}),
        "metadata": mask_sensitive(log.metadata if isinstance(log.metadata, dict) else {}),
        "user_agent": log.user_agent,
    }


def parse_datetime_param(value, label: str, *, exclusive_end: bool = False):
    """``(datetime|None, error)`` dari ``YYYY-MM-DD`` atau ISO-8601 (naive → lokal).

    ``exclusive_end=True`` (dipakai ``?date_to``) menggeser batas **tanggal-saja** ke
    **awal hari berikutnya** supaya rentangnya inklusif sampai akhir hari itu.
    Nilai kosong → ``(None, None)`` (filter dilewati).
    """
    text = str(value or "").strip()
    if text == "":
        return None, None

    moment = None

    # Tanggal-saja DICEK LEBIH DULU (strict full-match) karena ``parse_datetime``
    # Django juga menerima ``YYYY-MM-DD`` — tanpa cek ini, ``?date_to`` tanggal-saja
    # tidak akan pernah digeser ke awal hari berikutnya.
    if DATE_ONLY_RE.fullmatch(text):
        try:
            day = parse_date(text)
        except ValueError:
            day = None
        if day is not None:
            moment = datetime.combine(day, time.min)
            if exclusive_end:
                moment = moment + timedelta(days=1)

    if moment is None:
        try:
            moment = parse_datetime(text)
        except ValueError:
            moment = None

    if moment is None:
        return None, (
            f"Parameter '{label}' harus tanggal (YYYY-MM-DD) atau ISO-8601."
        )

    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment, timezone.get_current_timezone())

    return moment, None


def _parse_user_id(value):
    """``(int|None, error)`` untuk ``?user_id`` (angka ≥ 1)."""
    text = str(value or "").strip()
    if text == "":
        return None, None

    try:
        number = int(text)
    except (TypeError, ValueError):
        return None, "Parameter 'user_id' harus berupa angka."

    if number < 1:
        return None, "Parameter 'user_id' harus ≥ 1."

    return number, None


def filter_audit_logs(
    queryset,
    *,
    user_id=None,
    action=None,
    resource=None,
    resource_id=None,
    result=None,
    date_from=None,
    date_to=None,
    search=None,
):
    """``(queryset, error)`` — terapkan filter opsional ke queryset ``AuditLog``.

    Aturan:

      * ``action``: diakhiri titik → **prefix** (``master.`` cocok dengan
        ``master.create``/``master.update``); selain itu **exact** (case-insensitive);
      * ``resource``/``resource_id``/``result``: exact (case-insensitive);
      * ``date_from``/``date_to``: ``YYYY-MM-DD`` atau ISO-8601 (inklusif; ``date_to``
        tanggal-saja = sampai akhir hari itu);
      * ``search``: ``user__username`` + nama depan/belakang + ``action`` + ``resource``
        (case-insensitive, substring);
      * filter kosong = dilewati (**tidak** ada error).
    """
    action_text = str(action or "").strip()
    if action_text.endswith("."):
        queryset = queryset.filter(action__istartswith=action_text)
    elif action_text:
        queryset = queryset.filter(action__iexact=action_text)

    resource_text = str(resource or "").strip()
    if resource_text:
        queryset = queryset.filter(resource__iexact=resource_text)

    resource_id_text = str(resource_id or "").strip()
    if resource_id_text:
        queryset = queryset.filter(resource_id__iexact=resource_id_text)

    result_text = str(result or "").strip()
    if result_text:
        if result_text.upper() not in AuditLog.Result.values:
            return None, (
                "Parameter 'result' harus salah satu dari "
                + ", ".join(AuditLog.Result.values)
                + "."
            )
        queryset = queryset.filter(result=result_text.upper())

    number, error = _parse_user_id(user_id)
    if error:
        return None, error
    if number is not None:
        queryset = queryset.filter(user_id=number)

    moment, error = parse_datetime_param(date_from, "date_from")
    if error:
        return None, error
    if moment is not None:
        queryset = queryset.filter(timestamp__gte=moment)

    moment, error = parse_datetime_param(date_to, "date_to", exclusive_end=True)
    if error:
        return None, error
    if moment is not None:
        queryset = queryset.filter(timestamp__lt=moment)

    search_text = str(search or "").strip()
    if search_text:
        if len(search_text) > MAX_SEARCH_LENGTH:
            return None, f"Parameter 'search' maksimal {MAX_SEARCH_LENGTH} karakter."
        queryset = queryset.filter(
            Q(user__username__icontains=search_text)
            | Q(user__first_name__icontains=search_text)
            | Q(user__last_name__icontains=search_text)
            | Q(action__icontains=search_text)
            | Q(resource__icontains=search_text)
        )

    return queryset, None


def list_audit_logs(queryset, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    """Halaman audit (offset-based, urut **terbaru dulu**) → amplop ListPage.

    ``{rows, total_count, has_more, next_cursor}`` — bentuk yang sama dengan
    ``/api/v1/sync/records/`` (F15) & endpoint settings lain.
    """
    queryset = queryset.order_by("-timestamp", "-id")
    total = queryset.count()
    rows = [audit_row(log) for log in queryset[offset : offset + limit]]
    has_more = offset + len(rows) < total

    return {
        "rows": rows,
        "total_count": total,
        "has_more": has_more,
        "next_cursor": (offset + len(rows)) if has_more else None,
    }



