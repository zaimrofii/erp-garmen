# 💬 Kontrak Chat AI — MES Garmen

> **Status:** ✅ FINAL (Sprint A) · **Berlaku sejak:** 2026-10-18 · **Versi:** 1.0
> **Fase:** A (kontrak) — implementasi `integrations/ai_agent/` di **Sprint D**,
> UI di **Sprint E**.
> **Baca juga:** [`MCP-REGISTRY.md`](./MCP-REGISTRY.md), [`../analytics/CONTRACT.md`](../analytics/CONTRACT.md), [`../analytics/TOGGLE-CONTRACT.md`](../analytics/TOGGLE-CONTRACT.md).

---

## 1. Prinsip

| Prinsip | Konsekuensi |
|---|---|
| AI **read & propose only** | Tidak ada write langsung; semua write → HITL |
| Konteks = **payload terstruktur** | Bukan dump HTML/DOM/state React |
| Satu endpoint untuk semua kanal | `/api/v1/ai/chat` (desktop, floating, WA) |
| Floating icon = **panel samping** | Tidak redirect ke `/ai/chat` |
| Tool = registry tunggal | `AI_TOOL_REGISTRY`; `mcp-analytics` salah satu entri |
| Deterministik bila mungkin | Rule yang bisa dijawab tanpa LLM **tidak** memanggil LLM |
| Transparan | `tool_calls`, `confidence_score`, `impact_score`, `latency_ms` selalu ada |

---

## 2. Request

`POST /api/v1/ai/chat`

```json
{
  "message": "kenapa scrap di cutting naik minggu ini?",
  "context": {
    "page_type": "detail",
    "route": "/master/products/123",
    "resource_type": "product",
    "resource_id": "123",
    "filters": {},
    "visible_fields_snapshot": {
      "code": "KTS-001",
      "name": "Kaos Polos",
      "uom": "PCS",
      "category": "Kaos"
    }
  },
  "history": [
    {"role": "user", "content": "berapa scrap rate bulan ini?"},
    {"role": "assistant", "content": "Scrap rate bulan ini 3,4%."}
  ],
  "channel": "DESKTOP"
}
```

| Field | Tipe | Wajib | Aturan |
|---|---|---|---|
| `message` | string | ✅ | 1–2000 karakter; whitespace-only → 400 |
| `context` | object | ❌ (default kosong) | Lihat §4 |
| `history` | array | ❌ | Maks **10** pasangan; item `{role: user\|assistant, content}` |
| `channel` | enum | ❌ | `DESKTOP` \| `FLOATING` \| `WA` (default `DESKTOP`) |
| `context.page_type` | enum | ❌ | `detail` \| `list` \| `form` \| `report` \| `null` |
| `context.route` | string | ❌ | Path frontend, maks 300 karakter |
| `context.resource_type` | string/null | ❌ | `product`, `partner`, `bundle`, `order`, `work_order`, `invoice`, … |
| `context.resource_id` | string/null | ❌ | **Selalu string** (bukan number) agar aman untuk UUID/int |
| `context.filters` | object | ❌ | Filter aktif di halaman (primitif saja) |
| `context.visible_fields_snapshot` | object | ❌ | Maks 40 field; **hanya** field yang tampil |

### 2.1 Batas ukuran (ditolak 400 bila dilanggar)

| Bagian | Batas |
|---|---|
| `message` | 2000 karakter |
| `history` | 10 item, total 8000 karakter |
| `filters` | 20 key; nilai string ≤ 200 karakter |
| `visible_fields_snapshot` | 40 key; nilai string ≤ 500 karakter |
| Total body | 64 KB |

---

## 3. Response

```json
{
  "ok": true,
  "answer": "Scrap di Cutting naik 2,1 poin karena 3 bundle DRAFT tidak punya event > 24 jam.",
  "tool_calls": [
    {"tool": "mcp-analytics", "input": {"metric_id": "garment.scrap_rate", "dimension": "work_center"},
     "output_summary": "scrap_rate=5.8% (Cutting), baseline 3.7%"}
  ],
  "confidence_score": 0.92,
  "impact_score": "LOW",
  "hitl_required": false,
  "hitl_request_id": null,
  "decision_gate_result": "RULE_HIT",
  "tokens": {"prompt": 0, "completion": 0, "total_cost_usd": 0},
  "cache_hit": false,
  "latency_ms": 812
}
```

| Field | Tipe | Aturan |
|---|---|---|
| `ok` | bool | `false` hanya untuk kegagalan yang **tidak** melempar HTTP error (§6) |
| `answer` | string | Bahasa Indonesia; maks 4000 karakter |
| `tool_calls` | array | Urut eksekusi; `tool` = nama registry; `output_summary` ≤ 500 karakter (bukan output mentah) |
| `confidence_score` | float 0–1 | `< 0.60` → `answer` wajib menyertakan ketidakpastian |
| `impact_score` | enum | `LOW` \| `MEDIUM` \| `HIGH`; `HIGH` ⇒ `hitl_required=true` |
| `hitl_required` | bool | True bila aksi mengubah data atau impact HIGH |
| `hitl_request_id` | int/null | ID `AiHitlRequest` bila `hitl_required` |
| `decision_gate_result` | enum | `RULE_HIT` \| `LLM_NEEDED` \| `BLOCKED` |
| `tokens` | object | `prompt`, `completion`, `total_cost_usd` (0 bila tidak memanggil LLM) |
| `cache_hit` | bool | Cache jawaban deterministik (TTL 5 menit, key = hash payload) |
| `latency_ms` | int | Waktu server total |

---

## 4. Kontrak konteks per `page_type` (KUNCI)

| `page_type` | Route contoh | `resource_type` | `resource_id` | `filters` | `visible_fields_snapshot` |
|---|---|---|---|---|---|
| `detail` | `/master/products/123` | `product` | `"123"` | `{}` | field produk yang tampil |
| `list` | `/master/products` | `product` | `null` | filter aktif (mis. `{"q":"kaos"}`) | `{}` |
| `form` (create) | `/master/products/new` | `product` | `null` | `{}` | field form kosong |
| `form` (edit) | `/master/products/123/edit` | `product` | `"123"` | `{}` | field form terisi |
| `report` | `/reports/sales?period=2026-10` | `report` | `null` | `{"period":"2026-10"}` | `{}` |
| `report` (detail) | `/reports/sales?period=2026-10&customer_id=5` | `report` | `null` | `{"period":"2026-10","customer_id":"5"}` | `{}` |
| tanpa konteks | `/` atau route tak terduga | `null` | `null` | `{}` | `{}` |

Aturan tabel:

1. `page_type=list`/`report` **boleh** `resource_type` terisi dengan
   `resource_id=null` (konteks "sedang melihat daftar produk").
2. `page_type` selain itu: `resource_type` **wajib null** kalau `resource_id`
   null (§5).
3. `visible_fields_snapshot` **hanya** untuk `detail`/`form`; `list`/`report`
   mengirim `{}`.
4. Nilai `resource_id` **selalu string**; backend tidak melakukan cast implisit.

---

## 5. Aturan validasi konteks (KUNCI)

| # | Aturan | Pelanggaran |
|---|---|---|
| 1 | `resource_type` **wajib null** bila `resource_id` null, **kecuali** `page_type` = `list`/`report` | 400 `bad_context` |
| 2 | `resource_type` terisi + `resource_id` null + `page_type` bukan `list`/`report` | **400** `{"ok": false, "error": "bad_context"}` |
| 3 | `resource_id` terisi + `resource_type` null | 400 `bad_context` |
| 4 | `page_type` tidak dikenal | 400 `bad_context` |
| 5 | `resource_id` bukan string / kosong | 400 `bad_context` |
| 6 | User **tidak berhak** melihat resource (role/objek) | **200** `{"ok": false, "error": "forbidden_context"}` |
| 7 | Resource tidak ditemukan | **200** `{"ok": false, "error": "not_found_context"}` |
| 8 | Analytics OFF dan pertanyaan butuh analytics | **200** `{"ok": false, "error": "analytics_disabled"}` |
| 9 | `AI_AGENT_ENABLED=false` (stub lama) | **200** `{"ok": false, "reason": "not_implemented"}` (kompatibel §8) |

Aturan #6 memakai pemeriksaan yang **sama** dengan endpoint resource
(`RoleRoute`/permission DRF) — AI tidak boleh menjadi jalur bocor data.
Aturan #6–#8 memakai **HTTP 200 + ok:false** (bukan 403/503) karena ini
kegagalan konteks, bukan kegagalan transport.

---

## 6. Error contract

| Kondisi | HTTP | Body |
|---|---|---|
| Body tidak valid (JSON/tipe) | 400 | `{"ok": false, "error": "bad_request", "detail": "..."}` |
| Konteks tidak valid (§5 #1–#5) | 400 | `{"ok": false, "error": "bad_context", "detail": "..."}` |
| Anonim | 403 | `{"detail": "..."}` (permission DRF) |
| Role tidak boleh AI | 403 | `{"detail": "..."}` |
| Rate limit terlampaui | 429 | `{"ok": false, "error": "rate_limited", "retry_after_s": 30}` |
| Timeout LLM/tool | 200 | `{"ok": false, "error": "upstream_timeout"}` |
| Tool error (MCP down) | 200 | `{"ok": false, "error": "tool_unavailable", "tool": "mcp-analytics"}` |
| Circuit breaker terbuka | 200 | `{"ok": false, "error": "circuit_open", "tool": "..."}` |
| Analytics OFF saat dibutuhkan | 200 | `{"ok": false, "error": "analytics_disabled"}` |
| Konteks terlarang | 200 | `{"ok": false, "error": "forbidden_context"}` |
| `AI_AGENT_ENABLED=false` (stub lama) | 200 | `{"ok": false, "reason": "not_implemented"}` |

Tidak ada 5xx untuk kondisi bisnis; 5xx hanya bug server.

---

## 7. Kanal & floating panel

| Kanal | UI | Perilaku |
|---|---|---|
| `DESKTOP` | Halaman penuh `/ai/chat` | Chat dengan riwayat panjang |
| `FLOATING` | **Panel samping** (drawer) dari ikon mengambang | Tidak redirect; konteks halaman otomatis terisi |
| `WA` | Gateway WA (integrasi terpisah) | Tanpa UI; `context` minimal, `channel="WA"` |

Aturan floating (kunci):

1. Endpoint **sama** (`/api/v1/ai/chat`); beda hanya `channel` + `context`.
2. Klik ikon membuka panel; **tidak** `navigate('/ai/chat')`.
3. Panel mengirim `context.page_type/route/resource_*` halaman aktif.
4. Panel tidak menampilkan tool mentah; hanya `answer` + ringkasan tool.
5. Aksi yang butuh HITL menampilkan tombol "Ajukan Persetujuan", bukan
   mengeksekusi (§9).

---

## 8. Kompatibilitas stub lama (sampai Sprint D.5)

Stub saat ini: `integrations/ai/api.py` (62 baris) + `integrations/ai/hitl_views.py`
(306 baris), URL `/api/v1/ai/chat` & `/api/v1/ai/hitl/*`.

| Kondisi | Perilaku |
|---|---|
| `AI_AGENT_ENABLED=false` (default) | Stub lama: **200** `{"ok": false, "reason": "not_implemented", "schema_version": "1.0"}` |
| `AI_AGENT_ENABLED=true` | Stub lama menjadi **thin adapter** → delegasi ke `integrations/ai_agent/` |
| URL | Tidak berubah; tidak ada breaking change |

Sprint D.5 **tidak** menghapus stub; hanya menambah delegasi. Field `reason`
dipertahankan agar klien lama tetap mengenali respons.

---

## 9. HITL & decision gate

| Langkah | Aturan |
|---|---|
| 1 | Decision gate memeriksa **rule** dulu (mis. "analitik belum aktif", "role tidak berhak") |
| 2 | Bila rule cukup → `decision_gate_result=RULE_HIT`, **tanpa LLM** (`tokens` = 0) |
| 3 | Bila perlu LLM → `LLM_NEEDED`; tool dipanggil lewat `AI_TOOL_REGISTRY` |
| 4 | Bila usulan mengubah data atau `impact_score=HIGH` → `hitl_required=true`, buat `AiHitlRequest`, `hitl_request_id` diisi |
| 5 | AI **tidak** mengeksekusi write; eksekusi hanya lewat approve HITL (Sprint F) |

Endpoint HITL yang sudah ada (dipakai ulang, bukan diduplikasi):
`GET /api/v1/ai/hitl/queue/`, `POST /api/v1/ai/hitl/<id>/approve/`,
`POST /api/v1/ai/hitl/<id>/reject/`.

Aturan tambahan:

- `impact_score=HIGH` **selalu** `hitl_required=true` (tanpa pengecualian).
- `confidence_score < 0.60` → `answer` wajib memuat frasa ketidakpastian
  (mis. "perlu verifikasi") dan **tidak boleh** menyarankan aksi write.
- `tool_calls` disimpan pada `AiHitlRequest` (bila HITL) agar approver melihat
  dasar usulan.

---

## 9b. Epistemic Clarification (Fase Ringan, 2026-10)

Lapisan **deterministik** sebelum LLM: `integrations/ai_agent/clarification/`.
Tidak memanggil LLM dan tidak menulis data bisnis.

| Status | Kondisi | Response |
|---|---|---|
| `EXACT` | 1 kandidat skor ≥ 0.85 (atau semua `answer_hash` sama) | lanjut LLM normal |
| `AMBIGUOUS` | 2..5 kandidat berbeda | pertanyaan pilihan (0 token) + pending state |
| `WEAK` | 1 kandidat skor < 0.85 | konfirmasi ya/tidak (0 token) + pending state |
| `EMPTY` | 0 kandidat | `"Tidak ada <entity> untuk '<query>' di data saat ini."` (0 token) |
| `OUT_OF_SCOPE` | query < 2 karakter | `"Pertanyaan terlalu singkat. Mohon perjelas."` (0 token) |

**Pending state (Redis/cache):**

- TTL `600` detik, maks `3` turn; key `clarification:<user_id>:<session_id>`.
- Isi: `{candidates, original_query, question, turn_count, entity, updated_at}`.
- Kandidat: `{id, label, attrs, score, entity}`.

**Resolver balasan user (`clarification/resolver.py`, PURE):**

| Tipe | Contoh | Aksi |
|---|---|---|
| `RANK` | "yg kedua", "2", "nomor 2" | pilih `candidates[n-1]` |
| `FUZZY` | "kaos sate" | `rapidfuzz.partial_ratio ≥ 70` (fallback substring) |
| `CANCEL` | "bukan itu", "lupakan" | clear state → "Baik, saya lupakan…" |
| `ALL` | "semua", "semuanya" | ringkasan agregat deterministik |
| `ESCALATE` | turn ≥ 3 | tampilkan daftar lengkap + minta kriteria |
| `UNRESOLVED` | balasan tak dikenali | ulang pertanyaan + `turn_count += 1` |

Aturan tambahan:

1. Pesan yang tampak pertanyaan baru saat state aktif → state dibersihkan (ganti topik).
2. Respons klarifikasi `cacheable=false` → **tidak** masuk semantic cache.
3. `RANK`/`FUZZY` → `_resolved_candidate` diteruskan ke context builder (query by id),
   lalu lanjut LLM.
4. Angka murni di luar rentang ordinal **tidak** dianggap fuzzy (cegah "2" cocok
   ke kode `SO-042`).
5. Semua balasan klarifikasi tetap memakai shape §3
   (`decision_gate_result=RULE_HIT`, `tokens` = 0).

---

## 10. Privasi & batas

| Aturan | Detail |
|---|---|
| Tanpa kredensial | `context`/`history` tidak boleh memuat API key, password, token, `ODOO_API_KEY` |
| Tanpa PII berlebih | `visible_fields_snapshot` hanya field yang tampil; backend memangkas field sensitif (`password`, `api_key`, `npwp` opsional) |
| Retensi history | Disimpan maks 30 hari (Sprint F), lalu dianonimkan |
| Logging | `message` tidak di-log penuh pada level INFO (hanya hash + panjang) |
| Tool output | `output_summary` (bukan raw rows) agar tidak membocorkan dataset besar |

---

## 11. Keputusan Terkunci

1. Satu endpoint `/api/v1/ai/chat` untuk **semua** kanal (`DESKTOP`, `FLOATING`, `WA`).
2. Floating icon = **panel samping**; **tidak** redirect ke `/ai/chat`.
3. Konteks AI = **payload terstruktur** per `page_type` (§4), bukan dump DOM.
4. `resource_type` wajib null bila `resource_id` null, **kecuali**
   `page_type=list`/`report`.
5. Backend menolak **400 `bad_context`** untuk kombinasi terlarang.
6. Backend memvalidasi **role terhadap resource**; tidak boleh → 200
   `ok:false` `forbidden_context`.
7. AI **read & propose only**; write hanya lewat HITL.
8. `impact_score=HIGH` ⇒ `hitl_required=true` (tanpa pengecualian).
9. `confidence_score < 0.60` ⇒ tidak boleh menyarankan write.
10. `decision_gate_result=RULE_HIT` ⇒ **tanpa LLM** (`tokens=0`).
11. Stub lama `integrations/ai/` tetap hidup sampai Sprint D.5; menjadi thin
    adapter saat `AI_AGENT_ENABLED=true`, tetap `{ok:false}` saat false.
12. Endpoint HITL yang dipakai adalah yang **sudah ada** (`/api/v1/ai/hitl/*`).

---

## 12. Backlog

| Item | Fase | Catatan |
|---|---|---|
| Streaming jawaban (SSE/chunked) | E/F | kontrak response final tetap sama; tambah event stream |
| Memory percakapan lintas sesi (dual engine) | G | OPSIONAL setelah F stabil |
| Kanal WA dua arah penuh (balasan → thread) | F | butuh state percakapan |
| Multi-tool planning (chain > 3 tool) | F | batasi agar biaya terkendali |
| Sitasi sumber (link ke halaman/record) | E | `answer` + `sources[]` (aditif) |
| Terjemahan jawaban (EN) | G | tidak prioritas |
| Prompt/version registry + A/B test | F/G | observability dulu |
| Rate limit per-user (bukan per-IP) | F | pakai kuota token |
| Auto-ringkas history > 10 item | E | backend ringkas, bukan frontend |

---

## 10. Catatan implementasi Sprint D–F (2026-10-18)

| Komponen | Status | Catatan |
|---|---|---|
| Decision gate | ✅ Sprint D | `RULE_HIT`/`BLOCKED` tanpa LLM (`tokens=0`); `LLM_NEEDED` → `reason:"not_implemented"` (Sprint E belum memanggil LLM) |
| Endpoint chat | ✅ Sprint D | `POST /api/v1/ai/chat` (IsAuthenticated); `AI_AGENT_ENABLED=false` → stub lama tetap |
| HITL scorer/router | ✅ Sprint F.1 | `confidence_scorer` 0.95/0.0/0.7; `impact_scorer` LOW/MEDIUM/HIGH; `policy_checker` (operator tidak boleh write); `escalation_router` → `AIHitlQueue` |
| Endpoint HITL | ✅ Sprint F.1 | `GET /ai/hitl/queue/`, `POST /ai/hitl/<id>/approve|reject/`; delegasi dari stub lama, guard role sesuai `required_approver_role` |
| WA approval | ✅ Sprint F.2 | `POST /api/v1/wa/webhook/` — `APPROVE <id>` / `REJECT <id> <alasan>`; nomor wajib terdaftar (`AI_HITL_WA_APPROVERS`) |
| Observability | ✅ Sprint F.3 | `GET /api/v1/ai/observability/` (ADMIN/OWNER, cache 60 dtk); dashboard `/settings/ai-observability` |
| Cost & drift | ✅ Sprint F.4 | Budget bulanan per user (default $5) → 429 `budget_exceeded`; task drift harian + `AuditLog ai.drift_detected` |



## 13. LLM Integration (Sprint G)

| Aspek | Implementasi |
|---|---|
| Provider | `deepseek` default (`deepseek-chat`), fallback `gemini`; `AI_LLM_PROVIDER` |
| Endpoint | `POST /api/v1/ai/chat` — `LLM_NEEDED` memanggil LLM setelah decision gate |
| Context injection | `intent_classifier` → `tool_selector` → `context_builder` (MCP read-only) → `response_synthesizer`; prompt tidak pernah kosong |
| Data ke LLM | Metrik analytics (period + work_center untuk DIAGNOSTIC), resource allowlist, event bundle; batas baris dari `AI_CONFIG["mcp"]` |
| Privasi | `visible_fields_snapshot` disaring: password/api_key/token/secret selalu dibuang; npwp/credit_limit/salary/gaji hanya untuk FINANCE/ADMIN/OWNER; warning di log |
| Safety | System prompt melarang write action, harga/kredit/pajak untuk non-privileged, data produk di luar konteks, dan halusinasi; validator menolak `UPDATE`/`DELETE`/`INSERT`/`DROP`, memotong >5000 karakter, fallback untuk jawaban kosong |
| Cost | `tokens` + `total_cost_usd` per respons; classifier + synthesizer dicatat ke `AIDecisionLog`; `cost_tracker` memperbarui budget user |
| Budget | `check_budget` sebelum LLM → **429** `budget_exceeded` |
| Rate limit | Fixed-window **60 request/menit/user** → **429** `rate_limited`, `retry_after_s=60` |
| Cache | Exact-match sebelum LLM; cache hit = `tokens` 0 dan tidak ada panggilan LLM |
| HITL | LLM read-only → `hitl_required=false`; write tetap hanya lewat approve HITL |
| Error | LLM gagal → **200** `{ok:false, error:"llm_failed", detail, decision_gate_result:"LLM_NEEDED"}` |

Catatan operasional: setelah mengubah `.env`/settings, restart proses Django
(dev server dapat memegang settings lama).

---

