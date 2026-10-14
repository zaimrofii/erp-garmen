# Recon R0 — Realita Proyek sebelum Fase F1 (Read-only)

- **Tanggal:** 2026-10-09
- **Metode:** baca kode langsung (bukan dokumen). Tidak ada kode diubah.
- **Verifikasi:** `config/urls.py`, `apps_industry/garment/api/urls.py`, `*/api.py`, `*/views.py`,
  `models/*.py`, `master/models.py`, `frontend_app_v2/src/api/_adapter.ts`, `dummy/*`, `package.json`,
  `App.tsx` (v1 & v2), `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `.env`, `config/settings.py`.

> **Temuan dokumen:** file `docs/curent_project.json` (persis seperti di brief) **TIDAK ADA**. Yang ada:
> `django_app/docs/curent_project.json` (backend, ejaan "curent") dan
> `frontend_app_v2/docs/current-project.json` (frontend). Dokumen
> **"Dokumen Pengembangan Akhir"** dan **"Rencana Fase Final F1–F6"** juga **tidak ada di repo**
> (sudah di-scan lewat nama file & isi; hanya `frontend_app_v2/docs/blueprint.md` yang menyebut F1–F15).
> Karena itu daftar "23 endpoint" di bawah **direkonstruksi dari sumber otoritatif di repo**:
> `_adapter.ts` (28 key dummy) + komentar `@dummy - endpoint masa depan` di setiap `api/dummy/*.ts`.

---

## A. Endpoint — SUDAH ada vs BELUM

### A.1 Endpoint yang BELUM ada (placeholder dummy → target F1–F3) — **semua ❌**

Bukti absen: pola URL app garmen (`config/urls.py` + `apps_industry/garment/api/urls.py`) hanya punya
kontrak core `/metadata /chatter /devices /sync /finance /reconciliation /audit /print /wa /ai` +
pola industri `v1/<industry>/<resource>/...` dengan registry resource terbatas
(`work-orders`, `bundles`, `qc`, `order-lines`). **Tidak ada** router DRF (ViewSet/DefaultRouter) dan
**tidak ada** view untuk `dashboard/buffer/routing/reports/purchase/inventory/settings/hitl`
(grep menyeluruh: 0 match path, hanya kata "routing" di docstring modul `urls.py`).

| # | Key `MODE` | Endpoint target (persis) | Method | File lokasi | Auth target | Ada? |
|---|---|---|---|---|---|---|
| B1 | `dashboard` | `/api/v1/dashboard/summary` (sumber: `dummy/dashboard.ts`) | GET | rencana `apps_industry/garment/api/` (belum) | IsAuthenticated | ❌ |
| B2 | `bufferQueue` | `/api/v1/production/buffer-queue` (sumber: `dummy/bufferQueue.ts`) | GET | belum | IsAuthenticated | ❌ |
| B3 | `routing` | `/api/v1/routing/graph` (sumber: `dummy/routing.ts`) | GET | belum | IsAuthenticated | ❌ |
| B4 | `qcLog` | `/api/v1/quality/defects` (sumber: `dummy/qc.ts`) | GET | belum | IsAuthenticated | ❌ |
| B5 | `qcAql` | `/api/v1/quality/aql` (sumber: `dummy/qc.ts`) | GET | belum | IsAuthenticated | ❌ |
| B6 | `qcRework` | `/api/v1/quality/rework` (sumber: `dummy/qc.ts`) | GET | belum | IsAuthenticated | ❌ |
| B7 | `qcSubmit` | `/api/v1/quality/defects` (sumber: `dummy/qc.ts`) | POST | belum | IsAuthenticated | ❌ |
| B8 | `inventoryProducts` | `/api/v1/inventory/products` (sumber: `dummy/inventory.ts`) | GET | belum | IsAuthenticated | ❌ |
| B9 | `inventoryOperations` | `/api/v1/inventory/operations` (sumber: `dummy/inventory.ts`) | GET | belum | IsAuthenticated | ❌ |
| B10 | `inventoryReporting` | `/api/v1/inventory/reporting` (sumber: `dummy/inventory.ts`) | GET | belum | IsAuthenticated | ❌ |
| B11 | `purchaseOrders` | `/api/v1/purchase/orders` (sumber: `dummy/purchase.ts`) | GET | belum | IsAuthenticated | ❌ |
| B12 | `purchaseVendors` | `/api/v1/purchase/vendors` (sumber: `dummy/purchase.ts`) | GET | belum | IsAuthenticated | ❌ |
| B13 | `purchaseReporting` | `/api/v1/purchase/reporting` (sumber: `dummy/purchase.ts`) | GET | belum | IsAuthenticated | ❌ |
| B14 | `reportsLineEfficiency` | `/api/v1/reports/line-efficiency` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B15 | `reportsLeadTime` | `/api/v1/reports/lead-time` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B16 | `reportsOTD` | `/api/v1/reports/on-time-delivery` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B17 | `reportsWIP` | `/api/v1/reports/wip` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B18 | `reportsLineEfficiencyByWc` | `/api/v1/reports/line-efficiency/by-wc` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B19 | `reportsLeadTimeBundles` | `/api/v1/reports/lead-time/bundles` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B20 | `reportsOnTimeDeliveryOrders` | `/api/v1/reports/on-time-delivery/orders` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B21 | `reportsWipByWc` | `/api/v1/reports/wip/by-wc` (sumber: `dummy/reports.ts`) | GET | belum | IsAuthenticated | ❌ |
| B22 | `settingsRouting` | `/api/v1/settings/routing` (sumber: `dummy/settings.ts`) | GET | belum | IsAuthenticated | ❌ |
| B23 | `settingsRouting` | `/api/v1/settings/routing` (sumber: `dummy/settings.ts`) | POST | belum | IsAuthenticated | ❌ |
| B24 | `settingsBundling` | `/api/v1/settings/bundling` (sumber: `dummy/settings.ts`) | GET | belum | IsAuthenticated | ❌ |
| B25 | `settingsLineAllocation` | `/api/v1/settings/line-allocation` (sumber: `dummy/settings.ts`) | GET | belum | IsAuthenticated | ❌ |
| B26 | `settingsUsers` | `/api/v1/settings/users` (sumber: `dummy/settings.ts`) | GET | belum | IsAuthenticated | ❌ |
| B27 | `settingsUsers` | `/api/v1/settings/users` (sumber: `dummy/settings.ts`) | POST | belum | IsAuthenticated | ❌ |
| B28 | `settingsRoles` | `/api/v1/settings/roles` (sumber: `dummy/roles.ts`) | GET | belum | IsAuthenticated | ❌ |
| B29 | `settingsDevices` | `/api/v1/settings/devices` (sumber: `dummy/settings.ts`) | GET | belum | IsAuthenticated | ❌ |
| B30 | `hitl` | `/api/v1/hitl/approvals` (sumber: `dummy/hitl.ts`) | GET | belum | IsAuthenticated | ❌ |
| B31 | `hitl` | `/api/v1/hitl/approvals/{id}/decide` (sumber: `dummy/hitl.ts`) | POST | belum | IsAuthenticated | ❌ |

**8 endpoint F1 prioritas (inferensi dari modul/urutan dummy):** B1, B2, B3, B4, B5, B6, B8, B17.

> Hitungan: **28 resource dummy → 27 GET + 4 POST = 31 endpoint.** Brief menyebut "23 endpoint".
> Selisih ini adalah **inkonsistensi dokumen vs repo** (lihat §D/risiko). Bila "23" = 27 GET dikurangi
> 4 endpoint *detail* Reports (B18–B21, yang di komentar adapter disebut "Fase 21 — ADITIF"),
> maka 23 = modul inti. Konfirmasi dengan penulis dokumen Fase Final diperlukan.

### A.2 Endpoint yang SUDAH ada (dipakai adapter `'real'`) — ✅ dengan file + line + class

| Endpoint (path persis) | Method | File : line | View class | Auth |
|---|---|---|---|---|
| `/api/health/` | GET | `config/urls.py:60` | `health` | AllowAny (no-throttle) |
| `/api/v1/metadata/<resource>` [+`/`] | GET | `config/urls.py:64-69` | `MetadataView` | AllowAny |
| `/api/v1/chatter/<resource>/<id>` [+`/`] | GET | `config/urls.py:73-82` | `ChatterView` | AllowAny |
| `/api/v1/devices/me` | GET | `config/urls.py:97` | `DeviceMeView` (`core/device_profile/api.py`) | AllowAny |
| `/api/v1/devices/bind` [+`/`] | POST | `config/urls.py:100-101` | `DeviceBindView` | IsAuthenticated |
| `/api/v1/devices/unbind` [+`/`] | POST | `config/urls.py:102-107` | `DeviceUnbindView` | IsAuthenticated |
| `/api/v1/sync/odoo/<stage>/` | POST | `config/urls.py:109-113` | `SyncOdooView` (`integrations/erp_sync/api.py`) | IsAuthenticated |
| `/api/v1/sync/master/<entity>/` | POST | `config/urls.py:115-119` | `SyncMasterView` | IsAuthenticated |
| `/api/v1/sync/scrap/` | POST | `config/urls.py:121-125` | `SyncScrapView` | IsAuthenticated |
| `/api/v1/sync/records/` | GET | `config/urls.py:130-134` | `SyncRecordListView` (`integrations/erp_sync/monitoring.py:88`) | IsAuthenticated |
| `/api/v1/finance/invoices/` | GET | `config/urls.py:135-139` | `InvoiceListView` (`monitoring.py:134`) | IsAuthenticated |
| `/api/v1/reconciliation/report/` | GET | `config/urls.py:144-148` | `ReconciliationReportView` | IsAuthenticated |
| `/api/v1/audit/products-missing-odoo-id/` | GET | `config/urls.py:151-155` | `ProductAuditView` | IsAuthenticated |
| `/api/v1/garmen/orders/<id>/readiness/` | GET | `config/urls.py:160-164` | `OrderReadinessView` | IsAuthenticated |
| `/api/v1/garmen/orders/<id>/recompute-readiness/` | POST | `config/urls.py:165-169` | `OrderReadinessView` | IsAuthenticated |
| `/api/v1/print/bundle-tag` [+`/`] | POST | `config/urls.py:172-181` | `PrintBundleTagView` | IsAuthenticated |
| `/api/v1/print/kupon` [+`/`] | POST | `config/urls.py:182-183` | `PrintCouponView` | IsAuthenticated |
| `/api/v1/wa/send` [+`/`] | POST | `config/urls.py:185-186` | `WASendView` | IsAuthenticated |
| `/api/v1/ai/chat` [+`/`] + `/api/ai/chat` | POST | `config/urls.py:190-192` | `AiChatView` (stub `{ok:false}`) | IsAuthenticated |
| `/api/v1/<industry>/work-orders/` | POST | `garment/api/urls.py:48-52` | `WorkOrderCreateView` | IsAuthenticated |
| `/api/v1/<industry>/bundles/` | POST | `garment/api/urls.py:53-57` | `BundleCreateView` | IsAuthenticated |
| `/api/v1/<industry>/<resource>/<id>/schema/` | GET | `garment/api/urls.py:58-62` | `SchemaView` | AllowAny |
| `/api/v1/<industry>/<resource>/<id>/<action>/` | POST | `garment/api/urls.py:63-67` | `ActionView` | **IsAuthenticated** (Fase 4.1) |
| `/api/v1/<industry>/<resource>/` (registry: `work-orders`,`bundles`,`qc`,`order-lines`) | GET | `garment/api/urls.py:68-72` | `ResourceListView` | AllowAny |
| `/api/v1/<industry>/<resource>/<id>/` | GET | `garment/api/urls.py:73-77` | `ResourceDetailView` | AllowAny |

Catatan: **tidak ada router DRF (ViewSet/DefaultRouter)** sama sekali — semua URL eksplisit
(`path`/`re_path`), jadi grep urls.py cukup untuk konfirmasi absen.

---

## B. Ringkasan Frontend — status dummy → real

1. **Path `MODE` benar:** satu-satunya file adalah `frontend_app_v2/src/api/_adapter.ts`
   (48 baris). **Tidak ada** `frontend_app/src/api/_adapter.ts` (v1 metadata-driven, tanpa adapter) → **tidak ada duplikasi**.
2. **Total key `MODE`: 46.** **18 `'real'`** dan **28 `'dummy'`** (selaras dgn `stats.adapters_real=18, adapters_dummy=28` di `frontend_app_v2/docs/current-project.json`).
3. **18 key `'real'`:** `bundles, workOrders, orderLines, qcRows, syncOdoo, syncMaster, syncScrap, readiness, reconciliation, audit, invoiceQueue, syncMonitor, chatter, metadata, devices, aiChat, print, wa`.
4. **28 key `'dummy'`:** `dashboard, bufferQueue, routing, qcLog, qcAql, qcRework, qcSubmit, inventoryProducts, inventoryOperations, inventoryReporting, purchaseOrders, purchaseVendors, purchaseReporting, reportsLineEfficiency, reportsLeadTime, reportsOTD, reportsWIP, reportsLineEfficiencyByWc, reportsLeadTimeBundles, reportsOnTimeDeliveryOrders, reportsWipByWc, settingsRouting, settingsBundling, settingsLineAllocation, settingsUsers, settingsRoles, settingsDevices, hitl`.
5. **File nyata `src/api/dummy/*.ts`: 11 file** (`dashboard.ts, bufferQueue.ts, routing.ts, qc.ts, inventory.ts, purchase.ts, reports.ts, settings.ts, roles.ts, hitl.ts, _delay.ts` [helper]). **File `src/api/real/*.ts`: 14 file.**

---

## C. Tabel model backend untuk agregat (F1) — model | field kunci | ada? | catatan

| Model | field kunci | ada? | catatan |
|---|---|---|---|
| `Bundle` | `state` | ✅ | `models/bundle.py:42`, CharField default `DRAFT` |
| `Bundle` | `qty` | ✅ | `bundle.py:39` |
| `Bundle` | `qty_done` | ✅ | `bundle.py:40` |
| `Bundle` | `wc_id` | ⚠️ | **tidak ada field `wc_id`**; FK `current_work_center` (`bundle.py:43`) → atribut `current_work_center_id` |
| `Bundle` | `created_at` / `updated_at` | ✅ | `bundle.py:68-69` |
| `BundleEvent` | `event_type` | ✅ | `bundle_event.py:42` |
| `BundleEvent` | `wc_id` | ❌ | **TIDAK ada FK ke WorkCenter** (hanya `bundle` FK) |
| `BundleEvent` | `operator_id` | ❌ | yang ada FK `actor` (`bundle_event.py:34`) → `actor_id` |
| `BundleEvent` | `timestamp` | ⚠️ | nama field = **`ts`** (`bundle_event.py:33`, auto_now_add), bukan `timestamp` |
| `BundleEvent` | `payload` | ✅ | `bundle_event.py:49` JSONField |
| `WorkCenter` | `code` / `name` | ✅ | `work_center.py:17-18` |
| `WorkCenter` | `wc_type` | ❌ | **tidak ada**; hanya `description`, `is_active`, `config` (JSON) |
| `WorkCenter` | `capability_tags` | ❌ | **tidak ada**; kapabilitas bisa disimpan di `config` (JSON) — `work_center.py:21` |
| `Order` | `code` | ✅ | `order.py:36` |
| `Order` | `deadline` | ✅ | `order.py:59` (DateTimeField, `null=True, blank=True`) |
| `Order` | `status` | ⚠️ | nama field = **`state`** (`order.py:53`), bukan `status` |
| `Order` | `created_at` | ✅ | `order.py:60` |
| `ScrapAccumulator` | `wc_id` | ⚠️ | FK `work_center` (`scrap.py:25`) → `work_center_id` |
| `ScrapAccumulator` | `wo_id` | ❌ | **tidak ada**; yang ada FK `bundle` (`scrap.py:31`, `null=True`) — **bukan** WorkOrder |
| `ScrapAccumulator` | `scrap_qty` | ⚠️ | nama field = **`qty`** (`scrap.py:39`); ada juga `rework_qty`, `end_loss_qty` |
| `ScrapAccumulator` | `period_date` | ❌ | **tidak ada**; yang ada `created_at`/`updated_at` (`scrap.py:44-45`) |
| `master.Product` | `odoo_id` | ✅ | `master/models.py:46` (PositiveBigInteger, null/unique) |
| `master.Product` | `name` | ✅ | `master/models.py:70` |
| `master.Product` | `default_code` | ⚠️ | nama field = **`code`** (`master/models.py:64`); juga ada `odoo_tmpl_id` |

**Model routing SUDAH ada (untuk B3 `/routing/graph`):** `ProcessRouting` (`process_routing.py` — `code/name/is_active/created_at/updated_at`)
dan `RoutingStep` (`routing_step.py` — `routing`, `code`, `label`, `order`, `is_initial`, `is_terminal`,
`work_center`, `allowed_next_steps` (M2M self), `rework_target_step` (self-FK)). Node/edge DAG
**bisa dibangun dari DB** — tidak perlu model baru. Tapi mock routing di frontend memakai `smv`, `maxWip`,
`capability[]`, `position{x,y}`, `status` yang **tidak ada** di model (perlu derivasi/`config`).

**Model yang TIDAK ADA sama sekali (greenfield F1–F3):** PurchaseOrder/vendor, StockMove/inventory operation,
RoutingConfig (header editable), HITLApproval, KPI aggregates (line-efficiency/lead-time/OTD — hanya bisa diturunkan dari `Bundle`+`BundleEvent`+`WorkOrder`).

---

## D. Jawaban 5 pertanyaan

1. **Dua `current-project.json`:** backend = `django_app/docs/curent_project.json` (ejaan "curent", root `docs/` **tidak ada**); frontend = `frontend_app_v2/docs/current-project.json`. **Untuk F1 backend → update `django_app/docs/curent_project.json`.**
2. **Frontend aktif = `frontend_app_v2/`** (v3 hand-coded; `App.tsx` pakai react-router + `lazy()` per route). **`frontend_app/` = v1 arsip** (metadata-driven, `DynamicCanvas` + `parseMetadata`). Dikonfirmasi `django_app/docs/curent_project.json` (`frontend_repo.active = frontend_app_v2/`) & `frontend_app_v2/docs/blueprint.md`.
3. **Endpoint monitoring Fase 4.4 ADA + `IsAuthenticated`:** `/api/v1/sync/records/` (`SyncRecordListView`, `monitoring.py:88-91`) & `/api/v1/finance/invoices/` (`InvoiceListView`, `monitoring.py:134-137`), keduanya `permission_classes=[IsAuthenticated]`. ✅
4. **Trace bridge masih ADA (4 file) & TIDAK mengganggu:** `trace_bridge/{reader,normalize,api}.py` + `config.yaml` (+ tests). Ini **app FastAPI terpisah** (uvicorn, `python -m trace_bridge.api`, `/_ai/trace/<id>`) — **tidak** didaftarkan di `config/urls.py` dan **tidak** ada service-nya di `docker-compose.yml`. Jadi tidak mengganggu routing Django. Catatan gap lama: aksi bundle tidak memicu ERP sync (tidak ada listener `BUNDLE_STATE_CHANGED`).
5. **19 pre-existing failure:** masih tercatat di `django_app/docs/curent_project.json` (`test_pre_existing_failures: 19`, note: "Celery broker nyata + flake registry global — BUKAN regresi"). **Tidak** menjalankan suite penuh (sesuai batasan); status belum diverifikasi ulang → anggap masih relevan sampai dibuktikan ulang.

---

## E. Environment

1. **`ERP_ADAPTER`:** `django_app/.env:30` = **`odoo`** (mode produksi, JSON-RPC ke Odoo). Default `config/settings.py:460` juga `"odoo"`.
2. **`pytest` permanen?:** **Ya (setelah rebuild image).** Ada di `requirements.txt:25-26` (`pytest==9.1.1`, `pytest-django==4.14.0`) dan `Dockerfile:32-34` `pip install -r requirements.txt`. **Namun** komentar `requirements.txt:21-24` (I8.9) memperingatkan image `django` yang berjalan **belum** memuatnya → jalankan `docker compose build django` agar permanen.
3. **Beat schedule:** **14 entry aktif** (`config/settings.py:386-455`): 9× `sync-master-*` (02:00), `sync-sale-orders` (*/5), `sync-scrap-accumulator` (06/14/22), `sync-invoice` (*/15), `recompute-readiness` (04:00), `reconcile-stock` (Sen 03:00).

---

## Risiko tak terduga (bisa menggagalkan F1)

Tiga hal menyimpang dari dokumen dan berpotensi menghadang F1. **(1) Skema model tidak cocok dengan nama field yang diasumsikan dokumen:** `BundleEvent` **tidak punya `wc_id`** dan **tidak punya `operator_id`** (yang ada `actor`/`actor_id` dan `ts`, bukan `timestamp`); `WorkCenter` **tidak punya `wc_type`/`capability_tags`** (hanya `config` JSON); `Order` memakai **`state`** (bukan `status`); `ScrapAccumulator` **tidak punya `wo_id`/`period_date`** dan memakai **`qty`** (bukan `scrap_qty`); `Bundle` memakai **`current_work_center`** (bukan `wc_id`); `master.Product` memakai **`code`** (bukan `default_code`). Artinya endpoint agregat F1 (mis. `/reports/wip/by-wc`, `/quality/aql`, `/production/buffer-queue`) harus diturunkan dari `Bundle.current_work_center_id` + `BundleEvent`, **bukan** query langsung ke kolom yang diasumsikan — desain berubah, bukan sekadar "tambah view". **(2) Dokumen perencanaan tidak ada di repo dan hitungannya tak cocok:** `_adapter.ts` + komentar `@dummy` menunjukkan **28 resource → 31 endpoint (27 GET + 4 POST)**, sementara brief menyebut **23**; tanpa dokumen Fase Final §F1–F3, prioritas 8 endpoint F1 juga hanya inferensi — ini risiko scope creep / salah prioritas. **(3) Sebagian besar domain F1–F3 adalah *greenfield*** (Purchase, Inventory/StockMove, Settings admin, HITL, KPI) dengan **nol model** di backend; sementara `ERP_ADAPTER=odoo` berarti endpoint apa pun yang menyentuh Odoo akan memukul Odoo **live** saat dev/test, dan Trace Bridge tidak ter-container (tidak aktif di prod). Tambahan: backend status JSON memakai ejaan `curent_project.json` (bukan `current-project.json`) — tooling/dokumentasi lain yang merujuk path "benar" akan meleset.

---

*R0 selesai — read-only. Tidak ada file kode yang diubah; hanya `django_app/docs/recon-f1-result.md` (baru) + entri `recon_f1` di `django_app/docs/curent_project.json`.*
