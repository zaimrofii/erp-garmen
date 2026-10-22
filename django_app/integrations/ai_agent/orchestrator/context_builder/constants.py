"""Konstanta context builder (R-2) — dipisah dari builder."""
from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)

METRIC_IDS = (
    "garment.scrap_rate",
    "garment.rework_rate",
    "garment.lead_time",
    "garment.oee",
    "garment.wip_flow",
)

ANOMALY_KEYWORDS = (
    "manipulasi",
    "anomali operator",
    "input tidak wajar",
    "tidak wajar",
    "mencurigakan",
    "reliability",
    "reliabilitas",
    "operator tidak wajar",
)

STATUS_KEYWORDS = ("idle", "menganggur", "buffer", "overflow", "antrean")

GRAPH_KEYWORDS = ("relasi", "graph", "terkait", "terhubung")
DOCUMENT_KEYWORDS = ("sop", "prosedur", "dokumen")
CORRELATION_KEYWORDS = ("korelasi", "cacat per", "shift")
EXPLAIN_KEYWORDS = ("kenapa", "penyebab", "anomali")
SUMMARY_KEYWORDS = ("ringkasan", "summary", "hari ini")

METRIC_ROWS = 5

RESOURCE_ROWS = 5

EVENT_ROWS = 20

ALWAYS_SENSITIVE_FIELDS = (
    "password",
    "passwd",
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
)

RESTRICTED_FIELDS = (
    "npwp",
    "credit_limit",
    "creditlimit",
    "salary",
    "gaji",
)

PRIVILEGED_ROLES = {"FINANCE", "ADMIN", "OWNER"}

LIST_TABLES = {
    "product": "master_product",
    "partner": "master_partner",
    "order": "garment_order",
    "bundle": "garment_bundle",
}

FINANCIAL_FIELDS = {"sale_price", "cost_price", "credit_limit", "npwp"}

RESOURCE_TABLE_MAP = {
    "product": "master_product",
    "order": "garment_order",
    "workorder": "garment_workorder",
    "work_order": "garment_workorder",
    "bundle": "garment_bundle",
    "sync_record": "erp_sync_syncrecord",
}

CANDIDATE_ENTITIES = (
    "product",
    "order",
    "partner",
    "bundle",
    "work_center",
    "production_line",
)

ENTITY_LABELS = {
    "product": "produk",
    "order": "order",
    "partner": "customer",
    "bundle": "bundle",
    "work_center": "work center",
    "production_line": "line",
}

LIST_QUERY_HINTS = frozenset(
    {
        "apa",
        "saja",
        "semua",
        "daftar",
        "berapa",
        "jumlah",
        "total",
        "top",
        "paling",
        "tertinggi",
        "terendah",
        "termahal",
        "termurah",
        "aktif",
        "statistik",
        "laporan",
        "rekap",
        "tren",
        "minggu",
        "bulan",
        "hari",
        "tahun",
        "periode",
        "per",
        "bandingkan",
    }
)

AGGREGATE_KEYWORDS = (
    "tidak seimbang",
    "paling tidak seimbang",
    "seimbang",
    "bottleneck",
    "penyumbat",
    "hambatan",
    "menumpuk",
    "paling sibuk",
    "paling lambat",
    "paling cepat",
    "tertinggi",
    "terendah",
    "terbanyak",
    "tersedikit",
    "ranking",
    "urutkan",
    "bandingkan",
    "top",
)

QUESTION_STOPWORDS = frozenset(
    {
        "kenapa",
        "mengapa",
        "gimana",
        "bagaimana",
        "kapan",
        "siapa",
        "status",
        "detail",
        "info",
        "jelaskan",
        "tampilkan",
        "sebutkan",
        "carikan",
        "cari",
        "lihat",
        "tolong",
        "coba",
        "yang",
        "mana",
        "itu",
        "ini",
        "dan",
        "atau",
        "untuk",
        "dari",
        "pada",
        "dengan",
        "adalah",
        "bisa",
        "kah",
        "sih",
        "dong",
    }
)

PRICE_HINTS = ("harga", "price")

PRODUCT_NOUNS = (
    "kaos",
    "kemeja",
    "dress",
    "celana",
    "jaket",
    "baju",
    "rok",
    "koko",
    "kain",
)

PRICE_STOPWORDS = QUESTION_STOPWORDS | frozenset(
    {
        "harga",
        "price",
        "berapa",
        "produk",
        "product",
        "barang",
        "rp",
        "rupiah",
    }
)

_TOP_WORDS = r"(?:top|tertinggi|terbaik|ranking|peringkat)"

_TOP_ENTITIES = r"(?:customer|pelanggan|vendor|supplier)"

_COUNT_ENTITY_MAP = {
    "produk": "product",
    "product": "product",
    "order": "order",
    "orderan": "order",
    "bundle": "bundle",
    "paket": "bundle",
    "customer": "partner",
    "pelanggan": "partner",
    "partner": "partner",
    "vendor": "partner",
    "supplier": "partner",
}

_COUNT_PATTERN = re.compile(
    r"^\s*(\d+)\s+"
    r"(produk|product|order|orderan|bundle|paket|customer|pelanggan|"
    r"partner|vendor|supplier)\s+(.+?)\s*$",
    re.IGNORECASE,
)

CODE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+){1,4})\b")

__all__ = ("build_context",)
