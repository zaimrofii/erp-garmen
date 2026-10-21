"""Views endpoint analytics (B.2 settings/readiness + B.7 metrics/health).

Auth: `IsAuthenticated` (anonim 403) + guard role analytics
(`supervisor`/`owner`/`admin`; superuser selalu boleh).
Bentuk response: docs/analytics/CONTRACT.md §2.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from master.api import require_master_admin

from ..config import ANALYTICS_CONFIG
from ..core import registry
from ..core.event_listener import (
    ANALYTICS_CONFIG_CHANGED,
    SYNC_RECORD_CHANGED,
)
from core.event_bus.registry import get_listeners
from core.event_bus.signals import BUNDLE_STATE_CHANGED, SCRAP_RECORDED

from ..services import analytics_config_services as services

ANALYTICS_ROLE_CODES = {"SUPERVISOR", "OWNER", "ADMIN"}
GROUP_BY_VALUES = {"period", "work_center", "line"}


def _analytics_role_ok(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper() in ANALYTICS_ROLE_CODES


def require_analytics_role(request) -> None:
    """403 kalau role bukan supervisor/owner/admin."""
    if not _analytics_role_ok(request.user):
        raise PermissionDenied("Anda tidak berhak melihat analitik.")


def _validation_detail(exc: ValidationError) -> str:
    messages = getattr(exc, "messages", None) or [str(exc)]
    return "; ".join(str(message) for message in messages)


def _parse_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"{field} bukan ISO-8601") from None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _resolve_range(request) -> tuple[datetime, datetime, dict]:
    """Prioritas: `period=YYYY-MM` > `date_from`/`date_to` > bulan berjalan."""
    echo = {key: request.query_params[key] for key in request.query_params}

    period = request.query_params.get("period")
    if period:
        try:
            start = datetime.strptime(period, "%Y-%m")
        except ValueError:
            raise ValidationError("period harus format YYYY-MM") from None
        start = timezone.make_aware(start)
        if start.month == 12:
            end = timezone.make_aware(datetime(start.year + 1, 1, 1))
        else:
            end = timezone.make_aware(datetime(start.year, start.month + 1, 1))
        return start, end - timedelta(microseconds=1), echo

    raw_from = request.query_params.get("date_from")
    raw_to = request.query_params.get("date_to")
    now = timezone.localtime()
    default_from = timezone.make_aware(
        datetime(now.year, now.month, 1, 0, 0, 0)
    )
    start = _parse_datetime(raw_from, "date_from") if raw_from else default_from
    # Bulatkan `end` default ke MENIT supaya cache key stabil dalam 1 menit
    # (kalau memakai now() presisi mikrodetik, cache tidak pernah hit).
    end = (
        _parse_datetime(raw_to, "date_to")
        if raw_to
        else timezone.now().replace(second=0, microsecond=0)
    )

    if start > end:
        raise ValidationError("rentang tanggal tidak valid")

    return start, end, echo


def _base_payload(*, rows, summary, group_by, echo, start, end, cached, config) -> dict:
    from ..plugins.garment.models import MetricSnapshot

    return {
        "rows": rows,
        "summary": summary,
        "group_by": group_by,
        "filters": {
            "echo": echo,
            "resolved_from": start.isoformat() if start else None,
            "resolved_to": end.isoformat() if end else None,
        },
        "period": {
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
        },
        "generated_at": timezone.localtime(timezone.now()).isoformat(),
        "cached": cached,
        "enabled": bool(config.enabled),
        "disabled_reason": None if config.enabled else "analytics_disabled",
        "historical_data_available": MetricSnapshot.objects.exists(),
    }


def _cache_key(scope: str, params: dict) -> str:
    digest = hashlib.sha1(
        json.dumps(params, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"analytics:{services.cache_version()}:{scope}:{digest}"


def _overall_value(metric, filters: dict):
    """Nilai agregat satu metrik (weighted) untuk listing domain."""
    rows = metric.compute({**filters, "group_by": "period"})
    numerator = sum(row.get("numerator") or 0 for row in rows)
    denominator = sum(row.get("denominator") or 0 for row in rows)
    if denominator:
        return round(numerator / denominator * 100, 6)

    # lead_time: rata-rata berbobot n_bundles.
    total_n = sum(row.get("n_bundles") or 0 for row in rows)
    if total_n:
        weights = sum((row.get("value") or 0) * (row.get("n_bundles") or 0) for row in rows)
        return round(weights / total_n, 6)
    return None


class AnalyticsMetricsView(APIView):
    """`GET /api/v1/analytics/metrics/<domain>/` — daftar metrik domain."""

    permission_classes = [IsAuthenticated]

    def get(self, request, domain):
        require_analytics_role(request)

        try:
            start, end, echo = _resolve_range(request)
            group_by = request.query_params.get("group_by") or "period"
            if group_by not in GROUP_BY_VALUES:
                raise ValidationError("group_by tidak dikenal")
            granularity = request.query_params.get("granularity") or "day"
        except ValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metrics = registry.list_metrics(domain)
        if not metrics:
            return Response(
                {"detail": "domain tidak dikenal"}, status=status.HTTP_404_NOT_FOUND
            )

        config = services.get_config()
        nocache = request.query_params.get("_nocache") == "1"
        key = _cache_key(
            f"domain:{domain}",
            {
                "group_by": group_by,
                "granularity": granularity,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "wc": request.query_params.get("work_center_id"),
                "line": request.query_params.get("line_id"),
            },
        )

        if not nocache:
            cached = cache.get(key)
            if cached is not None:
                return Response({**cached, "cached": True})

        if not config.enabled:
            payload = _base_payload(
                rows=[],
                summary={},
                group_by=None,
                echo=echo,
                start=None,
                end=None,
                cached=False,
                config=config,
            )
        else:
            filters = {
                "granularity": granularity,
                "group_by": group_by,
                "date_from": start,
                "date_to": end,
                "work_center_id": request.query_params.get("work_center_id"),
                "line_id": request.query_params.get("line_id"),
            }
            rows = []
            enabled_metrics = []
            for metric in metrics:
                if not services.is_metric_enabled(metric.metric_id):
                    continue
                enabled_metrics.append(metric.metric_id)
                rows.append(
                    {
                        "key": metric.metric_id,
                        "label": metric.label,
                        "unit": metric.unit,
                        "value": _overall_value(metric, filters),
                    }
                )

            payload = _base_payload(
                rows=rows,
                summary={
                    "metric_count": len(rows),
                    "enabled_metrics": enabled_metrics,
                },
                group_by=group_by,
                echo=echo,
                start=start,
                end=end,
                cached=False,
                config=config,
            )

        if not nocache:
            cache.set(key, payload, ANALYTICS_CONFIG["cache_ttl_seconds"])

        return Response(payload)


class AnalyticsMetricView(APIView):
    """`GET /api/v1/analytics/metric/<metric_id>/` — satu metrik + metadata."""

    permission_classes = [IsAuthenticated]

    def get(self, request, metric_id):
        require_analytics_role(request)

        try:
            metric = registry.get_metric(metric_id)
        except KeyError:
            return Response(
                {"detail": "metrik tidak dikenal"}, status=status.HTTP_404_NOT_FOUND
            )

        try:
            start, end, echo = _resolve_range(request)
            group_by = request.query_params.get("group_by") or "period"
            if group_by not in GROUP_BY_VALUES:
                raise ValidationError("group_by tidak dikenal")
            granularity = request.query_params.get("granularity") or (
                metric.granularities[-1]
            )
            if granularity not in metric.granularities:
                raise ValidationError("granularity tidak didukung metrik ini")
        except ValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = services.get_config()
        nocache = request.query_params.get("_nocache") == "1"
        key = _cache_key(
            f"metric:{metric_id}",
            {
                "group_by": group_by,
                "granularity": granularity,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "wc": request.query_params.get("work_center_id"),
                "line": request.query_params.get("line_id"),
            },
        )

        if not nocache:
            cached = cache.get(key)
            if cached is not None:
                return Response({**cached, "cached": True})

        metadata = {
            "metric_id": metric.metric_id,
            "label": metric.label,
            "unit": metric.unit,
            "granularity": granularity,
            "source_models": list(metric.source_models),
            "formula_version": metric.formula_version,
            "null_policy": metric.null_policy,
        }
        filters = {
            "granularity": granularity,
            "date_from": start,
            "date_to": end,
            "work_center_id": request.query_params.get("work_center_id"),
            "line_id": request.query_params.get("line_id"),
        }

        if not config.enabled:
            payload = _base_payload(
                rows=[],
                summary={"metadata": metadata},
                group_by=None,
                echo=echo,
                start=None,
                end=None,
                cached=False,
                config=config,
            )
        elif not services.is_metric_enabled(metric_id):
            payload = _base_payload(
                rows=[],
                summary={"metadata": metadata, "reason": "metric_not_enabled"},
                group_by=group_by,
                echo=echo,
                start=start,
                end=end,
                cached=False,
                config=config,
            )
        else:
            rows = metric.compute({**filters, "group_by": group_by})
            payload = _base_payload(
                rows=rows,
                summary={
                    "metadata": metadata,
                    "value": _overall_value(metric, filters),
                },
                group_by=group_by,
                echo=echo,
                start=start,
                end=end,
                cached=False,
                config=config,
            )

        if not nocache:
            cache.set(key, payload, ANALYTICS_CONFIG["cache_ttl_seconds"])

        return Response(payload)


class AnalyticsHealthView(APIView):
    """`GET /api/v1/analytics/health/` — selalu 200 (bahkan OFF)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_analytics_role(request)

        from ..plugins.garment.models import MetricSnapshot

        config = services.get_config()
        listeners = 0
        for event_name in (
            BUNDLE_STATE_CHANGED,
            SCRAP_RECORDED,
            SYNC_RECORD_CHANGED,
            ANALYTICS_CONFIG_CHANGED,
        ):
            listeners += len(get_listeners(event_name))

        last_snapshot = MetricSnapshot.objects.order_by("-computed_at").first()
        now = timezone.localtime(timezone.now()).isoformat()

        return Response(
            {
                "ok": True,
                "enabled": bool(config.enabled),
                "disabled_reason": None if config.enabled else "analytics_disabled",
                "registry": {
                    "metrics_registered": len(registry.list_metrics()),
                    "metrics_active": len(registry.list_metrics("garment")),
                },
                "listeners": {"subscribed": listeners},
                "stream": {"connected": None, "backend": "redis"},
                "storage": {
                    "snapshots_total": MetricSnapshot.objects.count(),
                    "last_snapshot_at": (
                        timezone.localtime(last_snapshot.computed_at).isoformat()
                        if last_snapshot
                        else None
                    ),
                    "historical_data_available": MetricSnapshot.objects.exists(),
                },
                "toggle": {"checked_at": now, "source": "service_layer"},
                "generated_at": now,
            }
        )






class AnalyticsSettingsView(APIView):
    """`GET|PUT /api/v1/settings/analytics/` (ADMIN/OWNER)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_master_admin(request)
        return Response(services.config_payload(services.get_config()))

    def put(self, request):
        require_master_admin(request)

        if "enabled" in request.data:
            return Response(
                {"detail": "enabled hanya lewat endpoint enable/disable"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        config = services.get_config()
        domains = request.data.get(
            "enabled_domains", list(config.enabled_domains or [])
        )
        metrics = request.data.get(
            "enabled_metrics", list(config.enabled_metrics or [])
        )

        try:
            payload = services.update_filters(
                domains, metrics, user=request.user, request=request
            )
        except ValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(payload)


class AnalyticsEnableView(APIView):
    """`POST /api/v1/settings/analytics/enable/` — readiness pass setiap kali."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_master_admin(request)

        try:
            payload = services.enable(
                request.user,
                request.data.get("enabled_domains"),
                request.data.get("enabled_metrics"),
            )
        except services.ReadinessFailed as exc:
            return Response(
                {
                    "detail": "Kesiapan data belum terpenuhi",
                    "blockers": exc.blockers,
                    "checked_at": exc.checked_at,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except ValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(payload)


class AnalyticsDisableView(APIView):
    """`POST /api/v1/settings/analytics/disable/` — alasan wajib."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_master_admin(request)

        try:
            payload = services.disable(
                request.data.get("reason", ""), user=request.user, request=request
            )
        except ValidationError as exc:
            return Response(
                {"detail": _validation_detail(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(payload)


class AnalyticsReadinessView(APIView):
    """`GET /api/v1/analytics/readiness/` — readiness tanpa mengubah state."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_master_admin(request)
        return Response(services.readiness_report())

