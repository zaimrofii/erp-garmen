"""Kontrak tool produksi AI Agent (Fase 1).

`ToolResult` = envelope seragam untuk semua tool:
    {data, row_count, truncated, as_of, filters_applied, warnings, error}

`ToolSpec` = metadata yang dibutuhkan registry + function calling (nama, deskripsi,
JSON Schema, allowlist role, handler).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from django.utils import timezone

MAX_LIMIT = 100

#: Kode error standar (dipakai API + observability).
TOOL_NOT_FOUND = "tool_not_found"
INVALID_ARGUMENT = "invalid_argument"
FORBIDDEN = "forbidden"
NO_DATA = "no_data"
ERP_NOT_CONFIGURED = "erp_not_configured"
INTERNAL_ERROR = "internal_error"


def _now_iso() -> str:
    return timezone.now().isoformat()


@dataclass
class ToolResult:
    """Hasil satu eksekusi tool (selalu dikembalikan, tidak pernah raise)."""

    data: dict = field(default_factory=dict)
    row_count: int = 0
    truncated: bool = False
    as_of: str = ""
    filters_applied: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.as_of:
            self.as_of = _now_iso()

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "error": self.error,
            "data": self.data,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "as_of": self.as_of,
            "filters_applied": self.filters_applied,
            "warnings": self.warnings,
        }

    @classmethod
    def success(
        cls,
        data: dict,
        *,
        row_count: int = 0,
        truncated: bool = False,
        filters_applied: dict | None = None,
        warnings: list[str] | None = None,
    ) -> "ToolResult":
        return cls(
            data=data,
            row_count=row_count,
            truncated=truncated,
            filters_applied=filters_applied or {},
            warnings=list(warnings or []),
        )

    @classmethod
    def failure(cls, error: str, detail: str = "") -> "ToolResult":
        warnings = [detail] if detail else []
        if error == NO_DATA and not warnings:
            warnings = ["no_data"]
        return cls(data={}, error=error, warnings=warnings)


@dataclass(frozen=True)
class ToolSpec:
    """Spesifikasi tool yang bisa dipanggil agent."""

    name: str
    description: str
    parameters: dict
    roles: frozenset[str]
    handler: Callable[..., ToolResult]

    def schema(self) -> dict:
        """Format OpenAI-compatible `tools` payload."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def allows(self, role: str) -> bool:
        return str(role or "").strip().upper() in self.roles


def fn_schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def clamp_limit(value: Any, default: int = 20, maximum: int = MAX_LIMIT) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"limit tidak valid: {value!r}") from exc


def parse_iso_date(value: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} harus ISO date (YYYY-MM-DD)") from exc


def require_date_range(date_from: Any, date_to: Any) -> tuple[date, date] | None:
    """Validasi periode. Keduanya kosong -> None (snapshot/tanpa periode)."""
    if not date_from and not date_to:
        return None
    end = parse_iso_date(date_to, "date_to") if date_to else timezone.localdate()
    start = parse_iso_date(date_from, "date_from") if date_from else end - timedelta(days=6)
    if start > end:
        raise ValueError("date_from tidak boleh setelah date_to")
    return start, end


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


# --- Shared query layer (dipindahkan dari spike_tools_v2/v3) -------------------

ENTITIES = ("product", "order", "customer", "bundle", "work_center", "work_order")
AGG_ENTITIES = ENTITIES + ("scrap", "orderline")
OPS = ("sum", "avg", "count", "min", "max", "count_distinct")
FILTERABLE: dict[str, set[str]] = {
    "product": {"id", "code", "name", "category", "sale_price", "cost_price", "is_active"},
    "order": {"id", "code", "state", "customer_id", "created_at", "deadline", "completed_at"},
    "customer": {"id", "code", "name", "city", "is_customer", "is_vendor", "is_active"},
    "bundle": {
        "id",
        "code",
        "state",
        "qty",
        "qty_done",
        "work_order_id",
        "production_line_id",
        "current_work_center__code",
        "created_at",
    },
    "work_center": {"id", "code", "name", "wc_type", "is_active"},
    "work_order": {"id", "code", "state", "order_line_id", "order_line__order__code"},
    "scrap": {
        "id",
        "qty",
        "rework_qty",
        "end_loss_qty",
        "work_center__code",
        "bundle__state",
        "created_at",
    },
    "orderline": {"id", "order__code", "product_id", "product__name", "qty", "price_unit"},
}
GROUP_ALIASES: dict[str, dict[str, str]] = {
    "scrap": {
        "work_center": "work_center__code",
        "bundle": "bundle__code",
        "state": "bundle__state",
    },
    "order": {"customer": "customer__name", "state": "state"},
    "orderline": {"product": "product__name", "order": "order__code"},
    "product": {"category": "category"},
    "bundle": {
        "work_center": "current_work_center__code",
        "state": "state",
        "product": "work_order__order_line__product__name",
    },
    "work_order": {"state": "state"},
    "customer": {"city": "city"},
    "work_center": {"type": "wc_type"},
}
METRICS = (
    "garment.bottleneck",
    "garment.buffer_status",
    "garment.lead_time",
    "garment.line_balance",
    "garment.oee",
    "garment.rework_rate",
    "garment.scrap_rate",
    "garment.wc_idle_status",
    "garment.wip_flow",
)
DATE_FIELD = {
    "order": "created_at",
    "bundle": "created_at",
    "work_order": "created_at",
    "scrap": "created_at",
}


def model_for(entity: str):
    from apps_industry.garment.models import (
        Bundle,
        Order,
        OrderLine,
        ScrapAccumulator,
        WorkCenter,
        WorkOrder,
    )
    from master.models import Partner, Product

    mapping = {
        "product": Product,
        "order": Order,
        "customer": Partner,
        "bundle": Bundle,
        "work_center": WorkCenter,
        "work_order": WorkOrder,
        "scrap": ScrapAccumulator,
        "orderline": OrderLine,
    }
    key = str(entity or "").strip().lower()
    if key not in mapping:
        raise ValueError(f"entity tidak diizinkan: {entity!r}")
    return mapping[key]


def repo_for(entity: str):
    from integrations.ai_agent.data_access.registry import get_repo

    key = str(entity or "").strip().lower()
    if key not in ENTITIES:
        raise ValueError(f"entity tidak diizinkan: {entity!r}")
    repo = get_repo(key)
    if repo is None:
        raise ValueError(f"repository tidak ditemukan: {entity!r}")
    return repo


def clean_filters(entity: str, filters: Any) -> dict:
    if not filters:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("filters harus object")
    allowed = FILTERABLE[str(entity).strip().lower()]
    cleaned = {}
    for key, value in filters.items():
        key = str(key)
        if not any(key == item or key.startswith(f"{item}__") for item in allowed):
            raise ValueError(f"filter tidak diizinkan untuk {entity}: {key!r}")
        cleaned[key] = value
    return cleaned


def date_criteria(entity: str, date_from: Any, date_to: Any) -> dict:
    """Filter tanggal eksplisit; tanpa periode -> tanpa filter (snapshot)."""
    field_name = DATE_FIELD.get(str(entity).strip().lower())
    if field_name is None or (not date_from and not date_to):
        return {}
    period = require_date_range(date_from, date_to)
    if period is None:
        return {}
    start, end = period
    return {f"{field_name}__date__gte": start, f"{field_name}__date__lte": end}


def order_derived(record: dict) -> dict:
    """Tambahkan is_late / days_late / days_remaining ke baris order."""
    deadline = parse_datetime(record.get("deadline"))
    completed = parse_datetime(record.get("completed_at"))
    now = timezone.now()
    is_late = bool(deadline and completed and completed > deadline)
    record["is_late"] = is_late
    record["days_late"] = (completed - deadline).days if is_late else 0
    record["days_remaining"] = (deadline - now).days if deadline and not completed else None
    return record


__all__ = (
    "AGG_ENTITIES",
    "DATE_FIELD",
    "ENTITIES",
    "FILTERABLE",
    "GROUP_ALIASES",
    "METRICS",
    "OPS",
    "clean_filters",
    "date_criteria",
    "model_for",
    "order_derived",
    "repo_for",
)



__all__ = (
    "ERP_NOT_CONFIGURED",
    "FORBIDDEN",
    "INTERNAL_ERROR",
    "INVALID_ARGUMENT",
    "MAX_LIMIT",
    "NO_DATA",
    "TOOL_NOT_FOUND",
    "ToolResult",
    "ToolSpec",
    "clamp_limit",
    "fn_schema",
    "parse_datetime",
    "parse_iso_date",
    "require_date_range",
)
