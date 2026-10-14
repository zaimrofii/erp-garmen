# Cetak Biru Arsitektur Dasar Backend — Garment Mid-Scale Indonesia

**Portable, Configurable, Production-Ready, Multi-Device, Rework-Aware, Two-Stage Stock**

> ⚠️ **KONSEP BARU (2026-10-10)**: MES = ERP Produksi (single point of input).
> Klien buka 1 app saja: MES. Odoo = back-office pasif (akuntansi, pajak, e-Faktur).
> Sync: master dua arah, transaksi satu arah (MES → Odoo).
> Lihat `docs/REPLACE-NOTICE.md` + `docs/CHANGES-DETAIL-H1H5.md`.
>
> _(Path relatif dari folder ini: `../../docs/REPLACE-NOTICE.md` – dokumen root repo.)_

---

## 1. MENTAL MODEL

> ⚠️ **SUPERSEDED (2026-10-10)** — mental model di bawah digantikan konsep baru di NOTICE atas:
> MES = ERP Produksi / **single point of input**; Odoo = back-office pasif.
> Jangan menambah fitur yang mengarahkan user meng-input master/transaksi ke Odoo.
> Rujukan mengikat: `../../docs/REPLACE-NOTICE.md` (isi `docs/CHANGES-DETAIL-H1H5.md` bila ada).

```
Odoo    = Passive Notary (hanya catat bahan keluar & barang jadi masuk)
Django  = Otak (bundle, routing, rework, alokasi, stok WIP, rule engine)
React   = Wajah (operator HP/kios/scanner, supervisor, QC, admin)
AI      = Industrial Copilot (baca & usul, tidak eksekusi) — dokumen terpisah
```

**Inti:** Odoo tidak pernah tahu bundle, work center, routing, rework, atau overlap. Django adalah single source of truth. Semua aturan adalah konfigurasi, bukan kode.

---

## 2. ARSITEKTUR 3 LAPIS

```
┌───────────────────────────────────────────────────────────────┐
│ LAPIS 1: FRONTEND (React PWA — Multi-Device Adaptive)         │
│ • Operator HP: Scan QR → [MULAI]/[SELESAI]/[SCRAP]            │
│ • Operator Kios: Tablet stasioner per lini                    │
│ • Operator Scanner USB: Barcode gun + mini-PC                 │
│ • Supervisor: Dashboard Buffer Queue per WC (polling 5s)      │
│ • QC: Form per bundle (cacat, foto, rework vs scrap)          │
│ • Admin: UI Konfigurasi Routing, Bundling, Line, Device       │
│ • Offline-first: IndexedDB + Background Sync                  │
└───────────────────────────┬───────────────────────────────────┘
                            │ REST / 4G/5G / LAN
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ LAPIS 2: DJANGO CORE (Otak + Rule Engine + Cycle Handler)     │
│                                                               │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ A. CORE ENGINE (generik, semua industri)                │   │
│ │   • Auth & Role (operator, QC, supervisor, admin)       │   │
│ │   • Event Bus (Django Signals + Celery)                 │   │
│ │   • ERP Adapter Pattern (Null/Odoo/Accurate/SAP)        │   │
│ │   • State Machine Engine (generik)                      │   │
│ │   • Rule Engine (routing, bundling, allocation)         │   │
│ │   • Cycle Handler (Rework Loop)                         │   │
│ │   • Device Profile Manager                              │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                               │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ B. GARMENT PLUGIN (khusus garmen, configurable)         │   │
│ │   • Bundle Engine (size + SKU-variant matrix)           │   │
│ │   • Overlap Release Engine (DAG-based)                  │   │
│ │   • Process Routing Engine (DAG + Sub-Process)          │   │
│ │   • Rework Loop Handler (QC → Sewing → QC)              │   │
│ │   • Capability-Based Line Allocator                     │   │
│ │   • Tag-Based Order Router (+ piece-rate ticket)        │   │
│ │   • WC Queue Manager                                    │   │
│ │   • Scrap Accumulator per WC + End-Loss Tracker         │   │
│ │   • Priority Scheduler (tag-based)                      │   │
│ │   • Bottleneck Detector                                 │   │
│ │   • Two-Stage Stock Aggregator (WIP + FG)               │   │
│ └─────────────────────────────────────────────────────────┘   │
│                                                               │
│ ┌─────────────────────────────────────────────────────────┐   │
│ │ C. INTEGRATION SERVICES                                 │   │
│ │   • Thermal Printer (Bundle Tag ESC/POS + Kupon)        │   │
│ │   • Odoo Sync (JSON-RPC, Celery, idempotency, 2-stage)  │   │
│ │   • WA Gateway (notifikasi & approval HITL)             │   │
│ └─────────────────────────────────────────────────────────┘   │
└───────────────────────────┬───────────────────────────────────┘
                            │ JSON-RPC (2-stage: WIP + FG)
                            ▼
┌───────────────────────────────────────────────────────────────┐
│ LAPIS 3: ODOO VANILLA (Passive Notary — 2 Tahap)              │
│ • Master: product, BOM, partner                               │
│ • Transaksi: SO, Stock Move (WIP Issue + FG Receipt), Journal │
│ • Tidak tahu: bundle, WC, routing, rework, overlap, ticket    │
└───────────────────────────────────────────────────────────────┘
```

> **Catatan:** Lapis AI Agent berdiri di atas Lapis 2, berlangganan Event Bus, tidak mengubah Lapis 1/2/3. Detail lengkap ada di dokumen terpisah "Desain AI Agent".

---

## 3. TUJUH PRINSIP

1. **Odoo Tidak Pernah Tahu Bundle, WC, Routing, Rework, atau Overlap** — Odoo hanya catat SO, stock move, dan jurnal.
2. **Django = Single Source of Truth + Rule Engine + Cycle Handler** — Semua logika produksi ada di Django, bukan di Odoo.
3. **Routing = DAG + Rework Sub-Process (Bukan DAG Murni)** — Routing mendukung overlap dan siklus rework (QC → Sewing → QC).
4. **Two-Stage Stock Sync (WIP + FG)** — Bahan keluar dicatat saat bundle mulai (WIP Issue), barang jadi dicatat saat WO selesai (FG Receipt).
5. **Semua Aturan = Konfigurasi, Bukan Kode** — Routing, bundling, alokasi, rework, semua ada di database.
6. **Idempotency + Aggregation = Nyawa Integrasi** — Setiap sync ke Odoo harus idempoten dan teragregasi.
7. **UI = Multi-Device Adaptive, Bukan HP-Only** — Operator bisa pakai HP, kios tablet, atau scanner USB.

---

## 4. MODEL DATA INTI

```
> **REVISI F5.3 (2026-10-10) — bagian ini diganti dengan inventaris model yang BENAR-BENAR
> terpasang di kode** (hasil `django.apps.apps.get_models()` di container, 47 model total).
> Blok "desain awal" yang lama dipindahkan ke §4b sebagai referensi historis — beberapa
> field-nya **tidak** dipakai kode (mis. `WORK_ORDER.routing_id`, `parent_bundle_id`,
> `ODOO_MAPPING`, `synced_to_odoo`).

### 4a. Model terpasang — `apps_industry/garment` (15)

```
Order            code, customer(FK master.Partner), order_type, state, priority,
                 deadline, odoo_id
OrderLine        order(FK), product(FK master.Product), tag, ticket_code, qty, odoo_id
                 (readiness 1:1 → MaterialReadiness; work_orders 1:N)
WorkOrder        code, order_line(FK), state, qty_planned, qty_done
                 (TIDAK ada routing_id — routing diambil dari routing aktif pertama)
Bundle           code(unique), work_order(FK), size, sku_variant, qty, qty_done, state,
                 current_work_center(FK, null), production_line(FK, null),
                 version(SHA-256 optimistic lock), created_at, updated_at
BundleEvent      id(UUID PK), bundle(FK), ts(auto_now_add), actor(FK user, null),
                 event_type, text, payload(JSON) — APPEND-ONLY (tanpa updated_at)
WorkCenter       code, name, description, is_active, config(JSON)
                 (work_centers M2M ← ProductionLine)
ProcessRouting   code, name, description, is_active   (steps 1:N)
RoutingStep      routing(FK), code, label, order, is_initial, is_terminal,
                 work_center(FK, null), rework_target_step(FK self, null),
                 allowed_next_steps(M2M self), allowed_from(M2M self)
ProductionLine   code, name, description, is_active, work_centers(M2M WorkCenter)
ScrapAccumulator work_center(FK), bundle(FK, null), qty, rework_qty, end_loss_qty,
                 reason, notes
MaterialReadiness order_line(1:1), required_qty, received_qty, shortage_qty,
                 expected_date, status, po_ids(JSON), po_line_ids(JSON),
                 vendor_bill_ids(JSON), vendor_bill_status, vendor_bill_amount,
                 last_computed_at
StockReconciliation run_at, product(FK, null), product_odoo_id, mes_qty, odoo_qty,
                 diff, is_alert, notes
BundlingRule     name, size_matrix(JSON), bundle_size_default, is_active   [F3-A / B24]
LineAllocationRule name, wc_type, line(FK ProductionLine), priority, is_active,
                 config(JSON)                                              [F3-A / B25]
GarmentDeviceProfile device_profile(1:1 core DeviceProfile), work_center(FK, null), notes
```

### 4b. Model terpasang — core, master, integrasi

```
core_auth (2)        User, Role
state_machine (3)    StateMachine, State, Transition
rule_engine (3)      Rule, RuleCondition, RuleAction
cycle_handler (3)    CycleDefinition, CycleStep, CycleInstance   ← rework loop
device_profile (2)   DeviceProfile(code, name, is_active, config),
                     DeviceBinding(wc_code, device_profile(FK), user(null), cookie_token,
                     last_seen_at)
audit (1)            AuditLog
idempotency (1)      IdempotencyRecord
master (10)          Product(odoo_id, odoo_tmpl_id, code, name, is_active)
                     BOM(odoo_id, product, code, name) + BOMLine(bom, product, product_qty)
                     Partner(odoo_id, code, name, is_active)   ← TANPA email/phone/city
                     UoM · Location · Warehouse · Tax · Journal · Currency
                     (semua: odoo_id, code, name, is_active)
erp_sync (1)         SyncRecord(resource, resource_id(str), stage, status, erp_id, attempts,
                     last_error, payload(JSON), sent_at)  ← pengganti ODOO_MAPPING
printing (1)         PrintJob
```

**Total: 47 model** = 42 model milik project (garment 15 + master 10 + core 11 + integrasi 6)
+ 5 bawaan Django (`auth.Group/Permission`, `admin.LogEntry`, `contenttypes.ContentType`,
`sessions.Session`). Jalankan ulang hitungannya:

```bash
docker compose exec django python -c \
  "import django,os;os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings');django.setup();\
from django.apps import apps;print(len(apps.get_models()))"
```

### 4c. §4 desain awal yang TIDAK terpasang (referensi historis)

Blok "MODEL DATA INTI" versi pertama blueprint memakai nama/field berikut yang **tidak ada**
di kode sekarang — jangan dipakai saat onboarding:

| Desain awal | Realita kode |
|---|---|
| `WorkOrder.routing_id` (FK) | **tidak ada**; routing dipilih dari routing aktif pertama (`TwoStageAggregator.routing`) |
| `Bundle.parent_bundle_id`, `qr_code`, `printed_at` | **tidak ada**; QR = `Bundle.code`, cetak via `POST /api/v1/print/bundle-tag/` |
| `BundleEvent.wc_id`, `device_id`, `qty`, `metadata`, `synced_to_odoo`, `sync_batch_id` | **tidak ada** (`payload` JSON sebagai gantinya; `ts` = auto) |
| `Order.order_no`, `tags`, `channel`, `status` | `code`, `state`, `priority`, `deadline` |
| `OrderLine.size_matrix`, `sku_variant`, `bom_id` | `tag`, `ticket_code`, `qty` |
| `ProcessRouting.dag_definition`, `product_id`, `version` | `code`, `name`, `is_active`; DAG dibentuk dari `RoutingStep.order` + `allowed_next_steps` |
| `RoutingStep.step_no`, `wc_type`, `depends_on`, `overlap_pct` | `code`, `label`, `order`, `work_center`, `is_terminal`, `rework_target_step`, M2M `allowed_next_steps`/`allowed_from` |
| `DeviceProfile.wc_id`, `device_type` | `code`/`slug` + `config` JSON; relasi WC lewat `GarmentDeviceProfile` + `DeviceBinding` |
| `ODOO_MAPPING` | `SyncRecord` (stage WIP/FG/SCRAP/INVOICE + status SENT/FAILED/DUPLICATE) |
| `ScrapAccumulator.wo_id`, `period_date`, `scrap_qty` | relasi ke `bundle` (bukan WO), field `qty`, `rework_qty`, `end_loss_qty` |
```

---

## 5. ALUR DATA END-TO-END

**Contoh: 1000 Kaos Export + 20 Kaos Fast_Track + Rework**

### FASE A — Order Masuk & Tag-Based Routing

1. Order masuk via WA/desktop/API → `ORDER` + `ORDER_LINE` dibuat.
2. Tag `export` atau `fast_track` menentukan prioritas dan routing.
3. `TagRouter` pilih `PROCESS_ROUTING` yang sesuai.
4. `WORK_ORDER` dibuat per `ORDER_LINE`.
5. `BundleEngine` baca BOM attribute + size matrix.
6. Bundle dibuat per size/SKU-variant sesuai konfigurasi.
7. QR code di-generate → cetak bundle tag via thermal printer.
8. Bundle status = `CREATED`.

### FASE C — Eksekusi dengan DAG + Overlap + Rework

1. Operator scan QR di WC pertama → `BUNDLE_EVENT` START.
2. `OverlapReleaseEngine` cek DAG: step berikutnya bisa mulai jika dependency terpenuhi.
3. `CapabilityAllocator` pilih line/WC berdasarkan capability tags.
4. `WCQueueManager` atur antrean per WC.
5. Jika QC menemukan cacat → `ReworkLoopHandler`:
   - Bundle dikirim kembali ke step rework_target.
   - `BUNDLE_EVENT` REWORK dicatat.
   - Setelah selesai → kembali ke QC.
6. Scrap dicatat per WC → `SCRAP_ACCUMULATOR`.
7. End-loss dicatat saat bundle selesai.

### FASE D — Two-Stage Sync ke Odoo

1. **Stage 1 (WIP Issue):** Saat bundle pertama kali START, `TwoStageAggregator` kumpulkan qty → kirim stock move WIP Issue ke Odoo via Celery.
2. **Stage 2 (FG Receipt):** Saat WO selesai, aggregator kumpulkan qty FG → kirim stock move FG Receipt ke Odoo.
3. Idempotency via `ODOO_MAPPING` + `sync_batch_id`.
4. Retry otomatis jika gagal (Celery retry + exponential backoff).

### FASE E — Feedback & Dashboard

1. `BottleneckDetector` analisis queue per WC → kirim alert ke supervisor.
2. `PriorityScheduler` atur ulang prioritas berdasarkan tag & deadline.

   ### FASE B — Bundle Engine (Configurable Size + SKU-Variant)

3. Dashboard supervisor polling 5s → tampilkan buffer queue per WC.
4. Scrap & rework rate per WC ditampilkan untuk QC.

---

## 6. FITUR PER FASE

### PHASE 1 — FOUNDATION & PORTABLE OVERLAP + REWORK (MVP)

**1.1 Core Engine**

- Auth & Role (operator, QC, supervisor, admin)
- Event Bus (Django Signals + Celery)
- ERP Adapter Pattern (NullAdapter dulu)
- State Machine Engine generik

**1.2 Garment Plugin Dasar**

- Bundle Engine (size + SKU-variant matrix)
- Process Routing Engine (DAG + Sub-Process)
- Rework Loop Handler
- Overlap Release Engine
- Capability-Based Line Allocator
- Tag-Based Order Router
- WC Queue Manager
- Scrap Accumulator + End-Loss Tracker

**1.3 Integration**

- Thermal Printer (Bundle Tag ESC/POS + Kupon)
- Odoo Sync (JSON-RPC, Celery, idempotency, 2-stage)
- NullAdapter untuk dev tanpa Odoo

**1.4 UI Multi-Device**

- Operator HP: Scan QR → [MULAI]/[SELESAI]/[SCRAP]
- Operator Kios: Tablet stasioner per lini
- Operator Scanner USB: Barcode gun + mini-PC
- Supervisor: Dashboard Buffer Queue per WC
- QC: Form per bundle (cacat, foto, rework vs scrap)

**1.5 Admin UI Konfigurasi**

- Routing editor (DAG + sub-process + rework)
- Bundling config (size matrix + SKU-variant)
- Line & WC config (capability tags)
- Device profile config

**1.6 Deploy & UAT**

- Deploy VPS (Docker + docker-compose)
- UAT 2 klien beda alur + beda device
- Validasi portabilitas & adaptabilitas

**Output Sprint 1-4:** Sistem jalan penuh NullAdapter, DAG Routing + Rework, Bundle SKU-Variant, Two-Stage Sync.
**Output Sprint 5-6:** Ganti ke OdooAdapter, Thermal Printer + Kupon, Deploy VPS.
**Output Sprint 7-8:** Admin UI Konfigurasi (routing, bundling, device, capability).
**Output Sprint 9-10:** UAT 2 klien beda alur + beda device → bukti portabilitas & adaptabilitas.

---

### PHASE 2 — ADVANCE & ADAPTIVE

**2.1 Offline-First & Background Sync**

- IndexedDB + Service Worker
- Queue event lokal → sync saat online
- Conflict resolution (last-write-wins + manual override)

**2.2 Advanced Priority Scheduler**

- Multi-tag priority (export > fast_track > brand)
- Deadline-aware scheduling
- Dynamic re-prioritization

**2.3 Cross-WC Live Balance Dashboard**

- Flow graph antar WC
- Buffer queue visualization
- Bottleneck alert real-time

**2.4 Automated Odoo Reconciliation**

- Cek selisih stock WIP/FG antara Django & Odoo
- Auto-correct dengan approval supervisor
- Log reconciliation

---

### PHASE 3 — SAKTI (3-6 Bulan)

**3.1 AI-Driven Smart Overlapping & Predictive Split**

- Prediksi bottleneck → split bundle otomatis
- Overlap optimal berdasarkan histori

**3.2 Cross-WC Live Balance Dashboard (Flow Graph)**

- Visualisasi aliran bundle antar WC
- Prediksi queue berdasarkan kecepatan historis

**3.3 Computer Vision / CCTV AI Integration**

- Deteksi bundle di WC via kamera
- Auto-count qty tanpa scan

**3.4 Automated Odoo Financial & Costing Reconciliation**

- Cek HPP vs aktual
- Auto-jurnal penyesuaian

> **Catatan:** AI Agent (Decision Gate, MCP, KG+Vector, Context Pruning, HITL, Observability) didokumentasikan terpisah di "Desain AI Agent v4.3". Bagian non-AI tidak berubah.

---

## 7. STRUKTUR FOLDER DJANGO

```
> **REVISI F5.3** — struktur di bawah = hasil `ls` nyata pada container `django` (F5.3,
> 2026-10-10). Struktur lama (§7 versi awal) sudah tidak dipakai: tidak ada folder `api/`
> terpisah di root, tidak ada `adapter/` (sekarang `transport/`), dan `apps_industry/`
> berisi plugin industri.

```
django_app/                        # = /app di container `django`
├── config/                        # settings, urls, asgi/wsgi
│   └── tests/                     # test_settings_beat.py dll (5 file)
├── core/                          # CORE ENGINE (generik, lintas industri)
│   ├── audit/                     # AuditLog (jejak push ERP & aksi)
│   ├── auth/                      # User, Role (AUTH_USER_MODEL=core_auth.User)
│   ├── cycle_handler/             # CycleDefinition/Step/Instance — rework loop
│   ├── device_profile/            # DeviceProfile, DeviceBinding + api bind/me/unbind
│   ├── event_bus/                 # signals, registry listener, publisher (10 file)
│   ├── idempotency/               # IdempotencyRecord (kunci idempotensi push)
│   ├── rule_engine/               # Rule, RuleCondition, RuleAction
│   └── state_machine/             # StateMachine, State, Transition (guard transisi)
├── apps_industry/garment/         # GARMENT PLUGIN
│   ├── models/                    # 15 model (14 file: bundle, bundle_event,
│   │                              #   bundling_rule, device_profile, line_allocation_rule,
│   │                              #   material_readiness, order, process_routing,
│   │                              #   production_line, routing_step, scrap,
│   │                              #   stock_reconciliation, work_center, work_order)
│   ├── services/                  # 11 service (lihat daftar di bawah)
│   ├── api/                       # views.py, urls.py, industries.py,
│   │                              #   resources/, actions/, schema/, chatter/, settings/
│   ├── management/commands/       # seed_demo_bundles, seed_benchmark_data
│   └── tests/                     # factories.py + test model/service
├── integrations/
│   ├── erp_sync/                  # transport/ (Null + Odoo JSON-RPC), tasks*.py,
│   │                              #   monitoring.py (23 endpoint agregat), api.py,
│   │                              #   services/ (reconciliation, invoice, readiness)
│   ├── printing/                  # ESC/POS bundle tag + kupon
│   ├── wa_bot/                    # gateway WhatsApp (mock)
│   └── ai/                        # AiChatView (stub {ok:false})
├── master/                        # 10 model master Odoo (Product, BOM, BOMLine, Partner,
│   │                              #   UoM, Location, Warehouse, Tax, Journal, Currency)
│   └── tests/                     # 2 file
├── trace_bridge/                  # Trace Bridge FastAPI (/_ai/trace/{id}) + tests/
├── simulator/                     # klien simulator (agents, world, telemetry, llm,
│                                  #   scenarios, client, docs)
├── tools/                         # odoo_probe/, fixtures/
├── tests/integration/             # 32 file — kontrak endpoint per fase (F1/F2/F3-A)
├── docs/                          # dokumentasi (indeks: docs/README-index.md)
│   └── integrations/              # CONTRACT.md, api-signature.md, framework_jsonrpc_validation.md
├── runs/                          # artefak run simulator (51 file, bukan source)
├── scripts/                       # load_test.py, test-tembak.py
├── logs/                          # mes.jsonl (RotatingFileHandler — sumber Trace Bridge)
├── manage.py · requirements.txt · Dockerfile · Dockerfile.prod · .env
```

### Service layer (`apps_industry/garment/services/` — 11 service)

| Service | Fungsi |
|---|---|
| `bundle_engine.py` | buat bundle dari size + SKU-variant matrix |
| `overlap_release.py` | baca DAG routing → boleh mulai step berikutnya? |
| `rework_loop.py` | `ReworkLoopHandler` (QC → Sewing → QC) via cycle_handler |
| `tag_router.py` | pilih routing + ticket piece-rate dari tag order |
| `capability_allocator.py` | alokasi line/WC berdasarkan capability |
| `wc_queue.py` | antrean bundle per WC (`EXCLUDED_STATES = DONE/CANCELLED`) |
| `two_stage_aggregator.py` | payload WIP Issue / FG Receipt (+ penentu stage terminal) |
| `scrap_accumulator.py` | akumulasi scrap/rework/end-loss per WC |
| `priority_scheduler.py` | prioritas antrean dari rule tag (FAST_TRACK) |
| `bottleneck_detector.py` | deteksi WC bottleneck (default: queue > 10 **atau** avg wait > 60 menit) |
| `action_events.py` | pencatatan event aksi (audit/jejak) |
```

---

## 7b. BACKEND ENDPOINTS (23 — per 2026-10-10)

Semua endpoint **read-only atau GET+POST terbatas**, permission `IsAuthenticated`
(anonim → **403**), rate limit DRF: anon 60/menit · user 300/menit. Tabel ini
dihasilkan dari URLConf nyata (`django.urls.resolve` per path) + hitungan `def test_`
di file test yang memuat path tsb.

| ID | Group | Endpoint | Method | Auth | Test |
|---|---|---|---|---|---|
| B1 | Dashboard | `/api/v1/dashboard/summary/` | GET | IsAuthenticated | 11 |
| B2 | Production | `/api/v1/production/buffer-queue/` | GET | IsAuthenticated | 9 |
| B3 | Production | `/api/v1/routing/graph/` | GET | IsAuthenticated | 6 |
| B4 | Quality | `/api/v1/quality/defects/` | GET | IsAuthenticated | 13 |
| B5 | Quality | `/api/v1/quality/aql/` | GET | IsAuthenticated | 7 |
| B6 | Quality | `/api/v1/quality/rework/` | GET | IsAuthenticated | 7 |
| B7 | Inventory | `/api/v1/inventory/products/` | GET | IsAuthenticated | 7 |
| B7b | Quality | `/api/v1/quality/defects/` | **POST** | IsAuthenticated | 9 |
| B8 | Inventory | `/api/v1/inventory/operations/` | GET | IsAuthenticated | 7 |
| B10 | Purchase | `/api/v1/purchase/orders/` | GET | IsAuthenticated | 8 |
| B11 | Purchase | `/api/v1/purchase/reporting/` | GET | IsAuthenticated | 10 |
| B12 | Purchase | `/api/v1/purchase/vendors/` | GET | IsAuthenticated | 6 |
| B13 | Reports | `/api/v1/reports/line-efficiency/` | GET | IsAuthenticated | 9 |
| B16 | Reports | `/api/v1/reports/wip/` | GET | IsAuthenticated | 9 |
| B18 | Reports | `/api/v1/reports/line-efficiency/by-wc/` | GET | IsAuthenticated | 5 |
| B19 | Reports | `/api/v1/reports/lead-time/` | GET | IsAuthenticated | 6 |
| B19b | Reports | `/api/v1/reports/lead-time/bundles/` | GET | IsAuthenticated | 5 |
| B20 | Reports | `/api/v1/reports/on-time-delivery/` | GET | IsAuthenticated | 6 |
| B20b | Reports | `/api/v1/reports/on-time-delivery/orders/` | GET | IsAuthenticated | 5 |
| B21 | Reports | `/api/v1/reports/wip/by-wc/` | GET | IsAuthenticated | 5 |
| B22 | Settings | `/api/v1/settings/routing/` | GET+POST | IsAuthenticated | 16 |
| B24 | Settings | `/api/v1/settings/bundling/` | GET+POST | IsAuthenticated | 12 |
| B25 | Settings | `/api/v1/settings/line-allocation/` | GET+POST | IsAuthenticated | 15 |

Catatan kontrak:
- **B4 vs B7b** memakai path yang sama, beda method (GET daftar defect, POST catat defect baru).
- Amplop list **F1/F2/F3-A** = `{rows, total_count, has_more, next_cursor}`; endpoint
  monitoring Fase 4.4 (`/sync/records/`, `/finance/invoices/`) memakai `has_next`.
- Bentuk **custom** (bukan ListPage): B3 (node/edge DAG), B13 (rows per WC + trend/series),
  B16 (rows per WC + trend; `group_by=none` tanpa `rows`), B11 (KPI + `monthly_series` +
  `top_vendors`), B5/B18/B21 (rows + `generated_at`/`period`).
- B22/B24/B25 menerima **POST** (masing-masing menambah 1 migration F3-A:
  `garment.0009_bundlingrule`, `garment.0010_lineallocationrule`).
- Endpoint lain di luar 23 (= infrastruktur/ERP/kontrak core): `/api/health/`,
  `/api/schema/`, `/api/docs/`, `/api/v1/metadata/<resource>`, `/api/v1/chatter/...`,
  `/api/v1/devices/...`, `/api/v1/garmen/<resource>/...` (ResourceListView + ActionView),
  `/api/v1/sync/odoo/<stage>/`, `/api/v1/sync/master/<entity>/`, `/api/v1/sync/scrap/`,
  `/api/v1/sync/records/`, `/api/v1/garmen/orders/<id>/readiness|recompute-readiness/`,
  `/api/v1/reconciliation/report/`, `/api/v1/audit/products-missing-odoo-id/`,
  `/api/v1/print/bundle-tag|kupon/`, `/api/v1/wa/send/`, `/api/v1/ai/chat`.

## 7c. STATUS FASE (per 2026-10-10)

| Fase | Isi | Status |
|---|---|---|
| Sprint 0–9 (core: auth, event bus, state machine, rule engine, cycle handler, device) | fondasi generik | ✅ selesai |
| I1–I8 (integrasi Odoo: master sync, SO, readiness, scrap, invoice, vendor bill, rekonsiliasi, hardening) | 14 entry beat + TX WIP/FG/SCRAP/INVOICE | ✅ selesai |
| F1 | 12 endpoint agregat (B1–B16) | ✅ selesai |
| F2 + gap-fill | B10/B11 + field aditif G1–G5b (trend/series/lines/monthly_series) | ✅ selesai |
| F3-A | 11 endpoint (B5, B7b, B18–B25) + 2 migration | ✅ selesai |
| F5.2 | benchmark + optimasi N+1 (5 endpoint, 0 migration) — lihat `docs/perf-benchmark.md` | ✅ selesai |
| F5.3 | refresh blueprint + integration-config + indeks docs (dokumen ini) | ✅ selesai |
| **F3-B** | 5 endpoint sisa backend (users, roles, devices/HITL) — non-blocker pilot | ⏳ pending |
| **F4** | UAT 2 klien (butuh VPS + Klien A) — lihat `docs/uat-checklist.md` | ⏳ pending |
| **F6** | tuning lanjutan (index/cache — butuh migration) + go-live | ⏳ pending |

Angka status terkini (jumlah endpoint, test, fase) selalu di
`docs/curent_project.json` — dokumen itu **source of truth mesin**, halaman ini ringkasannya.

## 7d. KETERBATASAN YANG DIKETAHUI

Daftar lengkap + workaround: **`docs/known-limitations.md`** (Backend 8 · Frontend 6 ·
Ops 7 · Test 7). Tiga yang paling sering ditanya saat onboarding:

1. `BundleEvent` tidak menyimpan `wc_id` → atribusi WC dari `bundle.current_work_center`
   (kolom `from_step`/`to_step` nul di `/quality/rework/`).
2. `master.Partner` hanya `odoo_id/code/name/is_active` → UI vendor tanpa email/phone/city.
3. `WorkOrder` tidak punya FK routing → routing = routing aktif pertama.

---

| Komponen            | Teknologi (terverifikasi di `requirements.txt`, 2026-10-10)      |
| ------------------- | ---------------------------------------------------------------- |
| **ERP**             | Odoo Vanilla (Community/Enterprise) — eksternal, bukan container |
| **Backend**         | **Django 5.0.9** + **DRF 3.15.2** (Python **3.11**)              |
| **Realtime / WS**   | **daphne 4.2.3** (ASGI) + **channels 4.3.2** + channels-redis 4.3 |
| **Task Queue**      | **Celery 5.4** + **Redis 5.0.8** (broker, cache, channel layer)  |
| **Database**        | **PostgreSQL 15** + **psycopg 3.2.3**                            |
| **API docs**        | drf-spectacular (`/api/schema/`, `/api/docs/`)                   |
| **Test**            | **pytest 9.1.1** + pytest-django 4.14.0 (unit, integration, live) |
| **Frontend**        | Vite + React 18 + TypeScript (strict) + Tailwind v4, runtime **bun** |
| **Thermal Printer** | ESC/POS (`integrations/printing/`) via USB/Bluetooth             |
| **Odoo Sync**       | JSON-RPC via **httpx 0.27** (`integrations/erp_sync/transport/`) |
| **Deploy**          | Docker + `docker-compose.prod.yml` + Nginx (TLS) + certbot + service `backup` |
| **Observability**   | Trace Bridge (FastAPI `/_ai/trace/{id}`) + log JSONL `logs/mes.jsonl`; Sentry **opsional** (`SENTRY_DSN`) |
| **AI Agent**        | `/api/v1/ai/chat` masih **stub** (`{ok:false}`) — desain di dokumen terpisah |

---

## 9. SPRINT EKSEKUSI (10 MINGGU MVP)

| Sprint | Fokus                                       | Output                                                     |
| ------ | ------------------------------------------- | ---------------------------------------------------------- |
| **1**  | Core + Rule + Cycle + NullAdapter           | Auth, Event Bus, State Machine, Rule Engine, Cycle Handler |
| **2**  | DAG Routing + Rework Sub-Process            | PROCESS_ROUTING, ROUTING_STEP, ReworkLoopHandler           |
| **3**  | Bundle Engine (SKU-Variant) + Overlap       | BundleEngine, OverlapReleaseEngine                         |
| **4**  | Tag Router + Capability + Device Profile    | TagRouter, CapabilityAllocator, DeviceProfile              |
| **5**  | Two-Stage Aggregator + Odoo Sync            | TwoStageAggregator, OdooAdapter, Idempotency               |
| **6**  | Priority + Bottleneck + Rework Queue UI     | PriorityScheduler, BottleneckDetector, UI QC               |
| **7**  | Admin UI Konfigurasi                        | Routing editor, Bundling config, Line/WC config            |
| **8**  | Deploy + UAT Klien A                        | Docker deploy, UAT Klien A                                 |
| **9**  | Onboarding Klien B (beda alur, beda device) | UAT Klien B                                                |
| **10** | Validasi Portabilitas + Tuning              | Bukti portabilitas, tuning performa                        |

**Setelah MVP → Phase 2 (4-6 minggu) → Phase 3 (3-6 bulan).**

---

## 10. JEBAKAN YANG HARUS DIHINDARI

| Jebakan                         | Kenapa Bahaya                                            |
| ------------------------------- | -------------------------------------------------------- |
| **Odoo tahu bundle/WC/routing** | Odoo bukan MES. Jangan paksa Odoo kelola produksi.       |
| **Routing hardcoded**           | Tidak portable. Semua routing harus di DB.               |
| **Bundle size fixed**           | Tidak fleksibel. Bundle size harus dari BOM attribute.   |
| **Line allocation fixed**       | Tidak adaptif. Gunakan capability-based allocator.       |
| **Tanpa rework loop**           | Cacat tidak tertangani. Rework harus jadi siklus.        |
| **Tanpa end-loss**              | Scrap tidak akurat. End-loss harus dicatat.              |
| **Sync tanpa idempotency**      | Duplikasi stock move. Wajib idempotent.                  |
| **Sync tanpa aggregation**      | Banjiri Odoo. Agregasi WIP + FG.                         |
| **UI HP-only**                  | Operator lini butuh kios/scanner. Multi-device wajib.    |
| **Tanpa offline-first**         | Lantai produksi sering putus jaringan. IndexedDB + sync. |
| **Tanpa device profile**        | Tiap device beda kebutuhan. Device profile manager.      |
| **Tanpa priority scheduler**    | Order fast_track tenggelam. Tag-based priority.          |
| **Tanpa bottleneck detector**   | Supervisor buta. Deteksi & alert.                        |
| **Tanpa admin UI**              | Ubah routing harus coding. Admin UI wajib.               |
| **Tanpa audit log**             | Tidak bisa diaudit. Catat semua event.                   |
| **Tanpa NullAdapter**           | Dev tergantung Odoo. NullAdapter dulu.                   |
| **Tanpa Docker**                | Deploy ribet. Docker + compose.                          |
| **Tanpa UAT 2 klien**           | Tidak terbukti portable. UAT 2 klien beda alur.          |
| **Tanpa piece-rate ticket**     | Operator tidak tahu upah. Kupon piece-rate.              |
| **Tanpa two-stage sync**        | Stock WIP tidak akurat. Two-stage wajib.                 |

---

## 11. SLOGAN INTI

> **"Django yang mengatur bundle, routing, rework, dan device; React yang bicara ke operator di HP/kios/scanner; Odoo yang mencatat dua tahap: bahan keluar, barang jadi masuk. Routing, bundling, alokasi, dan rework = data, bukan kode. AI = dokumen terpisah, baca & usul, manusia eksekusi."**

Kalau semua aturan ada di database dan delapan belas peran tidak tercampur, arsitektur ini **antipeluru di lantai produksi garmen mana pun** — Garmen A, B, C, D — dengan alur, device, dan budaya berbeda, tanpa refactor core.

---

## 12. CHECKLIST SEBELUM TEKNIS

### Odoo Side:

- [ ] Odoo Vanilla terinstall (Community/Enterprise)
- [ ] Master product, BOM, partner sudah siap
- [ ] SO, Stock Move, Journal sudah dikonfigurasi
- [ ] JSON-RPC endpoint aktif & teruji
- [ ] User API dengan hak akses terbatas

### Django Side:

- [ ] Django 4.x + DRF terinstall
- [ ] PostgreSQL 15+ siap
- [ ] Celery + Redis siap
- [ ] Auth & Role (operator, QC, supervisor, admin) terdefinisi
- [ ] Event Bus (Django Signals + Celery) jalan
- [ ] State Machine Engine generik jalan
- [ ] Rule Engine jalan
- [ ] Cycle Handler (Rework Loop) jalan
- [ ] ERP Adapter Pattern (NullAdapter dulu) jalan
- [ ] Bundle Engine (size + SKU-variant) jalan
- [ ] Overlap Release Engine (DAG) jalan
- [ ] Process Routing Engine (DAG + Sub-Process) jalan
- [ ] Rework Loop Handler jalan
- [ ] Capability-Based Line Allocator jalan
- [ ] Tag-Based Order Router (+ piece-rate ticket) jalan
- [ ] WC Queue Manager jalan
- [ ] Scrap Accumulator + End-Loss Tracker jalan
- [ ] Priority Scheduler jalan
- [ ] Bottleneck Detector jalan
- [ ] Two-Stage Stock Aggregator (WIP + FG) jalan
- [ ] Thermal Printer (ESC/POS + Kupon) jalan
- [ ] Odoo Sync (JSON-RPC, Celery, idempotency) jalan
- [ ] Admin UI Konfigurasi jalan
- [ ] Audit log lengkap

### React Side:

- [ ] React 18 + PWA terinstall
- [ ] Operator HP: Scan QR → [MULAI]/[SELESAI]/[SCRAP]
- [ ] Operator Kios: Tablet stasioner per lini
- [ ] Operator Scanner USB: Barcode gun + mini-PC
- [ ] Supervisor: Dashboard Buffer Queue per WC (polling 5s)
- [ ] QC: Form per bundle (cacat, foto, rework vs scrap)
- [ ] Admin: UI Konfigurasi Routing, Bundling, Line, Device
- [ ] Offline-first: IndexedDB + Background Sync
- [ ] State Management + Optimistic UI

### Infra:

- [ ] Docker + docker-compose siap
- [ ] Nginx reverse proxy siap
- [ ] VPS dengan spec memadai
- [ ] Backup strategy (DB + file)
- [ ] Monitoring (Sentry + opsional Prometheus/Grafana)
- [ ] SSL certificate

### AI Agent Side:

- [ ] → Lihat dokumen terpisah "Desain AI Agent v4.3" §10

---

**Cetak biru backend final — Portable, Configurable, Production-Ready, Multi-Device, Rework-Aware, Two-Stage Stock. AI Agent terdokumentasi terpisah.**

Siap gas Sprint 1: Core Engine + Rule Engine + Cycle Handler + NullA
