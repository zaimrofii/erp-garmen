"""Service Kanban MES (FASE K2) — kolom + kartu + transisi dari `core.state_machine`.

Semua definisi kolom & aksi = **DATA** di `core.state_machine` (`State`,
`Transition`), bukan enum Python: menambah/mengubah kolom kanban cukup lewat baris
DB (admin/migration) — service ini tidak menyimpan daftar state apa pun.

Kenapa endpoint baru? Endpoint list generik (`GET /api/v1/garmen/bundles/`) hanya
bisa menyaring **satu** `state` per panggilan, sehingga papan kanban butuh N request
per refresh (satu per kolom). Endpoint kanban mengembalikan SEMUA kolom + kartunya
dalam **satu** response.

Bentuk response::

    {
      "resource": "bundles",
      "industry": "garmen",
      "machine": "garment.bundle",
      "columns": [
        {"state": "DRAFT", "label": "Draft", "order": 10, "count": 12,
         "cards": [{id, code, work_order_code, size, qty, state, allowed_actions}],
         "truncated": false}
      ],
      "transitions": [
        {"from": "DRAFT", "to": "CUTTING", "action_id": "BUNDLE_START",
         "label": "Mulai Bundle"}
      ],
      "total_count": 12,    # kartu setelah filter (semua kolom yang tampil)
      "limit": 50,          # batas kartu PER KOLOM
      "truncated": false,   # ada kolom yang kartunya terpotong `limit`
      "unknown_states": {}, # state di luar definisi mesin (tidak disembunyikan)
      "filters": {"applied": {...}, "ignored": [...]}
    }

`allowed_actions[]` tiap kartu memakai bentuk yang SAMA dengan endpoint list
(`serialize_bundle`) dan metadata (`build_state_machine_payload`):
`[{id, label, mode, endpoint}]` — di sini dirakit sekali dari tabel `Transition`
yang sudah dibaca (bukan query per kartu), jadi tombol aksi di kartu kanban
otomatis sinkron dengan state machine.

Kartu WorkOrder memakai kunci yang **sama** dengan kartu Bundle supaya frontend
memakai satu komponen: `work_order_code` = kode WO itu sendiri, `size` = `None`
(WorkOrder tidak punya ukuran), `qty` = `qty_planned`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Count, QuerySet

from apps_industry.garment.api.schema.builder import action_endpoint_payload
from core.state_machine.models import StateMachine, Transition

from ..models import Bundle, WorkOrder

logger = logging.getLogger(__name__)

__all__ = (
    "DEFAULT_LIMIT_PER_COLUMN",
    "MAX_LIMIT_PER_COLUMN",
    "MACHINE_CODES",
    "KanbanMachineNotFound",
    "UnknownKanbanResource",
    "apply_kanban_filters",
    "build_kanban_response",
    "get_kanban_actions",
    "get_kanban_columns",
    "get_kanban_queryset",
    "get_kanban_transitions",
    "get_state_machine_for_resource",
    "normalize_resource",
    "unknown_state_counts",
)

#: resource (segment URL) -> kode `StateMachine` di DB (`Transition.action_id`
#: juga dipakai apa adanya oleh `ActionView`).
MACHINE_CODES: dict[str, str] = {
    "bundles": "garment.bundle",
    "work-orders": "garment.work_order",
}

#: Batas kartu PER KOLOM (selaras `list_view.DEFAULT_LIMIT`/`MAX_LIMIT`).
DEFAULT_LIMIT_PER_COLUMN = 50
MAX_LIMIT_PER_COLUMN = 200

#: Filter tambahan yang hanya berlaku untuk resource yang punya FK-nya.
_FILTER_FIELDS: dict[str, dict[str, str]] = {
    "bundles": {
        "work_center_id": "current_work_center_id",
        "line_id": "production_line_id",
        "work_order_id": "work_order_id",
    },
    "work-orders": {},
}


class UnknownKanbanResource(ValidationError):
    """Resource kanban tidak dikenal (bukan `bundles`/`work-orders`) -> 404."""


class KanbanMachineNotFound(ValidationError):
    """Resource dikenal tetapi `StateMachine`-nya belum di-seed/tidak aktif -> 404."""


def _int_or_none(value: Any) -> int | None:
    """PURE — angka dari query param; `None` kalau kosong/bukan angka."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def normalize_resource(resource: str | None) -> str | None:
    """PURE — nama resource kanonik (lowercase) kalau dikenal; `None` kalau tidak."""
    if not resource:
        return None

    candidate = str(resource).strip().lower()
    return candidate if candidate in MACHINE_CODES else None


# ------------------------------------------------------------------ state machine
def get_state_machine_for_resource(resource: str) -> StateMachine:
    """`StateMachine` aktif untuk resource kanban (bundle/WO).

    Raises:
        UnknownKanbanResource: resource di luar `MACHINE_CODES` (-> 404).
        KanbanMachineNotFound: baris mesin belum ada / `is_active=False` (-> 404).
    """
    code = MACHINE_CODES.get(normalize_resource(resource) or "")
    if code is None:
        raise UnknownKanbanResource(f"Resource kanban '{resource}' tidak dikenal.")

    machine = StateMachine.objects.filter(code=code, is_active=True).first()
    if machine is None:
        raise KanbanMachineNotFound(
            f"State machine '{code}' untuk resource '{resource}' belum tersedia."
        )

    return machine


def get_kanban_queryset(resource: str) -> QuerySet:
    """Queryset dasar kanban + `select_related` supaya kartu tidak N+1."""
    normalized = normalize_resource(resource)
    if normalized == "bundles":
        return Bundle.objects.select_related(
            "work_order", "current_work_center", "production_line"
        )

    if normalized == "work-orders":
        return WorkOrder.objects.select_related("order_line")

    raise UnknownKanbanResource(f"Resource kanban '{resource}' tidak dikenal.")


def get_kanban_transitions(machine: StateMachine) -> list[dict]:
    """Semua transisi **aktif** mesin sebagai `{from, to, action_id, label}`.

    Urutan: `from_state.order` lalu `action_id` (stabil untuk render panah/legenda
    di frontend). Definisi diambil dari `Transition` (data), bukan dari kode.
    """
    rows = (
        Transition.objects.filter(machine=machine, is_active=True)
        .select_related("from_state", "to_state")
        .order_by("from_state__order", "action_id")
    )
    return [
        {
            "from": transition.from_state.code,
            "to": transition.to_state.code,
            "action_id": transition.action_id,
            "label": transition.label or transition.action_id,
        }
        for transition in rows
    ]


def get_kanban_actions(machine: StateMachine) -> dict[str, list[dict]]:
    """Peta `state.code -> [{id, label, mode}]` dari `Transition` aktif (1 query).

    Bentuk item sengaja identik dengan `build_state_machine_payload()`
    (`mode` lowercase, label fallback ke `action_id`); key `endpoint` ditambahkan
    per kartu oleh `_allowed_actions_for()` karena butuh id instance.
    """
    allowed: dict[str, list[dict]] = {}
    rows = (
        Transition.objects.filter(machine=machine, is_active=True)
        .select_related("from_state", "to_state")
        .order_by("action_id")
    )
    for transition in rows:
        allowed.setdefault(transition.from_state.code, []).append(
            {
                "id": transition.action_id,
                "label": transition.label or transition.action_id,
                "mode": str(transition.mode).lower(),
            }
        )

    return allowed


# -------------------------------------------------------------------------- filter
def apply_kanban_filters(
    resource: str, queryset: QuerySet, params: Mapping
) -> tuple[QuerySet, dict]:
    """Saring queryset: `?search=`, `?state=`, `?work_center_id=`, `?line_id=`, `?work_order_id=`.

    Return `(queryset, info)` — `info` melaporkan filter yang **dipakai** dan yang
    **diabaikan** (mis. `work_center_id` pada WorkOrder yang tidak punya FK itu)
    supaya frontend/QA tahu param tidak berlaku, bukan diam-diam dibuang.

    Nilai id bukan angka diperlakukan seperti "tidak ada yang cocok" (`none()`),
    konsisten dengan `BundleListCreateView._apply_filters`.
    """
    normalized = normalize_resource(resource) or str(resource)
    applied: dict[str, Any] = {}
    ignored: list[str] = []

    search = str(params.get("search") or "").strip()
    if search:
        queryset = queryset.filter(code__icontains=search)
        applied["search"] = search

    state = str(params.get("state") or "").strip()
    if state:
        queryset = queryset.filter(state__iexact=state)
        applied["state"] = state

    for param, field in _FILTER_FIELDS.get(normalized, {}).items():
        raw = params.get(param)
        if raw in (None, ""):
            continue

        parsed = _int_or_none(raw)
        if parsed is None:
            logger.info(
                "kanban %s: param '%s' bukan angka -> hasil kosong.", normalized, param
            )
            queryset = queryset.none()
            applied[param] = str(raw)
            continue

        queryset = queryset.filter(**{field: parsed})
        applied[param] = parsed

    for param in ("work_center_id", "line_id", "work_order_id"):
        if params.get(param) not in (None, "") and param not in applied:
            ignored.append(param)

    return queryset, {"applied": applied, "ignored": ignored}


# --------------------------------------------------------------------------- kartu
def _allowed_actions_for(
    instance, resource: str, industry: str, actions_by_state: dict
) -> list[dict]:
    """Aksi yang boleh dijalankan dari state instance (bentuk sama dgn list/metadata).

    Diambil dari peta hasil `get_kanban_actions()` (satu query untuk seluruh mesin)
    supaya tidak ada query per kartu; `endpoint` = prefix aksi kontrak §2/B.1.5
    (`/<industry>/<resource>/<id>/<ACTION_ID>/`, relatif `VITE_API_BASE_URL`).
    """
    actions = actions_by_state.get(instance.state, ())
    if not actions:
        return []

    prefix = f"/{industry}/{resource}/{instance.pk}/"
    payload: list[dict] = []
    for action in actions:
        item = dict(action)
        endpoint = action_endpoint_payload(prefix, str(action["id"]))
        if endpoint is not None:
            item["endpoint"] = endpoint
        payload.append(item)

    return payload


def _card_payload(
    instance, resource: str, industry: str, actions_by_state: dict
) -> dict:
    """Kartu kanban kontrak FASE K2 (kunci sama untuk bundle & work order)."""
    is_bundle = resource == "bundles"
    work_order_code = (
        instance.work_order.code
        if is_bundle and instance.work_order_id
        else instance.code
    )

    return {
        "id": instance.pk,
        "code": instance.code,
        "work_order_code": work_order_code,
        "size": instance.size if is_bundle else None,
        "qty": instance.qty if is_bundle else instance.qty_planned,
        "state": instance.state,
        "allowed_actions": _allowed_actions_for(
            instance, resource, industry, actions_by_state
        ),
    }


def get_kanban_columns(
    machine: StateMachine,
    queryset: QuerySet,
    *,
    resource: str = "bundles",
    industry: str = "garmen",
    limit: int = DEFAULT_LIMIT_PER_COLUMN,
    actions_by_state: dict | None = None,
) -> list[dict]:
    """Kolom kanban dari `State` (urut `order`, `code`) + kartu tiap state.

    `count` = jumlah SELURUH baris state itu (setelah filter); `cards` dipotong
    `limit` per kolom dan `truncated` menandai pemotongan tersebut.
    """
    if actions_by_state is None:
        actions_by_state = get_kanban_actions(machine)

    counts = dict(queryset.values_list("state").annotate(total=Count("pk")))

    columns: list[dict] = []
    for state in machine.states.order_by("order", "code"):
        total = int(counts.get(state.code, 0))
        cards = (
            [
                _card_payload(instance, resource, industry, actions_by_state)
                for instance in queryset.filter(state=state.code).order_by("code")[
                    :limit
                ]
            ]
            if total
            else []
        )
        columns.append(
            {
                "state": state.code,
                "label": state.label or state.code,
                "order": state.order,
                "count": total,
                "cards": cards,
                "truncated": total > len(cards),
            }
        )

    return columns


def unknown_state_counts(machine: StateMachine, queryset: QuerySet) -> dict:
    """Jumlah baris per state yang **tidak** ada di definisi mesin.

    State liar (mis. hasil import lama) tidak dibuatkan kolom kanban, tetapi tetap
    dilaporkan di response supaya tidak ada data yang senyap hilang dari layar.
    """
    known = {state.code for state in machine.states.all()}
    counts = queryset.values_list("state").annotate(total=Count("pk"))
    return {state: int(total) for state, total in counts if state not in known}


# ----------------------------------------------------------------------- perakitan
def _filter_report(resource: str, params: Mapping) -> dict:
    """Laporan filter TANPA menyentuh queryset (dipakai `build_kanban_response`)."""
    normalized = normalize_resource(resource) or str(resource)
    applied: dict[str, Any] = {}

    for param in ("search", "state"):
        value = str(params.get(param) or "").strip()
        if value:
            applied[param] = value

    for param in _FILTER_FIELDS.get(normalized, {}):
        raw = params.get(param)
        if raw in (None, ""):
            continue
        parsed = _int_or_none(raw)
        applied[param] = parsed if parsed is not None else str(raw)

    ignored = [
        param
        for param in ("work_center_id", "line_id", "work_order_id")
        if params.get(param) not in (None, "") and param not in applied
    ]
    return {"applied": applied, "ignored": ignored}


def build_kanban_response(
    resource: str,
    queryset: QuerySet,
    machine: StateMachine,
    *,
    industry: str = "garmen",
    limit: int = DEFAULT_LIMIT_PER_COLUMN,
    query_params: Mapping | None = None,
) -> dict:
    """Rakit response kanban lengkap (kolom + kartu + transisi) — satu request.

    `queryset` WAJIB sudah difilter pemanggil (`apply_kanban_filters`) supaya
    penyaringan tidak dijalankan dua kali; `query_params` hanya dipakai untuk blok
    pelaporan `filters`.
    """
    actions_by_state = get_kanban_actions(machine)
    columns = get_kanban_columns(
        machine,
        queryset,
        resource=resource,
        industry=industry,
        limit=limit,
        actions_by_state=actions_by_state,
    )

    return {
        "resource": resource,
        "industry": industry,
        "machine": machine.code,
        "columns": columns,
        "transitions": get_kanban_transitions(machine),
        "total_count": sum(column["count"] for column in columns),
        "limit": limit,
        "truncated": any(column["truncated"] for column in columns),
        "unknown_states": unknown_state_counts(machine, queryset),
        "filters": _filter_report(resource, query_params or {}),
    }
