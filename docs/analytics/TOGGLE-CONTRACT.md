# 🎚️ Kontrak Toggle Analytics — MES Garmen

> **Status:** ✅ FINAL (Sprint A) · **Berlaku sejak:** 2026-10-18 · **Versi:** 1.0
> **Fase:** A (kontrak) — implementasi di **Sprint B** (`integrations/analytics/`).
> **Baca juga:** [`CONTRACT.md`](./CONTRACT.md) §7, [`../ai/MCP-REGISTRY.md`](../ai/MCP-REGISTRY.md) §3.

---

## 1. Prinsip

Analytics adalah **fitur level-pertama** dengan **DEFAULT OFF** untuk setiap
klien baru. Menyalakan analytics adalah keputusan sadar admin/owner karena
metrik hanya bermakna jika data dasar sehat (produk punya `odoo_id`, bundle
punya event, scrap punya accumulator, sync tidak gagal).

| Prinsip | Konsekuensi |
|---|---|
| Default OFF | Klien baru tidak melihat analytics sampai enable eksplisit |
| Enable = butuh **readiness pass** | Setiap kali enable, bukan hanya pertama kali |
| Disable = **selalu boleh** | Tetapi **wajib alasan** |
| Disable ≠ hapus data | `MetricSnapshot` tetap ada (append-only) |
| Toggle = master switch | `enabled_domains`/`enabled_metrics` hanya berlaku saat `enabled=true` |
| Evaluasi via **service layer** | MCP/AI memanggil `analytics_config_services.get_config()`, bukan DB/HTTP |

---

## 2. Model `AnalyticsConfig` (singleton)

Tabel `analytics_analyticsconfig` — **satu baris** (pk=1). Dibuat lazy oleh
service layer dengan nilai default (OFF) bila belum ada.

| Field | Tipe | Default | Catatan |
|---|---|---|---|
| `enabled` | `BooleanField` | `False` | Master switch |
| `enabled_domains` | `JSONField(list[str])` | `[]` | Kosong = semua domain aktif (saat `enabled=true`) |
| `enabled_metrics` | `JSONField(list[str])` | `[]` | Kosong = semua metrik aktif; **menang** atas domains |
| `data_readiness_acknowledged_at` | `DateTimeField(null)` | `None` | Jejak **historis** enable berhasil (bukan izin permanen) |
| `enabled_by` | `FK(User, null, SET_NULL)` | `None` | User yang terakhir enable |
| `enabled_at` | `DateTimeField(null)` | `None` | Waktu enable terakhir |
| `disabled_reason` | `TextField(null)` | `"not_yet_enabled"` | **Kode enum** alasan OFF (lihat §2.2). Alasan manual admin disimpan di AuditLog, bukan di sini |
| `updated_at` | `DateTimeField(auto_now)` | — | Jejak perubahan config |

### 2.1 Aturan model

- **Singleton**: `save()` memaksa `pk=1` (atau `get_or_create(pk=1)`), tidak ada
  baris kedua.
- `enabled_domains`/`enabled_metrics` **harus list of string**; nilai non-list
  ditolak 400 (bukan disimpan sebagai string).
- Saat `enabled=True` → `disabled_reason` diisi `None`.
- Saat `enabled=False` → `disabled_reason` **wajib** (validasi service + DB
  check constraint bila memungkinkan).
- Tidak ada field `readiness` yang disimpan — readiness selalu dihitung ulang.

### 2.2 Nilai `disabled_reason` (enum)

`disabled_reason` menyimpan **kode** (English snake_case); teks bebas dari admin
disimpan di AuditLog `analytics.disable` (`metadata.reason`). Frontend
menerjemahkan kode ke Bahasa Indonesia.

| Nilai | Arti |
|---|---|
| `"not_yet_enabled"` | Belum pernah enable (default klien baru) |
| `"analytics_disabled"` | Pernah enable, lalu **disable manual** oleh admin |
| `"readiness_failed"` | OFF dan percobaan enable terakhir **ditolak readiness** (jejak historis) |
| `"auto_disabled"` | OFF karena mekanisme otomatis (anomali) — fase F |

Aturan:

- Respons endpoint analytics (§CONTRACT 2.2) selalu memakai
  `"analytics_disabled"` saat `enabled=false`, apa pun nilai kolomnya —
  kolom ini untuk **settings/audit**, bukan untuk payload metrik.
- Enable sukses → `disabled_reason = None`.
- `auto_disabled` belum diimplementasi; nilainya dicadangkan (fase F).

---

## 3. Endpoint

Base: `/api/v1/settings/analytics/`

| Method | Path | Guard | Fungsi |
|---|---|---|---|
| `GET` | `/api/v1/settings/analytics/` | `ADMIN/OWNER` | Baca konfigurasi (readiness terpisah di §3.5) |
| `PUT` | `/api/v1/settings/analytics/` | `ADMIN/OWNER` | Ubah `enabled_domains`/`enabled_metrics` (bukan `enabled`) |
| `POST` | `/api/v1/settings/analytics/enable/` | `ADMIN/OWNER` | Enable dengan readiness pass |
| `POST` | `/api/v1/settings/analytics/disable/` | `ADMIN/OWNER` | Disable + alasan wajib |
| `GET` | `/api/v1/analytics/readiness/` | `ADMIN/OWNER` | Cek readiness tanpa mengubah apa pun |

> `PUT` **tidak** boleh mengubah `enabled` (harus lewat `enable/`/`disable/`)
> supaya readiness & audit tidak bisa dilewati.

### 3.1 `GET /api/v1/settings/analytics/`

```json
{
  "enabled": false,
  "enabled_domains": [],
  "enabled_metrics": [],
  "data_readiness_acknowledged_at": null,
  "enabled_by": null,
  "enabled_at": null,
  "disabled_reason": "not_yet_enabled",
  "historical_data_available": false,
  "updated_at": "2026-10-18T05:00:00+07:00"
}
```

### 3.2 `PUT /api/v1/settings/analytics/`

Body:

```json
{"enabled_domains": ["garment"], "enabled_metrics": []}
```

| Kondisi | HTTP | Body |
|---|---|---|
| Sukses | 200 | config terbaru (shape §3.1) |
| `enabled` dikirim | 400 | `{"detail": "enabled hanya lewat endpoint enable/disable"}` |
| Bukan list / item bukan string | 400 | `{"detail": "enabled_domains harus list string"}` |
| Role bukan ADMIN/OWNER | 403 | `{"detail": "..."}` |

Efek samping: invalidasi cache prefix `analytics:` + AuditLog
`analytics.config_update` (metadata: before/after).

### 3.3 `POST /api/v1/settings/analytics/enable/`

Body opsional:

```json
{"enabled_domains": ["garment"], "enabled_metrics": []}
```

Alur (kunci):

1. `select_for_update()` pada baris config (cegah enable paralel).
2. Hitung readiness **sekarang** (`GET /api/v1/analytics/readiness/` logika).
3. Jika `ready == false` → **400**:

   ```json
   {"detail": "Kesiapan data belum terpenuhi", "blockers": ["..."],
    "checked_at": "2026-10-18T05:10:00+07:00"}
   ```

   AuditLog `analytics.enable_blocked` (metadata: blockers).
4. Jika `ready == true` → tulis `enabled=True`, `enabled_by`, `enabled_at`,
   `data_readiness_acknowledged_at = enabled_at`, `disabled_reason=None`,
   simpan domains/metrics, invalidasi cache, AuditLog
   `analytics.enable_success`. **`soft_blockers` TIDAK memblokir enable.**
5. Respons 200 shape §3.1 + `readiness` + `warnings` (dari `soft_blockers`):

   ```json
   {"enabled": true, "warnings": [
     {"code": "no_active_bundles", "message": "Tidak ada bundle aktif; analytics akan kosong sampai ada produksi."}
   ]}
   ```

**Readiness dicek ULANG setiap enable** — `data_readiness_acknowledged_at`
hanya jejak historis, **bukan** izin permanen.

### 3.4 `POST /api/v1/settings/analytics/disable/`

Body:

```json
{"reason": "Data master belum lengkap — menunggu perbaikan produk"}
```

| Kondisi | HTTP | Body |
|---|---|---|
| Sukses | 200 | shape §3.1 (`enabled:false`, `historical_data_available` tetap) |
| `reason` kosong/whitespace | **400** | `{"detail": "Alasan disable wajib diisi"}` |
| Sudah OFF | 200 | idempoten; `disabled_reason` diperbarui |

Efek samping: `enabled=False`, `disabled_reason="analytics_disabled"`
(alasan teks admin → AuditLog `metadata.reason`), AuditLog `analytics.disable`;
**tidak** menyentuh `MetricSnapshot`.

### 3.5 `GET /api/v1/analytics/readiness/`

```json
{
  "ready": true,
  "blockers": [],
  "soft_blockers": [],
  "checked_at": "2026-10-18T05:10:00+07:00",
  "thresholds": {
    "products_without_odoo_id_in_active_bundles": 0,
    "bundles_without_events_older_than_24h": 0,
    "scrap_without_accumulator_older_than_24h": 0,
    "sync_records_failed_recent_7d": 0
  },
  "counts": {
    "products_without_odoo_id_total": 12,
    "products_without_odoo_id_in_active_bundles": 0,
    "active_bundles": 47,
    "bundles_without_events_older_than_24h": 0,
    "scrap_without_accumulator_older_than_24h": 0,
    "sync_records_failed_recent_7d": 0
  }
}
```

---

## 4. Aturan readiness (kunci)

`ready = true` **jika dan hanya jika** `blockers == []` (**hard**).
`soft_blockers` **tidak** memblokir enable, tetapi wajib ditampilkan sebagai
warning di UI dan dikembalikan pada respons enable.

| # | Threshold | Tipe | Blocker bila | Definisi |
|---|---|---|---|---|
| 1 | `products_without_odoo_id_in_active_bundles` | Hard | `> 0` | Produk tanpa `odoo_id` yang dipakai `OrderLine` pada bundle **aktif** (state belum `DONE`/`CANCELLED`) |
| 2 | `bundles_without_events_older_than_24h` | Hard | `> 0` | Bundle aktif tanpa `BundleEvent` sama sekali, dibuat > 24 jam lalu |
| 3 | `scrap_without_accumulator_older_than_24h` | Hard | `> 0` | `BundleEvent` bertipe `SCRAP`/`REWORK` > 24 jam yang tidak punya baris `ScrapAccumulator` terkait |
| 4 | `sync_records_failed_recent_7d` | Hard | `> 0` | `SyncRecord.status = FAILED` dalam 7 hari terakhir |
| 5 | `no_active_bundles` | **Soft** | `counts.active_bundles == 0` | Belum ada bundle aktif (klien baru / produksi belum jalan) |

Aturan tambahan:

1. **Hanya produk yang dipakai bundle aktif** yang dihitung sebagai blocker.
   Produk historis tanpa `odoo_id` dicatat di
   `counts.products_without_odoo_id_total` **tetapi tidak memblokir**.
2. `blockers` berformat `<code>:<count>` (mis. `"produk_tanpa_odoo_id_di_bundle_aktif:3"`),
   sedangkan **`soft_blockers` berformat `<code>` saja** (tanpa count; angkanya
   ada di `counts`), mis. `"no_active_bundles"`. UI menerjemahkan kode.
3. Readiness **tidak** memakai cache (harus segar) dan tidak menulis apa pun.
4. Readiness **tidak** menyentuh Odoo live; semua dari DB MES.
5. **Klien baru tanpa bundle aktif** → `ready` tetap `true` bila hard blocker
   kosong, tetapi `soft_blockers=["no_active_bundles"]` (count di
   `counts.active_bundles: 0`) dan UI **wajib** menampilkan warning:
   *"Tidak ada bundle aktif; analytics akan kosong sampai ada produksi."*
   Admin **boleh** enable (keputusan Q3).
6. Soft blockers **tidak** mengubah `ready`; frontend wajib merender
   `blockers` **dan** `soft_blockers`.

---

## 5. Semantik evaluasi toggle (service layer)

`integrations/analytics/services/analytics_config_services.py` menyediakan
**satu pintu**:

```python
get_config() -> AnalyticsConfigDTO
is_metric_enabled(metric_id: str) -> bool
analytics_enabled() -> bool
```

Aturan evaluasi (dipakai endpoint analytics, MCP, AI, dan UI):

| `enabled` | `enabled_domains` | `enabled_metrics` | `is_metric_enabled("garment.scrap_rate")` |
|---|---|---|---|
| `false` | — | — | `False` (tidak mengevaluasi list) |
| `true` | `[]` | `[]` | `True` (permissive) |
| `true` | `["garment"]` | `[]` | `True` |
| `true` | `["finance"]` | `[]` | `False` |
| `true` | `[]` | `["garment.rework_rate"]` | `False` |
| `true` | `["finance"]` | `["garment.scrap_rate"]` | `True` (metrics menang) |

Catatan:

- Evaluasi **domain** memakai prefix `metric_id.split(".")[0]`.
- Daftar yang berisi nilai tak dikenal **tidak** mematikan semua; hanya
  memfilter (tidak ada efek samping).
- `get_config()` **selalu** mengembalikan objek (default OFF bila belum ada
  baris), **tidak** pernah `None`.

---

## 6. Jalur enforcement (keputusan #11)

| Pemanggil | Cara cek toggle | Dilarang |
|---|---|---|
| Endpoint analytics | `analytics_config_services.get_config()` | query `AnalyticsConfig.objects` langsung |
| `mcp-analytics` | `analytics_config_services.get_config()` | HTTP ke `/api/v1/...`, query DB |
| AI decision gate | `analytics_config_services.get_config()` | membaca cache sendiri |
| Frontend | response `enabled` dari endpoint | memanggil endpoint settings (role admin) |

Tujuan: satu sumber kebenaran + mudah di-mock di test + tidak ada duplikasi
logika filter.

---

## 7. Audit, cache, dan konkurensi

| Aspek | Aturan |
|---|---|
| Audit enable sukses | `analytics.enable_success` — metadata `{enabled_domains, enabled_metrics}` |
| Audit enable gagal | `analytics.enable_blocked` — metadata `{blockers, checked_at}` |
| Audit disable | `analytics.disable` — metadata `{reason}` |
| Audit update filter | `analytics.config_update` — metadata `{before, after}` |
| Cache | prefix `analytics:` dihapus setiap config berubah |
| Konkurensi | `select_for_update()` pada baris singleton saat enable/disable |
| Idempoten | disable saat OFF → 200; enable saat ON → readiness tetap dicek ulang |

---

## 8. Keputusan Terkunci

1. Toggle = fitur level-pertama, **DEFAULT OFF** untuk klien baru.
2. `enabled` = master switch; `enabled_domains`/`enabled_metrics` hanya
   dievaluasi saat `enabled=true`; kosong = semua aktif.
3. `enabled_metrics` menang atas `enabled_domains`.
4. **Enable wajib readiness pass SETIAP KALI**; `data_readiness_acknowledged_at`
   hanya jejak historis.
5. **Disable selalu boleh, wajib alasan**, dan **tidak menghapus** `MetricSnapshot`.
6. `ready = true` ⇔ `blockers == []`; hanya produk pada bundle aktif yang
   memblokir; produk historis hanya masuk `counts`.
6b. `soft_blockers` (mis. `no_active_bundles`) **tidak** memblokir enable;
    UI wajib menampilkan sebagai warning.
6c. `disabled_reason` memakai **kode enum** (`not_yet_enabled`,
    `analytics_disabled`, `readiness_failed`, `auto_disabled`); alasan teks
    admin disimpan di AuditLog.
7. OFF → endpoint analytics **200** dengan `disabled_reason="analytics_disabled"`.
8. `enabled` hanya bisa diubah lewat `enable/`/`disable/` (PUT tidak boleh).
9. Evaluasi toggle lewat **service layer** (`get_config()`), bukan DB/HTTP langsung.
10. Semua aksi toggle masuk AuditLog; cache `analytics:` diinvalidasi.

---

## 9. Backlog

| Item | Fase | Catatan |
|---|---|---|
| Endpoint baca snapshot historis saat OFF | C/D | butuh guard tambahan + pagination |
| Readiness terjadwal (Celery beat) + notifikasi WA | F | saat ini hanya on-demand |
| Override readiness per-klien (allowlist) | F+ | **hanya** dengan persetujuan owner + audit |
| Riwayat toggle (tabel `AnalyticsConfigLog`) | F | sekarang hanya AuditLog generik |
| UI wizard enable (3 langkah: readiness → pilih domain → konfirmasi) | C | endpoint sudah cukup |
| Per-domain readiness (mis. finance siap, garment belum) | C+ | kontrak sekarang global |


