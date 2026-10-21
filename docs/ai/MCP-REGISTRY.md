# 🔌 Registry MCP & Tool AI — MES Garmen

> **Status:** ✅ FINAL (Sprint A) · **Berlaku sejak:** 2026-10-18 · **Versi:** 1.0
> **Fase:** A (kontrak) — model & seeding di **Sprint D.1**, implementasi
> `mcp-analytics` di **Sprint D**.
> **Baca juga:** [`CHAT-CONTRACT.md`](./CHAT-CONTRACT.md), [`../analytics/CONTRACT.md`](../analytics/CONTRACT.md), [`../analytics/TOGGLE-CONTRACT.md`](../analytics/TOGGLE-CONTRACT.md) §6.

---

## 1. Prinsip

| Prinsip | Konsekuensi |
|---|---|
| **Satu** registry | `AI_TOOL_REGISTRY` (DB `AIToolRegistry`) — bukan daftar hard-coded tersebar |
| Semua tool **read-only** di fase ini | Write = fase terpisah + HITL |
| Tools tidak tahu toggle sendiri | Tool analytics memanggil **service layer** |
| Internal, bukan publik | `mcp_endpoint_url` memakai skema `internal://` |
| Gagal aman | Tool error → `{ok:false}` rapi, bukan 5xx |

---

## 2. MCP server — status Sprint H T3 (10 aktif, 5 placeholder T4)

| # | `name` | Fungsi | Status | `allowed_roles` |
|---|---|---|---|---|
| 1 | `mcp-postgres-query` | Query tabel allowlist (tanpa DDL/DML) | ✅ aktif | `supervisor`, `owner`, `admin` |
| 2 | `mcp-event-log` | Riwayat `BundleEvent`/event bus per bundle/order | ✅ aktif | `operator`, `supervisor`, `qc`, `owner`, `admin` |
| 3 | `mcp-odoo-rpc` | Baca master/transaksi Odoo (read-only, tanpa write) | ✅ aktif (T1) | `supervisor`, `owner`, `admin` |
| 4 | `mcp-calculator` | Aritmetika deterministik (qty, %, selisih tanggal) | ✅ aktif | semua role AI |
| 5 | `mcp-rule-engine` | Evaluasi aturan bisnis (`core.rule_engine`) tanpa menulis | ✅ aktif (T2) | `supervisor`, `owner`, `admin` |
| 6 | `mcp-knowledge-graph` | Relasi entitas (order → WO → bundle → event) | ⏳ T4 deferred | `supervisor`, `owner`, `admin` |
| 7 | `mcp-vector-search` | Pencarian semantik dokumen internal (SOP, catatan) | ⏳ T4 deferred | `supervisor`, `owner`, `admin` |
| 8 | `mcp-analytics` | Metrik analytics (lihat §3) | ✅ aktif | `supervisor`, `owner`, `admin` |
| 9 | `mcp-aggregator` | SUM/AVG/COUNT/MIN/MAX/P50/P90 via DB | ✅ aktif (T2) | `supervisor`, `owner`, `admin` |
| 10 | `mcp-time-series` | Deret metrik snapshot/live per jam/hari | ✅ aktif (T2) | `supervisor`, `owner`, `admin` |
| 11 | `mcp-comparator` | Banding 2 periode / 2 dimensi metrik | ✅ aktif (T3) | `supervisor`, `owner`, `admin` |
| 12 | `mcp-forecaster` | Forecast MA/linear + prediksi completion order | ✅ aktif (T3) | `supervisor`, `owner`, `admin` |
| — | `mcp-quality-correlation` | Korelasi cacat–operator–mesin | ⏳ T4 deferred | `supervisor`, `owner`, `admin` |
| — | `mcp-anomaly-explainer` | Menjelaskan penyebab anomali | ⏳ T4 deferred | `supervisor`, `owner`, `admin` |
| — | `mcp-scheduler` | Jadwal produksi & kapasitas WC | ⏳ T4 deferred | `supervisor`, `owner`, `admin` |

> **10 aktif** + **5 placeholder T4** (KG, vector, quality-correlation,
> anomaly-explainer, scheduler). T4 ditunda — lihat
> `docs/ai/BACKLOG-MCP-T4.md`.

Aturan umum:

- `allowed_roles` **memfilter**; tool tetap mengecek role user (defense in depth).
- Tool yang butuh data sensitif (Odoo, postgres) **tidak** diberikan ke
  `operator`/`qc`/`inventory`.
- Tidak ada tool write (`create/update/delete`) di Sprint D; semuanya via HITL
  + endpoint bisnis biasa.

---

## 3. Entri `mcp-analytics` (lengkap)

```json
{
  "name": "mcp-analytics",
  "mcp_endpoint_url": "internal://integrations.analytics.mcp_bridge",
  "schema": {
    "get_metric": {"metric_id": "str", "dimension": "str"},
    "list_metrics": {"domain": "str"}
  },
  "read_only": true,
  "allowed_roles": ["supervisor", "owner", "admin"],
  "rate_limit_per_minute": 60,
  "circuit_breaker_threshold": 5,
  "active": true
}
```

> **Catatan (Q4):** `admin` **boleh query** (read-only) melalui `mcp-analytics` —
> dia yang meng-enable analytics dan perlu melihat hasilnya. Write tetap **tidak**
> boleh untuk admin; semua write = HITL `supervisor` + `owner`.

### 3.1 Kontrak `schema`

| Method | Input | Output (ringkas) |
|---|---|---|
| `list_metrics` | `{"domain": "garment"}` | `{"ok": true, "metrics": [{"metric_id", "label", "unit", "enabled"}]}` |
| `get_metric` | `{"metric_id": "garment.scrap_rate", "dimension": "work_center"}` | `{"ok": true, "metric_id", "value", "unit", "rows", "period", "enabled"}` |

Aturan output:

- Tool **tidak** mengembalikan `rows` penuh ke LLM bila > 50 baris; dipotong
  dan diberi `truncated: true`.
- Field `enabled` disertakan agar LLM/decision gate tahu alasan kosong.
- Tidak ada field internal (`_listeners`, config mentah) di output.

---

## 4. Jalur enforcement toggle (KUNCI — keputusan #11)

```
AI decision gate / LLM tool-call
        │
        ▼
mcp-analytics (integrations/analytics/mcp_bridge.py)
        │  ── TIDAK query DB, TIDAK HTTP
        ▼
analytics_config_services.get_config()
        │
        ├── enabled=false → return {"ok": false, "error": "analytics_disabled",
        │                            "reason": "analytics_disabled"}
        └── enabled=true  → filter domain/metric → ambil nilai metrik
```

Aturan:

1. **Wajib** lewat `analytics_config_services.get_config()`; dilarang
   `AnalyticsConfig.objects.get(...)` di `mcp_bridge.py`.
2. Dilarang memanggil `GET /api/v1/analytics/...` via HTTP internal.
3. Saat disabled, MCP mengembalikan:

   ```json
   {"ok": false, "error": "analytics_disabled", "reason": "analytics_disabled"}
   ```

4. Decision gate dapat menjawab **"Analitik belum aktif"** tanpa memanggil LLM
   (`decision_gate_result=RULE_HIT`, `tokens=0`).
5. Filter `enabled_metrics`/`enabled_domains` diterapkan oleh service layer,
   bukan oleh MCP.

> **Catatan:** `error` dan `reason` sengaja sama (`"analytics_disabled"`).
> Tujuan: kompatibilitas Decision Gate yang membaca salah satu field.
> **JANGAN hapus salah satu** tanpa mengubah Decision Gate.

---

## 5. Rate limit & circuit breaker

| Mekanisme | Aturan |
|---|---|
| Rate limit | `rate_limit_per_minute` per **user+tool** (bukan per IP) |
| Counter | cache Redis key `mcp:rl:<user_id>:<tool>:<menit>` |
| Terlampaui | `{ok:false, error:"rate_limited", retry_after_s:N}` (tanpa 5xx) |
| Circuit breaker | hitung kegagalan berurutan; buka setelah `circuit_breaker_threshold` |
| Saat terbuka | `{ok:false, error:"circuit_open", tool:"mcp-analytics"}` |
| Half-open | 1 percobaan setelah 60 detik; sukses → tutup, gagal → buka lagi |
| Reset | sukses apa pun menutup breaker |
| Observability | metrik `mcp_calls_total{tool,outcome}`, `mcp_latency_ms` |

Kegagalan yang dihitung: exception tool, timeout, koneksi internal gagal.
`analytics_disabled` **bukan** kegagalan (tidak menaikkan breaker).

---

## 6. Model `AIToolRegistry` (Sprint D.1)

Tabel `ai_agent_aitoolregistry` — satu baris per tool. Seed 8 entri §2 saat
migrasi/data migration.

| Field | Tipe | Default | Catatan |
|---|---|---|---|
| `name` | `SlugField(unique)` | — | `mcp-analytics` (unik) |
| `mcp_endpoint_url` | `CharField(200)` | — | `internal://...` |
| `schema` | `JSONField` | `{}` | Peta method → parameter |
| `read_only` | `BooleanField` | `True` | Fase ini **selalu** true |
| `allowed_roles` | `JSONField(list[str])` | `[]` | Kosong = tidak ada role (deny by default) |
| `rate_limit_per_minute` | `PositiveIntegerField` | `60` | 0 = tanpa limit (hindari) |
| `circuit_breaker_threshold` | `PositiveIntegerField` | `5` | 0 = nonaktif |
| `active` | `BooleanField` | `True` | Tool nonaktif tidak muncul di registry |
| `created_at`/`updated_at` | `DateTimeField` | auto | — |

Aturan model:

- `name` unik + **tidak** boleh diubah setelah dipakai (audit history).
- `active=False` ⇒ tool tidak bisa dipanggil walau role cocok.
- `read_only=False` **ditolak** di Sprint D (validasi model/seed); fase write
  akan menambah flag terpisah + HITL wajib.
- Tidak ada field kredensial di model; kredensial tool tinggal di env/service.
- Perubahan registry dicatat AuditLog `ai.tool_registry_update`.

---

## 7. Keamanan & audit

| Aturan | Detail |
|---|---|
| Endpoint internal | `internal://` tidak diekspos ke internet; dipanggil in-process/Celery |
| Role check ganda | registry `allowed_roles` **dan** pengecekan role user di tool |
| Allowlist query | `mcp-postgres-query` hanya view/tabel allowlist; tanpa `SELECT *` bebas |
| Tanpa write | Tidak ada tool yang menulis tabel bisnis |
| Audit | Setiap panggilan dicatat `ai.tool_call` (tool, user, durasi, outcome) |
| Redaksi | Argumen sensitif (token/kata sandi) tidak di-log |
| Timeout | Default 5 detik per tool; total rangkaian ≤ 15 detik |
| Output | Dipotong (≤ 50 baris / ≤ 500 karakter ringkasan) sebelum ke LLM |

---

## 8. Keputusan Terkunci

1. **Satu** `AI_TOOL_REGISTRY` (DB), semua tool terdaftar di sana.
2. 8 MCP server awal: postgres-query, event-log, odoo-rpc, calculator,
   rule-engine, knowledge-graph, vector-search, analytics.
3. Semua tool **read-only** di fase ini; write = fase terpisah + HITL.
4. `mcp-analytics` **wajib** memanggil
   `analytics_config_services.get_config()` — **bukan** DB langsung, **bukan**
   HTTP.
5. Saat analytics OFF → `{ok:false, error:"analytics_disabled",
   reason:"analytics_disabled"}`.
6. Decision gate boleh menjawab "analitik belum aktif" tanpa LLM (`RULE_HIT`).
7. `allowed_roles` kosong = tidak ada role yang boleh (deny by default).
8. Rate limit per user+tool; circuit breaker 5 kegagalan berurutan.
9. `active=False` ⇒ tool tidak dipanggil.
10. Tidak ada kredensial di tabel registry.

---

## 9. Backlog

| Item | Fase | Catatan |
|---|---|---|
| Tool write (dengan HITL wajib) | F+ | desain flag `requires_hitl` |
| Per-tool kuota biaya (token) | F | terkait observability |
| Tool versioning (`version` + deprecation) | F/G | penting saat schema berubah |
| `mcp-vector-search` backend nyata (pgvector) | G | sekarang placeholder |
| Health-check per tool di `/health/` | F | status breaker terlihat |
| Registry UI (admin melihat tool & kuota) | E/F | read-only dulu |
| Sandbox tool pihak ketiga | G+ | di luar cakupan MES |

---

## 8. Catatan implementasi Sprint F (2026-10-18)

- **HITL queue** kini memakai `AIHitlQueue` (Sprint D) saat `AI_AGENT_ENABLED=true`;
  endpoint lama (`HITLRequest`) tetap hidup sebagai fallback (tanpa breaking change).
- **Observability dashboard** (sebelumnya backlog) **DONE**: `GET /api/v1/ai/observability/`
  + halaman `/settings/ai-observability` (KPI, grafik biaya/hari, tool calls,
  decision gate, top queries hash, HITL approval rate). Cache 60 detik, `?_nocache=1`.
- **Rate limit per-user** (sebelumnya backlog) **DONE sebagian**: kuota biaya bulanan
  per user (`AI_CONFIG.observability.user_monthly_budget_usd`, default $5) → HTTP 429
  `budget_exceeded`; kuota token per menit masih backlog Sprint G.


