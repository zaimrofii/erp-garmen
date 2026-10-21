"""Registry repository AI — auto-discover entity, alias kanonik terpusat."""

from __future__ import annotations

from .bundles import BundleRepository
from .invoices import InvoiceRepository
from .metrics import MetricsRepository
from .orders import OrderRepository
from .partners import PartnerRepository
from .payments import PaymentRepository
from .production_lines import ProductionLineRepository
from .products import ProductRepository
from .purchase_orders import PurchaseOrderRepository
from .work_centers import WorkCenterRepository
from .work_orders import WorkOrderRepository

REPOSITORIES = {
    "order": OrderRepository,
    "work_order": WorkOrderRepository,
    "bundle": BundleRepository,
    "partner": PartnerRepository,
    "product": ProductRepository,
    "work_center": WorkCenterRepository,
    "production_line": ProductionLineRepository,
    "invoice": InvoiceRepository,
    "purchase_order": PurchaseOrderRepository,
    "payment": PaymentRepository,
}

#: Alias kata kanonik normalizer → key repository.
ENTITY_ALIASES = {
    "produk": "product",
    "customer": "partner",
    "vendor": "partner",
}

#: Entity → key data context builder (kontrak lama dipertahankan).
ENTITY_DATA_KEYS = {
    "order": "orders",
    "work_order": "work_orders",
    "bundle": "bundles",
    "partner": "partners",
    "product": "product_list",
    "work_center": "work_centers",
    "production_line": "production_lines",
    "invoice": "invoices",
    "purchase_order": "purchase_orders",
    "payment": "payments",
}

METRICS = MetricsRepository()


def resolve_entity(entity: str) -> str | None:
    """Normalisasi alias → key registry; None bila bukan entity terdaftar."""
    key = str(entity or "").strip().lower()
    key = ENTITY_ALIASES.get(key, key)
    return key if key in REPOSITORIES else None


def get_repo(entity: str):
    key = resolve_entity(entity)
    cls = REPOSITORIES.get(key) if key else None
    return cls() if cls else None


def list_entities() -> list[str]:
    return list(REPOSITORIES)


__all__ = (
    "ENTITY_ALIASES",
    "ENTITY_DATA_KEYS",
    "METRICS",
    "REPOSITORIES",
    "get_repo",
    "list_entities",
    "resolve_entity",
)
