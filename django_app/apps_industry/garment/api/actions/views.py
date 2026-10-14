"""Endpoint aksi: `POST /api/v1/<industry>/<resource>/<id>/<action>/` (Kontrak §2, §5, §8).

Alur view:

  1. baca header `Idempotency-Key`, `X-Base-Version`, `X-Conflict-Policy`;
  2. **cek idempotency** — kalau key ini sudah pernah sukses, kembalikan response
     pertama apa adanya + `X-Idempotent-Replay: true` + `{"duplicate-ignored": true}`;
  3. kalau belum: jalankan `ActionExecutor` (400 transisi tidak sah / 409 konflik);
  4. simpan response **hanya kalau sukses (200)** — konflik/400 tidak di-cache
     supaya retry setelah state berubah tetap bisa jalan.

`Idempotency-Key` bersifat opsional: request tanpa key tetap diproses (kontrak
§10 menyarankan selalu mengirim, jadi ketiadaannya dicatat di log), dan isinya
string apa pun (tidak divalidasi UUID).

Fase A: segment `industry` di URL divalidasi whitelist (`api/industries.py`)
sebelum apa pun dikerjakan → industri tak dikenal dibalas **404 eksplisit**.

Fase C — urutan & policy konflik (header):

  * urutan: cek idempotency (replay) → cek konflik → eksekusi;
  * `X-Force: true` → setara `last_write_wins`: lewati cek konflik, timpa version;
  * `X-Conflict-Policy: last_write_wins` → lewati cek; `server_wins` / `manual`
    (default, dan nilai tak dikenal) → **409** + `{"current": {version, state,
    current_work_center}}`;
  * `X-Base-Version` tidak dikirim → **tanpa** cek konflik (jalur lama tetap jalan).

FASE 4.1 (hardening): permission = ``IsAuthenticated`` — endpoint ini MENGUBAH
state produksi, jadi anonim harus **403**. Klien simulator mengirim cookie sesi
(`DJANGO_SIM_COOKIE`, FASE 3.1.1) sehingga alur tetap jalan.
"""

from __future__ import annotations

import hashlib
import json
import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.api.actions.executor import (
    ActionExecutor,
    resolve_conflict_policy,
)
from apps_industry.garment.api.industries import require_industry
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from core.idempotency.services import IdempotencyService

logger = logging.getLogger(__name__)

IDEMPOTENCY_HEADER = "Idempotency-Key"
BASE_VERSION_HEADER = "X-Base-Version"
CONFLICT_POLICY_HEADER = "X-Conflict-Policy"
FORCE_HEADER = "X-Force"


class ActionView(APIView):
    """Jalankan satu aksi resource (mis. BUNDLE_START) secara idempotent."""

    # FASE 4.1 (hardening): aksi MENGUBAH data produksi → wajib login.
    # Sebelumnya `AllowAny` (komentar lama: "auth menyusul Fase 6").
    # Klien simulator sudah mengirim cookie sesi (FASE 3.1.1), jadi tidak putus.
    permission_classes = [IsAuthenticated]

    def post(self, request, industry: str, resource: str, id: int, action: str):
        """POST aksi; lihat docstring modul untuk alur lengkapnya."""
        # Fase A: validasi segment industri DULU (404 eksplisit) supaya industri
        # palsu (mis. "metadata"/"chatter") tidak pernah sampai ke executor.
        require_industry(industry)

        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        base_version = request.headers.get(BASE_VERSION_HEADER)
        # Fase C: prioritas `X-Force` > `X-Conflict-Policy` > default `manual`.
        conflict_policy = resolve_conflict_policy(
            request.headers.get(CONFLICT_POLICY_HEADER),
            request.headers.get(FORCE_HEADER),
        )
        # Hash idempotensi hanya dipakai bila ada `Idempotency-Key`
        # (IdempotencyService.check/save). Dihitung LAZILY dari `request.data`
        # (dict) — JANGAN `request.body` (di ASGI live stream body sudah
        # dikonsumsi → RawPostDataException). Request tanpa key tidak mem-parse
        # body di sini (menjaga perilaku lama: resource tak dikenal → 404).
        request_hash = None
        if idempotency_key:
            data = request.data if isinstance(request.data, dict) else {}
            request_hash = self._request_hash(
                request.method, resource, id, action, data
            )
        service = IdempotencyService()

        if not idempotency_key:
            logger.warning(
                "aksi %s/%s/%s tanpa header Idempotency-Key (kontrak §10 "
                "menyarankan selalu mengirim).",
                resource,
                id,
                action,
            )

        replay = service.check(idempotency_key, resource, id, action, request_hash)
        if replay is not None:
            body = dict(replay.response_body or {})
            body["duplicate-ignored"] = True
            response = Response(body, status=replay.response_status)
            response["X-Idempotent-Replay"] = "true"
            logger.info(
                "idempotency: replay key '%s' untuk %s#%s:%s.",
                idempotency_key,
                resource,
                id,
                action,
            )
            return response

        result = ActionExecutor().execute(
            resource_name=resource,
            instance_id=id,
            action_id=action,
            request=request,
            base_version=base_version,
            conflict_policy=conflict_policy,
        )
        status_code = result["status"]
        payload = result["payload"]

        # Fase 6: jejak audit (setelah eksekusi; replay idempotent tidak dicatat
        # ulang karena memang tidak mengeksekusi apa pun).
        self._audit(request, resource, id, action, status_code, payload)

        if status_code == status.HTTP_200_OK and idempotency_key:
            service.save(
                idempotency_key,
                resource,
                id,
                action,
                request_hash,
                status_code,
                payload,
            )

        return Response(payload, status=status_code)

    # --------------------------------------------------------------- internal
    @staticmethod
    def _audit(
        request, resource: str, id: int, action: str, status_code: int, payload: dict
    ) -> None:
        """Tulis AuditLog untuk aksi ini.

        Kegagalan audit **tidak boleh** membatalkan aksi produksi yang sudah
        berhasil, jadi exception di sini hanya dicatat di log.
        """
        try:
            AuditLogger().log(
                user=None,  # diambil dari request kalau sudah terautentikasi
                action=action,
                resource=resource,
                resource_id=id,
                request=request,
                payload={"status": status_code, "body": payload},
                result=ActionView._audit_result(status_code),
            )
        except Exception:  # noqa: BLE001 - audit tidak boleh mematikan alur produksi
            logger.exception("audit: gagal mencatat aksi %s#%s:%s", resource, id, action)

    @staticmethod
    def _audit_result(status_code: int) -> str:
        """Petakan status HTTP aksi -> ``AuditLog.Result``."""
        if status_code == status.HTTP_200_OK:
            return AuditLog.Result.OK
        if status_code == status.HTTP_409_CONFLICT:
            return AuditLog.Result.CONFLICT
        if status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
            return AuditLog.Result.DENIED
        return AuditLog.Result.FAILED

    @staticmethod
    def _request_hash(
        method: str, resource: str, id: int, action: str, body_data: dict
    ) -> str:
        """SHA-256 dari method+resource+id+action+body (deteksi key dipakai ulang).

        Body diambil dari ``request.data`` (dict) → **canonical JSON** — BUKAN
        ``request.body`` (di server ASGI live stream body sudah dikonsumsi
        sebelum view jalan → ``RawPostDataException``).
        """
        canonical = json.dumps(body_data or {}, sort_keys=True, separators=(",", ":"))
        raw = f"{method}|{resource}|{id}|{action}|{canonical}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
