"""Endpoint **settings** (F3A.2/B22,B24,B25 + F5.4.1/B26,B27,B28 + H1.9 routing + Sprint C sequences).

Resource konfigurasi/admin:

  * ``/api/v1/settings/routing/``         -> ``ProcessRouting`` + ``RoutingStep`` (model LAMA)
  * ``/api/v1/settings/routing/<id>/``    -> detail / ubah / nonaktifkan (H1.9)
  * ``/api/v1/settings/routing/<id>/steps/``            -> tambah step (H1.9)
  * ``/api/v1/settings/routing/<id>/steps/<step_id>/``  -> ubah / hapus step (H1.9)
  * ``/api/v1/settings/sequences/``        -> ``master.NumberSequence`` (Sprint C GET + H5.3 POST)
  * ``/api/v1/settings/sequences/<code>/preview/`` -> nomor berikutnya (tanpa increment)
  * ``/api/v1/settings/sequences/<code>/`` -> PUT prefix/padding/aktif/nama + H5.3 DELETE (soft)
  * ``/api/v1/settings/currencies/``        -> ``master.Currency`` (H5.2 — LIST + POST;
    ``/default/``, ``/<id>/``, ``/<id>/set-default/``). **MES-only** (ledger ``SKIPPED``).
  * ``/api/v1/settings/company/``          -> ``master.Company`` (H5.1 — **SINGLETON**:
    GET/PUT saja, create-on-first-PUT). **MES-only** (ledger ``SKIPPED``).
  * ``/api/v1/settings/integration/``      -> ``master.IntegrationConfig`` (H5.6 —
    **SINGLETON** + profil config; GET juga melaporkan ``effective``/``diverges``/
    ``needs_restart``). ``…/test-connection/`` = POST uji koneksi Odoo (read-only).
  * ``/api/v1/settings/wa/``               -> ``master.WAConfig`` (H5.8 — **SINGLETON**
    gateway WhatsApp: backend/url/key; GET juga melaporkan ``effective``/``diverges``/
    ``needs_restart``). ``…/test-connection/`` = POST uji gateway WA (read-only, mock).
  * ``/api/v1/settings/audit/``            -> ``core_audit.AuditLog`` (H5.5 — **daftar
    READ-ONLY** audit trail + filter; ``/<id>/`` = detail payload/metadata lengkap).
    Rahasia di payload/metadata **selalu** di-mask (``***``).
  * ``/api/v1/settings/printer/``          -> ``master.PrinterConfig`` (H5.7 —
    **SINGLETON** printer thermal ESC/POS: backend/USB id/host/port/mock dir; GET juga
    melaporkan ``effective``/``diverges``/``needs_restart``).
    ``…/test-connection/`` = POST uji printer (**tidak pernah mencetak**).
  * ``/api/v1/settings/permissions/``      -> matrix izin role × resource × action (H5.4 —
    **Opsi A′**: profil tersimpan di ``core_auth.RolePermission`` + ``effective``
    (snapshot kode) + ``diverges`` + ``banner``). ``PUT …/<role_id>/`` = bulk update
    (ADMIN/OWNER, ledger ``SKIPPED``) — **enforcement tetap hardcoded di kode**.
  * ``/api/v1/settings/bundling/``        -> ``BundlingRule`` (model baru, migrasi 0009)
  * ``/api/v1/settings/line-allocation/`` -> ``LineAllocationRule`` (model baru, migrasi 0010)
  * ``/api/v1/settings/users/``           -> ``core_auth.User``   (F5.4.1 / B26: GET+POST)
  * ``/api/v1/settings/users/<id>/``      -> ``core_auth.User``   (F5.4.1 / B26: PUT + DELETE soft)
  * ``/api/v1/settings/roles/``           -> ``core_auth.Role``   (F5.4.1 / B27: GET saja)
  * ``/api/v1/settings/devices/``         -> ``core_device_profile.DeviceProfile``
    (F5.4.1 / B28: GET saja — **katalog profil**, bukan binding; lihat docstring kelasnya)

Catatan F5.4.1 (keputusan mapping, disetujui saat recon):
  * ``Role`` tidak punya kolom ``label``/``permissions`` → B27 memakai ``label`` = ``Role.name``
    dan ``user_count`` = jumlah user ber-role tsb; ``permissions`` tidak ada di kontrak;
  * ``DeviceProfile`` tidak punya ``device_type``/``wc_code``/``last_seen_at`` → B28 memakai
    ``device_type`` = ``DeviceProfile.code``, ``label`` = ``DeviceProfile.name``,
    ``active`` = ``is_active``, ditambah ``binding_count`` (jumlah ``DeviceBinding``);
    ``wc_code``/``last_seen_at`` (milik ``DeviceBinding``) **tidak** ada di kontrak baris.

Didafarkan di ``config/urls.py`` (section kontrak core, SEBELUM ``include``
industri) karena ``settings`` bukan nama industri — pola
``v1/<industry>/<resource>/`` tidak boleh menangkap path ini.

Auth ``IsAuthenticated`` untuk **GET maupun POST** (konfigurasi admin).

Pemetaan body -> model existing (model LAMA **tidak** diubah):

  * ``ProcessRouting.code`` wajib unik tetapi tidak dikirim body → diturunkan dari
    ``name`` (slug uppercase) + sufiks angka bila bentrok;
  * ``steps[].wc_type`` (string) disimpan ke ``RoutingStep.label``; ``work_center``
    dibiarkan NULL karena body tidak menyebut instance WorkCenter;
  * ``steps[].depends_on`` (daftar ``step_no``) → edge ``allowed_next_steps`` dari
    step yang di-*depends* MENUJU step ini; step tanpa ``depends_on`` →
    ``is_initial=True``; step yang tidak dijadikan tujuan siapa pun →
    ``is_terminal=True``;
  * ``steps[].rework_target_step`` → ``RoutingStep.rework_target_step`` (self-FK),
    divalidasi ``<= step_no`` dan harus merujuk ``step_no`` yang ada di body;
  * ``product_id`` (opsional) divalidasi bertipe angka lalu **diabaikan**:
    ``ProcessRouting`` tidak punya kolom produk (pemetaan produk→routing memakai
    ``TagRouter``/rule engine, di luar scope).
"""

from __future__ import annotations

import logging
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import (
    BundlingRule,
    LineAllocationRule,
    ProcessRouting,
    ProductionLine,
    RoutingStep,
)
from core.audit import services as audit_services
from core.audit.models import AuditLog
from core.auth import permission_services
from core.auth.models import OPERATOR_CODE_ROLES, Role, User
from core.device_profile.models import DeviceBinding, DeviceProfile
from master import (
    company_services,
    currency_services,
    integration_config_services,
    printer_config_services,
    routing_services,
    sequence_services,
    wa_config_services,
)
from master.models import Currency, NumberSequence

logger = logging.getLogger(__name__)

__all__ = (
    "SettingsAuditDetailView",
    "SettingsAuditView",
    "SettingsBundlingView",
    "SettingsCompanyView",
    "SettingsCurrenciesView",
    "SettingsCurrencyDefaultView",
    "SettingsCurrencyDetailView",
    "SettingsCurrencySetDefaultView",
    "SettingsDevicesView",
    "SettingsIntegrationConfigView",
    "SettingsIntegrationTestConnectionView",
    "SettingsLineAllocationView",
    "SettingsPermissionRoleView",
    "SettingsPermissionsView",
    "SettingsPrinterConfigView",
    "SettingsPrinterTestConnectionView",
    "SettingsRolesView",
    "SettingsRoutingDetailView",
    "SettingsRoutingStepDetailView",
    "SettingsRoutingStepsView",
    "SettingsRoutingView",
    "SettingsSequenceDetailView",
    "SettingsSequencePreviewView",
    "SettingsSequencesView",
    "SettingsUserDetailView",
    "SettingsUsersView",
    "SettingsWAConfigView",
    "SettingsWATestConnectionView",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_OFFSET = 100000


def _list_params(request):
    """``(limit, offset, error)`` dari ``?limit``/``?cursor`` (offset-based)."""
    try:
        limit = int(request.query_params.get("limit") or DEFAULT_LIMIT)
        offset = int(request.query_params.get("cursor") or 0)
    except (TypeError, ValueError):
        return None, None, "Parameter 'limit'/'cursor' harus berupa angka."
    if limit < 1 or limit > MAX_LIMIT:
        return None, None, f"Parameter 'limit' harus antara 1 dan {MAX_LIMIT}."
    if offset < 0 or offset > MAX_OFFSET:
        return None, None, f"Parameter 'cursor' harus antara 0 dan {MAX_OFFSET}."
    return limit, offset, None


def _envelope(rows: list, total: int, offset: int) -> dict:
    """Amplop ListPage: ``{rows, total_count, has_more, next_cursor}``."""
    has_more = offset + len(rows) < total
    return {
        "rows": rows,
        "total_count": total,
        "has_more": has_more,
        "next_cursor": (offset + len(rows)) if has_more else None,
    }


def _unique_routing_code(name: str) -> str:
    """Kode unik & deterministik dari ``name`` (slug uppercase)."""
    base = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").upper()[:48] or "ROUTING"
    candidate = base
    seq = 2
    while ProcessRouting.objects.filter(code=candidate).exists():
        candidate = f"{base}-{seq}"
        seq += 1
    return candidate


def serialize_routing(routing: ProcessRouting) -> dict:
    """Routing + step-nya (``depends_on`` = step yang mengizinkan step ini)."""
    steps = []
    queryset = routing.steps.select_related(
        "rework_target_step", "work_center"
    ).order_by("order")
    for step in queryset:
        steps.append(
            {
                "id": step.pk,
                "step_no": step.order,
                "wc_type": step.label,
                "depends_on": sorted(prev.order for prev in step.allowed_from.all()),
                "rework_target_step": (
                    step.rework_target_step.order
                    if step.rework_target_step is not None
                    else None
                ),
                "is_initial": step.is_initial,
                "is_terminal": step.is_terminal,
            }
        )
    return {
        "id": routing.pk,
        "code": routing.code,
        "name": routing.name,
        "description": routing.description,
        "is_active": routing.is_active,
        "steps": steps,
    }


def serialize_bundling(rule: BundlingRule) -> dict:
    """Satu ``BundlingRule`` -> JSON (``size_matrix`` selalu objek)."""
    return {
        "id": rule.pk,
        "name": rule.name,
        "size_matrix": rule.size_matrix or {},
        "bundle_size_default": rule.bundle_size_default,
        "is_active": rule.is_active,
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


def serialize_allocation(rule: LineAllocationRule) -> dict:
    """Satu ``LineAllocationRule`` -> JSON (``line_id`` + ``line_code``)."""
    return {
        "id": rule.pk,
        "name": rule.name,
        "wc_type": rule.wc_type,
        "line_id": rule.line_id,
        "line_code": rule.line.code if rule.line is not None else None,
        "priority": rule.priority,
        "is_active": rule.is_active,
        "config": rule.config or {},
        "created_at": rule.created_at.isoformat(),
        "updated_at": rule.updated_at.isoformat(),
    }


def _is_int(value) -> bool:
    """True untuk ``int`` asli (``bool`` bukan integer di sini)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_steps(raw_steps):
    """``(parsed, error)`` — validasi ``steps`` body POST routing.

    ``parsed`` = daftar ``{step_no, wc_type, depends_on, rework_target_step}``
    terurut menaik ``step_no``. Aturan (sesuai brief B22):

      * ``step_no`` integer > 0 dan **unik**;
      * ``wc_type`` string tidak kosong;
      * ``depends_on`` daftar integer yang semuanya ADA di ``steps``;
      * ``rework_target_step`` (opsional) integer yang ada di ``steps`` dan
        ``<= step_no``.
    """
    parsed: list[dict] = []
    seen: set[int] = set()

    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            return None, f"steps[{index}] harus berupa objek."
        step_no = raw.get("step_no")
        if not _is_int(step_no) or step_no <= 0:
            return None, f"steps[{index}].step_no harus integer > 0."
        if step_no in seen:
            return None, f"steps[{index}].step_no={step_no} duplikat."
        seen.add(step_no)

        wc_type = str(raw.get("wc_type") or "").strip()
        if not wc_type:
            return None, f"steps[{index}].wc_type wajib diisi."

        depends_on = raw.get("depends_on") or []
        if not isinstance(depends_on, list) or any(not _is_int(dep) for dep in depends_on):
            return None, f"steps[{index}].depends_on harus daftar integer."

        rework = raw.get("rework_target_step")
        if rework is not None and not _is_int(rework):
            return None, f"steps[{index}].rework_target_step harus integer."

        parsed.append(
            {
                "step_no": step_no,
                "wc_type": wc_type,
                "depends_on": list(depends_on),
                "rework_target_step": rework,
            }
        )

    for item in parsed:
        for dep in item["depends_on"]:
            if dep not in seen:
                return None, f"step {item['step_no']} depends_on {dep} tidak ada di steps."
        rework = item["rework_target_step"]
        if rework is not None:
            if rework not in seen:
                return None, f"step {item['step_no']} rework_target_step {rework} tidak ada."
            if rework > item["step_no"]:
                return None, (
                    f"step {item['step_no']} rework_target_step={rework} harus <= step_no."
                )

    parsed.sort(key=lambda item: item["step_no"])
    return parsed, None


class SettingsRoutingView(APIView):
    """``GET|POST /api/v1/settings/routing/`` — konfigurasi DAG routing.

    **GET** → ListPage routing + step-nya::

        {"rows": [{"id", "code", "name", "description", "is_active",
                   "steps": [{"id", "step_no", "wc_type", "depends_on",
                              "rework_target_step", "is_initial", "is_terminal"}]}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    **POST** → buat routing baru (``ProcessRouting`` + ``RoutingStep``), body::

        {"name": "...", "product_id": 12?, "description": "?",
         "steps": [{"step_no": 1, "wc_type": "CUTTING", "depends_on": [],
                    "rework_target_step": null}]}

    Validasi → **400** (``{"detail": ...}``): ``name`` kosong; ``steps`` bukan
    array/kosong; ``step_no`` non-integer/duplikat; ``wc_type`` kosong;
    ``depends_on`` bukan daftar integer atau merujuk step_no tak dikenal;
    ``rework_target_step`` tak dikenal atau ``> step_no``.
    Sukses → **201** dengan objek routing (termasuk ``steps``).

    Permission ``IsAuthenticated`` (GET & POST) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List routing + steps; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = ProcessRouting.objects.all().order_by("code")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope([serialize_routing(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat routing + step; lihat docstring kelas."""
        data = request.data or {}

        name = str(data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "Field 'name' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        product_id = data.get("product_id")
        if product_id is not None and not _is_int(product_id):
            return Response(
                {"detail": "Field 'product_id' harus integer bila diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return Response(
                {"detail": "Field 'steps' wajib array tidak kosong."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed, error = _parse_steps(raw_steps)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            routing = ProcessRouting.objects.create(
                code=_unique_routing_code(name),
                name=name,
                description=str(data.get("description") or ""),
            )

            by_no: dict[int, RoutingStep] = {}
            for item in parsed:
                by_no[item["step_no"]] = RoutingStep.objects.create(
                    routing=routing,
                    code=f"STEP-{item['step_no']}",
                    label=item["wc_type"],
                    order=item["step_no"],
                    is_initial=not item["depends_on"],
                )

            depended_on: set[int] = set()
            for item in parsed:
                step = by_no[item["step_no"]]
                for dep in item["depends_on"]:
                    by_no[dep].allowed_next_steps.add(step)
                    depended_on.add(dep)
                rework = item["rework_target_step"]
                if rework is not None:
                    step.rework_target_step = by_no[rework]
                    step.save(update_fields=["rework_target_step"])

            for step_no, step in by_no.items():
                if step_no not in depended_on:
                    step.is_terminal = True
                    step.save(update_fields=["is_terminal"])

        logger.info(
            "settings.routing: routing %s dibuat (%d step).", routing.code, len(parsed)
        )
        return Response(serialize_routing(routing), status=status.HTTP_201_CREATED)


class SettingsRoutingDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/settings/routing/<id>/`` — detail/ubah/nonaktifkan.

    **H1.9** (extend B22 di tempat — TIDAK ada endpoint paralel ``master/routings/``):
    frontend master CRUD memakai endpoint ini bersama `POST /settings/routing/` (B22).

    **GET** → routing + ``steps`` (shape B22 apa adanya) **plus** field H1.9:
    ``capability_tags``, ``steps_count``, ``nodes[]``/``edges[]`` (shape
    `/api/v1/routing/graph/`), ``created_at``/``updated_at``. 404 kalau tidak ada.

    **PUT** → ubah header (``name``/``code``/``description``/``capability_tags``/
    ``active``); hanya field yang dikirim yang diubah. **DELETE** → soft delete
    (``is_active=False``) — **400** kalau masih ada ``Rule`` tag-router aktif yang
    menunjuk kode routing ini.

    Permission: GET ``IsAuthenticated``; PUT/DELETE **ADMIN/OWNER** (``_require_admin``).
    Keduanya menulis ``SyncRecord`` ``SKIPPED`` (MES-only) + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int):
        """Detail routing (field B22 + field H1.9)."""
        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        return Response(routing_services.routing_detail_row(routing))

    def put(self, request, pk: int):
        """Ubah header routing; lihat docstring kelas."""
        _require_admin(request)

        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = routing_services.update_routing(routing, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(routing_services.routing_detail_row(result.routing))

    def delete(self, request, pk: int):
        """Soft delete routing (guard rule tag-router aktif); lihat docstring kelas."""
        _require_admin(request)

        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = routing_services.deactivate_routing(routing, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(routing_services.routing_detail_row(result.routing))


class SettingsRoutingStepsView(APIView):
    """``POST /api/v1/settings/routing/<id>/steps/`` — tambah step (node DAG).

    Body::

        {"label": "SEWING"?, "wc_type": "SEWING"?, "order": 30?, "code": "STEP-30"?,
         "work_center_id": 7?, "depends_on_step_ids": [12], "next_step_ids": [14],
         "rework_target_step_id": 12?}

    ``label`` (alias ``wc_type``) wajib; ``order`` kosong → ``max(order)+10``;
    ``depends_on_step_ids`` = predecessor, ``next_step_ids`` = successor (keduanya
    mengubah M2M ``allowed_next_steps``; ``is_initial``/``is_terminal`` dihitung ulang).
    Validasi → **400**: ``order`` duplikat, work center tak dikenal, id step bukan
    milik routing ini, self-reference, atau **siklus DAG**. Sukses → **201** detail
    routing (termasuk step baru).

    Permission **ADMIN/OWNER**; menulis ``SyncRecord`` ``SKIPPED`` + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk: int):
        """Tambah step; lihat docstring kelas."""
        _require_admin(request)

        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = routing_services.create_step(routing, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            routing_services.routing_detail_row(result.routing), status=status.HTTP_201_CREATED
        )


class SettingsRoutingStepDetailView(APIView):
    """``PUT|DELETE /api/v1/settings/routing/<id>/steps/<step_id>/`` — ubah/hapus step.

    **PUT** → ubah step dan/atau edge-nya (``depends_on_step_ids``/``next_step_ids``
    mengganti penuh sisi yang dikirim; sisi yang tidak dikirim dipertahankan).
    **DELETE** → hapus step (structural: `RoutingStep` tidak punya ``is_active``) —
    edge yang menyentuh step ikut terhapus, ``rework_target_step`` step lain di-``NULL``.

    Validasi yang sama dengan step baru (400: order duplikat, id bukan milik routing
    ini, self-reference, siklus). 404 kalau step bukan milik routing tersebut.
    Permission **ADMIN/OWNER**; menulis ``SyncRecord`` ``SKIPPED`` + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get_step(routing: ProcessRouting, step_id: int):
        """Step milik ``routing`` atau ``None`` (→ 404)."""
        return routing.steps.filter(pk=step_id).first()

    def put(self, request, pk: int, step_id: int):
        """Ubah step; lihat docstring kelas."""
        _require_admin(request)

        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        step = self._get_step(routing, step_id)
        if step is None:
            return Response({"detail": "Step tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        result = routing_services.update_step(step, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(routing_services.routing_detail_row(result.routing))

    def delete(self, request, pk: int, step_id: int):
        """Hapus step (structural); lihat docstring kelas."""
        _require_admin(request)

        routing = ProcessRouting.objects.filter(pk=pk).first()
        if routing is None:
            return Response(
                {"detail": "Routing tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        step = self._get_step(routing, step_id)
        if step is None:
            return Response({"detail": "Step tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND)

        result = routing_services.delete_step(step, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(routing_services.routing_detail_row(result.routing))


class SettingsSequencesView(APIView):
    """``GET /api/v1/settings/sequences/`` — daftar penomoran dokumen (Sprint C).

    ListPage ``{rows, total_count, has_more, next_cursor}``; baris memuat
    ``{id, code, name, prefix, year, last_seq, padding, is_active, next_number,
    created_at, updated_at}`` (``next_number`` = **pratinjau**, tidak menaikkan counter).

    Query: ``?search=`` (code/name/prefix icontains), ``?active=true|false``,
    ``?year=<tahun>`` | ``?year=all`` (**default: tahun berjalan** — reset per tahun),
    ``?limit=`` (1..200) & ``?cursor=`` (offset) mengikuti helper B22.

    Permission ``IsAuthenticated`` → anonim **403**.

    **H5.3** menambah ``POST`` — buat baris sequence ``(code, year)`` baru
    (``last_seq=0``, ``is_active=True``). Body ``{code, name, prefix?, padding?}``:
    ``code`` = ``^[A-Z0-9]{2,16}$`` (auto-upper), ``prefix`` opsional (default = ``code``)
    ``^[A-Z0-9-]{1,16}$``, ``padding`` default 4 (1..10). Izin tulis **ADMIN/OWNER**
    (``_require_admin``) → **201** + baris baru; duplikat ``(code, year)`` → **400**.
    Tidak menyentuh B26/B27 (users/roles).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List sequence; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = NumberSequence.objects.all()

        year_param = request.query_params.get("year")
        if year_param not in (None, "", "all"):
            try:
                queryset = queryset.filter(year=int(year_param))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Parameter 'year' harus berupa angka atau 'all'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif year_param in (None, ""):
            # reset per tahun → default tampilkan tahun berjalan
            queryset = queryset.filter(year=sequence_services.current_year())

        active_param = request.query_params.get("active")
        if active_param not in (None, ""):
            active = _parse_bool(active_param)
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(prefix__icontains=search)
            )

        queryset = queryset.order_by("code", "year")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([sequence_services.sequence_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat sequence baru (ADMIN/OWNER); lihat docstring kelas."""
        _require_admin(request)

        year, error = _sequence_year_param(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        result = sequence_services.create_sequence(
            request.data or {}, request=request, year=year
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            sequence_services.sequence_row(result.sequence), status=status.HTTP_201_CREATED
        )


class SettingsSequencePreviewView(APIView):
    """``GET /api/v1/settings/sequences/<code>/preview/`` — nomor berikutnya (Sprint C).

    Response: ``{code, name, prefix, year, last_seq, padding, is_active, next_number}``.
    **Read-only**: counter TIDAK dinaikkan (dipakai tombol Preview di UI).

    ``?year=<tahun>`` opsional (default tahun berjalan). Kode tidak dikenal → **404**
    (bukan 400). Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, code: str):
        """Pratinjau nomor berikutnya tanpa increment; lihat docstring kelas."""
        year, error = _sequence_year_param(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        try:
            preview = sequence_services.preview_number(code.upper(), year=year)
        except sequence_services.SequenceNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        return Response(preview)


class SettingsSequenceDetailView(APIView):
    """``PUT /api/v1/settings/sequences/<code>/`` — ubah prefix/padding/aktif/nama.

    Hanya ``name``/``prefix``/``padding``/``active`` yang boleh diubah; ``code``,
    ``year``, dan ``last_seq`` ditolak dengan **400** (counter hanya naik lewat
    ``next_number``). ``?year=<tahun>`` opsional (default tahun berjalan).

    Kode tidak dikenal (atau belum punya baris di tahun tsb) → **404**; prefix kosong
    → **400**. Sukses → baris sequence terbaru. Permission **ADMIN/OWNER**
    (``_require_admin``); menulis ``SyncRecord`` ``SKIPPED`` (MES-only) + ``AuditLog``.

    **H5.3** menambah ``DELETE`` — soft delete (``is_active=False``) → **204**
    (tanpa body; baris TIDAK dihapus dari DB). Guard pemakaian → **400**: kode seed
    terlindungi (SO/PO/WO/INV/VB/PAY/JE/ADJ/TRF) atau ``last_seq > 0``.
    ``?year=<tahun>`` opsional; kode tidak dikenal → **404**.
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, code: str):
        """Ubah sequence; lihat docstring kelas."""
        _require_admin(request)

        year, error = _sequence_year_param(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        target_year = sequence_services.current_year() if year is None else year
        sequence = NumberSequence.objects.filter(
            code=code.upper(), year=target_year
        ).first()
        if sequence is None:
            return Response(
                {
                    "detail": (
                        f"Sequence '{code.upper()}' belum ada untuk tahun {target_year} "
                        "(nomor pertama dibuat oleh next_number)."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        result = sequence_services.update_sequence(sequence, request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(sequence_services.sequence_row(result.sequence))

    def delete(self, request, code: str):
        """Nonaktifkan (soft delete) sequence; lihat docstring kelas."""
        _require_admin(request)

        year, error = _sequence_year_param(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        target_year = sequence_services.current_year() if year is None else year
        sequence = NumberSequence.objects.filter(
            code=code.upper(), year=target_year
        ).first()
        if sequence is None:
            return Response(
                {
                    "detail": (
                        f"Sequence '{code.upper()}' tidak dikenal untuk tahun {target_year}."
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        result = sequence_services.deactivate_sequence(sequence, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


def _sequence_year_param(request):
    """``(year, error)`` dari ``?year=`` (None = tahun berjalan)."""
    raw = request.query_params.get("year")
    if raw in (None, ""):
        return None, None

    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, "Parameter 'year' harus berupa angka."


class SettingsCurrenciesView(APIView):
    """``GET|POST /api/v1/settings/currencies/`` — daftar & mata uang baru (H5.2).

    ListPage ``{rows, total_count, has_more, next_cursor}``; baris memuat
    ``{id, code, name, symbol, rate, is_default, is_active, odoo_id}``
    (``odoo_id`` = penanda baris hasil pull I1).

    Query: ``?search=`` (code/name/symbol icontains), ``?active=true|false``,
    ``?limit=`` (1..200) & ``?cursor=`` (offset) mengikuti helper B22.

    **POST** → **201** + baris baru; body ``{code, name, symbol?, rate?, is_default?}``
    (``code`` = **3 huruf A-Z** auto-upper & unik; ``name`` wajib; ``symbol`` ≤8;
    ``rate`` ≥0; ``is_default=true`` menjadikannya satu-satunya default MES). Izin tulis
    **ADMIN/OWNER** (``_require_admin``); duplikat/format salah → **400**.

    **MES-only**: ledger ``SyncRecord`` ``master.currency``/``MASTER_PUSH`` ditulis
    ``SKIPPED`` (tanpa push ke Odoo) + ``AuditLog`` — jejaknya di
    ``/api/v1/sync/records/?status=SKIPPED``. Permission ``IsAuthenticated`` →
    anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List mata uang; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Currency.objects.all().order_by("code")

        active_param = request.query_params.get("active")
        if active_param not in (None, ""):
            active = _parse_bool(active_param)
            if active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=active)

        search = str(request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(code__icontains=search)
                | Q(name__icontains=search)
                | Q(symbol__icontains=search)
            )

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])

        return Response(
            _envelope([currency_services.currency_row(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat mata uang baru (ADMIN/OWNER); lihat docstring kelas."""
        _require_admin(request)

        result = currency_services.create_currency(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            currency_services.currency_row(result.currency), status=status.HTTP_201_CREATED
        )


class SettingsCurrencyDefaultView(APIView):
    """``GET /api/v1/settings/currencies/default/`` — mata uang default MES (H5.2).

    Response ``{"currency": {…}|null}``. Dipakai form/dokumen untuk mengisi mata uang
    default (urutan: penanda ``is_default`` → fallback ``IDR`` aktif → aktif pertama).
    **Read-only** — tanpa efek samping. Permission ``IsAuthenticated`` (anonim **403**).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Mata uang default MES; lihat docstring kelas."""
        currency = currency_services.get_default_currency()

        return Response(
            {
                "currency": (
                    currency_services.currency_row(currency)
                    if currency is not None
                    else None
                )
            }
        )


class SettingsCurrencyDetailView(APIView):
    """``GET|PUT|DELETE /api/v1/settings/currencies/<id>/`` — detail, ubah, nonaktifkan.

    **PUT** hanya mengubah field yang dikirim (``code``/``name``/``symbol``/``rate``/
    ``active``/``is_default``) → **200** + baris terbaru. ``code`` pada PUT hanya
    divalidasi kalau nilainya **berubah**, sehingga baris hasil pull I1 (``ODOO-<id>``)
    tetap bisa diedit tanpa 400.

    **DELETE** = **soft delete** (``is_active=False``; baris **tetap** di DB supaya
    jejak audit & mirror I1 utuh) → **200** + ``{id, is_active:false, deleted:true,
    is_default:false, sync_record_id}``. **Guard → 400**: ``is_default`` (default MES) /
    kode terlindungi (IDR/USD) / baris hasil pull Odoo (``odoo_id``) — pesannya
    menjelaskan alasannya. Id tidak ada → **404**.

    Permission tulis **ADMIN/OWNER** (``_require_admin``); setiap tulis menulis ledger
    ``SKIPPED`` (MES-only) + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _get(currency_id: int):
        """Currency atau ``None``."""
        return Currency.objects.filter(pk=currency_id).first()

    def get(self, request, currency_id: int):
        """Detail mata uang; lihat docstring kelas."""
        currency = self._get(currency_id)
        if currency is None:
            return Response(
                {"detail": f"Mata uang {currency_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(currency_services.currency_row(currency))

    def put(self, request, currency_id: int):
        """Ubah mata uang; lihat docstring kelas."""
        _require_admin(request)

        currency = self._get(currency_id)
        if currency is None:
            return Response(
                {"detail": f"Mata uang {currency_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = currency_services.update_currency(
            currency, request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(currency_services.currency_row(result.currency))

    def delete(self, request, currency_id: int):
        """Nonaktifkan (soft delete) mata uang; lihat docstring kelas."""
        _require_admin(request)

        currency = self._get(currency_id)
        if currency is None:
            return Response(
                {"detail": f"Mata uang {currency_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = currency_services.deactivate_currency(currency, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "id": currency_id,
                "is_active": False,
                "deleted": True,
                "is_default": False,
                "sync_record_id": result.sync_record_id,
            },
            status=status.HTTP_200_OK,
        )


class SettingsCurrencySetDefaultView(APIView):
    """``POST /api/v1/settings/currencies/<id>/set-default/`` — jadikan default MES.

    Atomik: seluruh baris lain di-``unset``, baris ini di-``set`` ⇒ selalu **maksimal
    satu** mata uang ``is_default=True``. ``is_default`` bukan field Odoo ⇒ operasi ini
    **tidak** mengirim apa pun ke Odoo (hanya ``AuditLog``).

    * **200** → baris mata uang terbaru; **404** id tidak ada; **400** mata uang
      nonaktif; **403** kalau bukan ADMIN/OWNER.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, currency_id: int):
        """Set mata uang default; lihat docstring kelas."""
        _require_admin(request)

        currency = Currency.objects.filter(pk=currency_id).first()
        if currency is None:
            return Response(
                {"detail": f"Mata uang {currency_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        result = currency_services.set_default_currency(currency, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(currency_services.currency_row(result.currency))


class SettingsCompanyView(APIView):
    """``GET|PUT /api/v1/settings/company/`` — profil perusahaan MES (H5.1, **singleton**).

    **GET** → ``{"company": {…}|null}`` (``null`` = belum diisi; **tanpa** seed/efek
    samping — pola ``GET /master/taxes/default/`` H3.6). Baris memuat
    ``{id, name, legal_name, address, city, country, phone, email, npwp, website,
    logo_url, currency_id, currency, timezone, is_active, created_at, updated_at}``
    (``currency`` = baris mata uang H5.2 atau ``null``).

    **PUT** → **create-on-first-PUT** (baris pertama di-update; dibuat **sekali** bila
    belum ada ⇒ 2× PUT tetap 1 baris) → **200** + ``{"company": {…}}``. Body:
    ``name`` (wajib bila belum ada baris), ``legal_name``, ``address``, ``city``,
    ``country`` (ISO 2 huruf, auto-upper), ``phone``, ``email``, ``npwp`` (15/16 digit,
    dinormalisasi digit — pola H1.6), ``website``, ``logo_url``, ``currency_id``
    (FK `master.Currency` H5.2; ``null`` = kosongkan), ``timezone``, ``active``.
    Field yang **tidak** dikirim tidak diubah. Gagal validasi → **400**.

    Permission: GET ``IsAuthenticated`` (anonim **403**); PUT **ADMIN/OWNER**
    (``_require_admin``). **MES-only**: ledger ``SyncRecord``
    ``master.company``/``MASTER_PUSH`` ditulis ``SKIPPED`` (tanpa push ke Odoo) +
    ``AuditLog`` — jejaknya di ``/api/v1/sync/records/?status=SKIPPED``.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Profil perusahaan (atau ``null``); lihat docstring kelas."""
        company = company_services.get_company()

        return Response(
            {
                "company": (
                    company_services.company_row(company) if company is not None else None
                )
            }
        )

    def put(self, request):
        """Simpan profil perusahaan; lihat docstring kelas."""
        _require_admin(request)

        result = company_services.update_company(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"company": company_services.company_row(result.company)})


class SettingsIntegrationConfigView(APIView):
    """``GET|PUT /api/v1/settings/integration/`` — profil config MES ↔ Odoo (H5.6).

    **SINGLETON** + **Opsi B** (keputusan STEP 0): baris DB menyimpan **profil config**
    (editable, ber-jejak), tetapi **konsumen tetap membaca `.env`** (8 konsumen + 113
    referensi setting di test **tidak disentuh**) ⇒ nol risiko regresi. Aktivasi =
    salin ke `.env` + ``docker compose restart django celery_worker celery_beat``.

    **GET** → ``{"config": {…}|null, "effective": {…}, "diverges": {field: {db, env}},
    "needs_restart": bool, "restart_command": str}``:

      * ``config`` = profil tersimpan (``odoo_api_key`` **selalu** di-mask ``***``);
      * ``effective`` = nilai ``.env`` yang **benar-benar aktif** sekarang;
      * ``diverges`` = field yang beda DB vs ``.env`` (field rahasia di-mask);
      * ``needs_restart`` = ``bool(diverges)``.

    **PUT** → **create-on-first-PUT** (2× PUT tetap 1 baris) → **200** + amplop yang sama.
    Field: ``erp_adapter`` (``odoo``|``null``), ``odoo_url``, ``odoo_db``, ``odoo_user``,
    ``odoo_api_key`` (``***`` = **jangan ubah**, ``""`` = hapus), ``odoo_timeout``,
    ``odoo_location_{wip,production,fg,scrap}_id``, ``odoo_uom_id``,
    ``odoo_payment_journal_id``, ``odoo_picking_type_internal_id``,
    ``reconciliation_tolerance_units``, ``reconciliation_tolerance_pct`` (rasio 0..1),
    ``reconciliation_alert_wa_to`` (array atau string dipisah koma), ``active``.
    Guard: ``erp_adapter='odoo'`` ⇒ ``odoo_url``+``odoo_db``+``odoo_user`` wajib → **400**.

    Permission: GET ``IsAuthenticated`` (anonim **403**); PUT **ADMIN/OWNER**
    (``_require_admin``). **MES-only**: ledger ``SyncRecord``
    ``master.integration_config``/``MASTER_PUSH`` ditulis ``SKIPPED`` + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _envelope(config) -> dict:
        """Amplop respons: profil + effective + divergences + needs_restart."""
        return {
            "config": (
                integration_config_services.config_row(config)
                if config is not None
                else None
            ),
            "effective": integration_config_services.effective_row(),
            "diverges": integration_config_services.divergences(config),
            "needs_restart": integration_config_services.needs_restart(config),
            "restart_command": integration_config_services.RESTART_COMMAND,
        }

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Profil config + config efektif; lihat docstring kelas."""
        return Response(self._envelope(integration_config_services.get_config()))

    def put(self, request):
        """Simpan profil config; lihat docstring kelas."""
        _require_admin(request)

        result = integration_config_services.update_config(
            request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._envelope(result.config))


class SettingsIntegrationTestConnectionView(APIView):
    """``POST /api/v1/settings/integration/test-connection/`` — uji koneksi Odoo (H5.6).

    **Read-only, tanpa efek samping**: memakai kredensial **``.env``** (bukan baris DB —
    konsisten Opsi B) + ``adapters.factory.get_adapter("odoo").health_check()`` (ping
    ``common.version``, tidak butuh login). Respons ``{ok, adapter, url, server_version,
    message}``. Kalau ``ERP_ADAPTER != 'odoo'`` atau kredensial kurang → ``ok=false`` +
    pesan jelas (**bukan** error HTTP). Permission **ADMIN/OWNER** (anonim/operator 403).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):  # noqa: ARG002 - request tak dipakai
        """Uji koneksi Odoo; lihat docstring kelas."""
        _require_admin(request)

        return Response(integration_config_services.test_connection())


class SettingsWAConfigView(APIView):
    """``GET|PUT /api/v1/settings/wa/`` — profil gateway WhatsApp (H5.8).

    **SINGLETON** + **Opsi B** (keputusan STEP 0): baris DB menyimpan **profil gateway**
    (editable, ber-jejak), tetapi **konsumen tetap membaca `.env`**
    (``integrations/wa_bot/services.get_wa_gateway`` ⇒ dipakai ``POST /api/v1/wa/send/``,
    ``tasks_reconciliation.py`` alert rekonsiliasi, dan ``ai/hitl_views.py`` alert HITL)
    ⇒ nol risiko regresi. Aktivasi = salin ke `.env` +
    ``docker compose restart django celery_worker celery_beat``.

    **GET** → ``{"config": {…}|null, "effective": {…}, "diverges": {field: {db, env}},
    "needs_restart": bool, "restart_command": str}``:

      * ``config`` = profil tersimpan (``wa_api_key`` **selalu** di-mask ``***``);
      * ``effective`` = nilai ``.env`` yang **benar-benar aktif** sekarang;
      * ``diverges`` = field yang beda DB vs ``.env`` (field rahasia di-mask);
      * ``needs_restart`` = ``bool(diverges)``.

    **PUT** → **create-on-first-PUT** (2× PUT tetap 1 baris) → **200** + amplop yang sama.
    Field: ``wa_backend`` (``mock``|``real``|``api``), ``wa_api_url``, ``wa_api_key``
    (``***`` = **jangan ubah**, ``""`` = hapus), ``active``.
    Guard: ``wa_backend`` ``real``/``api`` ⇒ ``wa_api_url``+``wa_api_key`` wajib → **400**.

    Permission: GET ``IsAuthenticated`` (anonim **403**); PUT **ADMIN/OWNER**
    (``_require_admin``). **MES-only**: ledger ``SyncRecord``
    ``master.wa_config``/``MASTER_PUSH`` ditulis ``SKIPPED`` + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _envelope(config) -> dict:
        """Amplop respons: profil + effective + divergences + needs_restart."""
        return {
            "config": (
                wa_config_services.config_row(config) if config is not None else None
            ),
            "effective": wa_config_services.effective_row(),
            "diverges": wa_config_services.divergences(config),
            "needs_restart": wa_config_services.needs_restart(config),
            "restart_command": wa_config_services.RESTART_COMMAND,
        }

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Profil gateway + gateway efektif; lihat docstring kelas."""
        return Response(self._envelope(wa_config_services.get_config()))

    def put(self, request):
        """Simpan profil gateway; lihat docstring kelas."""
        _require_admin(request)

        result = wa_config_services.update_config(request.data or {}, request=request)
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._envelope(result.config))


class SettingsWATestConnectionView(APIView):
    """``POST /api/v1/settings/wa/test-connection/`` — uji gateway WA (H5.8).

    **Read-only, tanpa mengirim pesan**: memakai ``settings.WA_BACKEND`` (nilai ``.env``
    — konsisten Opsi B) + ``integrations.wa_bot.services.get_wa_gateway().health_check()``.
    Respons ``{ok, backend, url, mock, message}``. Backend ``real``/``api`` tanpa
    ``WA_API_URL``/``WA_API_KEY`` → ``ok=false`` + daftar env yang hilang (**bukan**
    error HTTP). Permission **ADMIN/OWNER** (anonim/operator 403).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):  # noqa: ARG002 - request tak dipakai
        """Uji gateway WA; lihat docstring kelas."""
        _require_admin(request)

        return Response(wa_config_services.test_connection())


class SettingsAuditView(APIView):
    """``GET /api/v1/settings/audit/`` — daftar **AuditLog** (H5.5, READ-ONLY).

    Audit trail (Fase 6) dibaca apa adanya — endpoint ini **tidak pernah**
    menulis/mengubah/menghapus baris audit (append-only). Nomor penerima/penulis
    audit tidak disentuh sama sekali.

    **Filter** (semua opsional, kosong = dilewati):

      * ``?user_id=<id>`` — pelaku (angka ≥ 1);
      * ``?action=master.create`` (exact) atau ``?action=master.`` (**prefix** karena
        diakhiri titik) — case-insensitive;
      * ``?resource=master.product`` (alias: ``?resource_type=``) & ``?resource_id=``;
      * ``?result=OK|FAILED|CONFLICT|DENIED`` (nilai lain → **400**);
      * ``?date_from=YYYY-MM-DD`` & ``?date_to=YYYY-MM-DD`` (inklusif; tanggal-saja
        ``date_to`` = sampai akhir hari itu) — juga menerima ISO-8601;
      * ``?search=`` — username + nama depan/belakang + action + resource (substring).

    **Paginasi** offset-based seperti endpoint settings lain: ``?limit`` (1..200,
    default 50) & ``?cursor`` (offset, default 0) → bentuk ListPage
    ``{rows, total_count, has_more, next_cursor}``, urut **terbaru dulu**.

    Baris daftar: ``{id, timestamp, user_id, username, full_name, action, resource,
    resource_id, result, request_id, ip_address, metadata_preview}`` — metadata
    **hanya preview** (JSON dipotong 100 karakter) supaya daftar tetap ringan; rahasia
    di dalamnya **selalu** di-mask ``***``. Detail lengkap ada di ``/<id>/``.

    Permission **ADMIN/OWNER** (``_require_admin``) — audit trail sensitif
    (siapa mengubah apa), **berbeda** dari ``/audit/products-missing-odoo-id/`` (F9)
    yang memang untuk operator. Anonim → 403.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Daftar audit + filter; lihat docstring kelas."""
        _require_admin(request)

        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        params = request.query_params
        queryset, error = audit_services.filter_audit_logs(
            AuditLog.objects.select_related("user"),
            user_id=params.get("user_id"),
            action=params.get("action"),
            # `resource_type` = alias ramah untuk frontend; nilai sama dengan `resource`.
            resource=params.get("resource") or params.get("resource_type"),
            resource_id=params.get("resource_id"),
            result=params.get("result"),
            date_from=params.get("date_from"),
            date_to=params.get("date_to"),
            search=params.get("search"),
        )
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            audit_services.list_audit_logs(queryset, limit=limit, offset=offset)
        )


class SettingsAuditDetailView(APIView):
    """``GET /api/v1/settings/audit/<id>/`` — detail satu ``AuditLog`` (H5.5, READ-ONLY).

    Amplop ``{"audit": {…}}`` dengan baris daftar **+** ``payload``, ``metadata``
    (keduanya lengkap, tetap di-mask) dan ``user_agent``. id tidak ada → **404**.
    Permission **ADMIN/OWNER** (anonim → 403); tidak ada efek samping apa pun.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, log_id: int):  # noqa: ARG002 - request tak dipakai
        """Detail audit; lihat docstring kelas."""
        _require_admin(request)

        log = AuditLog.objects.select_related("user").filter(pk=log_id).first()
        if log is None:
            return Response(
                {"detail": "Audit log tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"audit": audit_services.audit_detail(log)})


class SettingsPrinterConfigView(APIView):
    """``GET|PUT /api/v1/settings/printer/`` — profil printer thermal (H5.7).

    **SINGLETON** + **Opsi B** (keputusan STEP 0): baris DB menyimpan **profil printer**
    (editable, ber-jejak), tetapi **konsumen tetap membaca `.env`** —
    ``integrations/printing/backends.get_backend()`` (dipakai
    ``integrations/printing/api.py``: ``PrintBundleTagView``/``PrintCouponView``) tetap
    membaca ``settings.PRINTER_*`` ⇒ nol risiko regresi. Aktivasi = salin ke `.env` +
    ``docker compose restart django celery_worker celery_beat``.

    **GET** → ``{"config": {…}|null, "effective": {…}, "diverges": {field: {db, env}},
    "needs_restart": bool, "restart_command": str}``:

      * ``config`` = profil tersimpan (**tanpa mask** — host/port/USB id bukan rahasia);
      * ``effective`` = nilai ``.env`` yang **benar-benar aktif** sekarang;
      * ``diverges`` = field yang beda DB vs ``.env``;
      * ``needs_restart`` = ``bool(diverges)``.

    **PUT** → **create-on-first-PUT** (2× PUT tetap 1 baris) → **200** + amplop yang sama.
    Field: ``printer_backend`` (``mock``|``usb``|``network``), ``printer_usb_vendor_id``,
    ``printer_usb_product_id``, ``printer_network_host``, ``printer_network_port``
    (1..65535), ``printer_mock_dir``, ``active``.
    Guard kondisional: ``usb`` ⇒ vendor+product wajib; ``network`` ⇒ host+port wajib → **400**.

    Permission: GET ``IsAuthenticated`` (anonim **403**); PUT **ADMIN/OWNER**
    (``_require_admin``). **MES-only**: ledger ``SyncRecord``
    ``master.printer_config``/``MASTER_PUSH`` ditulis ``SKIPPED`` + ``AuditLog``.
    """

    permission_classes = [IsAuthenticated]

    @staticmethod
    def _envelope(config) -> dict:
        """Amplop respons: profil + effective + divergences + needs_restart."""
        return {
            "config": (
                printer_config_services.config_row(config) if config is not None else None
            ),
            "effective": printer_config_services.effective_row(),
            "diverges": printer_config_services.divergences(config),
            "needs_restart": printer_config_services.needs_restart(config),
            "restart_command": printer_config_services.RESTART_COMMAND,
        }

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Profil printer + printer efektif; lihat docstring kelas."""
        return Response(self._envelope(printer_config_services.get_config()))

    def put(self, request):
        """Simpan profil printer; lihat docstring kelas."""
        _require_admin(request)

        result = printer_config_services.update_config(
            request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self._envelope(result.config))


class SettingsPrinterTestConnectionView(APIView):
    """``POST /api/v1/settings/printer/test-connection/`` — uji printer (H5.7).

    **Read-only, TIDAK PERNAH mencetak**: memakai nilai ``.env`` (konsisten Opsi B) +
    probe aman per backend — ``mock`` = folder mock dir bisa dibuat/dipakai;
    ``usb`` = ``ok=false`` + pesan stub (backend USB belum diimplementasi);
    ``network`` = **TCP connect** ``host:port`` (timeout 5 s) **tanpa** mengirim bytes
    ESC/POS (kirim bytes = mencetak kertas nyata). Respons ``{ok, backend, message}``.
    Permission **ADMIN/OWNER** (anonim/operator 403).
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):  # noqa: ARG002 - request tak dipakai
        """Uji printer; lihat docstring kelas."""
        _require_admin(request)

        return Response(printer_config_services.test_connection())


class SettingsPermissionsView(APIView):
    """``GET /api/v1/settings/permissions/`` — matrix izin role × resource × action (H5.4).

    **Opsi A′ (keputusan STEP 0) — profil + viewer efektif**: baris
    ``core_auth.RolePermission`` menyimpan **profil izin** yang bisa diedit dari UI,
    sedangkan **enforcement** tetap **hardcoded di kode** (``_require_admin`` 27×,
    ``OPERATOR_CODE_ROLES``, 16 daftar role frontend) ⇒ halaman ini **tidak** mengubah
    perilaku izin sampai sprint enforcement ditulis.

    Respons:

      * ``matrix`` — profil tersimpan ``{role_id: {resource: {action: bool}}}``;
      * ``effective`` — aturan yang **benar-benar berlaku** sekarang (snapshot
        ``ROLE_CAPABILITIES`` di ``core/auth/permission_services.py`` — cermin kode,
        **bukan** sumber kebenaran);
      * ``diverges`` — sel yang beda profil vs efektif
        ``{role_id: {resource: {action: {profile, effective}}}}`` (hanya yang beda);
      * ``resources``/``actions`` — daftar statis (kontrak UI, bukan auto-generate);
      * ``roles`` — ``[{id, code, label, is_active}]`` (label = ``Role.name``, B27);
      * ``banner`` — peringatan wajib bahwa profil ≠ enforcement.

    Permission ``IsAuthenticated`` (anonim **403**); **tulis** (`PUT` per role) hanya
    ADMIN/OWNER. GET tidak punya efek samping (tidak membuat baris).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Matrix profil + efektif; lihat docstring kelas."""
        return Response(permission_services.get_envelope())


class SettingsPermissionRoleView(APIView):
    """``PUT /api/v1/settings/permissions/<role_id>/`` — bulk update profil izin (H5.4).

    Body (salah satu atau keduanya):

      * ``{"updates": [{"resource": "bundles", "action": "read", "allowed": true}, …]}``;
      * ``{"matrix": {"bundles": {"read": true, "create": false}}}``.

    **Atomic**: setiap sel = satu baris ``RolePermission`` (``unique_together`` role+
    resource+action ⇒ idempotent — menyimpan nilai yang sama tidak menduplikasi baris),
    ``get_or_create``+``update`` di dalam satu transaksi. Tanpa perubahan nyata → **200**
    tanpa ledger/audit baru (pola H5.6/H5.8). Validasi: resource/aksi wajib dari daftar
    statis, ``allowed`` wajib boolean → **400**; role tidak ada → **404**.

    Respons: amplop matrix (bentuk sama dengan GET) + ``role_id`` + ``updated_count`` +
    ``sync_record_id``/``sync_status`` (``SKIPPED`` — MES-only: enforcement tidak ikut
    berubah). Permission **ADMIN/OWNER** (``_require_admin``; anonim/operator 403).
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, role_id: int):
        """Simpan profil izin satu role; lihat docstring kelas."""
        _require_admin(request)

        role_exists = Role.objects.filter(pk=role_id).exists()
        if not role_exists:
            return Response(
                {"detail": "Role tidak ditemukan."}, status=status.HTTP_404_NOT_FOUND
            )

        result = permission_services.update_role_permissions(
            role_id, request.data or {}, request=request
        )
        if result.error:
            return Response({"detail": result.error}, status=status.HTTP_400_BAD_REQUEST)

        payload = permission_services.get_envelope()

        return Response(
            {
                **payload,
                "role_id": role_id,
                "updated_count": result.updated_count,
                "sync_record_id": result.sync_record_id,
                "sync_status": result.sync_status,
            }
        )


class SettingsBundlingView(APIView):
    """``GET|POST /api/v1/settings/bundling/`` — aturan bundling (``BundlingRule``).

    **GET** → ListPage::

        {"rows": [{"id", "name", "size_matrix", "bundle_size_default",
                   "is_active", "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    **POST** → buat aturan, body ``{"name": "...", "size_matrix": {"S": 10},
    "bundle_size_default": 12}``. ``size_matrix`` wajib objek JSON (default ``{}``);
    ``bundle_size_default`` integer >= 0 (default 0). Validasi gagal → **400**.

    Permission ``IsAuthenticated`` (GET & POST) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List aturan bundling; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = BundlingRule.objects.all().order_by("name")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope([serialize_bundling(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat aturan bundling; lihat docstring kelas."""
        data = request.data or {}

        name = str(data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "Field 'name' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        size_matrix = data.get("size_matrix", {})
        if not isinstance(size_matrix, dict):
            return Response(
                {"detail": "Field 'size_matrix' harus objek JSON."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bundle_size_default = data.get("bundle_size_default", 0)
        if not _is_int(bundle_size_default) or bundle_size_default < 0:
            return Response(
                {"detail": "Field 'bundle_size_default' harus integer >= 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rule = BundlingRule.objects.create(
            name=name,
            size_matrix=size_matrix,
            bundle_size_default=bundle_size_default,
        )
        logger.info("settings.bundling: rule %s dibuat.", rule.pk)
        return Response(serialize_bundling(rule), status=status.HTTP_201_CREATED)


class SettingsLineAllocationView(APIView):
    """``GET|POST /api/v1/settings/line-allocation/`` — aturan alokasi lini.

    **GET** → ListPage (opsional ``?wc_type=``, case-insensitive)::

        {"rows": [{"id", "name", "wc_type", "line_id", "line_code", "priority",
                   "is_active", "config", "created_at", "updated_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    **POST** → buat aturan, body ``{"name": "...", "wc_type": "SEWING",
    "line_id": 1, "priority": 5, "config": {}}``. ``line_id`` harus merujuk
    ``ProductionLine`` yang ada (kalau tidak → **404**); validasi lain → **400**.

    Permission ``IsAuthenticated`` (GET & POST) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List aturan alokasi (filter ``?wc_type=``); lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = LineAllocationRule.objects.select_related("line").all()
        wc_type = str(request.query_params.get("wc_type") or "").strip()
        if wc_type:
            queryset = queryset.filter(wc_type__iexact=wc_type)
        queryset = queryset.order_by("-priority", "name")

        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(
            _envelope([serialize_allocation(row) for row in rows], total, offset)
        )

    def post(self, request):
        """Buat aturan alokasi lini; lihat docstring kelas."""
        data = request.data or {}

        name = str(data.get("name") or "").strip()
        if not name:
            return Response(
                {"detail": "Field 'name' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        wc_type = str(data.get("wc_type") or "").strip()
        if not wc_type:
            return Response(
                {"detail": "Field 'wc_type' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        line_id = data.get("line_id")
        if not _is_int(line_id):
            return Response(
                {"detail": "Field 'line_id' harus integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        line = ProductionLine.objects.filter(pk=line_id).first()
        if line is None:
            return Response(
                {"detail": f"ProductionLine {line_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        priority = data.get("priority", 0)
        if not _is_int(priority):
            return Response(
                {"detail": "Field 'priority' harus integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = data.get("config", {})
        if not isinstance(config, dict):
            return Response(
                {"detail": "Field 'config' harus objek JSON."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rule = LineAllocationRule.objects.create(
            name=name,
            wc_type=wc_type,
            line=line,
            priority=priority,
            config=config,
        )
        logger.info("settings.line-allocation: rule %s dibuat.", rule.pk)
        return Response(serialize_allocation(rule), status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# B26/B27/B28 (F5.4.1) — settings users, roles, devices
# ---------------------------------------------------------------------------

#: Kode role yang dianggap "admin" untuk endpoint tulis settings (UPPERCASE, migrasi 0002).
ADMIN_ROLE_CODES = ("ADMIN", "OWNER")

#: Panjang minimum password saat create/update user (brief B26).
MIN_PASSWORD_LENGTH = 8


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def _is_admin(user) -> bool:
    """True untuk superuser **atau** user ber-role ``ADMIN``/``OWNER``.

    ``is_superuser`` dihitung admin supaya akun hasil ``createsuperuser`` (yang
    biasanya belum punya ``role``) tetap bisa mengelola user.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    return role is not None and str(role.code).upper() in ADMIN_ROLE_CODES


def _require_admin(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan admin/owner.

    Helper lokal (keputusan F5.4.1: tidak membuat file permissions baru).
    """
    if not _is_admin(request.user):
        raise PermissionDenied(
            "Hanya user dengan role ADMIN/OWNER yang boleh mengakses resource ini."
        )


def _parse_bool(raw) -> bool | None:
    """``True``/``False`` dari bool atau string ``true/false/1/0``; selain itu ``None``."""
    if isinstance(raw, bool):
        return raw
    text = str(raw or "").strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def _resolve_role(role_code):
    """``(role, error)`` — cari ``Role`` dari kode (case-insensitive)."""
    code = str(role_code or "").strip()
    if not code:
        return None, "Field 'role_code' wajib diisi."
    role = Role.objects.filter(code__iexact=code).first()
    if role is None:
        return None, f"Role {code!r} tidak ditemukan."
    return role, None


def serialize_user(user: User) -> dict:
    """Satu ``User`` -> JSON kontrak B26.

    ``full_name`` = derived (``get_full_name()``); ``role`` = ``Role.code``
    (UPPERCASE, mis. ``OPERATOR``) atau ``None`` untuk akun teknis tanpa role.

    F6.3: ``operator_code`` ikut dikirim (kolom "Kode Operator" di halaman admin) —
    ``None`` untuk role di luar OPERATOR/QC (invariant F6.1).
    """
    return {
        "id": user.pk,
        "username": user.username,
        "email": user.email,
        "full_name": user.get_full_name(),
        "role": user.role.code if user.role_id is not None else None,
        "operator_code": user.operator_code,
        "is_active": user.is_active,
        "is_staff": user.is_staff,
        "last_login": _iso(user.last_login),
        "date_joined": _iso(user.date_joined),
    }


def serialize_role(role: Role) -> dict:
    """Satu ``Role`` -> JSON kontrak B27 (``label`` = ``Role.name``)."""
    return {
        "id": role.pk,
        "code": role.code,
        "label": role.name,
        "description": role.description,
        "is_active": role.is_active,
        "user_count": getattr(role, "user_count", 0),
    }


def serialize_device(profile: DeviceProfile) -> dict:
    """Satu ``DeviceProfile`` -> JSON kontrak B28 (katalog profil, Opsi A).

    ``device_type`` = ``DeviceProfile.code``, ``label`` = ``name``,
    ``active`` = ``is_active``, ``binding_count`` = jumlah ``DeviceBinding``.
    """
    return {
        "id": profile.pk,
        "device_type": profile.code,
        "label": profile.name,
        "description": profile.description,
        "active": profile.is_active,
        "config": profile.config or {},
        "binding_count": getattr(profile, "binding_count", 0),
    }


def _validate_user_payload(data: dict, instance: User | None):
    """Validasi body create/update user → ``(values, error)``.

    Aturan (brief B26): ``username`` & ``email`` wajib dan unik (case-insensitive),
    email harus format valid, ``password`` wajib saat create dan minimal
    ``MIN_PASSWORD_LENGTH`` karakter (saat update boleh kosong = tidak diubah),
    ``role_code`` wajib saat create (saat update boleh kosong = tidak diubah),
    ``is_active`` opsional (string ``true/false`` diterima).
    """
    if not isinstance(data, dict):
        return {}, "Body harus berupa objek JSON."

    values: dict = {}

    username = str(data.get("username") or "").strip()
    if not username:
        return {}, "Field 'username' wajib diisi."
    username_clash = User.objects.filter(username__iexact=username)
    if instance is not None:
        username_clash = username_clash.exclude(pk=instance.pk)
    if username_clash.exists():
        return {}, f"Username {username!r} sudah dipakai."
    values["username"] = username

    email = str(data.get("email") or "").strip()
    if not email:
        return {}, "Field 'email' wajib diisi."
    try:
        validate_email(email)
    except ValidationError:
        return {}, f"Email {email!r} tidak valid."
    email_clash = User.objects.filter(email__iexact=email)
    if instance is not None:
        email_clash = email_clash.exclude(pk=instance.pk)
    if email_clash.exists():
        return {}, f"Email {email!r} sudah dipakai."
    values["email"] = email

    raw_password = data.get("password")
    password = str(raw_password) if raw_password is not None else ""
    if instance is None or password:
        if len(password) < MIN_PASSWORD_LENGTH:
            return {}, f"Password minimal {MIN_PASSWORD_LENGTH} karakter."
        values["password"] = password

    if instance is None or str(data.get("role_code") or "").strip():
        role, error = _resolve_role(data.get("role_code"))
        if error:
            return {}, error
        values["role"] = role

    if data.get("is_active") is not None:
        parsed_active = _parse_bool(data.get("is_active"))
        if parsed_active is None:
            return {}, "Field 'is_active' harus boolean."
        values["is_active"] = parsed_active

    for field in ("first_name", "last_name"):
        if data.get(field) is not None:
            values[field] = str(data.get(field)).strip()

    # F6.3 (Opsi B — TANPA endpoint baru): `operator_code` diubah lewat endpoint ini.
    #   * string kosong ("") / null → MINTA kode baru; `User.save()` (F6.1) mengundi
    #     kode unik karena nilainya kosong;
    #   * nilai 4/6 digit → dipakai apa adanya (divalidasi unik & formatnya);
    #   * role di luar OPERATOR/QC ditolak (invariant F6.1: kode hanya milik keduanya).
    if data.get("operator_code") is not None:
        raw_code = str(data.get("operator_code") or "").strip()
        effective_role = values.get("role") if "role" in values else getattr(instance, "role", None)
        effective_code = str(getattr(effective_role, "code", "") or "").upper()

        if effective_code not in OPERATOR_CODE_ROLES:
            return {}, (
                "Field 'operator_code' hanya untuk role "
                f"{' atau '.join(OPERATOR_CODE_ROLES)}."
            )

        if raw_code:
            if re.fullmatch(r"\d{4}|\d{6}", raw_code) is None:
                return {}, "Field 'operator_code' harus 4 atau 6 digit angka."

            code_clash = User.objects.filter(operator_code=raw_code)
            if instance is not None:
                code_clash = code_clash.exclude(pk=instance.pk)
            if code_clash.exists():
                return {}, f"Kode operator {raw_code!r} sudah dipakai."

        values["operator_code"] = raw_code

    return values, None


class SettingsUsersView(APIView):
    """``GET|POST /api/v1/settings/users/`` — daftar & pembuatan user (F5.4.1 / B26).

    **GET** → ListPage (admin/owner saja)::

        {"rows": [{"id", "username", "email", "full_name", "role", "is_active",
                   "is_staff", "last_login", "date_joined"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?q`` (cari di username/email/first_name/last_name, icontains),
    ``?role=<kode>`` (case-insensitive), ``?is_active=true|false``, ``?limit``,
    ``?cursor`` (offset). Urut ``username``.

    **POST** → buat user lewat ``User.objects.create_user()`` (password di-hash,
    **tidak** disimpan mentah), body::

        {"username", "email", "password", "first_name"?, "last_name"?,
         "role_code", "is_active"?}

    Validasi (gagal → **400**): username & email wajib + unik (case-insensitive),
    format email, password minimal 8 karakter, ``role_code`` harus ada.
    ``full_name`` = derived (``first_name + last_name``), ``role`` = ``Role.code``
    (UPPERCASE: ``OPERATOR``/``QC``/``SUPERVISOR``/``ADMIN``/``OWNER``).

    Permission ``IsAuthenticated`` + **admin/owner** → anonim **403**, non-admin **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List user + filter; lihat docstring kelas."""
        _require_admin(request)

        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = User.objects.select_related("role").all()

        query = str(request.query_params.get("q") or "").strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(first_name__icontains=query)
                | Q(last_name__icontains=query)
            )

        role_code = str(request.query_params.get("role") or "").strip()
        if role_code:
            queryset = queryset.filter(role__code__iexact=role_code)

        if request.query_params.get("is_active") is not None:
            is_active = _parse_bool(request.query_params.get("is_active"))
            if is_active is None:
                return Response(
                    {"detail": "Parameter 'is_active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=is_active)

        queryset = queryset.order_by("username")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(_envelope([serialize_user(row) for row in rows], total, offset))

    def post(self, request):
        """Buat user baru; lihat docstring kelas."""
        _require_admin(request)

        values, error = _validate_user_payload(request.data or {}, instance=None)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        password = values.pop("password")
        user = User.objects.create_user(password=password, **values)
        logger.info("settings.users: user %s (%s) dibuat.", user.pk, user.username)
        return Response(serialize_user(user), status=status.HTTP_201_CREATED)


class SettingsUserDetailView(APIView):
    """``PUT|DELETE /api/v1/settings/users/<id>/`` — ubah & nonaktifkan user (F5.4.1 / B26).

    * **PUT** → update user; body sama seperti POST tetapi ``password`` dan
      ``role_code`` **opsional** (kosong = nilai lama dipertahankan). Password
      baru di-hash ulang (``set_password``). Response **200** + baris user.
      Sejak F6.3 (Opsi B) body boleh membawa ``operator_code``:
      ``""``/``null`` = **regenerate** kode operator (diundi backend), nilai
      4/6 digit = dipakai apa adanya; hanya sah untuk role OPERATOR/QC.
    * **DELETE** → **soft delete**: hanya ``is_active=False`` (user tidak
      dihapus supaya jejak audit & relasi tetap utuh). Response **204**.

    User tidak ditemukan → **404**. Permission sama seperti list: admin/owner.
    """

    permission_classes = [IsAuthenticated]

    def put(self, request, user_id: int):
        """Update user; lihat docstring kelas."""
        _require_admin(request)

        user = User.objects.select_related("role").filter(pk=user_id).first()
        if user is None:
            return Response(
                {"detail": f"User {user_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        values, error = _validate_user_payload(request.data or {}, instance=user)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        password = values.pop("password", None)
        for field, value in values.items():
            setattr(user, field, value)
        if password:
            user.set_password(password)
        user.save()

        logger.info("settings.users: user %s (%s) diubah.", user.pk, user.username)
        return Response(serialize_user(user), status=status.HTTP_200_OK)

    def delete(self, request, user_id: int):
        """Soft delete user (``is_active=False``); lihat docstring kelas."""
        _require_admin(request)

        user = User.objects.filter(pk=user_id).first()
        if user is None:
            return Response(
                {"detail": f"User {user_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if user.is_active:
            user.is_active = False
            user.save(update_fields=["is_active"])
        logger.info("settings.users: user %s (%s) dinonaktifkan.", user.pk, user.username)

        return Response(status=status.HTTP_204_NO_CONTENT)


class SettingsRolesView(APIView):
    """``GET /api/v1/settings/roles/`` — daftar role (F5.4.1 / B27, read-only).

    Bentuk ListPage::

        {"rows": [{"id", "code", "label", "description", "is_active", "user_count"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    * ``label`` = ``Role.name`` (model **tidak** punya kolom ``label``);
    * ``user_count`` = jumlah ``User`` yang memakai role tsb (satu query agregat);
    * ``permissions`` **tidak** ada di kontrak: hak akses app diatur di klien
      (``ROLE_APPS``) — role = data di DB, bukan enum.

    Role adalah master data (seeding migrasi ``core_auth.0002``) → **tidak** ada
    POST/PUT/DELETE (method lain → **405**).

    Permission ``IsAuthenticated`` (semua role boleh melihat daftar role) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List role + ``user_count``; lihat docstring kelas."""
        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Role.objects.annotate(user_count=Count("users")).order_by("code")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(_envelope([serialize_role(row) for row in rows], total, offset))


class SettingsDevicesView(APIView):
    """``GET /api/v1/settings/devices/`` — katalog profil perangkat (F5.4.1 / B28).

    **Bukan** binding perangkat (itu ``/api/v1/devices/me|bind|unbind``); endpoint
    ini membaca **``core_device_profile.DeviceProfile``** untuk halaman admin
    ``/settings/devices``. Bentuk ListPage::

        {"rows": [{"id", "device_type", "label", "description", "active",
                   "config", "binding_count"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Pemetaan (keputusan F5.4.1 — ``DeviceProfile`` tidak punya field tsb):

    * ``device_type`` = ``DeviceProfile.code`` (``OPERATOR_HP``/``KIOSK_TABLET``/
      ``SCANNER_USB``/``DESKTOP``);
    * ``label`` = ``DeviceProfile.name``; ``active`` = ``DeviceProfile.is_active``;
    * ``binding_count`` = jumlah ``DeviceBinding`` yang memakai profil ini (aditif,
      monitoring);
    * ``wc_code`` & ``last_seen_at`` **tidak** ada di baris (milik ``DeviceBinding``,
      bukan profil). ``?wc_code=`` tetap diterima sebagai **filter bantu**
      (profil yang punya ≥1 binding di WC tsb).

    Query: ``?device_type=`` (case-insensitive), ``?wc_code=``, ``?active=true|false``,
    ``?limit``, ``?cursor``. Urut ``code``.

    Permission ``IsAuthenticated`` + **admin/owner** → anonim **403**, non-admin **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """List profil device (katalog) + ``binding_count``; lihat docstring kelas."""
        _require_admin(request)

        limit, offset, error = _list_params(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = DeviceProfile.objects.annotate(binding_count=Count("bindings"))

        device_type = str(request.query_params.get("device_type") or "").strip()
        if device_type:
            queryset = queryset.filter(code__iexact=device_type)

        wc_code = str(request.query_params.get("wc_code") or "").strip()
        if wc_code:
            queryset = queryset.filter(
                pk__in=DeviceBinding.objects.filter(
                    wc_code__iexact=wc_code
                ).values("device_profile_id")
            )

        if request.query_params.get("active") is not None:
            is_active = _parse_bool(request.query_params.get("active"))
            if is_active is None:
                return Response(
                    {"detail": "Parameter 'active' harus true|false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(is_active=is_active)

        queryset = queryset.order_by("code")
        total = queryset.count()
        rows = list(queryset[offset : offset + limit])
        return Response(_envelope([serialize_device(row) for row in rows], total, offset))




