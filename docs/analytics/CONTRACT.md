# 📊 Kontrak Analytics — MES Garmen

> **Status:** ✅ FINAL (Sprint A) · **Berlaku sejak:** 2026-10-18 · **Versi:** 1.0
> **Fase:** A (kontrak) — implementasi di **Sprint B** (`integrations/analytics/`).
> **Baca juga:** [`TOGGLE-CONTRACT.md`](./TOGGLE-CONTRACT.md), [`../ai/MCP-REGISTRY.md`](../ai/MCP-REGISTRY.md), [`../blueprint.md`](../blueprint.md) §7, [`../../django_app/docs/integration-config.md`](../../django_app/docs/integration-config.md).

---

## 1. Tujuan & ruang lingkup

Analytics = **lapisan turunan (derived), read-only** di atas sumber data final MES.
Bukan sumber kebenaran, bukan penulis data bisnis.

| Aspek | Keputusan |
|---|---|
| Lokasi | **Di dalam repo Django**: `integrations/analytics/` (bukan microservice) |
| Sifat | Read-only + append-only snapshot (`MetricSnapshot`) |
| Pemicu | **Event-driven** — subscribe `core.event_bus`, **bukan polling** |
| Sumber | Sumber **FINAL**: `BundleEvent`, `ScrapAccumulator`, `SyncRecord`, `WorkOrder`, `OrderLine` |
| Dilarang | Membaca model "mentah" sebagai basis metrik (mis. menghitung ulang dari payload device) |
| Toggle | Fitur level-pertama, **DEFAULT OFF** (lihat TOGGLE-CONTRACT) |
| AI | AI **baca & usul**; write lewat HITL (lihat `../ai/CHAT-CONTRACT.md`) |

Analytics **tidak** menggantikan laporan H4 (`/api/v1/reports/*`). Laporan H4 =
snapshot transaksi bisnis; analytics = metrik operasional produksi berjalan
(scrap/rework/lead time) dengan granularitas waktu + alert stream.

---

## 2. Shape response (NON-ListPage, konsisten H4)

Semua endpoint metrik memakai satu bentuk. Bentuk ini **aditif** terhadap H4
(`rows`, `summary`, `group_by`, `filters`, `period`, `generated_at`, `cached`)
dan menambah 3 field toggle/histori.

```json
{
  "rows": [],
  "summary": {},
  "group_by": "period|work_center|line|null",
  "filters": {
    "echo": {},
    "resolved_from": "2026-10-01T00:00:00+07:00",
    "resolved_to": "2026-10-18T23:59:59+07:00"
  },
  "period": {
    "from": "2026-10-01T00:00:00+07:00",
    "to": "2026-10-18T23:59:59+07:00"
  },
  "generated_at": "2026-10-18T05:10:00+07:00",
  "cached": false,
  "enabled": true,
  "disabled_reason": null,
  "historical_data_available": true
}
```

### 2.1 Aturan field

| Field | Tipe | Aturan |
|---|---|---|
| `rows` | array | Satu baris per grup; `key`/`label`/`value` + atribut metrik |
| `summary` | object | Agregat seluruh periode (mis. `scrap_rate`, `p50`, `p90`) |
| `group_by` | enum/`null` | `period` \| `work_center` \| `line` \| `null` |
| `filters.echo` | object | Parameter yang dikirim klien (apa adanya, sudah dinormalisasi tipe) |
| `filters.resolved_from/to` | ISO-8601 | Rentang **efektif** setelah default diterapkan |
| `period` | object | Sama dengan `resolved_*` (kompatibel H4) |
| `generated_at` | ISO-8601 | Waktu server menyusun respons (timezone `Asia/Jakarta`) |
| `cached` | bool | `true` bila respons diambil dari cache 60 dtk |
| `enabled` | bool | Cermin `AnalyticsConfig.enabled` saat request |
| `disabled_reason` | string/null | `null` saat aktif; `"analytics_disabled"` saat OFF |
| `historical_data_available` | bool | `MetricSnapshot.objects.exists()` — **tidak** bergantung toggle |

### 2.2 Saat analytics OFF (kunci)

Response **tetap HTTP 200** dengan `rows: []`, `summary: {}`, `enabled: false`,
`disabled_reason: "analytics_disabled"`. **Tidak pernah 503** dan tidak pernah
mengosongkan `historical_data_available`.

Contoh:

```json
{
  "rows": [],
  "summary": {},
  "group_by": null,
  "filters": {"echo": {}, "resolved_from": null, "resolved_to": null},
  "period": {"from": null, "to": null},
  "generated_at": "2026-10-18T05:12:00+07:00",
  "cached": false,
  "enabled": false,
  "disabled_reason": "analytics_disabled",
  "historical_data_available": true
}
```

> Catatan: `historical_data_available: true` berarti **snapshot lama masih ada**
> (disable tidak menghapus data). Endpoint khusus membaca snapshot historis
> dicatat sebagai backlog (lihat §10).

---

## 3. Endpoint (3)

Base: `/api/v1/analytics/`

### 3.1 `GET /api/v1/analytics/metrics/<domain>/`

Daftar metrik yang tersedia untuk domain (mis. `garment`).

| Param | Tipe | Default | Catatan |
|---|---|---|---|
| `domain` | path (str) | — | `garment` (satu-satunya domain Sprint B) |
| `group_by` | enum | `period` | `period` \| `work_center` \| `line` |
| `period` | `YYYY-MM` | bulan berjalan | Menang atas `date_from/date_to` |
| `date_from`,`date_to` | ISO-8601 | — | inklusif; `from > to` → 400 |
| `work_center_id`,`line_id` | int | — | filter dimensi |
| `_nocache` | `1` | — | bypass cache (tidak baca & tidak tulis) |

Response: shape §2 + `rows` berisi satu entri per metrik:

```json
{"key": "garment.scrap_rate", "label": "Scrap Rate", "unit": "%", "value": 3.42}
```

`summary` berisi `metric_count`, `period_days`, dan `enabled_metrics`.

### 3.2 `GET /api/v1/analytics/metric/<metric_id>/`

Nilai satu metrik + metadata (definisi, sumber, granularity, alert).

Param sama dengan §3.1 (tanpa `domain`, karena `metric_id` memuat domain).
Response shape §2 + field tambahan di `summary` dan objek `metadata`:

```json
{
  "metadata": {
    "metric_id": "garment.scrap_rate",
    "label": "Scrap Rate",
    "unit": "%",
    "granularity": "hour|day",
    "source_models": ["garment.ScrapAccumulator", "garment.BundleEvent"],
    "formula_version": "1.0",
    "null_policy": "denominator_zero_returns_null"
  }
}
```

`metric_id` tidak dikenal → **404** `{"detail": "metrik tidak dikenal"}`.

### 3.3 `GET /api/v1/analytics/health/`

Status kesehatan subsistem analytics (tanpa query metrik berat).

```json
{
  "ok": true,
  "enabled": false,
  "disabled_reason": "analytics_disabled",
  "registry": {"metrics_registered": 3, "metrics_active": 3},
  "listeners": {"subscribed": 4, "last_event_at": "2026-10-18T05:09:12+07:00"},
  "stream": {"connected": true, "backend": "redis"},
  "storage": {
    "snapshots_total": 1280,
    "last_snapshot_at": "2026-10-18T05:00:00+07:00",
    "historical_data_available": true
  },
  "toggle": {"checked_at": "2026-10-18T05:12:00+07:00", "source": "service_layer"},
  "generated_at": "2026-10-18T05:12:00+07:00"
}
```

`health` **selalu 200** (bahkan saat OFF); field `ok` menandakan subsistem
siap, bukan toggle.

---

## 4. Auth & role

| Aturan | Nilai |
|---|---|
| Permission class | `IsAuthenticated` |
| Anonim | **403** (pola endpoint H4; bukan 401) |
| Guard role (default) | `["supervisor", "owner", "admin"]` |
| Sumber role | `request.user.role.code` (UPPERCASE) — bukan query param |
| Sanitasi | `enabled_metrics`/`enabled_domains` **tidak** memperluas role |
| Audit | Akses metrik dicatat **sampled** (1/100) untuk hindari banjir log |

Role di luar guard → **403** `{"detail": "Anda tidak berhak melihat analitik."}`.

---

## 5. Cache

| Aspek | Nilai |
|---|---|
| TTL | **60 detik** (analytics lebih volatile dari H4 300 dtk) |
| Backend | cache Django default (`RedisCache` di produksi) |
| Key | `analytics:<metric_or_domain>:<sha1(normalized_filters)>` |
| `?_nocache=1` | tidak membaca **dan** tidak menulis cache |
| Invalidasi | saat toggle berubah (enable/disable/update config) → hapus prefix `analytics:` |
| `cached` | `true` hanya bila respons berasal dari cache |

Cache **tidak** dipakai saat `enabled=false` (respons toggle selalu dihitung
murah) dan tidak dipakai oleh `/health/`.

---

## 6. Error contract

| Kondisi | HTTP | Body |
|---|---|---|
| Anonim | 403 | `{"detail": "..."}` |
| Role tidak berhak | 403 | `{"detail": "..."}` |
| Param tak dikenal / format salah | 400 | `{"detail": "..."}` |
| `from > to` | 400 | `{"detail": "rentang tanggal tidak valid"}` |
| `metric_id` tak dikenal | 404 | `{"detail": "metrik tidak dikenal"}` |
| Analytics OFF | **200** | shape §2.2 (`enabled:false`) |
| Domain tak dikenal | 404 | `{"detail": "domain tidak dikenal"}` |

Tidak ada endpoint analytics yang membalas 5xx untuk kondisi toggle.

---

## 7. Semantik toggle (dari sisi pembaca)

Implementasi & siklus hidup lengkap ada di [`TOGGLE-CONTRACT.md`](./TOGGLE-CONTRACT.md).
Dari sisi endpoint analytics, aturannya:

| `enabled` | `enabled_domains` | `enabled_metrics` | Metrik yang dilayani |
|---|---|---|---|
| `false` | apa pun | apa pun | **tidak ada** (200 + `disabled_reason`) |
| `true` | `[]` | `[]` | **semua** (permissive default) |
| `true` | `["garment"]` | `[]` | hanya domain `garment` |
| `true` | `[]` | `["garment.scrap_rate"]` | hanya metrik itu |
| `true` | `["garment"]` | `["garment.rework_rate"]` | hanya `garment.rework_rate` (metrics menang) |

Aturan kunci:

1. `enabled` = **master switch**. Saat `false`, `enabled_domains`/`enabled_metrics`
   **tidak dievaluasi sama sekali**.
2. Daftar kosong = **semua aktif** (permissive default), bukan "tidak ada".
3. `enabled_metrics` **menang** atas `enabled_domains` bila keduanya diisi.
4. Metrik yang tidak lolos filter **tidak** muncul di `rows`; totalnya tetap
   terlihat di `/health/` (`registry.metrics_active`).
5. Toggle tidak pernah mengubah bentuk response (field tetap ada, nilai berubah).

---

## 8. Tiga metrik pertama (Sprint B.6)

Definisi ini **terkunci** untuk Sprint B. Perubahan formula wajib menaikkan
`formula_version` dan dicatat di backlog.

### 8.1 `garment.scrap_rate`

| Aspek | Nilai |
|---|---|
| Label / unit | Scrap Rate / `%` |
| Sumber | `garment.ScrapAccumulator` (`qty`), `garment.BundleEvent` (`BUNDLE_FINISH`), `garment.Bundle.qty` |
| Formula | `Σ ScrapAccumulator.qty ÷ Σ Bundle.qty (bundle FINISH pada periode) × 100` |
| Denominator 0 | hasil **`null`** (bukan 0) — `null_policy: denominator_zero_returns_null` |
| Granularity | `hour` (stream) & `day` (laporan) |
| Dimensi | `period` \| `work_center` \| `line` |
| Filter | `work_center_id`, `line_id`, rentang tanggal |
| Basis waktu | `ScrapAccumulator.created_at` (numerik) & `BundleEvent.ts` (denominator) |

> **Denominator = Σ `Bundle.qty` untuk bundle dengan `BUNDLE_FINISH` di periode;
> bukan `WorkOrder.qty_planned` (rencana ≠ realisasi).** Alasan: scrap_rate harus
> diukur terhadap input yang **benar-benar diproses**, bukan qty yang direncanakan.

### 8.2 `garment.rework_rate`

| Aspek | Nilai |
|---|---|
| Label / unit | Rework Rate / `%` |
| Sumber | `garment.BundleEvent` (`event_type = "REWORK"`), `garment.BundleEvent` (`BUNDLE_FINISH`) |
| Formula | `Σ qty rework ÷ Σ qty bundle FINISH × 100`; `qty` dari `payload.qty` bila ada, jika tidak 1 per event REWORK |
| Denominator 0 | `null` |
| Granularity | `day` (laporan), `hour` (stream) |
| Dimensi | `period` \| `work_center` (via `payload.work_center_id` bila ada) \| `line` |
| Catatan | `ScrapAccumulator.rework_qty` **tidak** dipakai sebagai numerator (bisa dobel dengan event); hanya cross-check di `health` |

> **Numerator `rework_rate` = Σ `BundleEvent(REWORK).payload.qty` (fallback
> 1/event bila `payload.qty` kosong). `ScrapAccumulator.rework_qty` dipakai
> HANYA sebagai cross-check, bukan numerator.**

### 8.3 `garment.lead_time`

| Aspek | Nilai |
|---|---|
| Label / unit | Lead Time / `jam` |
| Sumber | `garment.BundleEvent` (`BUNDLE_START`, `BUNDLE_FINISH`) per `bundle_id` |
| Formula | Tiap bundle: `ts(BUNDLE_FINISH) − ts(BUNDLE_START)`; `summary` = `p50`, `p90`, `avg`, `n_bundles` |
| Bundle tanpa pasangan | dilewati + dihitung di `summary.incomplete_pairs` |
| Granularity | `day` (agregasi p50 per hari) |
| Dimensi | `period` \| `line` (via bundle → order line → line) |
| Catatan | Bukan "cycle time per WC"; itu metrik terpisah (backlog) |

### 8.4 `garment.line_balance`

| Aspek | Nilai |
|---|---|
| Label / unit | Line Balance / `ratio` (0.0–1.0) |
| Sumber | `garment.Bundle` (`qty_done` per WC per line), `garment.ProductionLine` |
| Formula | `1 − (max_wc − avg_wc) / avg_wc` |
| 1 WC | `1.0` (sempurna seimbang) |
| Null policy | `no_line_returns_empty` |
| Granularity | `day` (period grouping); `week` menyusul |
| Dimensi | `period` \| `line` |
| Formula version | `1.0` |
| Implementasi | `integrations/analytics/plugins/garment/metrics/line_balance.py` |
| Catatan | 1 query agregat (GROUP BY line + WC); **tanpa** query per baris |

### 8.5 `garment.bottleneck`

| Aspek | Nilai |
|---|---|
| Label / unit | Bottleneck / `score` |
| Sumber | `garment.Bundle` (buffer × waktu tunggu per WC) |
| Formula | `buffer_length × avg_wait_hours` |
| Buffer | Count bundle **aktif** (state bukan `DONE`/`CANCELLED`) di WC |
| Avg wait | Rata-rata `EXTRACT(EPOCH FROM now − updated_at)` per bundle (jam) |
| Null policy | `no_active_returns_empty` |
| Granularity | `hour`, `day` (snapshot; nilai tidak berubah oleh granularity) |
| Dimensi | `period` \| `work_center` |
| Formula version | `1.0` |
| Implementasi | `.../metrics/bottleneck.py` |
| Catatan | Postgres tidak punya `AVG(timestamptz)` → `AVG(EXTRACT(EPOCH ...))`, tetap 1 query |

### 8.6 Stream alert (spike)

Semua metrik memakai kontrak alert yang sama (implementasi Sprint B/F):

```json
{"metric_id": "garment.scrap_rate", "window": "1h", "value": 7.8,
 "baseline": 3.1, "threshold": 5.0, "severity": "HIGH",
 "detected_at": "2026-10-18T05:30:00+07:00"}
```

| Aturan | Nilai |
|---|---|
| Baseline | rata-rata 7 hari terakhir pada granularity sama |
| Ambang statistik | `value > baseline + 3σ` (σ minimal 0.5 poin persen) |
| Ambang absolut | `scrap_rate > 5%`, `rework_rate > 3%`, `lead_time p90 > 2× baseline` |
| Cooldown | 1 alert per metrik per 30 menit |
| Kanal | event bus `analytics.alert` → WS + (opsional) WA (lihat `integration-config.md` §1.5) |

#### 8.6.1 `rework_spike`

| Aturan | Nilai |
|---|---|
| Trigger | `value > max(baseline_7d + 3σ, 3.0%)` |
| Baseline | rata-rata harian 7 hari terakhir (tidak termasuk hari ini) |
| σ minimal | `0.5` poin persen |
| Data minimum | baseline < 3 hari → tidak ada alert |
| Severity | `HIGH` bila melewati ambang absolut `3%`, selain itu `MEDIUM` |
| Kanal | WA **best-effort** (`ANALYTICS_ALERT_WA_TO` → `RECONCILIATION_ALERT_WA_TO`); error ditelan |
| Implementasi | `plugins/garment/streams/rework_spike.py` + listener `SCRAP_RECORDED` |
| Biaya | 0 token LLM (deterministik) |

---

## 9. Event-driven (bukan polling)

`integrations/analytics/apps.py` mendaftarkan listener lewat
`core.event_bus.registry.register_listener(...)` (pola sama dengan
`integrations/erp_sync/apps.py`). Event yang dikonsumsi:

| Event | Sumber | Dipakai untuk |
|---|---|---|
| `BUNDLE_STATE_CHANGED` | garment action executor | invalidasi cache metrik bundle |
| `SCRAP_RECORDED` | scrap accumulator service | numerator scrap/rework |
| `SYNC_RECORD_CHANGED` | erp_sync | readiness `sync_records_failed_recent_7d` |
| `analytics.config_changed` | service toggle | invalidasi cache + reset filter runtime |

Aturan:

- Listener **tidak** menulis ke tabel bisnis; hanya `MetricSnapshot` (append-only).
- Listener harus **idempoten** (event bisa di-retry oleh Celery).
- Kegagalan listener tidak boleh menggagalkan aksi operator (ditelan + log ERROR).
- Tidak ada `while True: sleep()` / polling; Celery beat hanya untuk **snapshot
  periodik** (agregasi per jam), bukan membaca mentah.

---

## 10. Keputusan Terkunci

1. Modul `integrations/analytics/` **di dalam** repo Django — bukan microservice.
2. Shape response = H4 + `enabled`, `disabled_reason`, `historical_data_available`.
3. OFF → **HTTP 200**, `rows: []`, `disabled_reason: "analytics_disabled"`,
   **tidak pernah 503**.
4. `enabled` master switch; `enabled_domains`/`enabled_metrics` hanya dievaluasi
   saat `enabled = true`; daftar kosong = semua aktif.
5. `enabled_metrics` menang atas `enabled_domains`.
6. Cache **60 dtk** + `?_nocache=1` (baca & tulis dilewati).
7. `historical_data_available` = `MetricSnapshot.objects.exists()`; **disable
   tidak menghapus snapshot**.
8. Sumber metrik = `BundleEvent`, `ScrapAccumulator`, `SyncRecord`, `WorkOrder`,
   `OrderLine` — bukan model mentah perangkat.
9. `MetricSnapshot` **append-only** (tidak ada UPDATE/DELETE dari aplikasi).
10. AI/MCP membaca analytics lewat **service layer**, bukan HTTP/DB langsung
    (lihat `../ai/MCP-REGISTRY.md`).
11. Tiga metrik pertama & formulanya terkunci di §8; ubah formula = naikkan
    `formula_version`.
12. **5 metrik aktif** (2026-10-21, Fase Ringan): `scrap_rate`, `rework_rate`,
    `lead_time`, `line_balance`, `bottleneck`. `cost_variance` dideferred ke
    Fase Berat.

---

## 11. Backlog (di luar Sprint A/B)

| Item | Fase | Catatan |
|---|---|---|
| Endpoint baca **snapshot historis** setelah disable | C/D | `GET /api/v1/analytics/snapshots/` (read-only, guard ketat) |
| Metrik tambahan: `wip_age`, `throughput_per_line`, `cycle_time_per_wc`, `otd` | C+ | butuh definisi produk |
| Aggregasi lintas klien (benchmark) | G+ | **jangan** tanpa anonimisasi |
| Streaming hasil analitik (SSE/WS push) | E/F | alert sudah via event bus; push query belum |
| Export Excel analytics | C | pola `integrations/erp_sync/export.py` |
| Cache berbasis `MetricSnapshot` (bukan query ulang) | B.6 | optimasi; kontrak response tidak berubah |
| Rate limit per-klien metrik berat | F | terkait observability |



