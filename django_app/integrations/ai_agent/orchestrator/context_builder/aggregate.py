"""Deteksi query agregat/top/count (R-2)."""


from __future__ import annotations

import re

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
