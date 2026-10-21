"""URL analytics (B.2.4: settings + readiness; B.7 menambah metrics/health)."""

from __future__ import annotations

from django.urls import path

from .views import (
    AnalyticsDisableView,
    AnalyticsEnableView,
    AnalyticsHealthView,
    AnalyticsMetricView,
    AnalyticsMetricsView,
    AnalyticsReadinessView,
    AnalyticsSettingsView,
)

urlpatterns = [
    path(
        "settings/analytics/",
        AnalyticsSettingsView.as_view(),
        name="analytics_settings",
    ),
    path(
        "settings/analytics/enable/",
        AnalyticsEnableView.as_view(),
        name="analytics_enable",
    ),
    path(
        "settings/analytics/disable/",
        AnalyticsDisableView.as_view(),
        name="analytics_disable",
    ),
    path(
        "analytics/readiness/",
        AnalyticsReadinessView.as_view(),
        name="analytics_readiness",
    ),
    path(
        "analytics/metrics/<str:domain>/",
        AnalyticsMetricsView.as_view(),
        name="analytics_metrics",
    ),
    path(
        "analytics/metric/<str:metric_id>/",
        AnalyticsMetricView.as_view(),
        name="analytics_metric",
    ),
    path(
        "analytics/health/",
        AnalyticsHealthView.as_view(),
        name="analytics_health",
    ),
]

__all__ = ("urlpatterns",)

