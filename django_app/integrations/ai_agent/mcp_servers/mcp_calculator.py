"""MCP `calculator` (D.3) — aritmetika deterministik, tanpa DB."""

from __future__ import annotations

from datetime import date
from typing import Any

SCHEMA = {"calc": {"operation": "str", "a": "num", "b": "num"}}

OPERATIONS = {"add", "subtract", "multiply", "divide", "percent", "date_diff"}


def _error(message: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "error": message, "status": status}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def handle(params: dict, user=None) -> dict[str, Any]:
    """Handler `mcp-calculator` (tanpa query DB)."""
    del user

    operation = params.get("operation")
    if operation not in OPERATIONS:
        return _error("operation_tidak_dikenal")

    if operation == "date_diff":
        try:
            start = date.fromisoformat(str(params.get("a")))
            end = date.fromisoformat(str(params.get("b")))
        except ValueError:
            return _error("tanggal_invalid")
        return {"ok": True, "result": (end - start).days}

    a = _number(params.get("a"))
    b = _number(params.get("b"))
    if a is None or b is None:
        return _error("angka_invalid")

    if operation == "add":
        result = a + b
    elif operation == "subtract":
        result = a - b
    elif operation == "multiply":
        result = a * b
    elif operation == "percent":
        result = a / 100 * b
    else:  # divide
        if b == 0:
            return _error("division_by_zero")
        result = a / b

    return {"ok": True, "result": result}


def register(registry) -> None:
    registry.register("mcp-calculator", handle, SCHEMA)

