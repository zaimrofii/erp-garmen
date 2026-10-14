"""ActionExecutor — eksekusi aksi resource lewat state machine (Kontrak §2 & §5).

Alur `execute()`:

  1. resolve `resource` -> (model, builder) lewat registry Sprint 3.1;
  2. ambil instance (404 kalau tidak ada);
  3. cek **conflict** (`X-Base-Version` vs version server) -> 409 kontrak §5.2/§8.4,
     dengan policy (Fase C): `X-Force: true` > `X-Conflict-Policy` > default
     `manual`. `last_write_wins` (atau `X-Force`) = lewati cek & timpa version;
     `server_wins`/`manual` = 409 tanpa eksekusi;
  4. resolve `Transition` dari state machine `garment.<resource>` untuk
     `action_id` + state saat ini (definisi = data, bukan kode);
  5. validasi lewat `StateMachineEngine.can_transition()` -> 400 kalau tidak sah;
  6. update `state` (Bundle otomatis menghitung ulang `version` di `save()`);
  7. kembalikan version baru + `expected_result` (field kritis yang berubah).

Bentuk return selalu `{"status": <http>, "payload": {...}}` supaya view cukup
`Response(result["payload"], status=result["status"])`.

Payload 200 (Fase B.2):: `{ok, resource, id, action, version, state,
expected_result:{state, fields}}` + field kritis (mis. `scrap`) diangkat ke top
level karena `offline-queue.checkExpectedResult()` frontend membacanya di sana.

Payload 409 (Fase C):: `{"status": "conflict", "current": {...}}` + alias
`{"conflict": {"current": {...}}}`. Key **top-level `current`** adalah yang
dibaca frontend (`api-client.ts` -> `readConflictCurrent()` -> `body['current']`)
dan disebut eksplisit di prototype §8.4 ("409 + `current.version` +
`current.state`"); alias bersarang disediakan supaya tooling/dokumentasi yang
menulis `conflict.current` juga cocok.

Catatan: `mode` (optimistic/pessimistic) hanya **hint UI** (kontrak §2.2) —
executor memperlakukan semua transisi sama; keputusan mode ada di frontend.
"""

from __future__ import annotations

import logging

from core.state_machine.services import StateMachineEngine, StateMachineEngineError

from apps_industry.garment.api.schema.registry import get_builder
from apps_industry.garment.services.action_events import record_resource_action

logger = logging.getLogger(__name__)

#: resource -> kode state machine (state aktual tetap di model domain).
RESOURCE_MACHINES = {
    "bundles": "garment.bundle",
    "work-orders": "garment.work_order",
}

#: Field kritis tambahan yang ikut berubah per action (selain `state`).
EXTRA_CRITICAL_FIELDS = {
    "BUNDLE_SCRAP": {"scrap": True},
}

POLICY_MANUAL = "manual"
POLICY_LAST_WRITE_WINS = "last_write_wins"
POLICY_SERVER_WINS = "server_wins"

#: Policy default (kontrak §8.2): butuh keputusan operator -> 409 + `current`.
DEFAULT_CONFLICT_POLICY = POLICY_MANUAL

#: Policy yang dikenal (kontrak §8.2). Nilai tak dikenal -> fail-closed ke `manual`
#: (tetap 409, tidak pernah "diam-diam menimpa").
CONFLICT_POLICIES: tuple[str, ...] = (
    POLICY_MANUAL,
    POLICY_LAST_WRITE_WINS,
    POLICY_SERVER_WINS,
)

#: Nilai header `X-Force` yang dianggap aktif (frontend `api-client.ts` mengirim
#: `"true"`; `1`/`yes`/`on` ikut diterima supaya ramah curl/manual test).
FORCE_TRUE_VALUES = frozenset({"true", "1", "yes", "on"})


def is_force_requested(value: str | None) -> bool:
    """PURE — `X-Force` aktif? (case-insensitive; nilai kosong/asing = tidak)."""
    return str(value or "").strip().lower() in FORCE_TRUE_VALUES


def normalize_conflict_policy(value: str | None) -> str:
    """PURE — policy kanonik; kosong/tak dikenal -> `manual` (fail-closed)."""
    candidate = str(value or "").strip().lower()
    return candidate if candidate in CONFLICT_POLICIES else DEFAULT_CONFLICT_POLICY


def resolve_conflict_policy(
    policy_header: str | None = None, force_header: str | None = None
) -> str:
    """PURE — prioritas Fase C: `X-Force` > `X-Conflict-Policy` > `manual`."""
    if is_force_requested(force_header):
        return POLICY_LAST_WRITE_WINS

    return normalize_conflict_policy(policy_header)


class ActionExecutor:
    """Eksekutor aksi state machine untuk resource garmen (stateless)."""

    def __init__(self, engine: StateMachineEngine | None = None):
        self._engine = engine or StateMachineEngine()

    # -------------------------------------------------------------------- public
    def execute(
        self,
        resource_name: str,
        instance_id: int,
        action_id: str,
        request=None,
        base_version: str | None = None,
        conflict_policy: str = DEFAULT_CONFLICT_POLICY,
    ) -> dict:
        """Eksekusi satu aksi; lihat docstring modul untuk urutannya."""
        builder_class = get_builder(resource_name)
        if builder_class is None:
            return self._error(404, f"Resource '{resource_name}' tidak dikenal.")

        instance = self._get_instance(builder_class, instance_id)
        if instance is None:
            return self._error(
                404, f"Resource '{resource_name}' dengan id {instance_id} tidak ditemukan."
            )

        builder = builder_class(instance=instance, request=request)
        current_version = builder.get_version()

        conflict = self._check_conflict(
            instance, current_version, base_version, conflict_policy
        )
        if conflict is not None:
            return conflict

        machine_code = RESOURCE_MACHINES.get(builder.RESOURCE_NAME)
        if machine_code is None:
            return self._error(400, f"Resource '{resource_name}' tidak mendukung aksi.")

        try:
            machine = self._engine.get_machine(machine_code)
            allowed, reason = self._engine.can_transition(
                machine, instance.state, action_id, {}
            )
        except StateMachineEngineError as exc:
            return self._error(400, str(exc))

        if not allowed:
            return self._error(400, reason)

        transition = self._engine.execute_transition(
            machine, instance.state, action_id, {}
        )
        instance.state = transition.to_state.code
        instance.save(update_fields=self._update_fields(type(instance)))

        # Fase E: jejak chatter (BundleEvent) + event bus → klien real-time.
        # Dijalankan SETELAH state tersimpan supaya event yang dikirim ke WS
        # benar-benar mencerminkan state baru (idempotent/409 sudah dijaga di atas).
        # FASE 4.3: `fields` dari body aksi (mis. scrap_qty/reason) ikut disimpan
        # ke `BundleEvent.payload` supaya jejak scrap tidak hilang.
        self._record_event(
            builder.RESOURCE_NAME,
            instance,
            action_id,
            transition.to_state.code,
            request,
            self._request_fields(request),
        )

        fresh = builder_class(instance=instance, request=request)
        to_state = transition.to_state.code
        fields = self._critical_fields(action_id, to_state)
        logger.info(
            "aksi '%s' %s#%s -> state '%s'.",
            action_id,
            builder.RESOURCE_NAME,
            instance.pk,
            to_state,
        )

        payload = {
            "ok": True,
            "resource": builder.RESOURCE_NAME,
            "id": instance.pk,
            "action": action_id,
            "version": fresh.get_version(),
            "expected_result": {"state": to_state, "fields": fields},
        }
        # Fase B.2: `offline-queue.checkExpectedResult()` frontend membaca `state`
        # dan field kritis di TOP LEVEL body (bukan di dalam `expected_result`),
        # jadi field kritis ikut diangkat ke atas. `setdefault` dipakai supaya key
        # inti (ok/version/id/resource/action) tidak mungkin tertimpa.
        for key, value in fields.items():
            payload.setdefault(key, value)

        return {"status": 200, "payload": payload}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _request_fields(request) -> dict:
        """Ambil ``fields`` dari body aksi (dict) — ``{}`` kalau tidak ada/tak valid.

        FASE 4.3 — body aksi kontrak §2 berbentuk ``{"fields": {...}}``; field
        inilah yang (sebelumnya dibuang) sekarang disimpan ke
        ``BundleEvent.payload``.

        Dibaca lewat ``request.data`` (**DRF**), BUKAN ``request.body``: di server
        ASGI live ``request.body`` melempar ``RawPostDataException`` (regresi
        `test_rawpostdata_regression`). Body tak terbaca / bukan dict → fields
        diabaikan, aksi tetap jalan.
        """
        if request is None:
            return {}
        try:
            data = request.data
        except Exception:  # noqa: BLE001 - body tak terbaca != gagalkan aksi
            logger.warning("aksi: body tidak terbaca -> 'fields' diabaikan.")
            return {}
        if not isinstance(data, dict):
            return {}
        fields = data.get("fields")
        return dict(fields) if isinstance(fields, dict) else {}

    @staticmethod
    def _record_event(
        resource_name: str,
        instance,
        action_id: str,
        to_state: str,
        request=None,
        fields: dict | None = None,
    ) -> None:
        """Jejak chatter + publish event bus (Fase E) — **tidak boleh** menggagalkan aksi.

        Aksi produksi sudah tersimpan saat baris ini dijalankan; jejak/real-time
        yang gagal (mis. tabel audit penuh) hanya dicatat di log.
        """
        try:
            record_resource_action(
                resource_name=resource_name,
                instance=instance,
                action_id=action_id,
                to_state=to_state,
                request=request,
                fields=fields,
            )
        except Exception:  # noqa: BLE001 - aksi sudah sukses, jejak jangan mematikannya
            logger.exception(
                "gagal mencatat event '%s' untuk %s#%s (aksi tetap sukses).",
                action_id,
                resource_name,
                getattr(instance, "pk", "?"),
            )

    @staticmethod
    def _get_instance(builder_class, instance_id: int):
        """Ambil instance lewat MODEL builder (+ select_related anti N+1)."""
        queryset = builder_class.MODEL.objects.all()
        if builder_class.SELECT_RELATED:
            queryset = queryset.select_related(*builder_class.SELECT_RELATED)
        return queryset.filter(pk=instance_id).first()

    def _check_conflict(
        self,
        instance,
        current_version: str,
        base_version: str | None,
        conflict_policy: str,
    ) -> dict | None:
        """409 kontrak §5.2/§8.4 kalau version frontend != version server.

        `base_version` kosong (`X-Base-Version` tidak dikirim) -> **tanpa cek
        konflik** (jalur lama/UI langsung tetap jalan). Policy `last_write_wins`
        (termasuk efek `X-Force: true`) -> cek dilewati & version ditimpa.
        """
        if not base_version or base_version == current_version:
            return None

        policy = normalize_conflict_policy(conflict_policy)
        if policy == POLICY_LAST_WRITE_WINS:
            logger.warning(
                "konflik version diabaikan (policy %s) untuk %s#%s.",
                policy,
                type(instance).__name__,
                instance.pk,
            )
            return None

        current = {
            "version": current_version,
            "state": instance.state,
            # Selalu ada (kontrak §8.4): `None` kalau bundle belum di WC mana pun.
            "current_work_center": (
                instance.current_work_center.code
                if getattr(instance, "current_work_center_id", None)
                else None
            ),
        }
        logger.info(
            "konflik version %s#%s (policy=%s): base=%s current=%s.",
            type(instance).__name__,
            instance.pk,
            policy,
            base_version,
            current_version,
        )

        return {
            "status": 409,
            "payload": {
                "status": "conflict",
                # Key yang DIBACA frontend: `api-client.ts` -> body['current'] (§8.4).
                "current": current,
                # Alias bersarang untuk tooling/dokumentasi yang menulis
                # `conflict.current` (Fase C) — isi sama persis.
                "conflict": {"current": current},
            },
        }

    @staticmethod
    def _critical_fields(action_id: str, to_state: str) -> dict:
        """Field kritis yang berubah akibat aksi ini (dipakai optimistic UI)."""
        fields = {"state": to_state}
        fields.update(EXTRA_CRITICAL_FIELDS.get(str(action_id).strip().upper(), {}))
        return fields

    @staticmethod
    def _update_fields(model) -> list[str]:
        """Field yang disimpan saat transisi (`version` hanya kalau model punya)."""
        fields = ["state", "updated_at"]
        field_names = {field.name for field in model._meta.get_fields()}
        if "version" in field_names:
            fields.append("version")
        return fields

    @staticmethod
    def _error(status: int, detail: str) -> dict:
        return {"status": status, "payload": {"detail": detail}}
