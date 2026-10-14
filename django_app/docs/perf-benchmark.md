# Performance Benchmark — Pre-Pilot (F5.2)

Laporan pengukuran endpoint agregat **sebelum pilot klien**: mana yang punya N+1,
apa yang dioptimasi, dan berapa angka sebelum/sesudahnya. Semua angka di dokumen ini
**hasil pengukuran**, bukan estimasi (kecuali yang ditandai eksplisit).

Ringkasan:

| Endpoint | Query (sebelum) | Query (sesudah) | N=1.000 | N=10.000 | Status |
|---|---|---|---|---|---|
| `/dashboard/summary/` | 45 | **14** | 68 ms | 552 ms | ✅ query konstan (waktu → §8 poin 3) |
| `/production/buffer-queue/` | 242 | **5** | 47 ms | 460 ms | ✅ query konstan (waktu → §8 poin 3) |
| `/reports/wip/` | 23 | **3** | 14 ms | 107 ms | ✅ |
| `/reports/line-efficiency/` | 27 | **5** | 51 ms | 386 ms | ✅ |
| `/inventory/products/` | 33 | **5** | 9 ms | 18 ms | ✅ |

- **0 migration**, **0 perubahan bentuk response** (kontrak F1/F3-A tetap), 19 test gagal
  = baseline pre-existing (lihat §7), bukan regresi.
- Gate F5.2: **N=1.000 → semua endpoint < 500 ms** ✅ (terlama 68 ms).

---

## 1. Environment

| Item | Nilai |
|---|---|
| Database | PostgreSQL 15 (container `garmen_postgres`), **dev, tanpa tuning** (`shared_buffers` default) |
| Aplikasi | Django **5.0.9** + DRF **3.15.2**, Python 3.11, psycopg 3.2.3 |
| Runtime | container `garmen_django` (`docker compose exec django ...`), TZ `Asia/Jakarta` |
| Host | mesin dev (bukan VPS produksi) — lihat catatan di §8 |
| Harness | `django.test.utils.CaptureQueriesContext` (jumlah query) + klien in-process `rest_framework.test.APIClient` (median 5 run) |

**Data uji** (dibuat `manage.py seed_benchmark_data`, prefix `BENCH-`):

| Skala | Bundle total | BundleEvent total | Work center | Order/WO/Produk |
|---|---|---|---|---|
| N=100 | 128 (100 bench + 28 dev) | 1.002 | 7 (6 bench + 1 dev) | 1 order, 4 WO, 1 produk |
| N=1.000 | 1.028 | 5.727 | 7 | 1 order, 40 WO, 1 produk |
| N=10.000 | 10.028 | 52.977 | 7 | 1 order, 400 WO, 1 produk |

Rasio event ≈ **5 event/bundle** (1 `BUNDLE_START` + 3 `BUNDLE_TRANSFER` + 1 `BUNDLE_FINISH`
per 4 bundle), `ts` disebar 7 hari supaya trend/series benar-benar terisi.

---

## 2. Metodologi

1. **Setup data uji** — `python manage.py seed_benchmark_data --bundles N --reset`
   (idempoten; `--reset` menghapus dulu). Command memakai `bulk_create` +
   `QuerySet.update()` (karena `BundleEvent.ts` = `auto_now_add`, `Bundle.updated_at`
   = `auto_now`) sehingga 10 rb bundle + 53 rb event selesai **± 11 detik**.
2. **Ukur per endpoint**: 5 run, ambil **median**; jumlah query dihitung pada run pertama
   dengan `CaptureQueriesContext`. Semua request memakai user terautentikasi
   (`force_authenticate`) sehingga tidak ada query sesi.
3. **Uji batas** (pencegah regresi) ada di `tests/integration/test_perf_queries.py`.
4. **Pembanding "sebelum"**:
   * angka query lama diukur dengan kode lama lewat test budget (data kecil: 10 bundle,
     3 WC) — langsung dari `assertNumQueries` yang gagal;
   * untuk skala N=1.000 dipakai **rekonstruksi pola loop lama** memakai API publik yang
     sama (`TwoStageAggregator.build_payload()` + `WCQueue.get_queue()` +
     `_line_efficiency_durations()`), karena helper lama sudah dihapus — lihat §5.

Catatan kejujuran: angka **ms** diukur **in-process** (tanpa latensi jaringan & tanpa
Nginx/TLS), jadi produksi akan sedikit lebih lambat; jumlah **query** tidak terpengaruh.

---

## 3. Hasil per endpoint (SESUDAH optimasi)

| Endpoint | N=100 | N=1.000 | N=10.000 | Query count | Status |
|---|---|---|---|---|---|
| `/dashboard/summary/` | 31,6 ms | 68,3 ms | 552,5 ms | **14** | ✅ query konstan |
| `/production/buffer-queue/` | 14,1 ms | 46,7 ms | 460,3 ms | **5** | ✅ query konstan |
| `/reports/wip/` | 6,9 ms | 14,3 ms | 107,2 ms | **3** | ✅ |
| `/reports/line-efficiency/` | 32,2 ms | 51,3 ms | 385,8 ms | **5** | ✅ |
| `/inventory/products/` | 7,9 ms | 9,0 ms | 17,8 ms | **5** | ✅ |

Yang penting: **jumlah query tidak naik** dari N=100 → N=10.000 (14/5/3/5/5). Kalau
sebuah endpoint kembali punya N+1, angka ini akan ikut naik dan uji budget §6 langsung
gagal — itulah yang membuat regresi ketahuan tanpa menunggu server lambat.

Catatan pembacaan: pada N=10.000 dashboard (552 ms) & buffer-queue (460 ms) sudah melewati
500 ms **bukan** karena jumlah query (konstan), tetapi karena volume baris yang diproses
Python + `BundleEvent` 53 rb — analisis & rencananya di §8 poin 3 dan §9.

## 4. Endpoint yang perlu optimasi (temuan SEBELUM)

Semua temuan ada di `integrations/erp_sync/monitoring.py` (nomor baris = posisi **sekarang**).

| # | Endpoint | Lokasi | Akar masalah (N+1) | Dampak terukur |
|---|---|---|---|---|
| 1 | `/dashboard/summary/` | `_wip_fg_qty()` (L326) + `_alerts()` (L360) | `TwoStageAggregator.build_payload()` dipanggil **per bundle**; tiap panggilan = 2 query (`routing` property → `ProcessRouting...first()` + `routing.steps.filter(work_center=…, is_terminal=True).exists()`). `_alerts()` memakai `BottleneckDetector.detect_all()` = 1 query queue **per WC** | **2.989 query** untuk 1.028 bundle (rekonstruksi N=1.000) |
| 2 | `/production/buffer-queue/` | `_buffer_queue_rows()` (L636) | `WCQueue.get_queue()` **per WC** + `_prev_wc_code()`/`_next_wc_code()` **per bundle** (masing-masing 2-3 query `routing.steps.filter`) | **242 query** @ 10 bundle = 24 query/bundle |
| 3 | `/inventory/products/` | `_stock_by_product()` (L1403) | pola `build_payload()` per bundle (idem #1) + menarik **semua** baris ke Python | **33 query** @ 10 bundle; 10.000 bundle → **933 ms** |
| 4 | `/reports/line-efficiency/` | `_efficiency_trend_for()` (dihapus) dipanggil per WC | tiap WC × 7 hari × `_line_efficiency_durations()` (2 query) → 14 query/WC | **27 query** @ 3 WC |
| 5 | `/reports/wip/` | `_wip_trend_for()` (dihapus) dipanggil per WC | 7 query agregat **per WC** | **23 query** @ 3 WC |

### Bukti sebelum → sesudah (jumlah query)

| Endpoint | Sebelum (kode lama, N=10 bundle) | Sesudah (N=10) | Sesudah (N=1.000) | Sesudah (N=10.000) |
|---|---|---|---|---|
| `/dashboard/summary/` | 45 | 14 | 14 | 14 |
| `/production/buffer-queue/` | 242 | 5 | 5 | 5 |
| `/inventory/products/` | 33 | 5 | 5 | 5 |
| `/reports/line-efficiency/` | 27 | 5 | 5 | 5 |
| `/reports/wip/` | 23 | 3 | 3 | 3 |

Kolom "Sebelum" = kode lama di data kecil (angka dari `assertNumQueries` yang gagal); kolom
selanjutnya = kode baru. Karena pola lama tumbuh per baris (24 query/bundle di buffer-queue),
angka "sebelum" pada N=1.000 **bukan 24× lipat dari 242** — dicek ulang lewat rekonstruksi:

> Rekonstruksi pola lama pada **N=1.000** (1.028 bundle): WIP/FG dashboard =
> **2.989 query / 3.135 ms**; kode baru = **14 query / 68 ms**
> (≈ **213× lebih sedikit query**, ≈ **46× lebih cepat**).

---

## 5. Optimasi yang diterapkan

Prinsip: **hanya query/loop** — tanpa migration, tanpa mengubah bentuk response
(diverifikasi ulang oleh 61 test endpoint di §8).

| Endpoint | Sebelum | Sesudah | Metode | Lokasi |
|---|---|---|---|---|
| `/dashboard/summary/` | 45 query (N=10) | **14 query, konstan** | (a) klasifikasi stage batch: set WC terminal via `_terminal_work_center_ids()` (1-2 query) lalu **1 query agregat** `Sum("qty", filter=~Q(...))` + `Sum("qty_done", filter=Q(...))`; (b) alert: 1 query `values("current_work_center__code").annotate(depth=Count("id"))` (depth identik `BottleneckDetector`, ambang tetap diambil dari detektor) | `_wip_fg_qty` L326, `_alerts` L360, helper L295/L310 |
| `/production/buffer-queue/` | 242 query (N=10) | **5 query, konstan** | 1 pass `Bundle…order_by("updated_at","id")` + group per WC di Python; `from_wc`/`to_wc` dari `_routing_wc_neighbors()` (1 fetch step + `prefetch_related`) menggantikan `_prev_wc_code`/`_next_wc_code` per bundle | `_routing_wc_neighbors` L563, `_buffer_queue_rows` L636 |
| `/inventory/products/` | 33 query (N=10) | **5 query, konstan** | `SUM` dikerjakan DB: `values("work_order__order_line__product_id").annotate(wip=…, fg=…)` (`.order_by()` dibersihkan agar `GROUP BY` benar). N=10.000: **933 ms → 18 ms (≈52×)** | `_stock_by_product` L1403 |
| `/reports/line-efficiency/` | 27 query (N=3 WC) | **5 query, konstan** | `_efficiency_trends_by_wc()`: 2 query (FINISH + START window 7 hari) lalu bucket per (WC, hari) — menggantikan 7×2 query per WC | L1728 |
| `/reports/wip/` | 23 query (N=3 WC) | **3 query, konstan** | `_wip_trends_by_wc()`: 1 query `values_list(wc, qty, updated_at)` + kumulatif per hari di Python — menggantikan 7 agregat per WC | L1857 |
| *(bersih-bersih)* | — | — | helper mati `_prev_wc_code()`/`_next_wc_code()` **dihapus** (tidak ada pemakai lain setelah map batch) | — |

Yang **sengaja tidak diubah** (bukan N+1 / di luar scope):
`_daily_trend()` (L441) & `_line_efficiency_durations()` (L1687) — masih dipakai
dashboard & endpoint by-wc (2 query per panggilan, tidak per baris);
`TwoStageAggregator.build_payload()` tetap utuh untuk jalur **tulis** (reconciliation & sync ERP).

---

## 6. Uji batas query (pencegah regresi)

File: **`tests/integration/test_perf_queries.py`** — 6 test (5 budget + 1 kontrol anonim 403),
data sengaja kecil (10 bundle / 3 WC) supaya angka query **tidak** ikut naik kalau data naik.

| Test | Budget | Aktual (sesudah) | Aktual (sebelum) |
|---|---|---|---|
| `/dashboard/summary/` | ≤ 30 | 14 | 45 ❌ |
| `/production/buffer-queue/` | ≤ 20 | 5 | 242 ❌ |
| `/reports/wip/` | ≤ 15 | 3 | 23 ❌ |
| `/reports/line-efficiency/` | ≤ 15 | 5 | 27 ❌ |
| `/inventory/products/` | ≤ 10 | 5 | 33 ❌ |

- Semantiknya **batas atas** (`assertLessEqual`), bukan angka eksak — tujuannya menangkap
  pertumbuhan query, bukan mengunci implementasi. Pesan gagal menyebut jumlah aktual +
  budget supaya penyebabnya cepat terlihat.
- Sebelum optimasi kelima test ini **gagal** (angka kolom terakhir) → membuktikan uji ini
  benar-benar menangkap N+1, bukan test kosong.

```bash
docker compose exec django python -m pytest tests/integration/test_perf_queries.py -q
# 6 passed
```

---

## 7. Status regresi & migration

| Cakupan | Hasil |
|---|---|
| Uji budget F5.2 (`test_perf_queries.py`) | **6 passed** |
| Endpoint terdampak: `test_dashboard_summary`, `test_buffer_queue`, `test_reports_wip`, `test_reports_line_efficiency`, `test_inventory_products`, `test_reports_wip_by_wc`, `test_reports_line_efficiency_by_wc` | **61 passed**, 0 failed |
| Suite `tests/` | 226 passed, **4 failed** |
| Suite `apps_industry/ core/ integrations/` | 964 passed, **15 failed** |
| **Total gagal** | **19** = baseline `django_app/docs/curent_project.json` → `project.test_pre_existing_failures: 19` |
| `makemigrations --check --dry-run` | `No changes detected` (**0 migration**) |

19 kegagalan itu semuanya di jalur Celery/ERP-sync/trace-bridge — mis. traceback
`integrations/erp_sync/tasks.py:45 → task.request.headers` bernilai `None` saat task dipanggil
tanpa konteks request (broker Celery nyata). Tidak ada yang menyentuh `monitoring.py`,
jadi **bukan regresi F5.2**. Sebarannya: `integrations/erp_sync/tests/test_tasks.py` (6),
`test_audit_sync_tasks.py` (3), `test_sync_endpoint.py` (3),
`tests/integration/test_failsafe_full_stack.py` (2), `test_audit_integration.py` (1),
`test_e2e_bundle_flow.py` (1), `test_invoice_listener.py` (1),
`tests/integration/test_task_idempotency.py` (1), `tests/integration/test_trace_bridge_e2e.py` (1).

---

## 8. Catatan & keterbatasan

1. **Angka ms diukur in-process** (tanpa Nginx/TLS/jaringan) → produksi akan lebih lambat;
   jumlah query tidak terpengaruh. Benchmark di VPS produksi perlu diulang (§9).
2. **DB dev tanpa tuning**; spec pilot (4 vCPU / 8 GB / 100 GB SSD — lihat
   `django_app/docs/onboarding-klien-baru.md`) belum diukur.
3. **N=10.000**: `/dashboard/summary/` 552 ms & `/production/buffer-queue/` 460 ms melewati
   500 ms — tetapi **jumlah query konstan** (14 & 5). Penyebabnya volume baris yang diproses
   (Python + `BundleEvent` 53 rb untuk trend/alert), bukan N+1. Perbaikannya
   (index/cache/materialized view) **butuh migration** ⇒ ditunda ke F6 sesuai larangan F5.2.
4. Angka "sebelum" pada N=1.000 hanya tersedia untuk pola **WIP/FG** (§4, rekonstruksi);
   empat endpoint lain diukur pada data kecil (N=10) karena helper lama sudah dihapus —
   rekonstruksi penuh buffer-queue memakan ± 59 detik (≈ 6 rb query) sehingga tidak diulang.
5. Data benchmark **sintetis** (1 produk, 1 order, 6 WC). Pada data nyata dengan banyak
   produk, `inventory/products` sedikit lebih berat (join lebih besar) tetapi **jumlah query
   tetap 5**; endpoint `purchase/*` tidak punya N+1 per baris sehingga tidak diubah.
6. `manage.py seed_benchmark_data` = **tool sementara** (prefix `BENCH-`), bukan fixture
   produksi. Setelah benchmark, data uji **sudah dihapus** dari DB dev
   (kembali 28 bundle / 477 event = kondisi semula).

---

## 9. Rekomendasi lanjutan (kandidat F6)

| # | Rekomendasi | Alasan / target |
|---|---|---|
| 1 | **Index** (butuh migration): `Bundle(current_work_center, state)`, `Bundle(updated_at)`, `BundleEvent(event_type, ts)` | 5 query agregat turun signifikan pada 10 rb+ baris; target N=10.000 < 500 ms |
| 2 | **Cache Redis TTL 60 s** untuk `/dashboard/summary/`, `/reports/wip/`, `/reports/line-efficiency/`, `/production/buffer-queue/` + invalidasi saat event `BUNDLE_STATE_CHANGED` | data monitoring toleran staleness; dashboard 552 ms → hitungan ms |
| 3 | **Ringkasan harian / materialized view** untuk trend (`_daily_trend` + trend per WC) | menghapus scan 53 rb `BundleEvent` tiap request |
| 4 | **Benchmark ulang di VPS produksi** + profil per-request (django-debug-toolbar / django-silk) | angka dev ≠ angka pilot |
| 5 | `EXPLAIN ANALYZE` pada 5 query agregat setelah index ditambah | memastikan index benar-benar dipakai |

---

## 10. Cara reproduksi

```bash
cd /path/ke/odoo-garmen-project          # container `django` + DB sudah jalan

# 1) data uji sintetis (idempoten; --reset = hapus dulu lalu seed)
docker compose exec django python manage.py seed_benchmark_data \
  --bundles 1000 --events-per-bundle 5 --reset

# 2) uji batas query (data kecil, cepat)
docker compose exec django python -m pytest tests/integration/test_perf_queries.py -q

# 3) ukur waktu + jumlah query pada skala data (median 5 run) — bentuk harness ada di §2;
#    skrip pengukur sementara dibuat di /app lalu dihapus (tidak dikomit)

# 4) bersihkan data uji (semua baris prefix BENCH-)
docker compose exec django python - <<'PY'
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from apps_industry.garment.management.commands.seed_benchmark_data import Command
Command()._purge()          # Bundle + BundleEvent + WorkOrder/Order/Product/Routing/WC BENCH-
PY
```

Dokumen terkait: `django_app/docs/curent_project.json` (status & baseline test),
`django_app/docs/known-limitations.md` (keterbatasan yang diterima),
`django_app/docs/onboarding-klien-baru.md` (spec VPS pilot),
`django_app/docs/uat-checklist.md` (target waktu respons yang diharapkan saat UAT).

