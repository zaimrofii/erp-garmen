# Konsep Baru: **TRACE BRIDGE v2 — Versi Hemat**

## Inti

**Jembatan baca log JSON yang sudah kamu punya → JSON ringkas ramah AI.** Nol LLM. Nol infra baru. Nol perubahan Django. Reuse `RequestIDMiddleware` + `JsonFormatter` dari Sprint 6.

## Posisi

```
Django (sudah ada):
  RequestIDMiddleware → X-Request-ID
  JsonFormatter       → log JSON terstruktur ke disk
        ↓
   [logs/mes.jsonl]  ← sudah ada, tidak perlu diubah
        ↓
  ┌──────────────────┐
  │  TRACE BRIDGE    │ ← 4 file, kode biasa
  │  - reader         │
  │  - normalize      │
  │  - api            │
  └──────────────────┘
        ↓
   ┌────┴────┐
   ▼         ▼
[Cline AI] [CLI/Kamu]
```

## Prinsip

| Prinsip                 | Alasan                                                |
| ----------------------- | ----------------------------------------------------- |
| **1 endpoint dulu**     | `GET /_ai/trace/{trace_id}` — tambah saat Cline butuh |
| **JSONL, bukan Jaeger** | Nol infra, cukup baca file yang sudah ada             |
| **Nol LLM**             | Deterministik, murah, debug sendiri                   |
| **Nol OTel dulu**       | `RequestIDMiddleware` + `JsonFormatter` sudah cukup   |
| **Sampling 100% dulu**  | Optimasi nanti saat ada beban                         |
| **Tidak sentuh Django** | Production tetap bersih                               |

## Struktur (4 file)

```
trace_bridge/
├── api.py          # FastAPI — GET /_ai/trace/{trace_id}
├── normalize.py    # JSONL log → span tree ringkas
├── reader.py       # baca logs/mes.jsonl by trace_id
└── config.yaml     # path log + port
```

**Bukan** 8 file. Gabungkan sampai butuh pisah.

## Alur Minimum

```
Django tulis logs/mes.jsonl (sudah ada via JsonFormatter)
    ↓ rotate
reader.py     → filter by X-Request-ID
    ↓
normalize.py  → susun span tree (start→end, durasi, error)
    ↓
api.py        → GET /_ai/trace/{trace_id}
    ↓
Cline / CLI   → baca JSON ringkas
```

## Contoh Output

**Input** (JSONL mentah, sudah ada):

```json
{"ts":"2026-10-06T10:00:01","request_id":"abc123","span":"POST /bundle/scan","ms":45,"level":"INFO"}
{"ts":"2026-10-06T10:00:02","request_id":"abc123","span":"db.lock(bundle_42)","ms":1200,"level":"ERROR","msg":"timeout"}
{"ts":"2026-10-06T10:00:03","request_id":"abc123","span":"retry","ms":800,"level":"ERROR","msg":"still locked"}
```

**Output** (JSON ringkas ke AI):

```json
{
  "trace_id": "abc123",
  "duration_ms": 2045,
  "spans": [
    { "name": "POST /bundle/scan", "ms": 45 },
    { "name": "db.lock(bundle_42)", "ms": 1200, "error": "timeout" },
    { "name": "retry", "ms": 800, "error": "still locked" }
  ],
  "errors": 2
}
```

Cline langsung tahu: **race condition di lock bundle**.

## Yang Wajib di Django (sudah ada, cek saja)

1. ✅ `RequestIDMiddleware` — Sprint 6, `X-Request-ID` atau UUID4
2. ✅ `JsonFormatter` — Sprint 6, `config/logging.py`
3. ✅ Log rotate — tambah `RotatingFileHandler` kalau belum

**Nol perubahan kode.** Kalau log belum ada `trace_id` di tiap baris, tambah 1 field di `JsonFormatter` — itu saja.

## Stack

- **FastAPI** — 1 endpoint
- **Pydantic** — validasi output
- **Typer** — CLI (opsional, tambah nanti)
- **Tanpa** OTel, Tempo, Loki, Sentry, Jaeger

## Output

1. **AI debug mandiri** — Cline baca trace tanpa kamu jelaskan
2. **Trace end-to-end** — agent → Django → Odoo (asal semua pakai `X-Request-ID` sama)
3. **Regression** — replay trace sebelum/sesudah perubahan
4. **Hemat token** — JSON ringkas, bukan dump log 10MB

## Urutan Eksekusi Gabungan

```
Sprint mini 1 — Trace Bridge (4 file, 1 minggu)
  → 1 endpoint jalan, Cline bisa baca trace

Sprint mini 2 — Simulator (skeleton + 1 agent, 1-2 minggu)
  → pakai X-Request-ID sama → trace muncul otomatis di bridge

Hasil: Simulator trigger API → trace muncul → Cline baca.
       Fondasi Fase J (agent + tool + observability).
```

## Yang Harus Diputuskan Sekarang

| #   | Pilihan          | Rekomendasi                                                |
| --- | ---------------- | ---------------------------------------------------------- |
| 1   | Backend trace    | **JSONL dulu** (nol infra)                                 |
| 2   | Jumlah endpoint  | **1 dulu** (`/_ai/trace/{id}`)                             |
| 3   | Integrasi Django | **Pakai `RequestIDMiddleware` + `JsonFormatter`** existing |
| 4   | Sampling         | **100% dulu**                                              |
| 5   | OTel             | **Tunda** sampai lintas-service                            |

## Kenapa Ini "Jos"

- **Kamu lemah di traceability** → Bridge paksa struktur (`trace_id`, `span`, `context`)
- **Nol LLM** → deterministik, bisa debug sendiri
- **Berpasangan dengan Simulator** → Simulator bikin event, Bridge baca
- **Tidak sentuh production** → Django tetap bersih
- **Reuse existing** → `RequestIDMiddleware` + `JsonFormatter` sudah ada dari Sprint 6

---

**Peran:** Trace Bridge = **mata & telinga**. AI = **otak**. Django & Simulator = **dunia nyata**. Tidak ada yang berubah di production.

**Mau aku buatkan Prompt 1 — Trace Bridge versi hemat (4 file) siap jalan minggu ini?**
