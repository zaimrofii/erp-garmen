"""Deteksi query agregat/top/count (R-2)."""


from __future__ import annotations

import re

from django.db.models import Count
from django.utils import timezone

from ...data_access.registry import get_repo

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


def is_aggregate_query(message: str) -> bool:
    """True bila pesan meminta agregat/peringkat (tidak perlu klarifikasi)."""
    text = str(message or "").lower()
    return any(keyword in text for keyword in AGGREGATE_KEYWORDS)


#: Kata yang menandakan pertanyaan count, bukan daftar/filter biasa.
_TOTAL_WORDS = ("total", "jumlah", "berapa banyak", "count")

#: "berapa order?" boleh, tetapi "berapa persen order telat?" bukan count.
_BERAPA_COUNT_PATTERN = re.compile(
    r"\bberapa\s+(?:jumlah\s+)?(?:order|orderan|bundle|paket|customer|"
    r"pelanggan|partner|produk|product|invoice|faktur|po|work order)\b",
    re.IGNORECASE,
)

#: Jangan anggap sebagai count kalau pesan meminta metrik/harga/daftar.
_TOTAL_NON_COUNT_WORDS = (
    "harga",
    "nilai",
    "termahal",
    "termurah",
    "rata-rata",
    "average",
    "persen",
    "telat",
    "lambat",
    "tren",
    "trend",
    "grafik",
    "chart",
    "scrap",
    "rework",
    "lead time",
    "lead_time",
    "oee",
    "bottleneck",
    "stok",
    "belanja",
    "royal",
)

_TOTAL_STATES = (
    "DONE",
    "IN_PROGRESS",
    "CONFIRMED",
    "DRAFT",
    "CUTTING",
    "SEWING",
    "QC",
    "REWORK",
    "SCRAP",
)

_DEFAULT_TOTAL_LABELS = {
    "order": "order",
    "bundle": "bundle",
    "customer": "customer",
    "product": "produk",
    "invoice": "invoice",
    "po": "purchase order",
    "work_order": "work order",
}


def _total_entity(text: str) -> str | None:
    """Tentukan entity count; work order / PO diprioritaskan dari 'order'."""
    if re.search(r"\bwork order\b|\bwo\b", text):
        return "work_order"
    if re.search(r"\bpurchase order\b|\bpo\b", text):
        return "po"
    if re.search(r"\border\b|\borderan\b", text):
        return "order"
    if re.search(r"\bbundle\b|\bpaket\b", text):
        return "bundle"
    if re.search(r"\bcustomer\b|\bpelanggan\b|\bpartner\b", text):
        return "customer"
    if re.search(r"\bproduk\b|\bproduct\b", text):
        return "product"
    if re.search(r"\binvoice\b|\bfaktur\b", text):
        return "invoice"
    return None


def _detect_total_query(message: str) -> dict | None:
    """Deteksi pertanyaan count eksplisit + filter periode/state.

    Contoh: ``total order``, ``berapa banyak bundle``, ``jumlah customer
    bulan ini``. Pertanyaan harga/metrik/daftar tidak dianggap count.
    """
    text = " ".join(str(message or "").lower().split())
    if not text:
        return None

    has_count_word = any(word in text for word in _TOTAL_WORDS)
    has_berapa_count = _BERAPA_COUNT_PATTERN.search(text) is not None
    if not has_count_word and not has_berapa_count:
        return None

    # "berapa harga produk" / "total scrap" bukan count entity.
    if any(word in text for word in _TOTAL_NON_COUNT_WORDS):
        return None

    entity = _total_entity(text)
    if entity is None:
        return None

    filters: dict = {}
    period = "semua"
    today = timezone.localdate()
    if "bulan ini" in text:
        filters["created_at__month"] = today.month
        filters["created_at__year"] = today.year
        period = "bulan_ini"
    elif "minggu ini" in text:
        filters["created_at__week"] = today.isocalendar()[1]
        filters["created_at__year"] = today.year
        period = "minggu_ini"
    elif "hari ini" in text:
        filters["created_at__date"] = today
        period = "hari_ini"
    elif "tahun ini" in text:
        filters["created_at__year"] = today.year
        period = "tahun_ini"

    state = next(
        (item for item in _TOTAL_STATES if re.search(rf"\b{item.lower()}\b", text)),
        "",
    )
    if state:
        filters["state"] = state

    return {
        "entity": entity,
        "label": _DEFAULT_TOTAL_LABELS.get(entity, entity),
        "period": period,
        "state": state,
        "filters": filters,
    }


def _total_queryset(entity: str):
    """Queryset dasar per entity; import model lazy agar app registry siap."""
    from apps_industry.garment.models import (
        Bundle,
        CustomerInvoice,
        Order,
        PurchaseOrder,
        WorkOrder,
    )
    from master.models import Partner, Product

    if entity == "order":
        return Order.objects.all()
    if entity == "bundle":
        return Bundle.objects.all()
    if entity == "customer":
        return Partner.objects.filter(is_customer=True)
    if entity == "product":
        return Product.objects.all()
    if entity == "invoice":
        return CustomerInvoice.objects.all()
    if entity == "po":
        return PurchaseOrder.objects.all()
    if entity == "work_order":
        return WorkOrder.objects.all()
    raise ValueError(f"entity total tidak dikenal: {entity}")


def _collect_total_count(query: dict) -> dict:
    """Hitung total + breakdown state langsung dari DB (bukan sampel 20)."""
    qs = _total_queryset(query["entity"])
    field_names = {field.name for field in qs.model._meta.get_fields()}
    filters = {
        key: value
        for key, value in (query.get("filters") or {}).items()
        if key.split("__")[0] in field_names
    }
    if filters:
        qs = qs.filter(**filters)

    total = int(qs.count())
    breakdown: dict[str, int] = {}
    state_field = "state" if "state" in field_names else None
    if state_field is None and "is_active" in field_names:
        state_field = "is_active"
    if state_field is not None:
        rows = (
            qs.values(state_field)
            .annotate(count=Count("id"))
            .order_by()
            .values_list(state_field, "count")
        )
        breakdown = {
            str(key if key is not None else "UNKNOWN"): int(count)
            for key, count in rows
        }

    return {
        **query,
        "total": total,
        "breakdown": breakdown,
    }


def _detect_top_query(message: str) -> dict | None:
    """Deteksi "top N customer"/"customer terbaik" dari pesan mentah."""
    text = str(message or "").lower()
    if not (
        re.search(rf"\b{_TOP_WORDS}\b.*\b{_TOP_ENTITIES}\b", text)
        or re.search(rf"\b{_TOP_ENTITIES}\b.*\b{_TOP_WORDS}\b", text)
    ):
        return None

    numbers = re.findall(r"\d+", text)
    limit = int(numbers[0]) if numbers else 10
    return {"entity": "customer", "limit": max(1, limit)}


def _detect_count_query(message: str) -> dict | None:
    """Deteksi "5 produk kaos polos" → daftar 5 produk (bukan klarifikasi)."""
    match = _COUNT_PATTERN.match(str(message or ""))
    if match is None:
        return None

    name = match.group(3).strip(" ?.,!")
    if not name:
        return None

    entity = _COUNT_ENTITY_MAP.get(match.group(2).lower())
    if entity is None:
        return None
    return {"count": int(match.group(1)), "entity": entity, "name": name}


def _count_query_rows(entity: str, name: str, limit: int) -> list[dict]:
    """Ambil maksimal `limit` baris yang cocok dengan nama/kota/kode."""
    repo = get_repo(entity)
    if repo is None or limit <= 0:
        return []

    try:
        if entity == "product":
            return repo.get_list(filters={"name__icontains": name}, limit=limit)
        if entity in {"order", "bundle"}:
            return repo.get_list(filters={"code__icontains": name}, limit=limit)
        rows = repo.get_list(limit=max(limit * 10, 50))
    except Exception:
        return []

    phrase = name.lower()
    return [
        row
        for row in rows
        if phrase in str(row.get("name") or "").lower()
        or phrase in str(row.get("city") or "").lower()
        or phrase in str(row.get("code") or "").lower()
    ][:limit]
