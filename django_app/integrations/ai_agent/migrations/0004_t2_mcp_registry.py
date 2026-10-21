"""Seed registry `mcp-aggregator` + `mcp-time-series` (Sprint H T2)."""

from __future__ import annotations

from django.db import migrations

TOOLS = [
    {
        "name": "mcp-aggregator",
        "mcp_endpoint_url": (
            "internal://integrations.ai_agent.mcp_servers.mcp_aggregator"
        ),
        "schema": {
            "aggregate": {
                "table": "str",
                "column": "str",
                "agg": "str",
                "filters": "dict?",
                "group_by": "str?",
            }
        },
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-time-series",
        "mcp_endpoint_url": (
            "internal://integrations.ai_agent.mcp_servers.mcp_time_series"
        ),
        "schema": {
            "get_metric_series": {
                "metric_id": "str",
                "granularity": "str",
                "period_from": "str?",
                "period_to": "str?",
                "group_by": "str?",
            }
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
    dependencies = [("ai_agent", "0003_odoo_rpc_schema")]

    operations = [migrations.RunPython(seed, unseed)]
