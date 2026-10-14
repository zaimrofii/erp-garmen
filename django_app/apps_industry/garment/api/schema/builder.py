"""Pembangun metadata schema resource (Kontrak Backend<->Frontend §1-§2).

Prinsip kontrak: **backend = otak, frontend = papan tulis**. Frontend tidak boleh
men-hardcode tombol/status/kolom, jadi semua yang dibutuhkan untuk render halaman
dikirim backend sebagai metadata JSON.

Bentuk JSON (Fase B.1 — selaras `ResourceMetadataSchema` Zod frontend,
`schema_version` di-hardcode "1.0")::

    {
      "schema_version": "1.0",
      "resource": {"name": "bundles", "label": "Bundle", "id": "1", "version": "<hash>"},
      "view_type": "form",
      "device_hint": "SCANNER_USB",
      "state_machine": {
        "current_state": "SEWING",
        "possible_states": [{"id": "DRAFT", "label": "Draft", "kind": "past"}, ...],
        "allowed_actions": [
          {"id": "BUNDLE_QC", "label": "QC", "mode": "optimistic",
           "endpoint": "/garmen/bundles/1/BUNDLE_QC/"}
        ]
      },
      "layout": {"sections": [
        {"id": "info-bundle", "label": "Info Bundle",
         "fields": [{"name": ..., "type": "string", "label": ..., "value": ..., "read_only": true}]}
      ]},
      "chatter": {"preview": [...], "total_count": 0, "has_more": false, "next_cursor": null}
    }

Perubahan Fase B.1:

  * ``resource`` = **objek** `{name, label, id, version}` (dulu string);
  * ``possible_states[]`` = `{id, label, kind}`, `kind` **diturunkan dari posisi**
    `current_state` (past/current/future);
  * ``layout`` = `{sections: [{id, label, fields}]}` (dulu array datar);
  * ``field.type`` SELALU salah satu enum frontend (string/number/boolean/date/
    enum/reference); widget industri dipisah ke `field.widget`;
  * ``allowed_actions[].endpoint`` = path aksi (lihat `ACTION_ENDPOINT_ROOT`)
    supaya frontend tidak perlu menebak URL lagi.

Key top-level `industry`/`title`/`version` tetap dikirim demi kompatibilitas
(Zod frontend men-strip key asing — bukan error).

Subclass wajib meng-implement semua hook `get_*`; `build()` merakit semuanya.
`allowed_actions[].mode` dikirim **lowercase** (`optimistic`/`pessimistic`) sesuai
kontrak §2.2, walau di DB tersimpan uppercase (`Transition.Mode`).
"""

from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from core.state_machine.models import StateMachine, Transition

logger = logging.getLogger(__name__)

#: Guard kompatibilitas frontend (kontrak §1). Jangan diubah tanpa kesepakatan.
SCHEMA_VERSION = "1.0"
VIEW_TYPE_FORM = "form"

#: Enum `field.type` frontend (`layout.schema.ts` -> LAYOUT_FIELD_TYPES) — B.1.4.
FIELD_TYPES: tuple[str, ...] = (
    "string",
    "number",
    "boolean",
    "date",
    "enum",
    "reference",
)

#: Alias tipe lama (pra B.1) -> tipe enum kontrak. `text` dulu dipakai luas.
FIELD_TYPE_ALIASES: dict[str, str] = {
    "text": "string",
    "bool": "boolean",
    "integer": "number",
    "float": "number",
}

#: Tipe lama `widget-<nama>` (pra B.1) -> dipecah jadi `type` + `widget`.
WIDGET_TYPE_PREFIX = "widget-"

#: Tipe pengganti bila tipe field tidak ada di enum kontrak.
FIELD_TYPE_FALLBACK = "string"

#: `possible_states[].kind` frontend (`state-machine.schema.ts` -> STATE_KINDS) — B.1.2.
STATE_KINDS: tuple[str, ...] = ("past", "current", "future")

#: `kind` yang dipakai kalau `current_state` tidak ada di daftar mesin.
KIND_UNKNOWN_FALLBACK = "future"

#: Root endpoint aksi — **relatif terhadap `VITE_API_BASE_URL`** frontend.
#: `integrations/api-client.ts` memanggil `fetch(baseUrl + path)` sedangkan
#: `VITE_API_BASE_URL` (`frontend_app/.env`) SUDAH memuat `/api/v1`, jadi jangan
#: diisi "/api/v1" (hasilnya dobel prefix `.../api/v1/api/v1/...`). Isi hanya
#: bila frontend kelak memakai baseUrl host-polos.
ACTION_ENDPOINT_ROOT = ""


def slugify(value: Any) -> str:
    """PURE — slug stabil untuk `id` section (mis. `"Info Bundle"` -> `"info-bundle"`)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "section"


def derive_state_kind(index: int, current_index: int) -> str:
    """PURE — `kind` dari POSISI state (mirror `deriveStateKinds` frontend, B.1.2).

    Urutan = urutan `possible_states` (`order`, `code` di DB): `past` sebelum
    `current_state`, `current` tepat di posisinya, `future` sesudahnya.
    """
    if current_index < 0:
        return KIND_UNKNOWN_FALLBACK
    if index < current_index:
        return "past"
    if index == current_index:
        return "current"
    return "future"


def state_entries_payload(states, current_state: str) -> list[dict]:
    """`possible_states[]` kontrak §5.1: `{id, label, kind}` (Fase B.1.2)."""
    codes = [state.code for state in states]
    current_index = codes.index(current_state) if current_state in codes else -1
    if current_index < 0 and codes:
        logger.warning(
            "state '%s' tidak ada di daftar mesin %s -> semua kind '%s'.",
            current_state,
            codes,
            KIND_UNKNOWN_FALLBACK,
        )

    return [
        {
            "id": state.code,
            "label": state.label or state.code,
            "kind": derive_state_kind(index, current_index),
        }
        for index, state in enumerate(states)
    ]


def action_endpoint_payload(prefix: str | None, action_id: str) -> str | None:
    """PURE — endpoint aksi kontrak §2 (Fase B.1.5); `None` bila prefix kosong.

    `prefix` = `/<industry>/<resource>/<id>/`. `action_id` dipakai **apa adanya**
    (uppercase `BUNDLE_QC`, bukan slug) supaya cocok dengan `Transition.action_id`
    di DB dan tidak perlu translasi di frontend.
    """
    if not prefix:
        return None

    return f"{ACTION_ENDPOINT_ROOT}{prefix}{action_id}/"


def chatter_event_payload(event) -> dict:
    """Satu event chatter dalam bentuk kontrak §8 (`ChatterEventSchema`).

    **Satu-satunya** serializer event chatter (Fase B.2): dipakai blok `chatter`
    di metadata DAN endpoint `GET /chatter/<resource>/<id>` (lewat
    `paginator.paginate_events(serializer=...)`) — supaya dua jalur itu tidak
    mungkin berbeda bentuk.
    """
    actor_id = getattr(event, "actor_id", None)
    actor_name = "System"
    if actor_id and getattr(event, "actor", None) is not None:
        actor_name = event.actor.get_username() or f"user#{actor_id}"

    payload = getattr(event, "payload", None)

    return {
        "id": str(event.pk),
        "actor": {"id": str(actor_id) if actor_id else "system", "name": actor_name},
        "type": event.event_type,
        "summary": event.text or "",
        # `payload` opsional di kontrak — tapi selalu dict (bukan null) supaya
        # `z.record(...)` Zod lolos walau event tidak punya data pendukung.
        "payload": payload if isinstance(payload, dict) else {},
        "created_at": event.ts.isoformat(),
    }


def build_state_machine_payload(
    machine_code: str,
    current_state: str,
    endpoint_prefix: str | None = None,
) -> dict:
    """Susun blok `state_machine` dari `core.state_machine` (data, bukan kode).

    `endpoint_prefix` (`/<industry>/<resource>/<id>/`) mengisi
    `allowed_actions[].endpoint` (Fase B.1.5); bila `None` key `endpoint` tidak
    dikirim (kontrak: opsional).
    """
    machine = StateMachine.objects.filter(code=machine_code, is_active=True).first()
    if machine is None:
        return {
            "current_state": current_state,
            "possible_states": [],
            "allowed_actions": [],
        }

    possible_states = state_entries_payload(
        list(machine.states.order_by("order", "code")), current_state
    )

    allowed_actions = []
    for transition in (
        Transition.objects.filter(
            machine=machine,
            from_state__code=current_state,
            is_active=True,
        )
        .select_related("to_state")
        .order_by("action_id")
    ):
        action = {
            "id": transition.action_id,
            "label": transition.label or transition.action_id,
            "mode": str(transition.mode).lower(),
        }
        endpoint = action_endpoint_payload(endpoint_prefix, transition.action_id)
        if endpoint is not None:
            action["endpoint"] = endpoint
        allowed_actions.append(action)

    return {
        "current_state": current_state,
        "possible_states": possible_states,
        "allowed_actions": allowed_actions,
    }


class BaseSchemaBuilder(ABC):
    """Base builder metadata resource (lihat docstring modul)."""

    SCHEMA_VERSION = SCHEMA_VERSION
    VIEW_TYPE = VIEW_TYPE_FORM

    #: Model Django pemilik resource; dipakai `SchemaView` untuk mengambil instance.
    MODEL = None
    #: Nama + label resource untuk blok `resource` (Fase B.1.1).
    RESOURCE_NAME = ""
    RESOURCE_LABEL = ""
    #: Opsional: relasi yang di-`select_related` view (hindari N+1).
    SELECT_RELATED: tuple[str, ...] = ()

    def __init__(self, instance, request, industry: str = "garmen"):
        self.instance = instance
        self.request = request
        self.industry = industry

    # ------------------------------------------------------------------ contract
    def build(self) -> dict:
        """Rakit metadata JSON resource (kontrak §1, bentuk Fase B.1)."""
        version = self.get_version()
        return {
            "schema_version": self.SCHEMA_VERSION,
            # Fase B.1.1: `resource` = OBJEK (dulu string).
            "resource": {
                "name": self.get_resource_name(),
                "label": self.get_resource_label(),
                "id": self.instance_id(),
                "version": version,
            },
            "view_type": self.VIEW_TYPE,
            "device_hint": self.get_device_hint(),
            "state_machine": self.get_state_machine(),
            "layout": self.get_layout(),
            "chatter": self.get_chatter(),
            # --- key tambahan (di luar kontrak; Zod frontend men-strip key asing)
            "industry": self.industry,
            "title": self.get_title(),
            "version": version,
        }

    # ---------------------------------------------------------------------- hooks
    @abstractmethod
    def get_resource_name(self) -> str:
        """Nama resource untuk frontend, mis. "work-orders"."""

    @abstractmethod
    def get_title(self) -> str:
        """Judul halaman, mis. "Bundle #12-L-001"."""

    @abstractmethod
    def get_version(self) -> str:
        """Hash state kritis (jadi `base_version` frontend, kontrak §2.3)."""

    @abstractmethod
    def get_device_hint(self) -> str:
        """Profil device yang diharapkan untuk resource ini."""

    @abstractmethod
    def get_state_machine(self) -> dict:
        """Blok `state_machine` (current_state + possible_states + allowed_actions)."""

    @abstractmethod
    def get_layout_sections(self) -> list[dict]:
        """Section + field **mentah** `[{section, fields}, ...]`.

        `get_layout()` yang membungkusnya ke bentuk kontrak §5.1
        (`{sections: [{id, label, fields}]}`) — Fase B.1.3.
        """

    @abstractmethod
    def get_chatter(self) -> dict:
        """Preview event terbaru + cursor (kontrak §8)."""

    # ------------------------------------------------------------------ derivasi
    def get_resource_label(self) -> str:
        """Label manusiawi resource (kontrak B.1.1); fallback ke nama resource."""
        return self.RESOURCE_LABEL or self.get_resource_name()

    def instance_id(self) -> str:
        """`resource.id` sebagai string (Zod `min(1)`); `""` kalau instance hilang."""
        return "" if self.instance is None else str(self.instance.pk)

    def action_endpoint_prefix(self) -> str | None:
        """Prefix path aksi kontrak §2: `/<industry>/<resource>/<id>/` (B.1.5)."""
        resource = self.get_resource_name()
        if self.instance is None or not resource:
            return None

        return f"/{self.industry}/{resource}/{self.instance.pk}/"

    def get_layout(self) -> dict:
        """`layout` kontrak §5.1: `{sections: [{id, label, fields}]}` (Fase B.1.3)."""
        return {
            "sections": [
                self.section_payload(raw) for raw in self.get_layout_sections()
            ]
        }

    # -------------------------------------------------------------------- helpers
    @classmethod
    def section_payload(cls, raw: dict) -> dict:
        """Bungkus satu section mentah `{section, fields}` → `{id, label, fields}`.

        `id` = slug stabil dari label (deterministik, tidak berubah antar build).
        """
        label = str(raw.get("label") or raw.get("section") or "")
        payload: dict[str, Any] = {
            "id": slugify(label),
            "label": label,
            "fields": list(raw.get("fields") or []),
        }
        if raw.get("columns") is not None:
            payload["columns"] = raw["columns"]
        return payload

    @staticmethod
    def field(
        name: str,
        type_: str,
        label: str,
        value: Any = None,
        read_only: bool = True,
        widget: str | None = None,
        **extra: Any,
    ) -> dict:
        """Satu field pada `layout` (Fase B.1.4).

        `type_` dinormalkan ke enum kontrak (`FIELD_TYPES`): `text` -> `string`.
        Tipe lama `widget-<nama>` dipecah jadi `type` (fallback `string`) +
        `widget`. `widget` eksplisit menang — mis. `garmen-qr-bundle`, nama yang
        terdaftar di `modules/garmen/register.ts`.

        `**extra` meneruskan atribut opsional kontrak (`required`, `min`, `max`,
        `step`, `maxLength`, ...) tanpa mengubah signature pemanggil lama.
        """
        field_type = FIELD_TYPE_ALIASES.get(type_, type_)
        widget_name = widget

        if isinstance(type_, str) and type_.startswith(WIDGET_TYPE_PREFIX):
            widget_name = widget or type_[len(WIDGET_TYPE_PREFIX) :]
            field_type = FIELD_TYPE_FALLBACK

        if field_type not in FIELD_TYPES:
            logger.warning(
                "field '%s': tipe '%s' tidak ada di enum kontrak -> '%s'.",
                name,
                type_,
                FIELD_TYPE_FALLBACK,
            )
            field_type = FIELD_TYPE_FALLBACK

        payload: dict[str, Any] = {
            "name": name,
            "type": field_type,
            "label": label,
            "value": value,
            "read_only": read_only,
        }
        if widget_name:
            payload["widget"] = widget_name

        payload.update(extra)
        return payload

    @staticmethod
    def empty_chatter() -> dict:
        """Chatter kosong untuk resource yang belum punya event log."""
        return {
            "preview": [],
            "total_count": 0,
            "has_more": False,
            "next_cursor": None,
        }

    @staticmethod
    def hash_state(*parts: Any) -> str:
        """SHA-256 dari bagian-bagian state kritis (resource tanpa field `version`)."""
        raw = "|".join("" if part is None else str(part) for part in parts)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
