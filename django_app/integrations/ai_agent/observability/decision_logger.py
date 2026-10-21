"""Decision logger + agregasi observability (F.1/F.3)."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from ..models import AIDecisionLog

logger = logging.getLogger(__name__)


def log_decision(**fields: Any) -> AIDecisionLog:
    """Simpan keputusan AI; field mengikuti AIDecisionLog."""
    return AIDecisionLog.objects.create(**fields)


def _query_hash(text: str) -> str:
    normalized = " ".join((text or "").lower().split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def aggregate_stats(
    date_from: datetime,
    date_to: datetime,
    group_by: str = "day",
) -> dict[str, Any]:
    """Agregat AIDecisionLog untuk dashboard observability (set-based)."""
    queryset = AIDecisionLog.objects.filter(
        timestamp__gte=date_from, timestamp__lte=date_to
    )

    totals_row = queryset.aggregate(
        requests=Count("id"),
        tokens_prompt=Sum("prompt_tokens"),
        tokens_completion=Sum("completion_tokens"),
        cost_usd=Sum("total_cost_usd"),
        cache_hits=Count("id", filter=Q(cache_hit=True)),
        hitl_required=Count("id", filter=Q(hitl_required=True)),
        hitl_approved=Count("id", filter=Q(hitl_decision="APPROVED")),
        hitl_rejected=Count("id", filter=Q(hitl_decision="REJECTED")),
        latency_avg_ms=Avg("latency_ms"),
    )

    totals = {
        "requests": int(totals_row["requests"] or 0),
        "tokens_prompt": int(totals_row["tokens_prompt"] or 0),
        "tokens_completion": int(totals_row["tokens_completion"] or 0),
        "cost_usd": float(totals_row["cost_usd"] or 0),
        "cache_hits": int(totals_row["cache_hits"] or 0),
        "hitl_required": int(totals_row["hitl_required"] or 0),
        "hitl_approved": int(totals_row["hitl_approved"] or 0),
        "hitl_rejected": int(totals_row["hitl_rejected"] or 0),
        "latency_avg_ms": float(totals_row["latency_avg_ms"] or 0),
    }

    by_day = [
        {
            "date": row["date"].isoformat() if row["date"] else "",
            "requests": int(row["requests"] or 0),
            "cost_usd": float(row["cost_usd"] or 0),
            "latency_avg_ms": float(row["latency_avg_ms"] or 0),
        }
        for row in queryset.annotate(date=TruncDate("timestamp"))
        .values("date")
        .annotate(
            requests=Count("id"),
            cost_usd=Sum("total_cost_usd"),
            latency_avg_ms=Avg("latency_ms"),
        )
        .order_by("date")
    ]

    by_gate = {
        row["decision_gate_result"]: int(row["count"] or 0)
        for row in queryset.values("decision_gate_result").annotate(count=Count("id"))
    }
    by_decision_gate = {
        "RULE_HIT": int(by_gate.get("RULE_HIT", 0)),
        "LLM_NEEDED": int(by_gate.get("LLM_NEEDED", 0)),
        "BLOCKED": int(by_gate.get("BLOCKED", 0)),
    }

    # JSON array `tools_called` tidak bisa di-aggregate set-based di SQLite/Postgres
    # tanpa fungsi jsonb; loop tipis ini hanya menyentuh kolom JSON (bukan seluruh baris).
    tool_stats: dict[str, dict[str, float]] = {}
    for tools in queryset.values_list("tools_called", flat=True):
        for call in tools or []:
            if not isinstance(call, dict):
                continue
            name = str(call.get("tool") or "").strip()
            if not name:
                continue
            bucket = tool_stats.setdefault(name, {"calls": 0, "duration_ms": 0.0})
            bucket["calls"] += 1
            duration = call.get("duration_ms")
            if isinstance(duration, (int, float)):
                bucket["duration_ms"] += float(duration)

    by_tool = [
        {
            "tool": name,
            "calls": int(bucket["calls"]),
            "avg_duration_ms": round(bucket["duration_ms"] / bucket["calls"], 2)
            if bucket["calls"]
            else 0,
        }
        for name, bucket in sorted(tool_stats.items(), key=lambda item: item[0])
    ]

    top_queries = [
        {"query_hash": _query_hash(row["query_text"]), "count": int(row["count"])}
        for row in queryset.values("query_text")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    ]

    requests = totals["requests"]
    decided = totals["hitl_approved"] + totals["hitl_rejected"]

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "group_by": group_by,
        "totals": totals,
        "by_day": by_day,
        "by_tool": by_tool,
        "by_decision_gate": by_decision_gate,
        "cache_hit_ratio": round(totals["cache_hits"] / requests, 4) if requests else 0.0,
        "hitl_approval_rate": round(totals["hitl_approved"] / decided, 4) if decided else 0.0,
        "top_queries": top_queries,
        "computed_at": timezone.now().isoformat(),
    }


__all__ = ("aggregate_stats", "log_decision")


