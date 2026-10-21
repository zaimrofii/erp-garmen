"""AppConfig AI Agent — autodiscover MCP saat Django siap."""

from __future__ import annotations

import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class AiAgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.ai_agent"
    verbose_name = "AI Agent"

    def ready(self) -> None:
        from .mcp_servers import registry

        count = registry.discover_mcp_servers()
        logger.info("ai_agent: %d MCP server terdaftar.", count)
