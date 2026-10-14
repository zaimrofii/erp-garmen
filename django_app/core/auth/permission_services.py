"""Service **Permission Matrix** (H5.4) — profil izin role × resource × action.

**Keputusan STEP 0 (Opsi A′ — "matrix tersimpan + viewer efektif")**:

  * baris ``core_auth.RolePermission`` menyimpan **profil izin** yang bisa diedit dari
    UI Settings (ber-jejak ledger ``SyncRecord`` ``core_auth.role_permission``/
    ``MASTER_PUSH`` ber-status **``SKIPPED``** + ``AuditLog``);
  * ⚠️ **enforcement TIDAK dibaca dari sini** — penjaga yang benar-benar berlaku tetap
    **hardcoded di kode** (``_require_admin`` 27×, ``OPERATOR_CODE_ROLES``, dan 16
    daftar role di ``frontend_app_v2/src/App.tsx``). Karena itu endpoint mengembalikan
    DUA kolom: ``matrix`` (profil tersimpan) dan ``effective`` (:data:`ROLE_CAPABILITIES`
    — **snapshot cermin kode**, BUKAN sumber kebenaran) + ``diverges`` (sel yang beda) +
    ``banner`` (peringatan jujur "profil ≠ enforcement").
  * **non-breaking total**: tidak ada konsumen kode yang membaca tabel ini; sprint
    *enforcement* terpisah yang nanti menghubungkannya ke guard.

Daftar resource/action **statis** (:data:`RESOURCES` / :data:`ACTIONS`) — sengaja tidak
di-generate otomatis supaya kontrak UI stabil dan perubahan harus disengaja.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction

from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .models import Role, RolePermission

logger = logging.getLogger(__name__)

__all__ = (
    "ACTIONS",
    "BANNER",
    "CONFIG_RESOURCE",
    "Capabilities",
    "MES_ONLY_REASON",
    "RESOURCES",
    "ROLE_CAPABILITIES",
    "PermissionWriteResult",
    "divergences",
    "effective_matrix",
    "envelope",
    "parse_updates",
    "profile_matrix",
    "role_rows",
    "update_role_permissions",
)

#: Kunci sync matrix izin (jangan diganti string literal di view).
CONFIG_RESOURCE = SyncResource.ROLE_PERMISSION_MATRIX.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: profil izin hanya disimpan di MES (Opsi A′) — enforcement TETAP "
    "hardcoded di kode (`_require_admin`, `OPERATOR_CODE_ROLES`, daftar role frontend); "
    "ledger ditulis SKIPPED sampai sprint enforcement menghubungkan matrix ke guard."
)

#: Peringatan wajib yang dikirim ke UI (halaman menampilkannya apa adanya).
BANNER = (
    "⚠️ Perubahan di halaman ini disimpan sebagai PROFIL (audit trail). Enforcement "
    "belum berubah — backend masih memakai guard hardcoded (_require_admin, "
    "OPERATOR_CODE_ROLES, daftar role frontend). Sprint enforcement terpisah akan "
    "menghubungkan matrix ini ke guard."
)

#: Resource MES yang dipetakan di matrix (statis; turunan namespace URL existing).
RESOURCES: tuple[str, ...] = (
    "bundles",
    "dashboard",
    "finance",
    "inventory",
    "master",
    "orders",
    "permissions",
    "purchases",
    "qc",
    "reports",
    "settings",
    "sync",
    "work-orders",
)

#: Aksi CRUD yang dipetakan (statis).
ACTIONS: tuple[str, ...] = ("read", "create", "update", "delete")

# --- himpunan role (cermin daftar di kode) ---------------------------------
#: Semua role seeding (core_auth.0002 + 0004).
ALL_ROLES = ("ADMIN", "INVENTORY", "OPERATOR", "OWNER", "PURCHASING", "QC", "SUPERVISOR")
#: ``_is_admin``/``_require_admin`` (backend guard tulis Settings) + SETTINGS_ROLES frontend.
ADMIN_ONLY = ("ADMIN",)
ADMIN_OWNER = ("ADMIN", "OWNER")
#: ``App.tsx``: REPORTS_ROLES = ['supervisor','admin','owner'].
REPORTING_ROLES = ("SUPERVISOR", "ADMIN", "OWNER")
#: ``App.tsx``: PRODUCTION_ROLES = ['operator','supervisor','owner'].
PRODUCTION_ROLES = ("OPERATOR", "SUPERVISOR", "OWNER")
#: ``App.tsx``: QUALITY_ROLES = ['qc','supervisor','admin','owner'].
QUALITY_ROLES = ("QC", "SUPERVISOR", "ADMIN", "OWNER")
#: ``App.tsx``: QC_ROLES = ['qc','supervisor','operator','owner'].
QC_INPUT_ROLES = ("QC", "SUPERVISOR", "OPERATOR", "OWNER")
#: ``App.tsx``: INVENTORY_ROLES = ['inventory','admin','owner'].
INVENTORY_ROLES = ("INVENTORY", "ADMIN", "OWNER")
#: ``App.tsx``: PURCHASING_ROLES = ['purchasing','admin','owner'] (input master H1 + PO H2.2).
PURCHASING_ROLES = ("PURCHASING", "ADMIN", "OWNER")
#: ``App.tsx``: FINANCE_ROLES = ['admin','owner'].
FINANCE_ROLES = ("ADMIN", "OWNER")
#: ``App.tsx``: BUFFER_QUEUE/ROUTING/READINESS_ROLES = ['supervisor','owner'].
SUPERVISOR_OWNER = ("SUPERVISOR", "OWNER")

#: Tipe kemampuan: ``{resource: {action: (kode role yang BOLEH)}}``.
Capabilities = dict[str, dict[str, tuple[str, ...]]]

#: **Snapshot** aturan izin yang berlaku hari ini (cermin guard kode — BUKAN sumber
#: kebenaran; kalau guard berubah, snapshot ini di-update manual bersama sprint-nya).
ROLE_CAPABILITIES: Capabilities = {
    "bundles": {
        "read": ("ADMIN", *PRODUCTION_ROLES),
        "create": ("ADMIN", *SUPERVISOR_OWNER),
        "update": ("ADMIN", *PRODUCTION_ROLES),
        "delete": ADMIN_OWNER,
    },
    "dashboard": {
        # Dashboard terbuka untuk semua role yang login (tidak ada route guard khusus).
        "read": ALL_ROLES,
        "create": (),
        "update": (),
        "delete": (),
    },
    "finance": {
        # FINANCE_ROLES + endpoint invoice/payment/journal (H3.x) = ADMIN/OWNER.
        "read": FINANCE_ROLES,
        "create": FINANCE_ROLES,
        "update": FINANCE_ROLES,
        "delete": ADMIN_OWNER,
    },
    "inventory": {
        # INVENTORY_ROLES (H2.5/H2.6) + BUFFER_QUEUE_ROLES untuk baca antrean.
        "read": ("INVENTORY", "SUPERVISOR", "ADMIN", "OWNER"),
        "create": INVENTORY_ROLES,
        "update": INVENTORY_ROLES,
        "delete": ADMIN_OWNER,
    },
    "master": {
        # H1.1–H1.9: master diinput MES oleh PURCHASING/ADMIN/OWNER.
        "read": PURCHASING_ROLES,
        "create": PURCHASING_ROLES,
        "update": PURCHASING_ROLES,
        "delete": ADMIN_OWNER,
    },
    "orders": {
        # SALES_ROLES (App.tsx = ['admin','owner']) + SUPERVISOR baca progress.
        "read": ("SUPERVISOR", "ADMIN", "OWNER"),
        "create": ADMIN_OWNER,
        "update": ADMIN_OWNER,
        "delete": ADMIN_OWNER,
    },
    "permissions": {
        # H5.4: baca matrix = ADMIN (SETTINGS_ROLES); tulis bulk = _require_admin.
        "read": ADMIN_ONLY,
        "create": ADMIN_OWNER,
        "update": ADMIN_OWNER,
        "delete": ADMIN_OWNER,
    },
    "purchases": {
        "read": ("PURCHASING", "SUPERVISOR", "ADMIN", "OWNER"),
        "create": PURCHASING_ROLES,
        "update": PURCHASING_ROLES,
        "delete": ADMIN_OWNER,
    },
    "qc": {
        "read": QC_INPUT_ROLES,
        "create": QUALITY_ROLES,
        "update": QUALITY_ROLES,
        "delete": ADMIN_OWNER,
    },
    "reports": {
        "read": REPORTING_ROLES,
        "create": (),
        "update": (),
        "delete": (),
    },
    "settings": {
        "read": ADMIN_ONLY,
        "create": ADMIN_OWNER,
        "update": ADMIN_OWNER,
        "delete": ADMIN_OWNER,
    },
    "sync": {
        # F15 monitoring sync + /sync/* (pelaku sync = ADMIN/OWNER, baca = supervisor+).
        "read": ("SUPERVISOR", "ADMIN", "OWNER"),
        "create": ADMIN_OWNER,
        "update": ADMIN_OWNER,
        "delete": (),
    },
    "work-orders": {
        "read": ("ADMIN", *PRODUCTION_ROLES),
        "create": ("ADMIN", *SUPERVISOR_OWNER),
        "update": ("ADMIN", *PRODUCTION_ROLES),
        "delete": ADMIN_OWNER,
    },
}


@dataclass
class PermissionWriteResult:
    """Hasil satu operasi tulis profil izin (dipakai view)."""

    role: Role | None = None
    updated_count: int = 0
    error: str | None = None
    sync_record_id: int | None = None
    updates: list[dict] = field(default_factory=list)

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


#: Aksi audit lokal (hindari impor lintas-app ke `master.services`).
ACTION_UPDATE = "core_auth.permission.update"


# ---------------------------------------------------------------------------
# Baris response: profil (DB) + effective (snapshot kode) + divergences
# ---------------------------------------------------------------------------
def _empty_cell() -> dict:
    """Sel matrix kosong: ``{resource: {action: False}}`` (semua resource/action)."""
    return {resource: {action: False for action in ACTIONS} for resource in RESOURCES}


def role_rows(roles) -> list[dict]:
    """Baris role untuk UI: ``{id, code, label, is_active}`` (label = ``Role.name``)."""
    return [
        {
            "id": role.pk,
            "code": role.code,
            "label": role.name,
            "is_active": bool(role.is_active),
        }
        for role in roles
    ]


def profile_matrix(roles, rows) -> dict:
    """Profil tersimpan → ``{role_id: {resource: {action: bool}}}`` (tanpa baris = False).

    Resource/action di luar daftar statis **diabaikan** (tidak bisa dibuat lewat API),
    jadi bentuk matrix dijamin persis ``RESOURCES`` × ``ACTIONS`` untuk setiap role.
    """
    matrix = {str(role.pk): _empty_cell() for role in roles}

    for row in rows:
        key = str(row.role_id)
        if key not in matrix:
            continue
        if row.resource in RESOURCES and row.action in ACTIONS:
            matrix[key][row.resource][row.action] = bool(row.allowed)

    return matrix


def effective_matrix(roles) -> dict:
    """Aturan yang **benar-benar berlaku** sekarang (snapshot ``ROLE_CAPABILITIES``).

    Snapshot di-keyed **resource → action → kode role**; di sini dibalik menjadi
    ``{role_id: {resource: {action: bool}}}`` supaya bentuknya sama dengan ``matrix``
    (profil). Role yang belum ada di snapshot (mis. role baru buatan admin) → semua
    ``False`` (konservatif: belum ada guard yang mengenalnya).
    """
    matrix: dict = {}

    for role in roles:
        code = str(role.code or "").strip().upper()
        cell: dict = {}

        for resource in RESOURCES:
            allowed_roles = ROLE_CAPABILITIES.get(resource, {})
            cell[resource] = {
                action: code in allowed_roles.get(action, ()) for action in ACTIONS
            }

        matrix[str(role.pk)] = cell

    return matrix


def divergences(profile: dict, effective: dict) -> dict:
    """Sel yang **beda** profil vs efektif — ``{role_id: {resource: {action: {profile, effective}}}}``."""
    found: dict = {}

    for role_key, cell in profile.items():
        role_diff: dict = {}

        for resource, actions in cell.items():
            action_diff: dict = {}

            for action, allowed in actions.items():
                other = bool(effective.get(role_key, {}).get(resource, {}).get(action, False))
                if bool(allowed) != other:
                    action_diff[action] = {"profile": bool(allowed), "effective": other}

            if action_diff:
                role_diff[resource] = action_diff

        if role_diff:
            found[role_key] = role_diff

    return found


def envelope(roles, rows) -> dict:
    """Amplop GET/PUT matrix: profil + efektif + divergensi + daftar + banner."""
    profile = profile_matrix(roles, rows)
    effective = effective_matrix(roles)

    return {
        "matrix": profile,
        "effective": effective,
        "diverges": divergences(profile, effective),
        "resources": list(RESOURCES),
        "actions": list(ACTIONS),
        "roles": role_rows(roles),
        "banner": BANNER,
    }


def get_envelope() -> dict:
    """Amplop matrix lengkap dari DB (read-only, tanpa efek samping)."""
    roles = list(Role.objects.order_by("code"))
    rows = list(RolePermission.objects.all())

    return envelope(roles, rows)


# ---------------------------------------------------------------------------
# Ledger (SKIPPED) + audit — pola H5.1/H5.2/H5.6/H5.7/H5.8
# ---------------------------------------------------------------------------
def _payload(role: Role, updates: list[dict]) -> dict:
    """Payload ledger/audit: role + daftar sel yang diubah (ringkas, JSON-safe)."""
    return {
        "role_id": role.pk,
        "role_code": role.code,
        "updates": [
            {
                "resource": item["resource"],
                "action": item["action"],
                "allowed": bool(item["allowed"]),
            }
            for item in updates
        ],
    }


def _record_mes_only(role: Role, updates: list[dict]) -> int:
    """Tulis/segarkan ``SyncRecord`` matrix izin lalu tandai ``SKIPPED``."""
    payload = _payload(role, updates)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(CONFIG_RESOURCE, role.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(
    role: Role,
    updates: list[dict],
    request,
    *,
    created: int,
    updated: int,
) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=ACTION_UPDATE,
            resource=CONFIG_RESOURCE,
            resource_id=role.pk,
            request=request,
            payload=_payload(role, updates),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, "created": created, "updated": updated},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD
        logger.exception(
            "core_auth.permission_matrix: gagal menulis audit (role %s).", role.pk
        )


# ---------------------------------------------------------------------------
# Validasi + tulis (bulk per role, atomic)
# ---------------------------------------------------------------------------
def _parse_bool(value):
    """``(bool|None, error)`` untuk nilai boolean murni (bukan string)."""
    if isinstance(value, bool):
        return value, None

    return None, "harus true|false"


def parse_updates(data):
    """``(updates, error)`` dari body PUT → daftar ``{resource, action, allowed}``.

    Dua bentuk diterima (boleh digabung):

      * ``{"updates": [{"resource": "bundles", "action": "read", "allowed": true}, …]}``;
      * ``{"matrix": {"bundles": {"read": true, "create": false}}}``.

    Validasi: resource/action wajib dari daftar statis; ``allowed`` wajib boolean;
    duplikat (resource, action) diambil yang **pertama**; tanpa entri → error.
    """
    payload = data if isinstance(data, dict) else {}
    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()

    raw_updates = payload.get("updates")
    if raw_updates is not None:
        if not isinstance(raw_updates, list):
            return None, "Field 'updates' harus berupa daftar objek."
        for index, item in enumerate(raw_updates):
            if not isinstance(item, dict):
                return None, f"Item 'updates[{index}]' harus berupa objek."
            resource = str(item.get("resource") or "").strip()
            action = str(item.get("action") or "").strip().lower()
            if resource not in RESOURCES:
                return None, f"Resource {resource!r} tidak dikenal (lihat 'resources')."
            if action not in ACTIONS:
                return None, f"Aksi {action!r} tidak dikenal (lihat 'actions')."
            allowed, error = _parse_bool(item.get("allowed"))
            if error:
                return None, f"Field 'allowed' pada updates[{index}] {error}."
            key = (resource, action)
            if key in seen:
                continue
            seen.add(key)
            entries.append({"resource": resource, "action": action, "allowed": allowed})

    raw_matrix = payload.get("matrix")
    if raw_matrix is not None:
        if not isinstance(raw_matrix, dict):
            return None, "Field 'matrix' harus objek {resource: {action: bool}}."
        for resource, actions in raw_matrix.items():
            if resource not in RESOURCES:
                return None, f"Resource {resource!r} tidak dikenal (lihat 'resources')."
            if not isinstance(actions, dict):
                return None, f"Nilai matrix[{resource!r}] harus objek {{action: bool}}."
            for action, value in actions.items():
                key_action = str(action).strip().lower()
                if key_action not in ACTIONS:
                    return None, f"Aksi {action!r} tidak dikenal (lihat 'actions')."
                allowed, error = _parse_bool(value)
                if error:
                    return None, f"matrix[{resource!r}][{action!r}] {error}."
                key = (resource, key_action)
                if key in seen:
                    continue
                seen.add(key)
                entries.append(
                    {"resource": resource, "action": key_action, "allowed": allowed}
                )

    if not entries:
        return None, (
            "Tidak ada perubahan: kirim 'updates' (daftar) atau 'matrix' "
            "(objek {resource: {action: bool}})."
        )

    return entries, None


def update_role_permissions(role_id, data, request=None) -> PermissionWriteResult:
    """PUT profil izin satu role — bulk **atomic** + ledger ``SKIPPED`` + audit.

    Setiap sel = satu baris ``RolePermission`` (``unique_together`` ⇒ idempotent):
    sel baru dibuat, sel yang berubah di-update, sel yang nilainya sama tidak disentuh.
    Kalau **tidak ada** perubahan nyata → tidak ada ledger/audit baru (pola H5.6/H5.8).
    """
    role = Role.objects.filter(pk=role_id).first()
    if role is None:
        return PermissionWriteResult(error="Role tidak ditemukan.")

    updates, error = parse_updates(data)
    if error:
        return PermissionWriteResult(role=role, error=error)

    created = 0
    updated = 0

    with transaction.atomic():
        for item in updates:
            row, was_created = RolePermission.objects.get_or_create(
                role=role,
                resource=item["resource"],
                action=item["action"],
                defaults={"allowed": item["allowed"]},
            )
            if was_created:
                created += 1
            elif bool(row.allowed) != bool(item["allowed"]):
                row.allowed = bool(item["allowed"])
                row.save(update_fields=("allowed", "updated_at"))
                updated += 1

    if created == 0 and updated == 0:
        # Tidak ada perubahan -> tidak ada audit/ledger (idempotent PUT).
        return PermissionWriteResult(role=role, updates=updates)

    record_id = _record_mes_only(role, updates)
    _audit(role, updates, request, created=created, updated=updated)

    logger.info(
        "core_auth.permission_matrix: role %s diperbarui (%s baru, %s berubah, ledger=%s).",
        role.code,
        created,
        updated,
        record_id,
    )

    return PermissionWriteResult(
        role=role,
        updated_count=created + updated,
        sync_record_id=record_id,
        updates=updates,
    )




