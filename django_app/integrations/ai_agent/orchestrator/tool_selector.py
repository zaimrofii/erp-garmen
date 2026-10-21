"""Tool selector (G.2) — intent → MCP yang relevan (read-only)."""

from __future__ import annotations

import re

from .text_normalizer import normalize

TOOL_MAP: dict[str, list[str]] = {
    "ANALYTICS_QUERY": ["mcp-analytics"],
    "DATA_LOOKUP": ["mcp-postgres-query"],
    "DIAGNOSTIC": ["mcp-analytics", "mcp-event-log"],
    "GENERAL_CHAT": [],
    "UNKNOWN": [],
}

_ODOO_KEYWORDS = ("odoo",)
_ODOO_WORD = re.compile(r"\b(po|so)\b", re.IGNORECASE)
_ODOO_CANONICALS = frozenset({"invoice", "purchase_order", "stok"})
_RULE_KEYWORDS = ("boleh", "cukup", "lanjut")
_AGG_KEYWORDS = ("total", "rata-rata", "p50", "p90")
_SERIES_KEYWORDS = ("tren", "historis", "per jam", "30 hari")
_COMPARE_KEYWORDS = ("kenapa", "banding", "vs", "dibanding")
_COMPARE_WORD = re.compile(r"lebih\s+(lambat|cepat|baik|buruk)", re.IGNORECASE)
_FORECAST_KEYWORDS = ("prediksi", "forecast", "kapan selesai", "estimasi")
_BALANCE_KEYWORDS = ("line balance", "line_balance", "seimbang", "balance")
_BOTTLENECK_KEYWORDS = ("bottleneck", "penyumbat", "hambatan", "menumpuk")
_FORECAST_WORD = re.compile(r"kapan\s+.*selesai", re.IGNORECASE)
_ENTITY_POSTGRES = re.compile(
    r"\border\b|\bwork order\b|\bbundle\b|\bcustomer\b|\bproduk\b|"
    r"\bpartner\b|nilai stok",
    re.IGNORECASE,
)
_POSTGRES_CANONICALS = frozenset(
    {"produk", "order", "work_order", "bundle", "customer", "partner"}
)
_DIMENSION_ANALYTICS = re.compile(
    r"\bwork center\b|\bwc\b|\bline\b|paling sibuk|paling lambat",
    re.IGNORECASE,
)
_ANALYTICS_CANONICALS = frozenset(
    {"work_center", "production_line", "scrap", "rework", "lead_time"}
)


def _mentions_odoo(message: str, canonicals: set[str]) -> bool:
    text = (message or "").lower()
    if any(keyword in text for keyword in _ODOO_KEYWORDS):
        return True
    if _ODOO_WORD.search(text):
        return True
    return bool(canonicals & _ODOO_CANONICALS)


def select_tools(
    intent: str, context: dict | None = None, message: str = ""
) -> list[str]:
    """Daftar MCP unik; konteks resource / keyword Odoo menambah tool."""
    tools = list(TOOL_MAP.get(str(intent or "").upper(), []))
    normalized = normalize(message)
    text = normalized["normalized"]
    canonicals = set(normalized["canonicals"])

    resource_type = (context or {}).get("resource_type")
    if resource_type and "mcp-postgres-query" not in tools:
        tools.append("mcp-postgres-query")

    normalized_intent = str(intent or "").upper()
    if _mentions_odoo(message, canonicals) and "mcp-odoo-rpc" not in tools:
        tools.append("mcp-odoo-rpc")
    if (
        canonicals & _POSTGRES_CANONICALS or _ENTITY_POSTGRES.search(text)
    ) and "mcp-postgres-query" not in tools:
        tools.append("mcp-postgres-query")
    if (
        canonicals & _ANALYTICS_CANONICALS or _DIMENSION_ANALYTICS.search(text)
    ) and "mcp-analytics" not in tools:
        tools.append("mcp-analytics")

    # R.4 — metrik line_balance / bottleneck selalu butuh mcp-analytics.
    if any(
        keyword in text for keyword in _BALANCE_KEYWORDS + _BOTTLENECK_KEYWORDS
    ) and "mcp-analytics" not in tools:
        tools.append("mcp-analytics")

    if normalized_intent == "DIAGNOSTIC" and any(
        keyword in text for keyword in _RULE_KEYWORDS
    ):
        if "mcp-rule-engine" not in tools:
            tools.append("mcp-rule-engine")
    if normalized_intent == "DIAGNOSTIC" and (
        any(keyword in text for keyword in _COMPARE_KEYWORDS)
        or _COMPARE_WORD.search(text)
    ):
        if "mcp-comparator" not in tools:
            tools.append("mcp-comparator")
    if normalized_intent == "ANALYTICS_QUERY":
        if any(keyword in text for keyword in _AGG_KEYWORDS) and (
            "mcp-aggregator" not in tools
        ):
            tools.append("mcp-aggregator")
        if any(keyword in text for keyword in _SERIES_KEYWORDS) and (
            "mcp-time-series" not in tools
        ):
            tools.append("mcp-time-series")
        if (
            any(keyword in text for keyword in _FORECAST_KEYWORDS)
            or _FORECAST_WORD.search(text)
        ) and ("mcp-forecaster" not in tools):
            tools.append("mcp-forecaster")

    return tools


__all__ = ("TOOL_MAP", "select_tools")
