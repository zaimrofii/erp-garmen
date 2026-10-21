"""Policy checker HITL (F.1) — PURE."""

from __future__ import annotations

from typing import Any

APPROVER_ROLES = ("SUPERVISOR", "OWNER")


def check(risk_level: str, user_role: str) -> dict[str, Any]:
    """Tentukan apakah aksi boleh diajukan dan role approver yang dibutuhkan."""
    risk = str(risk_level or "").upper()
    role = str(user_role or "").strip().upper()

    if risk == "LOW":
        return {"allowed": True, "required_role": None, "reason": None}

    required = "OWNER" if risk == "HIGH" else "SUPERVISOR"

    if role in ("OPERATOR", "QC") and risk in ("MEDIUM", "HIGH"):
        return {
            "allowed": False,
            "required_role": required,
            "reason": "operator_tidak_boleh_write",
        }

    return {"allowed": True, "required_role": required, "reason": None}


__all__ = ("check",)

