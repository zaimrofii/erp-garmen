"""Kandidat klarifikasi (R-2) — lookup, attrs, dedup."""


from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ...data_access.registry import ENTITY_DATA_KEYS, get_repo, resolve_entity

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
)


def _candidate_haystack(row: dict) -> str:
    return " ".join(
        str(value) for value in row.values() if value not in (None, "")
    ).lower()


def _format_rupiah(value) -> str:
    """Format harga gaya Indonesia: ``50000`` → ``"Rp50.000"``."""
    if value in (None, ""):
        return "harga belum diisi"
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "harga belum diisi"
    if amount <= 0:
        return "harga belum diisi"
    return "Rp{:,.0f}".format(amount).replace(",", ".")


def _candidate_attrs(entity: str, row: dict) -> dict:
    """Atribut pembeda per entity — bukti untuk user, BUKAN kode.

    Prinsip Fix #14: "disambiguate by evidence, not by ID". Owner/operator
    tidak hafal kode, jadi produk memakai harga + kategori, order memakai
    customer/status, dan seterusnya.
    """
    attrs: dict = {}

    if entity == "product":
        attrs["harga"] = _format_rupiah(row.get("sale_price"))
        attrs["kategori"] = row.get("category") or "tanpa kategori"
        return attrs

    if entity == "order":
        if row.get("customer_name"):
            attrs["customer"] = row["customer_name"]
        if row.get("state"):
            attrs["status"] = row["state"]
        if row.get("deadline"):
            attrs["deadline"] = str(row["deadline"])[:10]
        return attrs

    if entity == "partner":
        if row.get("city"):
            attrs["kota"] = row["city"]
        types = []
        if row.get("is_customer"):
            types.append("customer")
        if row.get("is_vendor"):
            types.append("vendor")
        if types:
            attrs["tipe"] = "/".join(types)
        return attrs

    if entity == "bundle":
        if row.get("product_name"):
            attrs["produk"] = row["product_name"]
        if row.get("state"):
            attrs["status"] = row["state"]
        if row.get("qty") is not None:
            attrs["qty"] = row["qty"]
        return attrs

    if entity == "work_center":
        if row.get("capacity_per_hour") is not None:
            attrs["kapasitas/jam"] = row["capacity_per_hour"]
        if row.get("wc_type"):
            attrs["tipe"] = row["wc_type"]
        return attrs

    if entity == "production_line" and row.get("code"):
        attrs["line"] = row["code"]
        return attrs

    if row.get("code"):
        attrs["kode"] = row["code"]
    if row.get("state"):
        attrs["status"] = row["state"]
    return attrs


def _candidate_rows(entity: str, data: dict) -> list[dict]:
    key = ENTITY_DATA_KEYS.get(entity, "")
    existing = data.get(key)
    if isinstance(existing, list) and existing:
        return existing
    repo = get_repo(entity)
    if repo is None:
        return []
    try:
        return repo.get_list(limit=20)
    except Exception:
        return []


def _product_phrase(raw: str) -> str | None:
    """Ambil frasa nama produk dari pesan (mis. 'kaos polos')."""
    text = str(raw or "").lower()
    pattern = (
        r"\b(?:" + "|".join(PRODUCT_NOUNS) + r")\s+[a-z0-9][a-z0-9\- ]{0,30}"
    )
    match = re.search(pattern, text)
    if match:
        return match.group(0).strip(" ?.,!")

    tokens = [
        token.strip("?.,!")
        for token in text.split()
        if token.strip("?.,!")
        and token.strip("?.,!") not in PRICE_STOPWORDS
    ]
    if not tokens:
        return None
    phrase = tokens[-1]
    return None if phrase in LIST_QUERY_HINTS else phrase


def _make_candidate(entity: str, row: dict, score: float) -> dict:
    """Bentuk kandidat standar {id,label,attrs,score,entity}."""
    return {
        "id": row.get("id"),
        "label": str(
            row.get("name") or row.get("code") or f"{entity} #{row.get('id')}"
        ),
        "attrs": _candidate_attrs(entity, row),
        "score": score,
        "entity": entity,
    }


def _dedup_candidates(candidates: list[dict]) -> list[dict]:
    """Buang kandidat duplikat (label + harga + kategori sama) — Fix #16B."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict] = []
    for candidate in candidates:
        attrs = candidate.get("attrs") or {}
        key = (
            str(candidate.get("label") or "").strip().lower(),
            str(attrs.get("harga") or ""),
            str(attrs.get("kategori") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _specific_lookup(normalized: dict) -> tuple[str, list[str]] | None:
    """Deteksi pencarian SATU entitas (bukan daftar/agregat).

    Return `(entity, tokens_spesifik)` atau `None` bila query bersifat daftar
    atau agregat (Fix #13D: agregat dijawab metrik, bukan klarifikasi).
    """
    if is_aggregate_query(str(normalized.get("raw") or "")):
        return None

    tokens = list(normalized.get("tokens") or [])
    if not tokens or any(token in LIST_QUERY_HINTS for token in tokens):
        return None

    entity = None
    for canonical in normalized.get("canonicals") or []:
        resolved = resolve_entity(canonical)
        if resolved in CANDIDATE_ENTITIES:
            entity = resolved
            break
    if entity is None:
        return None

    specificity = [
        token
        for token in tokens
        if len(token) >= 2
        and token not in QUESTION_STOPWORDS
        and token not in LIST_QUERY_HINTS
        and resolve_entity(token) is None
    ]
    if not specificity:
        return None
    return entity, specificity


def _collect_candidates(
    normalized: dict, data: dict
) -> tuple[list[dict], str | None]:
    """Kandidat {id,label,attrs,score} untuk klarifikasi (R.3)."""
    lookup = _specific_lookup(normalized)
    if lookup is None:
        return [], None

    entity, tokens = lookup

    # Fix #13A — kode spesifik (mis. KPP-DEWASA-V2) → lookup by code (EXACT).
    raw_message = str(normalized.get("raw") or "").upper()
    codes = [
        code
        for code in CODE_PATTERN.findall(raw_message)
        if any(char.isdigit() for char in code)
    ]
    if codes:
        code = codes[0]
        repo = get_repo(entity)
        code_rows: list[dict] = []
        if repo is not None:
            try:
                code_rows = repo.get_list(
                    filters={"code__icontains": code}, limit=5
                )
            except Exception:
                code_rows = []
        data_key = ENTITY_DATA_KEYS.get(entity, "")
        if code_rows and data_key:
            data[data_key] = code_rows
        score = 0.95 if len(code_rows) == 1 else 0.7
        return _dedup_candidates(
            [_make_candidate(entity, row, score) for row in code_rows]
        ), entity

    rows = _candidate_rows(entity, data)

    # Pilih baris dengan jumlah token cocok TERBANYAK (hindari melebar ke semua
    # produk hanya karena satu kata sama).
    scored = []
    for row in rows:
        haystack = _candidate_haystack(row)
        hits = sum(1 for token in tokens if token in haystack)
        if hits:
            scored.append((hits, row))
    best_hits = max((hits for hits, _row in scored), default=0)
    matched = [row for hits, row in scored if hits == best_hits]

    # Token berangka (mis. KPP-DEWASA-V2) boleh menghasilkan EMPTY yang tegas.
    if not matched and not any(
        char.isdigit() for token in tokens for char in token
    ):
        return [], None

    score = 0.9 if len(matched) == 1 else 0.7
    candidates = _dedup_candidates(
        [_make_candidate(entity, row, score) for row in matched[:20]]
    )
    return candidates, entity
