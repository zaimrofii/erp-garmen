"""MCP `event-log` (D.3) — riwayat BundleEvent per bundle/order."""

from __future__ import annotations

from datetime import datetime
from typing import Any

MAX_LIMIT = 200

SCHEMA = {
    "query": {
        "bundle_id": "int?",
        "order_id": "int?",
        "event_types": "list[str]?",
        "date_from": "str?",
        "date_to": "str?",
        "limit": "int",
    }
}


def _error(message: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "error": message, "status": status}


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def handle(params: dict, user=None) -> dict[str, Any]:
    """Handler `mcp-event-log` (read-only)."""
    del user

    from apps_industry.garment.models import BundleEvent

    bundle_id = params.get("bundle_id")
    order_id = params.get("order_id")
    if bundle_id is None and order_id is None:
        return _error("bundle_id_atau_order_id_wajib")

    queryset = BundleEvent.objects.all()
    if bundle_id is not None:
        queryset = queryset.filter(bundle_id=bundle_id)
    if order_id is not None:
        queryset = queryset.filter(bundle__work_order__order_line__order_id=order_id)

    event_types = params.get("event_types") or []
    if event_types:
        if not isinstance(event_types, list) or any(
            not isinstance(item, str) for item in event_types
        ):
            return _error("event_types_invalid")
        queryset = queryset.filter(event_type__in=event_types)

    date_from = _parse(params.get("date_from"))
    date_to = _parse(params.get("date_to"))
    if params.get("date_from") and date_from is None:
        return _error("date_from_invalid")
    if params.get("date_to") and date_to is None:
        return _error("date_to_invalid")
    if date_from is not None:
        queryset = queryset.filter(ts__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(ts__lte=date_to)

    limit = params.get("limit", MAX_LIMIT)
    if not isinstance(limit, int) or limit <= 0:
        return _error("limit_invalid")
    limit = min(limit, MAX_LIMIT)

    events = [
        {
            "ts": event.ts.isoformat(),
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "actor_username": event.actor.username if event.actor_id else None,
            "actor_name": (
                f"{event.actor.first_name} {event.actor.last_name}".strip()
                if event.actor_id
                else None
            ),
            "payload_summary": {
                key: str(value)[:50] for key, value in list(event.payload.items())[:5]
            },
        }
        for event in queryset.order_by("-ts")[:limit]
    ]
    return {"ok": True, "events": events, "count": len(events)}


def register(registry) -> None:
    registry.register("mcp-event-log", handle, SCHEMA)

