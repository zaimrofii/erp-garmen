"""Registry MCP in-memory (autodiscover `mcp_*.py`)."""

from __future__ import annotations

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, dict] = {}
_DISCOVERED = False


class _Registrar:
    """API sempit untuk modul MCP mendaftarkan handler-nya."""

    def register(self, name: str, handler, schema: dict) -> None:
        if name in _REGISTRY:
            raise ValueError(f"MCP duplikat: {name}")
        _REGISTRY[name] = {"name": name, "handler": handler, "schema": schema}


_REGISTRAR = _Registrar()


def discover_mcp_servers() -> int:
    """Impor semua `mcp_*.py` dan panggil `register(...)` (idempoten)."""
    global _DISCOVERED
    if _DISCOVERED:
        return len(_REGISTRY)

    import integrations.ai_agent.mcp_servers as package

    for module_info in pkgutil.iter_modules(package.__path__):
        if not module_info.name.startswith("mcp_"):
            continue

        module = importlib.import_module(f"{package.__name__}.{module_info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(_REGISTRAR)

    _DISCOVERED = True
    logger.info("ai_agent: %d MCP server terdaftar.", len(_REGISTRY))
    return len(_REGISTRY)


def get_mcp(name: str) -> dict:
    if not _DISCOVERED:
        discover_mcp_servers()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"MCP tidak terdaftar: {name}") from None


def list_mcp() -> list[str]:
    if not _DISCOVERED:
        discover_mcp_servers()
    return sorted(_REGISTRY)


def _reset_for_tests() -> None:
    global _DISCOVERED
    _REGISTRY.clear()
    _DISCOVERED = False


__all__ = ("discover_mcp_servers", "get_mcp", "list_mcp")
