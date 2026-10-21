"""Builder context (R-2) — collectors + keyword + build_context."""


from __future__ import annotations
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from ...config import AI_CONFIG
from ...data_access.registry import (
    ENTITY_DATA_KEYS,
    METRICS,
    get_repo,
    resolve_entity,
)
from ...mcp_servers import (
    mcp_analytics,
    mcp_comparator,
    mcp_event_log,
    mcp_forecaster,
    mcp_odoo_rpc,
    mcp_postgres_query,
)
from ..conversation_context import resolve_followup
from ..text_normalizer import normalize

from .constants import (
    logger,
    METRIC_IDS,
    METRIC_ROWS,
    RESOURCE_ROWS,
    EVENT_ROWS,
    ALWAYS_SENSITIVE_FIELDS,
    RESTRICTED_FIELDS,
    PRIVILEGED_ROLES,
    LIST_TABLES,
    FINANCIAL_FIELDS,
    RESOURCE_TABLE_MAP,
    CANDIDATE_ENTITIES,
    ENTITY_LABELS,
    LIST_QUERY_HINTS,
    AGGREGATE_KEYWORDS,
    QUESTION_STOPWORDS,
    PRICE_HINTS,
    PRODUCT_NOUNS,
    PRICE_STOPWORDS,
    _TOP_WORDS,
    _TOP_ENTITIES,
    _COUNT_ENTITY_MAP,
    _COUNT_PATTERN,
    CODE_PATTERN,
    __all__,
)
from .aggregate import (
    is_aggregate_query,
    _detect_top_query,
    _detect_count_query,
    _count_query_rows,
)
from .candidates import (
    _candidate_haystack,
    _format_rupiah,
    _candidate_attrs,
    _candidate_rows,
    _product_phrase,
    _make_candidate,
    _dedup_candidates,
    _specific_lookup,
    _collect_candidates,
)


def _max_rows() -> int:
    return int(AI_CONFIG.get("mcp", {}).get("max_rows_to_llm", 50))


def _label_work_centers(rows: list[dict]) -> list[dict]:
    """Ganti label baris dimensi work_center (key=id) dengan kode WC."""
    ids = {
        int(row.get("key"))
        for row in rows
        if isinstance(row, dict) and str(row.get("key", "")).isdigit()
    }
    if not ids:
        return rows

    from apps_industry.garment.models import WorkCenter

    labels = dict(WorkCenter.objects.filter(pk__in=ids).values_list("pk", "code"))
    for row in rows:
        key = row.get("key")
        if isinstance(row, dict) and str(key).isdigit():
            row["label"] = labels.get(int(key), row.get("label", ""))
    return rows


def _role_code(user) -> str:
    role = getattr(user, "role", None)
    return str(getattr(role, "code", "") or "").strip().upper()


def _sanitize_snapshot(snapshot: dict, user) -> tuple[dict, list[str]]:
    """Buang field sensitif dari `visible_fields_snapshot` sebelum ke LLM."""
    role = _role_code(user)
    privileged = role in PRIVILEGED_ROLES
    clean: dict = {}
    filtered: list[str] = []

    for key, value in snapshot.items():
        lowered = str(key).lower()
        if any(hint in lowered for hint in ALWAYS_SENSITIVE_FIELDS):
            filtered.append(str(key))
            continue
        if not privileged and any(hint in lowered for hint in RESTRICTED_FIELDS):
            filtered.append(str(key))
            continue
        clean[key] = value

    if filtered:
        logger.warning(
            "ai_agent: field konteks disaring sebelum LLM: %s",
            ", ".join(sorted(filtered)),
        )
    return clean, filtered


def _filter_financial_rows(rows: list[dict], user) -> list[dict]:
    """Sembunyikan harga/kredit dari role non-privileged pada data list."""
    if _role_code(user) in PRIVILEGED_ROLES:
        return rows
    return [
        {key: value for key, value in row.items() if key not in FINANCIAL_FIELDS}
        for row in rows
    ]


def _sort_products_by_price(
    rows: list[dict], descending: bool = True
) -> list[dict]:
    """Urutkan produk termahal/termurah bila kolom harga tersedia."""
    if not rows or any("sale_price" not in row for row in rows):
        return rows
    return sorted(
        rows,
        key=lambda row: float(row.get("sale_price") or 0),
        reverse=descending,
    )


def _query_table(
    table: str,
    user,
    limit: int = 20,
    columns: list[str] | None = None,
    filters: dict | None = None,
) -> tuple[list[dict], dict | None]:
    """Query tabel allowlist via MCP postgres; aman tanpa exception."""
    payload: dict[str, Any] = {"table": table, "limit": limit}
    if columns:
        payload["columns"] = columns
    if filters:
        payload["filters"] = filters
    try:
        result = mcp_postgres_query.handle(payload)
    except Exception:
        return [], {"tool": "mcp-postgres-query", "error": "exception"}

    if not result.get("ok"):
        return [], {
            "tool": "mcp-postgres-query",
            "error": str(result.get("error") or "unknown"),
        }
    rows = list(result.get("rows") or [])[:limit]
    return _filter_financial_rows(rows, user), None


def _label_lines(rows: list[dict]) -> list[dict]:
    """Ganti label baris dimensi line (key=id) dengan kode line."""
    ids = {
        int(row.get("key"))
        for row in rows
        if isinstance(row, dict) and str(row.get("key", "")).isdigit()
    }
    if not ids:
        return rows

    from apps_industry.garment.models import ProductionLine

    labels = dict(ProductionLine.objects.filter(pk__in=ids).values_list("pk", "code"))
    for row in rows:
        key = row.get("key")
        if isinstance(row, dict) and str(key).isdigit():
            row["label"] = labels.get(int(key), row.get("label", ""))
    return rows


def _matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _metric_result(user, metric_id: str, dimension: str) -> dict:
    """Ambil satu metrik via MCP analytics; gagal aman (tidak raise)."""
    try:
        return mcp_analytics.handle_request(
            "get_metric",
            {"metric_id": metric_id, "dimension": dimension},
            user=user,
        )
    except Exception:
        return {"ok": False, "error": "exception", "metric_id": metric_id}


def _collect_stock(user) -> tuple[list[dict], list[dict]]:
    """Stok Odoo untuk produk MES yang punya `odoo_id` (limit 20)."""
    products, product_error = _query_table(
        "master_product",
        user,
        limit=20,
        columns=["id", "code", "name", "odoo_id", "cost_price"],
    )
    errors: list[dict] = []
    if product_error:
        errors.append(product_error)

    privileged = _role_code(user) in PRIVILEGED_ROLES
    stock: list[dict] = []
    for product in products:
        odoo_id = product.get("odoo_id")
        if odoo_id in (None, ""):
            continue
        result = mcp_odoo_rpc.handle(
            "get_stock", {"product_odoo_id": odoo_id}, user=user
        )
        if not result.get("ok"):
            errors.append(
                {
                    "tool": "mcp-odoo-rpc",
                    "error": str(result.get("error") or "unknown"),
                }
            )
            continue
        quantity = sum(
            float(row.get("quantity") or 0) for row in result.get("data") or []
        )
        item = {
            "product_id": product.get("id"),
            "code": product.get("code"),
            "name": product.get("name"),
            "odoo_id": odoo_id,
            "quantity": quantity,
        }
        if privileged:
            item["cost_price"] = product.get("cost_price")
        stock.append(item)
    return stock, errors


def _collect_dimension_metrics(user, dimension: str) -> tuple[list[dict], list[dict]]:
    metrics: list[dict] = []
    errors: list[dict] = []
    for metric_id in METRIC_IDS:
        try:
            result = mcp_analytics.handle_request(
                "get_metric",
                {"metric_id": metric_id, "dimension": dimension},
                user=user,
            )
        except Exception:
            errors.append({"tool": "mcp-analytics", "metric_id": metric_id})
            continue
        if not result.get("ok"):
            errors.append(
                {
                    "tool": "mcp-analytics",
                    "metric_id": metric_id,
                    "error": str(result.get("error") or "unknown"),
                }
            )
            continue
        rows = list(result.get("rows") or [])[:_max_rows()]
        if dimension == "work_center":
            rows = _label_work_centers(rows)
        else:
            rows = _label_lines(rows)
        metrics.append(
            {
                "metric_id": result.get("metric_id", metric_id),
                "unit": result.get("unit"),
                "rows": rows,
            }
        )
    return metrics, errors


def _collect_product_quality() -> list[dict]:
    from django.db.models import Sum

    from apps_industry.garment.models import ScrapAccumulator
    from master.models import Product

    rows = (
        ScrapAccumulator.objects.values(
            "bundle__work_order__order_line__product_id"
        )
        .annotate(scrap=Sum("qty"), rework=Sum("rework_qty"))
        .order_by("-scrap")[:20]
    )
    ids = [
        row["bundle__work_order__order_line__product_id"]
        for row in rows
        if row["bundle__work_order__order_line__product_id"]
    ]
    names = dict(
        Product.objects.filter(pk__in=ids).values_list("pk", "name")
    )
    return [
        {
            "product_id": row["bundle__work_order__order_line__product_id"],
            "product": names.get(
                row["bundle__work_order__order_line__product_id"], ""
            ),
            "scrap_qty": float(row["scrap"] or 0),
            "rework_qty": float(row["rework"] or 0),
        }
        for row in rows
    ]


def _collect_inventory_value(user) -> dict:
    stock, errors = _collect_stock(user)
    if _role_code(user) not in PRIVILEGED_ROLES:
        return {"restricted": True, "items": stock, "errors": errors}
    total = sum(
        float(item.get("quantity") or 0) * float(item.get("cost_price") or 0)
        for item in stock
    )
    return {"total_value": round(total, 2), "items": stock, "errors": errors}


def _system_status() -> dict:
    """Ringkasan read-only untuk GENERAL_CHAT/UNKNOWN."""
    from apps_industry.garment.models import Bundle, Order
    from integrations.analytics.services import analytics_config_services
    from master.models import Product

    return {
        "analytics_enabled": bool(analytics_config_services.analytics_enabled()),
        "product_count": Product.objects.filter(is_active=True).count(),
        "order_count": Order.objects.count(),
        "bundle_active": Bundle.objects.exclude(state__in=["DONE", "CANCELLED"]).count(),
        "metrics": ["scrap_rate", "rework_rate", "lead_time"],
    }


def _metric_for_message(message: str) -> str:
    text = (message or "").lower()
    if "rework" in text:
        return "garment.rework_rate"
    if "lead" in text or "lambat" in text:
        return "garment.lead_time"
    return "garment.scrap_rate"


def _collect_comparison(user, message: str) -> dict | None:
    now = timezone.now()
    result = mcp_comparator.handle(
        "compare_periods",
        {
            "metric_id": _metric_for_message(message),
            "period_a": {
                "from": (now - timedelta(days=7)).isoformat(),
                "to": now.isoformat(),
            },
            "period_b": {
                "from": (now - timedelta(days=14)).isoformat(),
                "to": (now - timedelta(days=7)).isoformat(),
            },
        },
        user=user,
    )
    return result if result.get("ok") else None


def _collect_forecast(user, message: str) -> dict | None:
    result = mcp_forecaster.handle(
        "forecast_metric",
        {
            "metric_id": _metric_for_message(message),
            "horizon_days": 7,
            "method": "ma",
        },
        user=user,
    )
    return result if result.get("ok") else None


def _collect_metrics(user, include_work_center: bool = False) -> tuple[list[dict], list[dict]]:
    metrics: list[dict] = []
    errors: list[dict] = []

    for metric_id in METRIC_IDS:
        dimensions = ["period"]
        if include_work_center and metric_id != "garment.lead_time":
            dimensions.append("work_center")

        for dimension in dimensions:
            try:
                result = mcp_analytics.handle_request(
                    "get_metric",
                    {"metric_id": metric_id, "dimension": dimension},
                    user=user,
                )
            except Exception:
                errors.append({"tool": "mcp-analytics", "metric_id": metric_id})
                continue

            if not result.get("ok"):
                errors.append(
                    {
                        "tool": "mcp-analytics",
                        "metric_id": metric_id,
                        "error": str(result.get("error") or "unknown"),
                    }
                )
                continue

            rows = list(result.get("rows") or [])
            if dimension == "period":
                # Baris metrik period diurutkan naik — ambil periode TERBARU.
                rows = rows[-METRIC_ROWS:]
            else:
                rows = rows[:_max_rows()]
            if dimension == "work_center":
                rows = _label_work_centers(rows)
            metrics.append(
                {
                    "metric_id": result.get("metric_id", metric_id),
                    "dimension": dimension,
                    "unit": result.get("unit"),
                    "rows": rows,
                }
            )

    return metrics, errors


def _collect_resource(
    context: dict, user=None
) -> tuple[list[dict], dict | None]:
    resource_type = str(context.get("resource_type") or "")
    table = RESOURCE_TABLE_MAP.get(resource_type)
    resource_id = context.get("resource_id")
    if table is None or resource_id is None:
        return [], None
    # Produk hanya dibuka untuk halaman detail/form; list memakai resource_list.
    if resource_type == "product" and context.get("page_type") not in {
        "detail",
        "form",
    }:
        return [], None

    try:
        result = mcp_postgres_query.handle(
            {
                "table": table,
                "filters": {"id": resource_id},
                "limit": min(RESOURCE_ROWS, _max_rows()),
            }
        )
    except Exception:
        return [], {"tool": "mcp-postgres-query", "error": "exception"}

    if not result.get("ok"):
        return [], {
            "tool": "mcp-postgres-query",
            "error": str(result.get("error") or "unknown"),
        }

    rows = list(result.get("rows") or [])[:RESOURCE_ROWS]
    return _filter_financial_rows(rows, user), None


def _collect_events(context: dict) -> tuple[list[dict], dict | None]:
    if str(context.get("resource_type") or "") != "bundle":
        return [], None
    bundle_id = context.get("resource_id")
    if bundle_id is None:
        return [], None

    try:
        result = mcp_event_log.handle(
            {"bundle_id": bundle_id, "limit": min(EVENT_ROWS, _max_rows())}
        )
    except Exception:
        return [], {"tool": "mcp-event-log", "error": "exception"}

    if not result.get("ok"):
        return [], {
            "tool": "mcp-event-log",
            "error": str(result.get("error") or "unknown"),
        }

    return list(result.get("events") or [])[:EVENT_ROWS], None


def _collect_bundles() -> tuple[list[dict], list[dict]]:
    """Durasi bundle terbaru untuk pertanyaan 'bundle mana paling lambat?'."""
    errors: list[dict] = []
    try:
        result = mcp_postgres_query.handle(
            {
                "table": "garment_bundle",
                "columns": ["id", "code", "qty", "state"],
                "limit": 100,
            }
        )
    except Exception:
        return [], [{"tool": "mcp-postgres-query", "error": "exception"}]

    if not result.get("ok"):
        return [], [
            {
                "tool": "mcp-postgres-query",
                "error": str(result.get("error") or "unknown"),
            }
        ]

    bundles: list[dict] = []
    for row in result.get("rows") or []:
        if not isinstance(row, dict) or row.get("id") is None:
            continue
        try:
            events_result = mcp_event_log.handle(
                {"bundle_id": row["id"], "limit": 20}
            )
        except Exception:
            errors.append({"tool": "mcp-event-log", "error": "exception"})
            continue
        if not events_result.get("ok"):
            errors.append(
                {
                    "tool": "mcp-event-log",
                    "error": str(events_result.get("error") or "unknown"),
                }
            )
            continue

        starts: list = []
        finishes: list = []
        for event in events_result.get("events") or []:
            timestamp = parse_datetime(str(event.get("ts") or ""))
            if timestamp is None:
                continue
            if event.get("event_type") == "BUNDLE_START":
                starts.append(timestamp)
            elif event.get("event_type") == "BUNDLE_FINISH":
                finishes.append(timestamp)

        if not starts or not finishes:
            continue
        hours = (max(finishes) - min(starts)).total_seconds() / 3600
        bundles.append(
            {
                "code": row.get("code"),
                "state": row.get("state"),
                "qty": row.get("qty"),
                "lead_time_hours": round(hours, 2),
            }
        )

    bundles.sort(key=lambda item: item["lead_time_hours"], reverse=True)
    return bundles[:5], errors


def _extract_specific_code(normalized: dict, data: dict, errors: list[dict]) -> None:
    """Isi key *_specific bila pesan menyebut kode bisnis eksplisit."""
    matches = CODE_PATTERN.findall(str(normalized.get("raw") or "").upper())
    if not matches:
        return
    code = matches[0]

    entity = None
    data_key = None
    if "-BND-" in code or code.startswith("BND-"):
        entity, data_key = "bundle", "bundle_specific"
    elif code.startswith("SO-") or "-SO-" in code:
        entity, data_key = "order", "order_specific"
    elif "-INV-" in code or code.startswith("INV-"):
        entity, data_key = "invoice", "invoice_specific"
    elif "-PO-" in code or code.startswith("PO-"):
        entity, data_key = "purchase_order", "po_specific"
    elif code.startswith("RICH-WO") or "-WO-" in code:
        entity, data_key = "work_order", "wo_specific"

    if entity is None:
        return
    repo = get_repo(entity)
    if repo is None:
        return
    try:
        data[data_key] = repo.get_list(filters={"code": code}, limit=1)
    except Exception:
        errors.append(
            {"tool": "data-access", "entity": data_key, "error": "exception"}
        )


def _auto_detect_keywords(
    normalized: dict,
    user,
    page_context: dict,
    page_data: dict,
) -> tuple[dict, list[dict]]:
    """Ambil data dari keyword pesan, apa pun page_type-nya.

    Data halaman hanya dipakai untuk dedupe bila keyword menunjuk entity
    yang sama (mis. "produk" di halaman list product) agar tidak query 2×.
    """
    canonicals = set(normalized["canonicals"])
    tokens = set(normalized["tokens"])
    text = normalized["normalized"]
    page_resource = str(page_context.get("resource_type") or "")

    data: dict[str, Any] = {}
    errors: list[dict] = []
    seen: set[str] = set()

    _extract_specific_code(normalized, data, errors)

    for canonical in normalized["canonicals"]:
        entity = resolve_entity(canonical)
        if entity is None or entity in seen:
            continue
        seen.add(entity)

        page_rows = None
        if page_resource == entity:
            page_rows = page_data.get("resource_list")
            if page_rows is None:
                page_rows = page_data.get("resource")

        if page_rows is not None:
            rows = list(page_rows)
        else:
            repo = get_repo(entity)
            if repo is None:
                continue
            try:
                rows = repo.get_list(limit=20)
            except Exception:
                errors.append(
                    {"tool": "data-access", "entity": entity, "error": "exception"}
                )
                rows = []

        data_key = ENTITY_DATA_KEYS.get(entity, f"{entity}s")
        if entity == "product":
            rows = _filter_financial_rows(rows, user)
            rows = _sort_products_by_price(
                rows, descending="murah" not in canonicals
            )
        data[data_key] = rows

        if entity in {"product", "partner"}:
            data["auto_detected"] = {
                "resource_type": entity,
                "rows": rows,
                "count": len(rows),
                "source": "page" if page_rows is not None else "keyword",
            }

    if "stok" in canonicals:
        stock, stock_errors = _collect_stock(user)
        data["stock"] = stock
        errors.extend(stock_errors)

    if "bundle" in canonicals:
        wc_match = re.search(r"\b([A-Z]+-\d+)\b", normalized["raw"].upper())
        if wc_match:
            try:
                data["bundles_in_wc"] = METRICS.bundles_in_work_center(
                    wc_match.group(1), limit=20
                )
            except Exception:
                errors.append(
                    {
                        "tool": "metrics",
                        "entity": "bundles_in_work_center",
                        "error": "exception",
                    }
                )

    if "invoice" in canonicals and "belum" in canonicals:
        repo = get_repo("invoice")
        if repo:
            try:
                data["unpaid_invoices"] = repo.get_list(
                    filters={"state__in": ["CONFIRMED", "SENT"]}, limit=20
                )
            except Exception:
                errors.append(
                    {"tool": "data-access", "entity": "unpaid_invoices", "error": "exception"}
                )

    if "purchase_order" in canonicals and "belum" in canonicals:
        repo = get_repo("purchase_order")
        if repo:
            try:
                data["open_purchase_orders"] = repo.get_list(
                    filters={"state__in": ["DRAFT", "CONFIRMED"]}, limit=20
                )
            except Exception:
                errors.append(
                    {
                        "tool": "data-access",
                        "entity": "open_purchase_orders",
                        "error": "exception",
                    }
                )

    if "bundle" in canonicals and "order" in canonicals:
        try:
            data["bundles_by_order"] = METRICS.bundles_by_order()
        except Exception:
            errors.append(
                {"tool": "metrics", "entity": "bundles_by_order", "error": "exception"}
            )

    if "scrap" in canonicals and "customer" in canonicals:
        try:
            data["scrap_by_customer"] = METRICS.scrap_by_customer()
        except Exception:
            errors.append(
                {"tool": "metrics", "entity": "scrap_by_customer", "error": "exception"}
            )

    if "customer" in canonicals and (
        "belanja" in canonicals or "royal" in canonicals
    ):
        try:
            data["customer_total_spend"] = METRICS.customer_total_spend()
        except Exception:
            errors.append(
                {
                    "tool": "metrics",
                    "entity": "customer_total_spend",
                    "error": "exception",
                }
            )

    if "work_center" in canonicals or "sibuk" in canonicals:
        metrics, metric_errors = _collect_dimension_metrics(user, "work_center")
        data["metrics_by_wc"] = metrics
        errors.extend(metric_errors)

    if "production_line" in canonicals or "lambat" in canonicals:
        metrics, metric_errors = _collect_dimension_metrics(user, "line")
        data["metrics_by_line"] = metrics
        errors.extend(metric_errors)

    # R.4 — metrik line_balance & bottleneck (diminta eksplisit).
    if "seimbang" in text or "balance" in tokens or "line_balance" in tokens:
        data["line_balance"] = _metric_result(
            user, "garment.line_balance", "line"
        )

    if any(
        keyword in text
        for keyword in ("bottleneck", "penyumbat", "hambatan", "menumpuk")
    ):
        data["bottleneck"] = _metric_result(
            user, "garment.bottleneck", "work_center"
        )

    # Fix #13C — pertanyaan harga produk: lookup produk via nama (bukan klarifikasi).
    if any(hint in text for hint in PRICE_HINTS) and (
        "produk" in canonicals
        or "barang" in tokens
        or any(noun in text for noun in PRODUCT_NOUNS)
    ):
        phrase = _product_phrase(normalized.get("raw") or "")
        rows: list[dict] = []
        repo = get_repo("product")
        if phrase and repo is not None:
            try:
                rows = repo.get_list(
                    filters={"name__icontains": phrase}, limit=10
                )
            except Exception:
                errors.append(
                    {
                        "tool": "data-access",
                        "entity": "product_price",
                        "error": "exception",
                    }
                )
        if rows:
            data["product_list"] = _filter_financial_rows(rows, user)
            data["_entity_label"] = "produk"
            score = 0.95 if len(rows) == 1 else 0.7
            data["_candidates"] = _dedup_candidates(
                [_make_candidate("product", row, score) for row in rows[:20]]
            )
        elif phrase:
            data["_candidates"] = []
            data["_entity_label"] = "produk"

    if "lambat" in canonicals or "late" in tokens:
        try:
            data["order_late_stats"] = METRICS.order_late_percentage()
        except Exception:
            errors.append(
                {"tool": "metrics", "entity": "order_late_stats", "error": "exception"}
            )

    if "customer" in canonicals and "order" in canonicals:
        try:
            data["customer_orders"] = METRICS.customer_orders()
        except Exception:
            errors.append(
                {"tool": "metrics", "entity": "customer_orders", "error": "exception"}
            )

    if "produk" in canonicals and (
        "produksi" in canonicals or "diproduksi" in tokens
    ):
        try:
            data["product_production"] = METRICS.product_production()
        except Exception:
            errors.append(
                {"tool": "metrics", "entity": "product_production", "error": "exception"}
            )

    if ("produk" in canonicals and "rewel" in canonicals) or _matches(
        text, r"rework per produk"
    ):
        data["product_quality"] = _collect_product_quality()

    if ("stok" in canonicals and {"nilai", "total"} & tokens) or _matches(
        text, r"total nilai"
    ):
        data["inventory_value"] = _collect_inventory_value(user)

    return data, errors


def _expand_detail_context(page_context: dict) -> tuple[dict, list[dict]]:
    """Expand relasi hanya untuk halaman detail (Fix #8)."""
    data: dict[str, Any] = {}
    errors: list[dict] = []
    if page_context.get("page_type") != "detail":
        return data, errors

    resource_type = str(page_context.get("resource_type") or "")
    resource_id = page_context.get("resource_id")
    if resource_id in (None, ""):
        return data, errors

    try:
        if resource_type == "product":
            from django.db.models import Sum

            from apps_industry.garment.models import Bundle, Order, OrderLine

            aggregate = Bundle.objects.filter(
                work_order__order_line__product_id=resource_id,
                state="DONE",
            ).aggregate(total=Sum("qty_done"))
            data["product_production_count"] = int(aggregate["total"] or 0)

            order_ids = list(
                OrderLine.objects.filter(product_id=resource_id)
                .values_list("order_id", flat=True)
                .distinct()[:10]
            )
            data["related_orders"] = get_repo("order").get_list(
                filters={"id__in": order_ids}, limit=10
            )
            data["related_bundles"] = get_repo("bundle").get_list(
                filters={"work_order__order_line__product_id": resource_id},
                limit=10,
            )
            customer_ids = list(
                Order.objects.filter(lines__product_id=resource_id)
                .values_list("customer_id", flat=True)
                .distinct()[:10]
            )
            data["related_customers"] = get_repo("partner").get_list(
                filters={"id__in": customer_ids}, limit=10
            )

        elif resource_type == "order":
            data["related_bundles"] = get_repo("bundle").get_list(
                filters={"work_order__order_line__order_id": resource_id},
                limit=20,
            )
            data["related_invoices"] = get_repo("invoice").get_list(
                filters={"order_id": resource_id}, limit=10
            )

        elif resource_type == "bundle":
            bundle = get_repo("bundle").get_by_id(resource_id)
            if bundle:
                data["bundle_order"] = {
                    "order_code": bundle.get("order_code"),
                    "customer_name": bundle.get("customer_name"),
                    "product_name": bundle.get("product_name"),
                }
    except Exception:
        errors.append(
            {"tool": "detail-expand", "resource_type": resource_type, "error": "exception"}
        )

    return data, errors


def build_context(
    intent: str,
    tools: list[str],
    message: str,
    context: dict | None = None,
    user=None,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """Kumpulkan data relevan dari MCP → dict siap masuk prompt.

    `history` dipakai hanya untuk me-resolve follow-up ("peringkat kedua?");
    seluruh retrieval tetap dilakukan terhadap effective message.
    """
    followup = resolve_followup(message, history or [])
    effective_message = followup["resolved_message"] or message
    effective_norm = normalize(effective_message)
    text = effective_norm["normalized"]

    page_context = dict(context or {})
    snapshot = page_context.get("visible_fields_snapshot")
    if isinstance(snapshot, dict):
        page_context["visible_fields_snapshot"], _ = _sanitize_snapshot(
            snapshot, user
        )

    data: dict[str, Any] = {
        "intent": str(intent or "UNKNOWN"),
        "message": message or "",
        "normalized_message": effective_norm["normalized"],
        "context": page_context,
        "tools": list(tools or []),
    }
    if followup["is_followup"]:
        data["resolved_message"] = effective_message
        data["followup"] = followup
        data["_followup_rank"] = followup["target_rank"]
        data["_followup_entity"] = followup["target_entity"]
    errors: list[dict] = []

    # Fix #17B/#17C — permintaan terstruktur dari RAW message.
    top_query = _detect_top_query(message)
    if top_query is not None:
        data["_aggregate_query"] = True
        data["_top_query"] = top_query
        try:
            data["customer_total_spend"] = METRICS.customer_total_spend(
                limit=top_query["limit"]
            )
        except Exception:
            errors.append(
                {
                    "tool": "metrics",
                    "entity": "customer_total_spend",
                    "error": "exception",
                }
            )
        return data

    count_query = _detect_count_query(message)
    if count_query is not None:
        data[ENTITY_DATA_KEYS.get(count_query["entity"], "rows")] = (
            _count_query_rows(
                count_query["entity"],
                count_query["name"],
                count_query["count"],
            )
        )
        data["_entity_label"] = ENTITY_LABELS.get(
            count_query["entity"], "data"
        )
        data["_aggregate_query"] = True
        data["_count_query"] = count_query
        data["requested_count"] = count_query["count"]
        return data

    if data["intent"] in {"GENERAL_CHAT", "UNKNOWN"}:
        try:
            data["system_status"] = _system_status()
        except Exception:
            errors.append({"tool": "system-status", "error": "exception"})

    # 1) Data halaman (tetap dipertahankan).
    resource_collected = False
    page_type = page_context.get("page_type")
    if page_type == "list":
        list_table = LIST_TABLES.get(str(page_context.get("resource_type") or ""))
        if list_table:
            rows, list_error = _query_table(list_table, user)
            if list_table == "master_product":
                rows = _sort_products_by_price(rows)
                data["product_list"] = rows
            data["resource_list"] = rows
            data["resource_list_count"] = len(rows)
            if list_error:
                errors.append(list_error)
    elif page_type in {"detail", "form"} and page_context.get("resource_id"):
        rows, resource_error = _collect_resource(page_context, user)
        resource_collected = True
        if rows:
            data["resource"] = rows
        if resource_error:
            errors.append(resource_error)

    # 2) Keyword auto-detect SELALU berjalan, semua page_type.
    keyword_data, keyword_errors = _auto_detect_keywords(
        effective_norm, user, page_context, data
    )
    data.update(keyword_data)
    errors.extend(keyword_errors)

    # 3) Expand relasi halaman detail (Fix #8).
    detail_data, detail_errors = _expand_detail_context(page_context)
    data.update(detail_data)
    errors.extend(detail_errors)

    # 4) R.3 / Fix #13 — kandidat klarifikasi (spesifik) atau hasil resolve user.
    aggregate = is_aggregate_query(effective_message)
    if aggregate:
        data["_aggregate_query"] = True

    resolved = page_context.get("_resolved_candidate")
    if isinstance(resolved, dict) and resolved.get("id") is not None:
        entity = str(resolved.get("entity") or "")
        repo = get_repo(entity)
        data_key = ENTITY_DATA_KEYS.get(entity, "")
        rows: list[dict] = []
        if repo is not None and data_key:
            try:
                rows = repo.get_list(filters={"id": resolved["id"]}, limit=1)
            except Exception:
                errors.append({"tool": "clarification", "error": "exception"})
        if rows:
            data[data_key] = rows
        data["_resolved_candidate"] = rows[0] if rows else dict(resolved)
        data["_candidates"] = []
        data["_entity_label"] = ENTITY_LABELS.get(entity, "data")
    else:
        has_specific_code = any(
            str(key).endswith("_specific") and bool(value)
            for key, value in data.items()
        )
        if not has_specific_code and not aggregate:
            candidates, entity = _collect_candidates(effective_norm, data)
            if entity is not None:
                data["_candidates"] = candidates
                data["_entity_label"] = ENTITY_LABELS.get(entity, "data")


    if "mcp-odoo-rpc" in data["tools"]:
        odoo_id = (
            page_context.get("odoo_id")
            or page_context.get("product_odoo_id")
            or (snapshot or {}).get("odoo_id")
        )
        if odoo_id:
            odoo_result = mcp_odoo_rpc.handle(
                "get_stock",
                {"product_odoo_id": odoo_id},
                user=user,
            )
            if odoo_result.get("ok"):
                data["odoo_stock"] = odoo_result.get("data")
            else:
                errors.append(
                    {
                        "tool": "mcp-odoo-rpc",
                        "error": str(odoo_result.get("error") or "unknown"),
                    }
                )
        else:
            data["odoo_note"] = (
                "Odoo RPC dipilih, tetapi product_odoo_id tidak tersedia di konteks."
            )

    if "mcp-analytics" in data["tools"]:
        metrics, metric_errors = _collect_metrics(
            user, include_work_center=data["intent"] == "DIAGNOSTIC"
        )
        data["metrics"] = metrics
        errors.extend(metric_errors)

    if "mcp-postgres-query" in data["tools"]:
        if (
            data["intent"] == "DATA_LOOKUP"
            and not page_context.get("resource_type")
            and "bundle" in text
        ):
            bundles, bundle_errors = _collect_bundles()
            if bundles:
                data["bundles"] = bundles
            errors.extend(bundle_errors)

        if not resource_collected:
            rows, resource_error = _collect_resource(page_context, user)
            if rows:
                data["resource"] = rows
            if resource_error:
                errors.append(resource_error)

    if "mcp-event-log" in data["tools"]:
        events, event_error = _collect_events(page_context)
        if events:
            data["events"] = events
        if event_error:
            errors.append(event_error)

    if "mcp-comparator" in data["tools"]:
        comparison = _collect_comparison(user, effective_message)
        if comparison:
            data["comparison"] = comparison
        else:
            errors.append({"tool": "mcp-comparator", "error": "no_data"})

    if "mcp-forecaster" in data["tools"]:
        forecast = _collect_forecast(user, effective_message)
        if forecast:
            data["forecast"] = forecast
        else:
            errors.append({"tool": "mcp-forecaster", "error": "insufficient_data"})

    if errors:
        data["errors"] = errors

    return data
