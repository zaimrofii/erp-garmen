"""AI data access layer — repository per entity + registry."""

from .base import BaseRepository
from .invoices import InvoiceRepository
from .payments import PaymentRepository
from .purchase_orders import PurchaseOrderRepository
from .registry import (
    ENTITY_ALIASES,
    ENTITY_DATA_KEYS,
    METRICS,
    REPOSITORIES,
    get_repo,
    list_entities,
    resolve_entity,
)

__all__ = (
    "BaseRepository",
    "ENTITY_ALIASES",
    "ENTITY_DATA_KEYS",
    "InvoiceRepository",
    "METRICS",
    "PaymentRepository",
    "PurchaseOrderRepository",
    "REPOSITORIES",
    "get_repo",
    "list_entities",
    "resolve_entity",
)
