"""Seed registry `mcp-comparator` + `mcp-forecaster` (Sprint H T3)."""

from __future__ import annotations

from django.db import migrations

TOOLS = [
    {
        "name": "mcp-comparator",
        "mcp_endpoint_url": (
            "internal://integrations.ai_agent.mcp_servers.mcp_comparator"
        ),
        "schema": {
            "compare_periods": {
                "metric_id": "str",
                "period_a": "dict",
                "period_b": "dict",
                "group_by": "str?",
            },
            "compare_dimensions": {
                "metric_id": "str",
                "dimension_a": "dict",
                "dimension_b": "dict",
                "period_from": "str",
                "period_to": "str",
            },
        },
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-forecaster",
        "mcp_endpoint_url": (
            "internal://integrations.ai_agent.mcp_servers.mcp_forecaster"
        ),
        "schema": {
            "forecast_metric": {
                "metric_id": "str",
                "horizon_days": "int",
                "method": "str?",
            },
            "predict_completion": {"order_id": "int|str", "method": "str?"},
        },
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
]


def seed(apps, schema_editor):
    Tool = apps.get_model("ai_agent", "AIToolRegistry")
    for tool in TOOLS:
        Tool.objects.update_or_create(
            name=tool["name"],
            defaults={
                "mcp_endpoint_url": tool["mcp_endpoint_url"],
                "schema": tool["schema"],
                "read_only": True,
                "allowed_roles": tool["allowed_roles"],
                "rate_limit_per_minute": 60,
                "circuit_breaker_threshold": 5,
                "active": True,
            },
        )


def unseed(apps, schema_editor):
    Tool = apps.get_model("ai_agent", "AIToolRegistry")
    Tool.objects.filter(name__in=[tool["name"] for tool in TOOLS]).delete()


class Migration(migrations.Migration):
    dependencies = [("ai_agent", "0004_t2_mcp_registry")]

    operations = [migrations.RunPython(seed, unseed)]
