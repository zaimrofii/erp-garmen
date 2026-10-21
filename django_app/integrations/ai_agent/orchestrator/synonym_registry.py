"""Registry sinonim istilah MES/ERP — SATU sumber kebenaran.

Tambahkan sinonim baru HANYA di file ini. Tool selector, context builder,
normalizer, dan conversation context membaca dari registry yang sama.
"""

from __future__ import annotations

# Format: {kata_kanonik: [sinonim1, sinonim2, ...]}
# Frasa multi-kata didukung; normalizer mencocokkan frasa terpanjang lebih dulu.
SYNONYM_MAP: dict[str, list[str]] = {
    # ── ENTITAS BISNIS ──────────────────────────────────────────────
    "produk": ["barang", "item", "sku", "artikel", "product", "katalog"],
    "order": [
        "orderan",
        "pesanan",
        "penjualan",
        "so",
        "sales order",
        "po customer",
        "order penjualan",
    ],
    "work_order": [
        "wo",
        "spk",
        "surat perintah kerja",
        "production order",
        "perintah produksi",
        "mo",
        "manufacturing order",
    ],
    "bundle": ["paket", "lot", "batch", "grup", "kumpulan barang", "bundel"],
    "customer": ["pelanggan", "client", "buyer", "pembeli"],
    "vendor": ["supplier", "pemasok", "penyuplai"],
    "partner": ["mitra", "rekan", "business partner"],
    "work_center": [
        "wc",
        "stasiun kerja",
        "mesin",
        "station",
        "cell",
        "tempat kerja",
        "work centre",
    ],
    "production_line": [
        "line",
        "lini",
        "lini produksi",
        "assembly line",
        "deretan stasiun",
    ],
    "invoice": ["faktur", "tagihan", "inv"],
    "payment": ["pembayaran", "bayar", "pelunasan"],
    "purchase_order": [
        "po",
        "pesanan beli",
        "order pembelian",
        "pr",
        "purchase requisition",
    ],
    "journal_entry": ["je", "jurnal umum", "entri jurnal", "gl entry"],
    "bom": ["resep", "formula", "bill of materials", "resep produk"],
    "routing": ["alur proses", "process plan", "rute produksi"],
    "stok": ["stock", "inventory", "persediaan", "gudang", "inventori"],
    "produksi": ["production", "manufacturing", "pembuatan"],
    # ── METRIK / KONSEP ─────────────────────────────────────────────
    "scrap": ["reject", "afkir", "cacat", "waste", "buang", "sisa"],
    "rework": ["perbaikan", "repair", "re-process", "perbaiki", "kerja ulang"],
    "lead_time": [
        "waktu tunggu",
        "waktu proses",
        "cycle time",
        "lama proses",
        "durasi",
    ],
    "bottleneck": [
        "penyumbat",
        "hambatan",
        "constraint",
        "titik lambat",
        "leher botol",
    ],
    "buffer": ["antrean", "queue", "stok antara", "penyangga"],
    "wip": ["barang setengah jadi", "in-process", "setengah jadi"],
    "fg": ["barang jadi", "produk akhir", "end product", "finished goods"],
    "rm": ["bahan baku", "material", "input", "bahan mentah"],
    "qc": [
        "quality control",
        "kendali mutu",
        "pengawasan kualitas",
        "quality check",
        "cek kualitas",
        "inspeksi",
    ],
    "oee": [
        "overall equipment effectiveness",
        "efektivitas mesin",
        "efisiensi mesin",
    ],
    "hpp": ["cogs", "cost of goods sold", "biaya pokok", "cost price", "biaya produksi"],
    "output": ["hasil produksi", "luaran", "keluaran"],
    "downtime": ["waktu henti", "mesin mati", "berhenti", "idle"],
    "defect": ["cacat produk", "defect", "ng"],
    # ── KATA SIFAT / INTENT ─────────────────────────────────────────
    "mahal": [
        "larang",
        "termahal",
        "tinggi harga",
        "premium",
        "pricey",
        "harga tinggi",
    ],
    "murah": ["rendah harga", "termurah", "ekonomis", "budget", "harga rendah"],
    "kritis": ["tipis", "rendah", "habis", "kurang", "minimum", "low"],
    "sibuk": ["ramai", "padat", "banyak kerja", "overload"],
    "lambat": ["lelet", "lama", "delay", "terlambat", "telat", "slow", "late"],
    "cepat": ["gesit", "singkat", "kilat", "fast"],
    "rewel": [
        "bermasalah",
        "sering error",
        "trouble",
        "rusak",
        "error",
    ],
    "royal": ["banyak beli", "boros belanja", "sultan", "big spender"],
    "boros": ["banyak pakai", "high usage", "pemakaian tinggi", "wasteful"],
    "naik": ["meningkat", "up", "melonjak", "spike", "increase"],
    "turun": ["menurun", "down", "drop", "decrease"],
    "terbaru": ["latest", "paling baru", "terakhir", "recent", "baru"],
    "terlama": ["oldest", "paling lama", "paling tua"],
    # ── FOLLOW-UP / KONTEKS ─────────────────────────────────────────
    "peringkat": ["rank", "ranking", "urutan", "posisi"],
    "pertama": ["1", "satu", "first", "nomor 1", "top"],
    "kedua": ["2", "dua", "second", "nomor 2"],
    "ketiga": ["3", "tiga", "third", "nomor 3"],
    "kemarin": ["yesterday", "hari lalu"],
    "tadi": ["barusan", "sebelumnya", "yang tadi"],
    "lagi": ["lain", "lainnya", "more"],
    # ── TAMBAHAN OPERASIONAL ────────────────────────────────────────
    "kapasitas": ["capacity", "daya tampung"],
    "efisiensi": ["efficiency", "efektivitas"],
    "target": ["sasaran", "goal", "target produksi"],
    "harga": ["price", "tarif", "nilai jual"],
    "jumlah": ["count", "banyaknya", "kuantitas", "qty"],
    "kualitas": ["quality", "mutu"],
    "pengiriman": ["delivery", "pengantaran", "kirim"],
    "belum": ["unpaid", "outstanding", "tertunda"],
    "belanja": ["spend", "spending", "pembelian"],
}

# Reverse map: sinonim (lowercase) → kata kanonik.
REVERSE_MAP: dict[str, str] = {}
for canonical, synonyms in SYNONYM_MAP.items():
    REVERSE_MAP[canonical] = canonical
    for synonym in synonyms:
        REVERSE_MAP[synonym.lower()] = canonical

#: Kata yang menandakan pesan adalah lanjutan percakapan.
FOLLOWUP_CANONICALS = frozenset(
    {"peringkat", "pertama", "kedua", "ketiga", "kemarin", "tadi", "lagi"}
)

#: Peringkat eksplisit ("kedua" → 2).
RANK_CANONICALS: dict[int, str] = {1: "pertama", 2: "kedua", 3: "ketiga"}

#: Kata kanonik → entity yang dipakai conversation context.
ENTITY_CANONICALS: dict[str, str] = {
    "produk": "product",
    "order": "order",
    "work_order": "work_order",
    "bundle": "bundle",
    "customer": "customer",
    "vendor": "vendor",
    "partner": "partner",
    "work_center": "work_center",
    "production_line": "production_line",
    "invoice": "invoice",
    "purchase_order": "purchase_order",
}


def get_canonical(word: str) -> str | None:
    """Return kata kanonik kalau dikenal, None kalau tidak."""
    if not word:
        return None
    cleaned = str(word).lower().strip().strip(".,!?;:()[]{}\"'")
    return REVERSE_MAP.get(cleaned)


def expand_keywords(keywords: list[str]) -> list[str]:
    """Expand keyword dengan kata kanonik dan seluruh sinonimnya."""
    result: list[str] = []
    for keyword in keywords or []:
        canonical = get_canonical(keyword)
        for value in (keyword, canonical):
            if value and value not in result:
                result.append(value)
        if canonical:
            for synonym in SYNONYM_MAP.get(canonical, []):
                if synonym not in result:
                    result.append(synonym)
    return result


__all__ = (
    "ENTITY_CANONICALS",
    "FOLLOWUP_CANONICALS",
    "RANK_CANONICALS",
    "REVERSE_MAP",
    "SYNONYM_MAP",
    "expand_keywords",
    "get_canonical",
)
