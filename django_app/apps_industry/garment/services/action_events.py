"""Jejak chatter + event bus untuk aksi resource (Fase E).

Sebelum Fase E action endpoint hanya mengubah `state`: tidak ada baris chatter
(tagihan lama Sprint 3) dan tidak ada event yang bisa diteruskan ke klien
real-time. Modul ini menutup celah itu **tanpa mengubah bentuk response aksi**
(kontrak B.2/C tetap utuh):

  1. satu baris `BundleEvent` (append-only — sudah jadi sumber chatter §8);
  2. `publisher.publish(...)` -> sinyal sinkron + Celery + group WebSocket.

Aturan penting: kegagalan di sini **tidak boleh** membatalkan aksi yang sudah
tersimpan (aksi produksi > jejak/real-time), jadi pemanggil membungkusnya dengan
try/except — lihat `ActionExecutor._record_event`.

Bundle event memakai `chatter_event_payload()` (serializer kontrak §8 yang sama
dengan metadata/chatter) sehingga klien bisa memvalidasi event real-time dengan
`ChatterEventSchema` yang sama. Aksi work-order **tidak** menulis `BundleEvent`
(chatter WO = gabungan event bundle-nya) sehingga payload-nya tanpa `event` —
klien memperbarui lewat `onInvalidate` seperti biasa.
"""

from __future__ import annotations

import logging

from apps_industry.garment.api.schema.builder import chatter_event_payload
from apps_industry.garment.models import BundleEvent
from core.event_bus import publisher, signals

logger = logging.getLogger(__name__)

__all__ = (
    "record_bundle_action",
    "record_resource_action",
    "record_work_order_action",
)


def record_bundle_action(
    *, bundle, action_id: str, to_state: str, request=None, fields: dict | None = None
) -> dict:
    """Tulis `BundleEvent` + publish `BUNDLE_STATE_CHANGED`; return payload event bus.

    FASE 4.3: `fields` (body aksi, mis. ``{"scrap_qty": 3, "reason": "stitch"}``
    untuk ``BUNDLE_SCRAP``) di-merge ke ``BundleEvent.payload`` — sebelumnya body
    aksi dibuang sehingga jejak scrap (qty + alasan) hilang. ``payload`` adalah
    **JSONField** milik `BundleEvent` (satu-satunya tempat data pendukung event;
    tidak ada field ``metadata`` terpisah), dan `chatter_event_payload()` sudah
    mengeksposnya → otomatis ikut terkirim ke chatter & event WebSocket tanpa
    perubahan serializer.
    """
    event_payload: dict = {"state": to_state}
    if fields:
        event_payload.update(fields)

    event = BundleEvent.objects.create(
        bundle=bundle,
        actor=_actor_from_request(request),
        event_type=str(action_id),
        text=f"{action_id} → {to_state}",
        payload=event_payload,
    )

    payload = {
        "bundle_id": bundle.pk,
        "bundle_code": str(getattr(bundle, "code", "") or ""),
        "action": str(action_id),
        "state": to_state,
        "version": str(getattr(bundle, "version", "") or ""),
        "event": chatter_event_payload(event),
    }
    publisher.publish(signals.BUNDLE_STATE_CHANGED, payload)
    return payload


def record_work_order_action(*, work_order, action_id: str, to_state: str) -> dict:
    """Publish `WORK_ORDER_STATE_CHANGED` untuk satu work order (tanpa `BundleEvent`)."""
    payload = {
        "wo_id": work_order.pk,
        "wo_code": str(getattr(work_order, "code", "") or ""),
        "action": str(action_id),
        "state": to_state,
        "version": str(getattr(work_order, "version", "") or ""),
    }
    publisher.publish(signals.WORK_ORDER_STATE_CHANGED, payload)
    return payload


def record_resource_action(
    *,
    resource_name: str,
    instance,
    action_id: str,
    to_state: str,
    request=None,
    fields: dict | None = None,
) -> dict | None:
    """Dispatch jejak event sesuai `resource_name` (``None`` kalau belum didukung).

    ``fields`` hanya dipakai resource ``bundles`` (work-order tidak menulis
    `BundleEvent`, jadi jejaknya hanya lewat event bus).
    """
    name = str(resource_name or "").strip().lower()
    if name == "bundles":
        return record_bundle_action(
            bundle=instance,
            action_id=action_id,
            to_state=to_state,
            request=request,
            fields=fields,
        )
    if name == "work-orders":
        return record_work_order_action(
            work_order=instance, action_id=action_id, to_state=to_state
        )

    logger.debug("resource '%s' belum punya jejak event (dilewati).", resource_name)
    return None


def _actor_from_request(request):
    """User terautentikasi dari request, atau `None` (AnonymousUser tidak valid FK)."""
    user = getattr(request, "user", None)
    return user if getattr(user, "is_authenticated", False) else None
