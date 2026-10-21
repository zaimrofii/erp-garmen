"""Context builder (R-2) — re-export API lama agar import tetap valid."""
from __future__ import annotations

from . import aggregate as _aggregate
from . import builder as _builder
from . import candidates as _candidates
from . import constants as _constants


from .builder import _max_rows
from .builder import _label_work_centers
from .builder import _role_code
from .builder import _sanitize_snapshot
from .builder import _filter_financial_rows
from .builder import _sort_products_by_price
from .builder import _query_table
from .builder import _label_lines
from .builder import _matches
from .builder import _metric_result
from .builder import _collect_stock
from .builder import _collect_dimension_metrics
from .builder import _collect_product_quality
from .builder import _collect_inventory_value
from .builder import _system_status
from .builder import _metric_for_message
from .builder import _collect_comparison
from .builder import _collect_forecast
from .builder import _collect_metrics
from .builder import _collect_resource
from .builder import _collect_events
from .builder import _collect_bundles
from .builder import _extract_specific_code
from .builder import _auto_detect_keywords
from .builder import _expand_detail_context
from .builder import build_context
from .aggregate import is_aggregate_query
from .aggregate import _detect_top_query
from .aggregate import _detect_count_query
from .aggregate import _count_query_rows
from .candidates import _candidate_haystack
from .candidates import _format_rupiah
from .candidates import _candidate_attrs
from .candidates import _candidate_rows
from .candidates import _product_phrase
from .candidates import _make_candidate
from .candidates import _dedup_candidates
from .candidates import _specific_lookup
from .candidates import _collect_candidates

__all__ = (
    "_max_rows",
    "_label_work_centers",
    "_role_code",
    "_sanitize_snapshot",
    "_filter_financial_rows",
    "_sort_products_by_price",
    "_query_table",
    "_label_lines",
    "_matches",
    "_metric_result",
    "_collect_stock",
    "_collect_dimension_metrics",
    "_collect_product_quality",
    "_collect_inventory_value",
    "_system_status",
    "_metric_for_message",
    "_collect_comparison",
    "_collect_forecast",
    "_collect_metrics",
    "_collect_resource",
    "_collect_events",
    "_collect_bundles",
    "_extract_specific_code",
    "_auto_detect_keywords",
    "_expand_detail_context",
    "build_context",
    "is_aggregate_query",
    "_detect_top_query",
    "_detect_count_query",
    "_count_query_rows",
    "_candidate_haystack",
    "_format_rupiah",
    "_candidate_attrs",
    "_candidate_rows",
    "_product_phrase",
    "_make_candidate",
    "_dedup_candidates",
    "_specific_lookup",
    "_collect_candidates",
    "logger",
    "METRIC_IDS",
    "METRIC_ROWS",
    "RESOURCE_ROWS",
    "EVENT_ROWS",
    "ALWAYS_SENSITIVE_FIELDS",
    "RESTRICTED_FIELDS",
    "PRIVILEGED_ROLES",
    "LIST_TABLES",
    "FINANCIAL_FIELDS",
    "RESOURCE_TABLE_MAP",
    "CANDIDATE_ENTITIES",
    "ENTITY_LABELS",
    "LIST_QUERY_HINTS",
    "AGGREGATE_KEYWORDS",
    "QUESTION_STOPWORDS",
    "PRICE_HINTS",
    "PRODUCT_NOUNS",
    "PRICE_STOPWORDS",
    "_TOP_WORDS",
    "_TOP_ENTITIES",
    "_COUNT_ENTITY_MAP",
    "_COUNT_PATTERN",
    "CODE_PATTERN",
    "__all__",
)

from ...data_access.registry import get_repo  # noqa: E402,F401  (re-export lama)

_MODULES = (_builder, _candidates, _aggregate, _constants)


def __getattr__(name: str):
    """Fallback: atribut lama (mcp_analytics, METRICS, …) tetap dapat diakses."""
    for module in _MODULES:
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(name)


