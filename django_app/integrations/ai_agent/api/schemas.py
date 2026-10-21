"""Pydantic schemas chat AI (boundary validation) — CHAT-CONTRACT §2–§5."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ALLOWED_PAGE_TYPES = {"detail", "list", "form", "report"}
MAX_MESSAGE = 2000
MAX_HISTORY = 10
MAX_HISTORY_CHARS = 8000
MAX_FILTER_KEYS = 20
MAX_SNAPSHOT_KEYS = 40


class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_type: str | None = None
    route: str | None = Field(default=None, max_length=300)
    resource_type: str | None = None
    resource_id: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    visible_fields_snapshot: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE)
    context: ChatContext | None = None
    history: list[HistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY)
    channel: Literal["DESKTOP", "FLOATING", "WA"] = "DESKTOP"


def validate_context(context: ChatContext | None) -> str | None:
    """Kembalikan pesan error (→ 400 bad_context) atau ``None`` bila valid."""
    if context is None:
        return None

    page_type = context.page_type
    if page_type is not None and page_type not in ALLOWED_PAGE_TYPES:
        return "page_type tidak dikenal"

    resource_type = context.resource_type
    resource_id = context.resource_id

    if resource_id is not None:
        if not isinstance(resource_id, str) or not resource_id.strip():
            return "resource_id harus string tidak kosong"
        if not resource_type:
            return "resource_type wajib bila resource_id terisi"
    elif resource_type and page_type not in {"list", "report"}:
        return "resource_type wajib null bila resource_id null"

    if len(context.filters) > MAX_FILTER_KEYS:
        return "filters melebihi 20 key"
    if any(
        isinstance(value, str) and len(value) > 200
        for value in context.filters.values()
    ):
        return "nilai filters melebihi 200 karakter"

    if len(context.visible_fields_snapshot) > MAX_SNAPSHOT_KEYS:
        return "visible_fields_snapshot melebihi 40 field"
    if any(
        isinstance(value, str) and len(value) > 500
        for value in context.visible_fields_snapshot.values()
    ):
        return "nilai visible_fields_snapshot melebihi 500 karakter"

    return None


def validate_history(history: list[HistoryItem]) -> str | None:
    if len(history) > MAX_HISTORY:
        return "history melebihi 10 item"
    if sum(len(item.content) for item in history) > MAX_HISTORY_CHARS:
        return "history melebihi 8000 karakter"
    return None


__all__ = ("ChatContext", "ChatRequest", "HistoryItem", "validate_context", "validate_history")
