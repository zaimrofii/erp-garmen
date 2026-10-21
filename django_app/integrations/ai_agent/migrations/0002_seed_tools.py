"""Seed 8 MCP server ke AIToolRegistry (D.1.5).

Sumber: docs/ai/MCP-REGISTRY.md §2. Idempoten (update_or_create by name).
"""

from __future__ import annotations

from django.db import migrations

TOOLS = [
    {
        "name": "mcp-postgres-query",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_postgres_query",
        "schema": {
            "query": {"table": "str", "columns": "list[str]", "filters": "dict", "limit": "int"}
        },
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-event-log",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_event_log",
        "schema": {"query": {"bundle_id": "int?", "order_id": "int?", "event_types": "list[str]?"}},
        "allowed_roles": ["operator", "supervisor", "qc", "owner", "admin"],
    },
    {
        "name": "mcp-odoo-rpc",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_odoo_rpc",
        "schema": {"read": {"model": "str", "domain": "list", "fields": "list[str]"}},
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-calculator",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_calculator",
        "schema": {"calc": {"operation": "str", "a": "num", "b": "num"}},
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-rule-engine",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_rule_engine",
        "schema": {"evaluate": {"rule_code": "str", "facts": "dict"}},
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-knowledge-graph",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_knowledge_graph",
        "schema": {"traverse": {"entity": "str", "entity_id": "str"}},
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-vector-search",
        "mcp_endpoint_url": "internal://integrations.ai_agent.mcp_servers.mcp_vector_search",
        "schema": {"search": {"query": "str", "top_k": "int"}},
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
    {
        "name": "mcp-analytics",
        "mcp_endpoint_url": "internal://integrations.analytics.mcp_bridge",
        "schema": {
            "get_metric": {"metric_id": "str", "dimension": "str"},
            "list_metrics": {"domain": "str"},
        },
        "allowed_roles": ["supervisor", "owner", "admin"],
    },
]

NAMES = [tool["name"] for tool in TOOLS]


def seed_tools(apps, schema_editor):
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


def unseed_tools(apps, schema_editor):
    Tool = apps.get_model("ai_agent", "AIToolRegistry")
    Tool.objects.filter(name__in=NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [("ai_agent", "0001_initial")]

    operations = [migrations.RunPython(seed_tools, unseed_tools)]
