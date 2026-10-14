"""Service CRUD master Routing DAG (H1.9) — model **garment**, resource master.

Pola **sama** dengan ``master/work_center_services.py`` (H1.7) dan
``master/production_line_services.py`` (H1.8): satu operasi tulis = data +
``SyncRecord`` (``master.process_routing`` / ``MASTER_PUSH``) + ``AuditLog``
(``master.create|update|delete``).

Kekhususan H1.9 — **MES-only** (keputusan pemilik proyek, berbasis probe Odoo 17):

  * `ProcessRouting`/`RoutingStep` milik app ``garment`` dan sudah dipakai
    `TagRouter` (pilih routing via ``Rule.params['routing_code']``),
    `capability_allocator`, `overlap_release`, `two_stage_aggregator` (butuh
    ``is_terminal``), serta monitoring (`_routing_nodes_edges`, `/routing/graph/`);
  * probe: ``mrp.routing`` **tidak ada** di Odoo 17 dan ``mrp.routing.workcenter`` =
    **Operation** per-BoM (wajib ``bom_id``+``workcenter_id``) → tidak ada padanan DAG
    ⇒ **tidak ada push/pull**, ``odoo_id`` juga tidak ditambah;
  * aturan "setiap CUD master → SyncRecord" tetap dipenuhi lewat
    ``SyncStatus.SKIPPED`` (``mark_skipped``, sama seperti H1.7/H1.8) ⇒ terlihat di
    `/api/v1/sync/records/?status=SKIPPED` tanpa antrean palsu;
  * **API tetap B22** (`/api/v1/settings/routing/`, sub-resource baru) — service ini
    TIDAK mendaftarkan URL sendiri; halaman master di frontend memakai endpoint B22
    yang di-extend (tidak ada endpoint paralel `/master/routings/`);
  * langkah penyimpanan **step** memakai ``allowed_next_steps`` (edge maju) seperti
    B22: ``depends_on_step_ids`` (predecessor) diperluas menjadi edge
    ``dep[allowed_next_steps].add(step)``; ``validate_dag`` menolak siklus
    (DFS, ``MAX_DAG_DEPTH``), self-reference, dan referensi lintas routing;
  * setelah setiap perubahan step, ``is_initial``/``is_terminal`` **dihitung ulang**
    untuk seluruh routing (initial = tanpa edge masuk, terminal = tanpa edge keluar)
    supaya konsumen lama (`two_stage_aggregator`, monitoring) tetap benar;
  * **DELETE step = hapus baris (structural)** — berbeda dari soft delete master di
    H1.1–H1.8 dengan alasan yang dicatat: `RoutingStep` **tidak punya** ``is_active``,
    dan menambahkannya membuat konsumen (allocator/monitoring) membaca step nonaktif
    sebagai bagian DAG. Soft delete tetap dipakai untuk **routing** (``is_active``).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from django.db import transaction

from apps_industry.garment.models import ProcessRouting, RoutingStep, WorkCenter
from apps_industry.garment.services.tag_router import TagRouter
from core.audit.models import AuditLog
from core.audit.services import AuditLogger
from core.rule_engine.models import RuleAction
from integrations.erp_sync.idempotency import SyncIdempotency
from integrations.erp_sync.models import SyncResource, SyncStage, SyncStatus

from .services import ACTION_CREATE, ACTION_DELETE, ACTION_UPDATE, parse_bool
from .work_center_services import normalize_tags

logger = logging.getLogger(__name__)

__all__ = (
    "MES_ONLY_REASON",
    "MAX_DAG_DEPTH",
    "RoutingWriteResult",
    "active_routing_rules_count",
    "create_routing",
    "create_step",
    "deactivate_routing",
    "delete_step",
    "find_cycle",
    "generate_routing_code",
    "routing_detail_row",
    "routing_graph",
    "routing_payload",
    "routing_row",
    "routing_steps",
    "step_row",
    "update_routing",
    "update_step",
    "validate_dag",
    "validate_routing_payload",
    "validate_step_payload",
)

#: Resource sync (jangan ganti string literal di view).
ROUTING_RESOURCE = SyncResource.MASTER_PROCESS_ROUTING.value
STAGE = SyncStage.MASTER_PUSH.value

#: Alasan baku status ``SKIPPED`` (disimpan di ``SyncRecord.last_error``).
MES_ONLY_REASON = (
    "MES-only: Process Routing tidak dikirim ke Odoo — Odoo 17 tidak punya DAG "
    "routing (mrp.routing sudah dihapus; mrp.routing.workcenter = Operation per-BoM)."
)

#: Batas panjang (selaras kolom model — beda dari DB = 400, bukan 500).
MAX_CODE_LENGTH = 64
MAX_NAME_LENGTH = 150
MAX_DESCRIPTION_LENGTH = 2000
MAX_STEP_CODE_LENGTH = 64
MAX_LABEL_LENGTH = 150

#: Kedalaman maksimum penelusuran DAG (proteksi graf rusak/terlalu dalam).
MAX_DAG_DEPTH = 10

#: Kelipatan ``order`` saat step baru dibuat tanpa ``order`` eksplisit.
AUTO_ORDER_STEP = 10


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def step_row(step: RoutingStep) -> dict:
    """Satu step dalam bentuk kontrak B22 (shape F3A **tidak** diubah).

    ``depends_on`` = daftar ``step_no`` predecessor (via ``allowed_from``),
    ``wc_type`` = ``label`` (B22 memetakan wc_type ke ``label``), ``rework_target_step``
    = ``step_no`` tujuan rework (atau ``None``).
    """
    return {
        "id": step.pk,
        "step_no": step.order,
        "wc_type": step.label,
        "depends_on": sorted(prev.order for prev in step.allowed_from.all()),
        "rework_target_step": (
            step.rework_target_step.order if step.rework_target_step is not None else None
        ),
        "is_initial": step.is_initial,
        "is_terminal": step.is_terminal,
    }


def routing_steps(routing: ProcessRouting) -> list[RoutingStep]:
    """Step routing urut ``order`` (dengan relasi yang dibutuhkan serializer)."""
    return list(
        routing.steps.select_related("rework_target_step").order_by("order").prefetch_related("allowed_from")
    )


def routing_row(routing: ProcessRouting, *, with_steps: bool = True) -> dict:
    """Baris routing kompatibel B22 (``id/code/name/description/is_active/steps``).

    Dipakai untuk payload sync & audit; endpoint list B22 **tetap** memakai
    ``settings.views.serialize_routing`` sehingga shape GET-nya tidak berubah.
    """
    row = {
        "id": routing.pk,
        "code": routing.code,
        "name": routing.name,
        "description": routing.description,
        "is_active": routing.is_active,
    }
    if with_steps:
        row["steps"] = [step_row(step) for step in routing_steps(routing)]

    return row


def routing_graph(routing: ProcessRouting) -> tuple[list[dict], list[dict]]:
    """``(nodes, edges)`` DAG — **shape sama** dengan `/api/v1/routing/graph/`.

    ``nodes`` = ``{id, label, step_no}``; ``edges`` = ``{from, to, overlap_pct,
    is_rework}`` (``overlap_pct`` selalu 0 — model belum menyimpan overlap).
    """
    steps = routing_steps(routing)
    node_ids = {step.pk for step in steps}
    nodes = [
        {"id": step.pk, "label": step.label or step.code, "step_no": step.order}
        for step in steps
    ]

    edges: list[dict] = []
    for step in steps:
        for nxt in step.allowed_next_steps.all():
            if nxt.pk in node_ids:
                edges.append(
                    {"from": step.pk, "to": nxt.pk, "overlap_pct": 0, "is_rework": False}
                )
        if step.rework_target_step_id and step.rework_target_step_id in node_ids:
            edges.append(
                {
                    "from": step.pk,
                    "to": step.rework_target_step_id,
                    "overlap_pct": 0,
                    "is_rework": True,
                }
            )

    return nodes, edges


def routing_detail_row(routing: ProcessRouting) -> dict:
    """Detail routing = baris B22 + field H1.9 (``capability_tags``/``steps_count``).

    Field BARU hanya ada di sini (bukan di list B22) supaya 16 test F3A tetap hijau
    tanpa perubahan shape: ``capability_tags``, ``steps_count``, ``nodes[]``/``edges[]``
    (shape routing-graph), plus ``created_at``/``updated_at``.
    """
    nodes, edges = routing_graph(routing)
    row = routing_row(routing)
    row.update(
        {
            "capability_tags": list(routing.capability_tags or []),
            "steps_count": len(row["steps"]),
            "nodes": nodes,
            "edges": edges,
            "created_at": _iso(routing.created_at),
            "updated_at": _iso(routing.updated_at),
        }
    )

    return row


def routing_payload(routing: ProcessRouting) -> dict:
    """Payload yang disimpan di ``SyncRecord.payload`` (jejak audit master)."""
    row = routing_row(routing)

    return {
        "code": row["code"],
        "name": row["name"],
        "description": row["description"],
        "capability_tags": list(routing.capability_tags or []),
        "active": row["is_active"],
        "steps": [
            {
                "step_no": step["step_no"],
                "wc_type": step["wc_type"],
                "depends_on": step["depends_on"],
                "rework_target_step": step["rework_target_step"],
            }
            for step in row["steps"]
        ],
    }


# ---------------------------------------------------------------------------
# Validasi DAG (PURE bagian graf — dipakai view & test tanpa HTTP)
# ---------------------------------------------------------------------------
def _adjacency(routing: ProcessRouting, *, drop_incoming_to: int | None = None) -> dict[int, set[int]]:
    """Graf ``{step_id: {step_id tujuan}}`` dari ``allowed_next_steps``.

    ``drop_incoming_to`` membuang edge yang **menuju** step itu (dipakai saat update:
    edge masuk diganti, sedangkan edge keluarnya dipertahankan lalu ditimpa payload).
    """
    graph: dict[int, set[int]] = {step.pk: set() for step in routing.steps.all()}
    for step in routing.steps.prefetch_related("allowed_next_steps"):
        for nxt in step.allowed_next_steps.all():
            if nxt.pk not in graph:
                continue
            if drop_incoming_to is not None and nxt.pk == drop_incoming_to:
                continue
            graph[step.pk].add(nxt.pk)

    return graph


def find_cycle(graph: dict[int, set[int]]) -> list[int] | None:
    """Cari satu siklus di DAG → daftar node siklus, atau ``None`` kalau bersih.

    DFS iteratif dengan batas kedalaman ``MAX_DAG_DEPTH`` (graf yang lebih dalam
    dianggap tidak valid — sama semangatnya dengan guard siklus BOM H1.5).
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[int, int] = dict.fromkeys(graph, WHITE)

    for start in graph:
        if color[start] != WHITE:
            continue
        path: list[int] = []
        stack: list[tuple[int, int]] = [(start, 0)]
        while stack:
            node, index = stack[-1]
            if index == 0:
                color[node] = GREY
                path.append(node)
                if len(path) > MAX_DAG_DEPTH:
                    return list(path)
            neighbours = sorted(graph.get(node, ()))
            if index < len(neighbours):
                stack[-1] = (node, index + 1)
                target = neighbours[index]
                if color[target] == GREY:
                    # Siklus: potong path mulai dari target.
                    return path[path.index(target) :] + [target]
                if color[target] == WHITE:
                    stack.append((target, 0))
                continue
            color[node] = BLACK
            path.pop()
            stack.pop()

    return None


def validate_dag(
    routing: ProcessRouting,
    *,
    step_id: int | None = None,
    depends_on_step_ids=(),
    next_step_ids=(),
    rework_target_step_id: int | None = None,
) -> str | None:
    """Validasi graf setelah perubahan step → pesan error atau ``None``.

    Semantik edge mengikuti B22: ``depends_on_step_ids`` = **predecessor**
    (step yang mengizinkan step ini) dan ``next_step_ids`` = **successor**
    (step lanjutan yang boleh). Keduanya menyentuh M2M ``allowed_next_steps``.

    Aturan (semuanya **400** di view, bukan 500):

      * semua id harus step **routing ini** (referensi lintas routing → 400);
      * step tidak boleh menunjuk dirinya sendiri (depends/next/rework);
      * ``rework_target_step_id`` harus step routing ini;
      * setelah edge baru dipasang (dan edge lama step ini diganti saat update),
        graf ``allowed_next_steps`` **tidak boleh punya siklus** (mis. A→B→C→A).
    """
    steps = {step.pk: step for step in routing.steps.all()}
    deps = [int(value) for value in depends_on_step_ids]
    nexts = [int(value) for value in next_step_ids]

    if step_id is not None and step_id not in steps:
        return f"Step {step_id} bukan bagian routing '{routing.code}'."

    for label, values in (("depends_on_step_ids", deps), ("next_step_ids", nexts)):
        for value in values:
            if value not in steps:
                return (
                    f"Step {value} bukan bagian routing '{routing.code}' "
                    f"({label} harus step routing yang sama)."
                )
            if step_id is not None and value == step_id:
                return f"Step tidak boleh menunjuk dirinya sendiri ({label})."

    if rework_target_step_id is not None:
        rework = int(rework_target_step_id)
        if rework not in steps:
            return (
                f"Step {rework} bukan bagian routing '{routing.code}' "
                "(rework_target_step_id harus step routing yang sama)."
            )
        if step_id is not None and rework == step_id:
            return "Step tidak boleh menunjuk dirinya sendiri sebagai rework_target_step."

    graph = _adjacency(routing, drop_incoming_to=step_id if step_id is not None else None)
    if step_id is not None:
        # Edge keluar step ini diganti penuh oleh payload.
        graph[step_id] = set()
    for predecessor in deps:
        if step_id is not None:
            graph[predecessor].add(step_id)
    for successor in nexts:
        if step_id is not None:
            graph[step_id].add(successor)

    cycle = find_cycle(graph)
    if cycle is not None:
        daftar = " → ".join(str(node) for node in cycle)
        return f"Routing '{routing.code}' akan membentuk siklus: {daftar}."

    return None


class _RoutingValidationError(Exception):
    """Error validasi internal yang memicu rollback ``transaction.atomic``."""


# ---------------------------------------------------------------------------
# Validasi payload (scalar) — dipakai view & test tanpa HTTP
# ---------------------------------------------------------------------------
def generate_routing_code(name: str) -> str:
    """Kode unik & deterministik dari ``name`` (slug uppercase + sufiks angka).

    Cermin ``settings.views._unique_routing_code`` (B22) — dipakai saat ``code``
    tidak dikirim pada create.
    """
    base = re.sub(r"[^A-Za-z0-9]+", "-", str(name or "")).strip("-").upper()[:48] or "ROUTING"

    candidate = base
    seq = 2
    while ProcessRouting.objects.filter(code=candidate).exists():
        candidate = f"{base}-{seq}"
        seq += 1

    return candidate


def validate_routing_payload(data, instance: ProcessRouting | None = None):
    """Validasi body POST/PUT routing → ``(values, error)``.

    Create: ``name`` wajib; ``code`` opsional → dibangkitkan dari nama (slug
    uppercase, sufiks angka bila bentrok — perilaku sama dengan B22). Update: hanya
    field yang dikirim. ``capability_tags`` memakai aturan H1.7/H1.8 (array string
    ≤ 20 × ≤ 32 karakter, trim + dedupe case-insensitive, huruf dipertahankan).
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            return None, "Field 'name' wajib diisi."
        if len(name) > MAX_NAME_LENGTH:
            return None, f"Field 'name' maksimal {MAX_NAME_LENGTH} karakter."
        values["name"] = name

    if "code" in payload:
        code = str(payload.get("code") or "").strip()
        if code:
            if len(code) > MAX_CODE_LENGTH:
                return None, f"Field 'code' maksimal {MAX_CODE_LENGTH} karakter."
            duplicates = ProcessRouting.objects.filter(code__iexact=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode routing '{code}' sudah dipakai routing lain."
            values["code"] = code
        elif instance is None:
            values["code"] = generate_routing_code(values.get("name", ""))

    if "description" in payload:
        description = str(payload.get("description") or "").strip()
        if len(description) > MAX_DESCRIPTION_LENGTH:
            return None, f"Field 'description' maksimal {MAX_DESCRIPTION_LENGTH} karakter."
        values["description"] = description

    if "capability_tags" in payload:
        tags, error = normalize_tags(payload.get("capability_tags"))
        if error:
            return None, error
        values["capability_tags"] = tags

    if "active" in payload:
        active = parse_bool(payload.get("active"))
        if active is None:
            return None, "Field 'active' harus true|false."
        values["is_active"] = active

    return values, None


def validate_step_payload(routing: ProcessRouting, data, instance: RoutingStep | None = None):
    """Validasi scalar body POST/PUT step → ``(values, error)``.

    Graf (edge/siklus) divalidasi terpisah oleh ``validate_dag``. ``label`` wajib
    (boleh dikirim sebagai ``label`` atau ``wc_type`` — B22 memetakan ``wc_type`` ke
    ``label``). ``order`` opsional: default ``max(order)+AUTO_ORDER_STEP`` dan
    **duplikat → 400** (constraint DB ``uniq_routing_step_order`` tidak boleh menjadi
    500). ``work_center_id`` opsional tapi harus ADA bila diisi; ``code`` opsional
    (default ``STEP-<order>``) dan unik per routing.

    ``is_initial``/``is_terminal`` **tidak diterima** dari payload: keduanya selalu
    di-*derive* dari edge (``_recompute_flags``) supaya konsumen lama
    (`two_stage_aggregator`, monitoring) tidak bisa melihat flag yang tidak konsisten
    dengan graf.
    """
    payload = data if isinstance(data, dict) else {}
    values: dict = {}

    if instance is None or "label" in payload or "wc_type" in payload:
        raw_label = payload.get("label", payload.get("wc_type"))
        label = str(raw_label or "").strip()
        if not label:
            return None, "Field 'label' (atau 'wc_type') wajib diisi."
        if len(label) > MAX_LABEL_LENGTH:
            return None, f"Field 'label' maksimal {MAX_LABEL_LENGTH} karakter."
        values["label"] = label

    if instance is None or "order" in payload or "step_no" in payload:
        raw_order = payload.get("order", payload.get("step_no"))
        if raw_order is None:
            if instance is None:
                orders = list(routing.steps.values_list("order", flat=True))
                values["order"] = (max(orders) + AUTO_ORDER_STEP) if orders else AUTO_ORDER_STEP
        else:
            if isinstance(raw_order, bool) or not isinstance(raw_order, int) or raw_order <= 0:
                return None, "Field 'order' harus integer > 0."
            duplicates = routing.steps.filter(order=raw_order)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, (
                    f"Order {raw_order} sudah dipakai step lain di routing "
                    f"'{routing.code}'; pakai order lain atau kosongkan untuk otomatis."
                )
            values["order"] = raw_order

    if "code" in payload:
        code = str(payload.get("code") or "").strip()
        if len(code) > MAX_STEP_CODE_LENGTH:
            return None, f"Field 'code' maksimal {MAX_STEP_CODE_LENGTH} karakter."
        if code:
            duplicates = routing.steps.filter(code=code)
            if instance is not None:
                duplicates = duplicates.exclude(pk=instance.pk)
            if duplicates.exists():
                return None, f"Kode step '{code}' sudah dipakai step lain di routing ini."
            values["code"] = code

    if "work_center_id" in payload:
        raw_work_center = payload.get("work_center_id")
        if raw_work_center in (None, ""):
            values["work_center"] = None
        else:
            try:
                work_center_id = int(raw_work_center)
            except (TypeError, ValueError):
                return None, "Field 'work_center_id' harus angka id Work Center."
            work_center = WorkCenter.objects.filter(pk=work_center_id).first()
            if work_center is None:
                return None, f"Work center {work_center_id} tidak ditemukan."
            values["work_center"] = work_center

    if instance is None and "code" not in values:
        order = int(values.get("order", AUTO_ORDER_STEP))
        base_code = f"STEP-{order}"
        candidate = base_code
        seq = 2
        while routing.steps.filter(code=candidate).exists():
            candidate = f"{base_code}-{seq}"
            seq += 1
        values["code"] = candidate

    return values, None


# ---------------------------------------------------------------------------
# Tulis (create / update / soft delete routing & step) — ledger SKIPPED + audit
# ---------------------------------------------------------------------------
@dataclass
class RoutingWriteResult:
    """Hasil satu operasi tulis routing/step (dipakai view).

    **Tanpa** ``task_id``/``queued``: H1.9 MES-only → tidak ada task push yang
    di-enqueue; jejak sync cukup ditandai ``SyncStatus.SKIPPED``.
    """

    routing: ProcessRouting | None = None
    step: RoutingStep | None = None
    error: str | None = None
    sync_record_id: int | None = None

    @property
    def sync_status(self) -> str | None:
        """Status ledger yang ditulis (``SKIPPED``) — ``None`` kalau tak ada tulis."""
        return SyncStatus.SKIPPED.value if self.sync_record_id else None


def _record_mes_only(routing: ProcessRouting) -> int:
    """Tulis/segarkan ``SyncRecord`` routing lalu tandai ``SKIPPED`` (pola H1.7/H1.8)."""
    payload = routing_payload(routing)
    sync = SyncIdempotency()
    record = sync.get_or_create_sync_record(ROUTING_RESOURCE, routing.pk, STAGE, payload)

    if dict(record.payload or {}) != payload:
        record.payload = payload
        record.save(update_fields=("payload", "updated_at"))

    sync.mark_skipped(record, MES_ONLY_REASON)

    return record.pk


def _audit(action: str, routing: ProcessRouting, request, metadata: dict | None = None) -> None:
    """Tulis ``AuditLog`` — best-effort (audit tidak boleh menggagalkan CRUD)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=ROUTING_RESOURCE,
            resource_id=routing.pk,
            request=request,
            payload=routing_payload(routing),
            result=AuditLog.Result.OK,
            metadata={"mes_only": True, **(metadata or {})},
        )
    except Exception:  # noqa: BLE001 - audit tidak boleh menggagalkan CRUD master
        logger.exception(
            "master.routing: gagal menulis audit (%s, routing %s).", action, routing.pk
        )


def active_routing_rules_count(routing_code: str) -> int:
    """Jumlah ``Rule`` tag-router AKTIF yang menunjuk kode routing ini.

    Routing dipilih `TagRouter` lewat ``Rule.params['routing_code']`` (tidak ada FK
    dari model lain ke ``ProcessRouting``), jadi guard soft delete yang benar adalah
    memeriksa **rule aktif** — bukan "WorkOrder aktif".
    """
    return RuleAction.objects.filter(
        action_type=TagRouter.ROUTE_ACTION,
        params__routing_code=routing_code,
        rule__is_active=True,
        rule__code__startswith=TagRouter.RULE_PREFIX,
    ).count()


def _apply_edges(step: RoutingStep, depends_on=None, next_steps=None) -> None:
    """Pasang edge ``allowed_next_steps`` (incoming dari ``depends_on``, outgoing ``next_steps``).

    Incoming: semua step lain yang menunjuk ``step`` dibersihkan lebih dulu (replace
    penuh), lalu ``depends_on`` ditambahkan. Outgoing: ``step.allowed_next_steps``
    di-``set()`` penuh (``None`` = jangan sentuh).
    """
    routing = step.routing
    for other in routing.steps.exclude(pk=step.pk):
        other.allowed_next_steps.remove(step)

    for predecessor in depends_on or ():
        predecessor.allowed_next_steps.add(step)

    if next_steps is not None:
        step.allowed_next_steps.set(next_steps)


def _recompute_flags(routing: ProcessRouting) -> None:
    """Hitung ulang ``is_initial``/``is_terminal`` seluruh routing dari edge.

    ``is_initial`` = tidak punya edge masuk; ``is_terminal`` = tidak punya edge keluar.
    Dipanggil setelah setiap perubahan step supaya konsumen lama (yang membaca kedua
    flag itu, mis. `two_stage_aggregator` & monitoring) selalu konsisten dengan graf.
    """
    for step in routing.steps.prefetch_related("allowed_from", "allowed_next_steps"):
        initial = not step.allowed_from.exists()
        terminal = not step.allowed_next_steps.exists()
        if step.is_initial != initial or step.is_terminal != terminal:
            step.is_initial = initial
            step.is_terminal = terminal
            step.save(update_fields=("is_initial", "is_terminal"))


def _steps_by_id(routing: ProcessRouting, raw_ids, label: str):
    """``(list[RoutingStep], error)`` dari daftar id step (harus step routing ini)."""
    if raw_ids is None:
        return [], None
    if not isinstance(raw_ids, list):
        return None, f"Field '{label}' harus array id step."

    steps = {step.pk: step for step in routing.steps.all()}
    result: list[RoutingStep] = []
    for item in raw_ids:
        if isinstance(item, bool):
            return None, f"Id step {item!r} tidak valid (harus angka)."
        try:
            value = int(item)
        except (TypeError, ValueError):
            return None, f"Id step {item!r} tidak valid (harus angka)."
        step = steps.get(value)
        if step is None:
            return None, (
                f"Step {value} bukan bagian routing '{routing.code}' "
                f"({label} harus step routing yang sama)."
            )
        if step not in result:
            result.append(step)

    return result, None


def create_routing(data, request=None) -> RoutingWriteResult:
    """Buat routing + ledger ``SKIPPED`` + audit (opsional ``steps[]`` bentuk B22).

    Jalur create utama di API tetap **POST B22** (``settings.views``); fungsi ini
    menyediakan jalur yang sama untuk service/test, termasuk membuat step awal dari
    ``steps[{step_no, wc_type, depends_on, rework_target_step}]`` (edge dibentuk
    setelah semua step ada, sama seperti B22).
    """
    values, error = validate_routing_payload(data)
    if error:
        return RoutingWriteResult(error=error)

    payload = data if isinstance(data, dict) else {}
    raw_steps = payload.get("steps")

    try:
        with transaction.atomic():
            routing = ProcessRouting.objects.create(**values)

            if raw_steps is not None:
                if not isinstance(raw_steps, list):
                    raise _RoutingValidationError("Field 'steps' harus array.")
                _create_steps_b22(routing, raw_steps)

            routing.refresh_from_db()
            record_id = _record_mes_only(routing)
            _audit(ACTION_CREATE, routing, request, {"code": routing.code})
    except _RoutingValidationError as exc:
        return RoutingWriteResult(error=str(exc))

    logger.info("master.routing: routing %s dibuat (ledger=%s, MES-only).", routing.pk, record_id)
    return RoutingWriteResult(routing=routing, sync_record_id=record_id)


def _create_steps_b22(routing: ProcessRouting, raw_steps: list) -> None:
    """Buat semua step dari bentuk B22 lalu pasang edge (dipanggil di dalam atomic).

    Melempar ``_RoutingValidationError`` kalau ada yang invalid supaya seluruh
    transaksi (routing + step) di-rollback.
    """
    by_no: dict[int, RoutingStep] = {}
    pending: list[tuple[RoutingStep, list[int], int | None]] = []

    for index, raw_step in enumerate(raw_steps):
        item = dict(raw_step) if isinstance(raw_step, dict) else {}
        step_no = item.get("step_no")
        if isinstance(step_no, bool) or not isinstance(step_no, int) or step_no <= 0:
            raise _RoutingValidationError(f"steps[{index}].step_no harus integer > 0.")
        if step_no in by_no:
            raise _RoutingValidationError(f"steps[{index}].step_no={step_no} duplikat.")

        step_values, error = validate_step_payload(
            routing,
            {
                "step_no": step_no,
                "label": item.get("wc_type"),
                "code": item.get("code"),
                "work_center_id": item.get("work_center_id"),
            },
        )
        if error:
            raise _RoutingValidationError(f"steps[{index}]: {error}")

        step = RoutingStep.objects.create(routing=routing, **step_values)
        by_no[step_no] = step

        deps = item.get("depends_on") or []
        if not isinstance(deps, list) or any(
            isinstance(dep, bool) or not isinstance(dep, int) for dep in deps
        ):
            raise _RoutingValidationError(f"steps[{index}].depends_on harus daftar integer.")

        rework = item.get("rework_target_step")
        if rework is not None and (isinstance(rework, bool) or not isinstance(rework, int)):
            raise _RoutingValidationError(f"steps[{index}].rework_target_step harus integer.")

        pending.append((step, deps, rework))

    for step, deps, rework in pending:
        unknown = [dep for dep in deps if dep not in by_no]
        if unknown:
            daftar = ", ".join(str(dep) for dep in unknown)
            raise _RoutingValidationError(f"step {step.order} depends_on {daftar} tidak ada di steps.")
        if rework is not None and rework not in by_no:
            raise _RoutingValidationError(
                f"step {step.order} rework_target_step {rework} tidak ada."
            )

        _apply_edges(
            step,
            depends_on=[
                by_no[dep]
                for dep in deps
                if dep != step.order and by_no[dep].pk != step.pk
            ],
            next_steps=list(step.allowed_next_steps.all()),
        )
        if rework is not None:
            step.rework_target_step = by_no[rework]
            step.save(update_fields=("rework_target_step",))

    error = validate_dag(routing)
    if error:
        raise _RoutingValidationError(error)

    _recompute_flags(routing)


def update_routing(routing: ProcessRouting, data, request=None) -> RoutingWriteResult:
    """Ubah routing (hanya field yang dikirim) + ledger ``SKIPPED`` + audit."""
    values, error = validate_routing_payload(data, instance=routing)
    if error:
        return RoutingWriteResult(routing=routing, error=error)

    if not values:
        return RoutingWriteResult(routing=routing)

    for field, value in values.items():
        setattr(routing, field, value)
    routing.save()

    record_id = _record_mes_only(routing)
    _audit(ACTION_UPDATE, routing, request, {"fields": sorted(values)})

    logger.info("master.routing: routing %s diubah (ledger=%s, MES-only).", routing.pk, record_id)
    return RoutingWriteResult(routing=routing, sync_record_id=record_id)


def deactivate_routing(routing: ProcessRouting, request=None) -> RoutingWriteResult:
    """Soft delete (``is_active=False``) + ledger ``SKIPPED`` + audit.

    **Guard**: error kalau masih ada ``Rule`` tag-router AKTIF yang menunjuk kode
    routing ini (``Rule.params['routing_code']``) — routing dipilih lewat rule, bukan
    FK, jadi ini padanan realistis dari "masih dipakai WorkOrder aktif".
    """
    references = active_routing_rules_count(routing.code)
    if references > 0:
        return RoutingWriteResult(
            routing=routing,
            error=(
                f"Routing '{routing.code}' masih dipakai {references} rule tag-router aktif; "
                "matikan/pindahkan rule itu dulu sebelum menonaktifkan routing."
            ),
        )

    if routing.is_active:
        routing.is_active = False
        routing.save(update_fields=("is_active",))

    record_id = _record_mes_only(routing)
    _audit(ACTION_DELETE, routing, request, {"soft_delete": True})

    logger.info(
        "master.routing: routing %s dinonaktifkan (ledger=%s, MES-only).", routing.pk, record_id
    )
    return RoutingWriteResult(routing=routing, sync_record_id=record_id)


# ---------------------------------------------------------------------------
# Step (nested) — create / update / hapus
# ---------------------------------------------------------------------------
def _step_edge_ids(routing: ProcessRouting, data: dict, *, instance: RoutingStep | None):
    """``(depends_on, next_steps, error)`` — daftar step dari payload edge.

    ``depends_on_step_ids`` = predecessor, ``next_step_ids`` = successor. Untuk
    update, ``None`` berarti "jangan ubah edge sisi itu"; list kosong berarti
    "kosongkan".
    """
    has_deps = "depends_on_step_ids" in data or "depends_on" in data
    has_nexts = "next_step_ids" in data

    depends_on, next_steps = [], []
    if instance is not None and not has_deps:
        depends_on = None
    elif has_deps:
        raw = data.get("depends_on_step_ids", data.get("depends_on"))
        depends_on, error = _steps_by_id(routing, raw if raw is not None else [], "depends_on_step_ids")
        if error:
            return None, None, error

    if instance is not None and not has_nexts:
        next_steps = None
    elif has_nexts:
        raw = data.get("next_step_ids")
        next_steps, error = _steps_by_id(routing, raw if raw is not None else [], "next_step_ids")
        if error:
            return None, None, error

    return depends_on, next_steps, None


def create_step(routing: ProcessRouting, data, request=None) -> RoutingWriteResult:
    """Tambah step ke routing (+ edge) + ledger ``SKIPPED`` + audit.

    Step dibuat di dalam ``transaction.atomic`` supaya `validate_dag` bisa menguji
    graf dengan pk step yang sudah ada; kalau ada siklus/self-ref/lintas routing,
    seluruh transaksi di-rollback dan pesan error dikembalikan ke view (→ 400).
    """
    payload = data if isinstance(data, dict) else {}
    values, error = validate_step_payload(routing, payload)
    if error:
        return RoutingWriteResult(routing=routing, error=error)

    depends_on, next_steps, error = _step_edge_ids(routing, payload, instance=None)
    if error:
        return RoutingWriteResult(routing=routing, error=error)

    rework_id = payload.get("rework_target_step_id")
    rework = None
    if rework_id is not None:
        rework_steps, error = _steps_by_id(routing, [rework_id], "rework_target_step_id")
        if error:
            return RoutingWriteResult(routing=routing, error=error)
        rework = rework_steps[0]

    try:
        with transaction.atomic():
            step = RoutingStep.objects.create(routing=routing, **values)
            error = validate_dag(
                routing,
                step_id=step.pk,
                depends_on_step_ids=[item.pk for item in depends_on or []],
                next_step_ids=[item.pk for item in next_steps or []],
                rework_target_step_id=rework.pk if rework is not None else None,
            )
            if error:
                raise _RoutingValidationError(error)

            _apply_edges(step, depends_on=depends_on, next_steps=next_steps)
            if rework is not None:
                step.rework_target_step = rework
                step.save(update_fields=("rework_target_step",))
            _recompute_flags(routing)

            routing.refresh_from_db()
            record_id = _record_mes_only(routing)
            _audit(ACTION_CREATE, routing, request, {"step_id": step.pk, "step_code": step.code})
    except _RoutingValidationError as exc:
        return RoutingWriteResult(routing=routing, error=str(exc))

    logger.info(
        "master.routing: step %s ditambah ke routing %s (ledger=%s, MES-only).",
        step.pk,
        routing.pk,
        record_id,
    )
    return RoutingWriteResult(routing=routing, step=step, sync_record_id=record_id)


def update_step(step: RoutingStep, data, request=None) -> RoutingWriteResult:
    """Ubah step (+ ganti edge-nya) + ledger ``SKIPPED`` + audit.

    Edge incoming/outgoing boleh dikirim sekaligus; yang **tidak** dikirim
    dipertahankan. Validasi graf memakai daftar *efektif* (payload atau nilai
    sekarang) supaya simulasi ``validate_dag`` sama dengan hasil akhir.
    """
    routing = step.routing
    payload = data if isinstance(data, dict) else {}

    values, error = validate_step_payload(routing, payload, instance=step)
    if error:
        return RoutingWriteResult(routing=routing, step=step, error=error)

    depends_on, next_steps, error = _step_edge_ids(routing, payload, instance=step)
    if error:
        return RoutingWriteResult(routing=routing, step=step, error=error)

    effective_deps = (
        depends_on if depends_on is not None else list(step.allowed_from.all())
    )
    effective_nexts = (
        next_steps if next_steps is not None else list(step.allowed_next_steps.all())
    )

    rework = None
    if "rework_target_step_id" in payload:
        raw_rework = payload.get("rework_target_step_id")
        if raw_rework in (None, ""):
            rework = "clear"
        else:
            steps, error = _steps_by_id(routing, [raw_rework], "rework_target_step_id")
            if error:
                return RoutingWriteResult(routing=routing, step=step, error=error)
            rework = steps[0]

    try:
        with transaction.atomic():
            if values:
                for field, value in values.items():
                    setattr(step, field, value)
                step.save()

            error = validate_dag(
                routing,
                step_id=step.pk,
                depends_on_step_ids=[item.pk for item in effective_deps],
                next_step_ids=[item.pk for item in effective_nexts],
                rework_target_step_id=(
                    rework.pk if isinstance(rework, RoutingStep) else None
                ),
            )
            if error:
                raise _RoutingValidationError(error)

            _apply_edges(step, depends_on=effective_deps, next_steps=effective_nexts)
            if rework == "clear":
                step.rework_target_step = None
                step.save(update_fields=("rework_target_step",))
            elif isinstance(rework, RoutingStep):
                step.rework_target_step = rework
                step.save(update_fields=("rework_target_step",))
            _recompute_flags(routing)

            routing.refresh_from_db()
            record_id = _record_mes_only(routing)
            _audit(ACTION_UPDATE, routing, request, {"step_id": step.pk, "step_code": step.code})
    except _RoutingValidationError as exc:
        return RoutingWriteResult(routing=routing, step=step, error=str(exc))

    logger.info(
        "master.routing: step %s routing %s diubah (ledger=%s, MES-only).",
        step.pk,
        routing.pk,
        record_id,
    )
    return RoutingWriteResult(routing=routing, step=step, sync_record_id=record_id)


def delete_step(step: RoutingStep, request=None) -> RoutingWriteResult:
    """Hapus step dari routing (structural) + ledger ``SKIPPED`` + audit.

    **Bukan** soft delete — `RoutingStep` tidak punya ``is_active`` dan menambahkannya
    akan membuat konsumen (allocator/monitoring) membaca step nonaktif sebagai bagian
    DAG. Edge yang menyentuh step ini otomatis ikut terhapus (M2M), sedangkan step lain
    yang menjadikannya ``rework_target_step`` otomatis di-``SET_NULL``. ``order``/``code``
    step lain tidak diubah (tetap unik); ``is_initial``/``is_terminal`` dihitung ulang.
    """
    routing = step.routing
    step_code = step.code

    try:
        with transaction.atomic():
            step.delete()
            _recompute_flags(routing)

            routing.refresh_from_db()
            record_id = _record_mes_only(routing)
            _audit(ACTION_DELETE, routing, request, {"step_code": step_code})
    except _RoutingValidationError as exc:
        return RoutingWriteResult(routing=routing, error=str(exc))

    logger.info(
        "master.routing: step %s (routing %s) dihapus (ledger=%s, MES-only).",
        step_code,
        routing.pk,
        record_id,
    )
    return RoutingWriteResult(routing=routing, sync_record_id=record_id)



