# 🧱 Refactor Contract — AI Chat (`views.py` + `context_builder.py`)

> **Status:** 📝 DESIGN ONLY — belum ada kode diubah · **Tanggal:** 2026-10-21
> **Baseline:** backend **3052 passed / 0 failed / 1 skipped** · frontend **1771 passed**
> **Prinsip:** refactor = **perilaku SAMA**. Fix dan refactor **tidak boleh** satu commit.

---

## 1. Tujuan

Memecah dua file terbesar tanpa mengubah perilaku/kontrak:

| File | Baris | Fungsi | Masalah |
|---|---|---|---|
| `integrations/ai_agent/api/views.py` | 535 | 12 | `AiChatView.post` **292 baris**, 22 `if`, kedalaman 7 |
| `integrations/ai_agent/orchestrator/context_builder.py` | 1515 | 36 | `_auto_detect_keywords` **237 baris**, `build_context` 188 baris |

## 2. Non-goals

- Tidak mengubah kontrak `POST /api/v1/ai/chat` (field respons, status code).
- Tidak mengubah semantik klarifikasi (TTL 600 dtk, maks 3 turn, `RULE_HIT`, 0 token).
- Tidak mengubah nama key data konteks (`_candidates`, `_aggregate_query`, …).
- Tidak menambah fitur, tidak memperbaiki bug (bug = commit terpisah).

---

## 3. Baseline & gate

| Gate | Nilai wajib |
|---|---|
| Backend full suite | **3052 passed / 0 failed / 1 skipped** (tidak boleh turun) |
| Frontend | 1771 passed (tidak disentuh) |
| Smoke manual | 6 pertanyaan (lihat §7) |
| `python -m compileall` | 0 error |

---

## 4. Target struktur `api/views.py`

### 4.1 File

```
api/views.py                          ~90 baris  (AiChatView: validasi + delegasi)
api/handlers/__init__.py              ~10 baris
api/handlers/clarification.py        ~110 baris  (pending state + resolver)
api/handlers/llm_pipeline.py         ~160 baris  (decision gate → intent → tools → context → synth)
api/handlers/logging.py               ~60 baris  (log_decision + cost_tracker + audit)
```

### 4.2 Kontrak publik

```python
# handlers/clarification.py
def handle_pending_clarification(request, message: str) -> Response | None: ...

# handlers/llm_pipeline.py
def run_pipeline(request, message: str, context: dict, *, session_id: str) -> dict: ...

# handlers/logging.py
def finalize(request, result: dict, *, intent: str, model_used: str,
             classifier_cost: float, audit_text: str) -> None: ...
```

### 4.3 Invarian

1. `AiChatView.post` **tetap ada** dan menjadi orkestrator tipis (urutan tidak berubah):
   validasi → rate limit → klarifikasi → role guard → decision gate → cache → LLM → log.
2. `views.py` **tetap mengimpor modul yang sama** di level modul (`context_builder`,
   `response_synthesizer`, `intent_classifier`, `tool_selector`, `rule_evaluator`,
   `pending_state`). Tujuan: patch path test yang ada
   (`integrations.ai_agent.api.views.<modul>...`) **tetap valid** tanpa menyentuh test.
3. Handler memakai **objek modul yang sama** (bukan `from ... import build_context`),
   agar `patch.object` pada modul tetap berlaku.
4. Signature helper lama (`_response`, `_tool_calls`, `_clarification_response`)
   dipertahankan minimal sampai refactor selesai.

---

## 5. Target struktur `context_builder`

### 5.1 File (paket, bukan file tunggal)

```
orchestrator/context_builder/__init__.py        ~60 baris  (build_context + re-export)
orchestrator/context_builder/aggregate.py       ~120 baris (is_aggregate_query, top/count query)
orchestrator/context_builder/candidates.py      ~170 baris (specific lookup, kandidat, dedup, attrs)
orchestrator/context_builder/keywords.py        ~260 baris (_auto_detect_keywords, per domain)
orchestrator/context_builder/detail_expand.py   ~90 baris  (_expand_detail_context)
orchestrator/context_builder/resources.py       ~120 baris (_collect_resource/stocks/bundles/events)
orchestrator/context_builder/metrics.py         ~120 baris (_collect_metrics, _metric_result, dimension)
orchestrator/context_builder/constants.py       ~80 baris  (LIST_TABLES, labels, hints, patterns)
```

### 5.2 Kontrak publik

```python
def build_context(intent, tools, message, context=None, user=None, history=None) -> dict: ...
def is_aggregate_query(message: str) -> bool: ...
```

- `_detect_top_query`, `_detect_count_query`, `_collect_candidates` dkk menjadi **internal**
  (boleh diimpor test yang sudah ada lewat `context_builder.<nama>` → **wajib di-re-export**
  di `__init__.py` sampai test dimigrasi).

### 5.3 Invarian data

Key yang **wajib** tetap ada dan berbentuk sama:
`intent`, `message`, `normalized_message`, `context`, `tools`, `product_list`, `orders`,
`partners`, `bundles`, `metrics_by_line`, `metrics_by_wc`, `line_balance`, `bottleneck`,
`customer_total_spend`, `_candidates`, `_entity_label`, `_aggregate_query`,
`_top_query`, `_count_query`, `requested_count`, `_resolved_candidate`.

---

## 6. Urutan eksekusi

| Fase | Isi | Gate |
|---|---|---|
| **R-1** | Extract `handlers/` dari `views.py` (3 file) | full suite 3052 hijau + smoke |
| **R-2** | Pecah `context_builder.py` → paket (7 modul) | full suite 3052 hijau + smoke |
| R-3 (opsional) | Migrasi test ke import baru (hapus re-export) | full suite hijau |

Satu fase = satu commit (lihat §9).

---

## 7. Strategi test

- **Tidak mengubah assertion** selama refactor. Perubahan hanya bila import/patch path
  benar-benar pindah (dan itu **tidak** diharapkan karena §4.3 dan §5.2).
- Full suite dijalankan tiap fase (±3 menit).
- Smoke manual (6 pertanyaan):
  1. `produk KPP-DEWASA-V2?` → EXACT (detail)
  2. `berapa harga kaos polos?` → daftar kandidat dengan harga/kategori
  3. `yg ke 4` → memilih kandidat ke-4
  4. `line mana tidak seimbang?` → dijawab (bukan tanya)
  5. `top 3 customer?` → ranking pelanggan
  6. `5 produk kaos polos` → daftar 5 (bukan klarifikasi)

---

## 8. Risiko & mitigasi

| Risiko | Mitigasi |
|---|---|
| Patch path test patah | Pertahankan import modul di `views.py` + re-export di `context_builder/__init__.py` |
| Import cycle (`context_builder` ↔ `synthesizer`) | `context_builder` tetap tidak mengimpor synthesizer; arah dependensi satu arah |
| Perubahan perilaku tak sengaja | Bandingkan respons JSON sebelum/sesudah via smoke; diff assertion test = 0 |
| Konflik dengan Fase Sedang | Refactor selesai **sebelum** HITL action agar tidak menumpuk cabang |

---

## 9. Commit policy

- `refactor(ai): extract chat handlers from AiChatView` (R-1)
- `refactor(ai): split context_builder into package` (R-2)
- Tidak menggabung fix bug/seed/docs ke commit refactor.
- Tiap commit harus lulus full suite; tidak ada `--no-verify`.

---

## 10. Estimasi

| Langkah | Estimasi |
|---|---|
| R-1 views (extract + test) | **3–4 jam** |
| R-2 context_builder (split + test) | **5–6 jam** |
| R-3 migrasi import test (opsional) | 1–2 jam |
| **Total** | **9–12 jam** |

