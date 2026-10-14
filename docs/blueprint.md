# 📄 `docs/blueprint.md` — Blueprint Terpadu (Backend + Frontend) v5.0

Simpan di **root repo**: `odoo-garmen-project/docs/blueprint.md`

```markdown
# Blueprint Terpadu — MES Garmen (v5.0)

**Backend + Frontend + Integrasi Odoo + Roadmap H1–H5**

> **Status:** ✅ ACTIVE · **Berlaku sejak:** 2026-10-10 · **Versi:** 5.0
> **Konsep:** MES = ERP Produksi (single point of input). Odoo = back-office pasif.
> **Baca juga:** `docs/REPLACE-NOTICE.md` (perubahan konsep), `docs/CHANGES-DETAIL-H1H5.md` (aturan H1–H5).

---

## 📌 Daftar Isi

1. [Konsep & Mental Model](#1-konsep--mental-model)
2. [Arsitektur 3 Lapis](#2-arsitektur-3-lapis)
3. [Stack Teknologi](#3-stack-teknologi)
4. [Struktur Repo](#4-struktur-repo)
5. [Backend (Django) — 28 Endpoint Aktif](#5-backend-django--28-endpoint-aktif)
6. [Frontend (React v3) — 47 MODE Real](#6-frontend-react-v3--47-mode-real)
7. [Integrasi Odoo](#7-integrasi-odoo)
8. [Model Data (47 Model)](#8-model-data-47-model)
9. [Role & Permission](#9-role--permission)
10. [Ops & Deploy](#10-ops--deploy)
11. [Status Proyek](#11-status-proyek)
12. [Roadmap H1–H5 — MES sebagai ERP](#12-roadmap-h1h5--mes-sebagai-erp)
13. [Aturan Emas](#13-aturan-emas)

---

## 1. Konsep & Mental Model

### 1.1 Konsep Baru (Berlaku)
```

┌─────────────────────────────────────────────────────────────┐
│ MES = ERP PRODUKSI (Single Point of Input) │
│ Semua input master & transaksi DI MES │
│ Klien buka 1 app saja: MES │
└──────────────────────┬──────────────────────────────────────┘
│ Sync dua arah (master) + satu arah (transaksi)
▼
┌─────────────────────────────────────────────────────────────┐
│ ODOO = BACK-OFFICE PASIF │
│ Akuntansi, pajak, e-Faktur, laporan keuangan formal │
│ User Odoo = akuntan saja (bukan operator produksi) │
└─────────────────────────────────────────────────────────────┘

```

**Inti:**
- Klien buka **1 app**: MES (bukan 2 app Odoo + MES)
- **MES** = source of truth untuk semua data produksi & bisnis
- **Odoo** = pencatat pasif + back-office (opsional dibuka)
- **Sync:** master dua arah, transaksi satu arah (MES → Odoo)

### 1.2 Konsep Lama (Deprecated — JANGAN Dipakai)

❌ "Odoo = tempat input master (Product/BOM/Partner/SO/PO)"
❌ "MES = hanya view + scan QR"
❌ "Klien buka 2 app: Odoo (input) + MES (monitor)"

Detail di `docs/REPLACE-NOTICE.md`.

### 1.3 Mental Model per Layer

```

Odoo = Passive Notary (catat bahan keluar, barang jadi masuk, invoice, pajak)
Django = Otak MES (bundle, routing, rework, alokasi, stok WIP, rule engine, master CRUD)
React = Wajah (operator HP/kios/scanner, supervisor, QC, admin, owner)
AI = Industrial Copilot (baca & usul, tidak eksekusi) — fase J, dokumen terpisah

```

---

## 2. Arsitektur 3 Lapis

```

┌───────────────────────────────────────────────────────────────┐
│ LAPIS 1: FRONTEND (React v3 — PWA Multi-Device) │
│ • Operator HP/Kios/Scanner: Scan QR → MULAI/SELESAI/SCRAP │
│ • Supervisor: Dashboard Buffer Queue, Routing, Reports │
│ • QC: Form per bundle (cacat, foto, rework vs scrap) │
│ • Admin/Owner: Master CRUD, Settings, User Management │
│ • Offline-first: IndexedDB + Background Sync │
│ • 47 MODE real, 0 dummy │
└────────────────────────────────┬──────────────────────────────┘
│ REST + WebSocket
▼
┌───────────────────────────────────────────────────────────────┐
│ LAPIS 2: DJANGO CORE (Otak + Source of Truth) │
│ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ A. CORE ENGINE (generik lintas industri) │ │
│ │ • Auth & Role (7 role) │ │
│ │ • Event Bus (Signals + Celery) │ │
│ │ • State Machine Engine │ │
│ │ • Rule Engine │ │
│ │ • Cycle Handler (Rework Loop) │ │
│ │ • Device Profile Manager │ │
│ │ • Audit Log + Idempotency │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ B. GARMENT PLUGIN (khusus garmen, configurable) │ │
│ │ • Bundle Engine (size + SKU-variant matrix) │ │
│ │ • Overlap Release Engine (DAG-based) │ │
│ │ • Process Routing Engine (DAG + Sub-Process) │ │
│ │ • Rework Loop Handler (QC → Sewing → QC) │ │
│ │ • Capability-Based Line Allocator │ │
│ │ • Tag-Based Order Router (+ piece-rate ticket) │ │
│ │ • WC Queue Manager │ │
│ │ • Scrap Accumulator + End-Loss Tracker │ │
│ │ • Priority Scheduler (tag-based) │ │
│ │ • Bottleneck Detector │ │
│ │ • Two-Stage Stock Aggregator (WIP + FG) │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ C. INTEGRATION SERVICES │ │
│ │ • Thermal Printer (ESC/POS + Kupon) │ │
│ │ • Odoo Sync (JSON-RPC, Celery, idempotency, 2-stage) │ │
│ │ • WA Gateway (stub → real) │ │
│ │ • Trace Bridge (FastAPI, terpisah) │ │
│ └─────────────────────────────────────────────────────────┘ │
│ │
│ 28 endpoint aktif · 47 model · 14 beat entry · 19 service │
└────────────────────────────────┬──────────────────────────────┘
│ JSON-RPC (async via Celery)
▼
┌───────────────────────────────────────────────────────────────┐
│ LAPIS 3: ODOO VANILLA (Back-office Pasif) │
│ • Master: product, BOM, partner, location, tax, journal │
│ • Transaksi: SO, PO, Stock Move (WIP/FG), Scrap, Invoice │
│ • Akuntansi, pajak, e-Faktur, laporan keuangan formal │
│ • TIDAK tahu: bundle, WC, routing, rework, overlap, ticket │
└───────────────────────────────────────────────────────────────┘

```

> **Catatan:** AI Agent Layer berdiri di atas Lapis 2, berlangganan Event Bus, tidak mengubah Lapis 1/2/3. Detail di dokumen terpisah.

---

## 3. Stack Teknologi

| Komponen | Teknologi | Versi |
|---|---|---|
| **Backend** | Django + DRF | Django **5.0.9** + DRF **3.15.2** (Python **3.11**) |
| **ASGI / WS** | daphne + channels | **daphne 4.2.3** + **channels 4.3.2** + channels-redis 4.3 |
| **Task Queue** | Celery + Redis | **Celery 5.4** + **Redis 5.0.8** |
| **Database** | PostgreSQL + psycopg | **PostgreSQL 15** + **psycopg 3.2.3** |
| **API Docs** | drf-spectacular | `/api/schema/` + `/api/docs/` |
| **Test Backend** | pytest | **pytest 9.1.1** + pytest-django 4.14.0 |
| **Frontend** | Vite + React + TS + Tailwind | React 18 + TS strict + Tailwind v4 |
| **Frontend Runtime** | bun | **bun 1.4.2** |
| **Printer** | ESC/POS (custom) | USB/Bluetooth/Network |
| **Odoo Sync** | JSON-RPC via httpx | httpx 0.27 |
| **Deploy** | Docker + Nginx + Certbot | `docker-compose.prod.yml` |
| **Observability** | Trace Bridge (FastAPI) + Sentry (opsional) | `/_ai/trace/{id}` + logs JSONL |
| **AI Agent** | `/api/v1/ai/chat` masih stub | Fase J |

---

## 4. Struktur Repo

```

odoo-garmen-project/
├── docker-compose.yml # dev
├── docker-compose.prod.yml # production
├── .env # dev
├── .env.prod.example # template produksi
├── .gitignore # abaikan .env*
├── nginx/
│ ├── nginx.conf
│ └── conf.d/mes.conf
├── scripts/
│ ├── generate-ssl.sh
│ ├── backup.sh
│ └── restore.sh
├── docs/ # ← root docs (baru)
│ ├── REPLACE-NOTICE.md
│ ├── CHANGES-DETAIL-H1H5.md
│ └── blueprint.md # dokumen ini
├── django_app/ # backend
│ ├── config/ # settings, urls, asgi/wsgi
│ ├── core/ # auth, event_bus, state_machine, rule_engine,
│ │ # cycle_handler, device_profile, audit, idempotency
│ ├── apps_industry/garment/ # plugin garmen (models, services, api, tests)
│ ├── integrations/
│ │ ├── erp_sync/ # transport/, tasks*.py, monitoring.py, api.py
│ │ ├── printing/ # ESC/POS
│ │ ├── wa_bot/ # gateway WhatsApp
│ │ └── ai/ # AiChatView (stub)
│ ├── master/ # 10 model master Odoo
│ ├── trace_bridge/ # FastAPI Trace Bridge
│ ├── tests/integration/ # test per endpoint
│ ├── docs/ # dokumentasi backend (17+ file)
│ ├── manage.py · requirements.txt · Dockerfile · Dockerfile.prod
├── frontend_app_v2/ # frontend (aktif)
│ ├── src/ # (lihat §6)
│ ├── docs/ # dokumentasi frontend (5 file)
│ ├── tests/ # unit + live
│ ├── package.json · vite.config.ts · tsconfig.json
└── frontend_app/ # frontend v1 (arsip)

```

---

## 5. Backend (Django) — 28 Endpoint Aktif

### 5.1 Kontrak Core (Fase I & Fase 4)

| Method | Path | Auth | Fungsi |
|---|---|---|---|
| GET | `/api/health/` | Anon | Health check |
| GET | `/api/schema/` | Anon | OpenAPI schema |
| GET | `/api/docs/` | Anon | Swagger UI |
| GET | `/api/v1/metadata/<resource>/` | IsAuth | Schema resource |
| GET | `/api/v1/chatter/<resource>/<id>/` | IsAuth | Chatter paginasi |
| GET | `/api/v1/devices/me` | Device cookie | Profile device |
| POST | `/api/v1/devices/bind` | IsAuth | Bind device |
| POST | `/api/v1/devices/unbind` | IsAuth | Unbind device |
| POST | `/api/v1/auth/login/` | AllowAny | Login admin (username+password) |
| POST | `/api/v1/auth/login-operator/` | AllowAny | Login operator (kode 4 digit) |
| POST | `/api/v1/auth/logout/` | IsAuth | Logout |
| GET | `/api/v1/auth/me/` | IsAuth | Current user |
| POST | `/api/v1/auth/change-password/` | IsAuth | Ganti password |
| POST | `/api/v1/auth/reset-password/<user_id>/` | Admin/Owner | Reset password |

### 5.2 Resource Garmen (Fase 3)

| Method | Path | Auth |
|---|---|---|
| GET | `/api/v1/garmen/<resource>/` | AllowAny |
| GET | `/api/v1/garmen/<resource>/<id>/` | AllowAny |
| GET | `/api/v1/garmen/<resource>/<id>/schema/` | AllowAny |
| POST | `/api/v1/garmen/<resource>/<id>/<ACTION_ID>/` | IsAuth |
| POST | `/api/v1/garmen/work-orders/` | IsAuth |
| POST | `/api/v1/garmen/bundles/` | IsAuth |

`resource ∈ {bundles, work-orders, order-lines, qc}`

### 5.3 Sync ERP (Fase I)

| Method | Path | Auth |
|---|---|---|
| POST | `/api/v1/sync/odoo/<stage>/` | IsAuth |
| POST | `/api/v1/sync/master/<entity>/` | IsAuth |
| POST | `/api/v1/sync/scrap/` | IsAuth |
| GET | `/api/v1/sync/records/` | IsAuth |
| GET | `/api/v1/garmen/orders/<id>/readiness/` | IsAuth |
| POST | `/api/v1/garmen/orders/<id>/recompute-readiness/` | IsAuth |
| GET | `/api/v1/reconciliation/report/` | IsAuth |
| GET | `/api/v1/audit/products-missing-odoo-id/` | IsAuth |
| GET | `/api/v1/finance/invoices/` | IsAuth |

`stage ∈ {WIP, FG}` · `entity ∈ {uom, location, warehouse, tax, journal, currency, product, bom, partner}`

### 5.4 Endpoint Agregat F1–F3A (23 endpoint)

| ID | Group | Endpoint | Method | Test |
|---|---|---|---|---|
| B1 | Dashboard | `/api/v1/dashboard/summary/` | GET | 11 |
| B2 | Production | `/api/v1/production/buffer-queue/` | GET | 9 |
| B3 | Production | `/api/v1/routing/graph/` | GET | 6 |
| B4 | Quality | `/api/v1/quality/defects/` | GET / **POST** | 13 / 9 |
| B5 | Quality | `/api/v1/quality/aql/` | GET | 7 |
| B6 | Quality | `/api/v1/quality/rework/` | GET | 7 |
| B7 | Inventory | `/api/v1/inventory/products/` | GET | 7 |
| B8 | Inventory | `/api/v1/inventory/operations/` | GET | 7 |
| B10 | Purchase | `/api/v1/purchase/orders/` | GET | 8 |
| B11 | Purchase | `/api/v1/purchase/reporting/` | GET | 10 |
| B12 | Purchase | `/api/v1/purchase/vendors/` | GET | 6 |
| B13 | Reports | `/api/v1/reports/line-efficiency/` | GET | 9 |
| B16 | Reports | `/api/v1/reports/wip/` | GET | 9 |
| B18 | Reports | `/api/v1/reports/line-efficiency/by-wc/` | GET | 5 |
| B19 | Reports | `/api/v1/reports/lead-time/` | GET | 6 |
| B19b | Reports | `/api/v1/reports/lead-time/bundles/` | GET | 5 |
| B20 | Reports | `/api/v1/reports/on-time-delivery/` | GET | 6 |
| B20b | Reports | `/api/v1/reports/on-time-delivery/orders/` | GET | 5 |
| B21 | Reports | `/api/v1/reports/wip/by-wc/` | GET | 5 |
| B22 | Settings | `/api/v1/settings/routing/` | GET+**POST** | 16 |
| B24 | Settings | `/api/v1/settings/bundling/` | GET+**POST** | 12 |
| B25 | Settings | `/api/v1/settings/line-allocation/` | GET+**POST** | 15 |
| B26 | Settings | `/api/v1/settings/users/` | GET+POST+PUT+DELETE | 21 |
| B27 | Settings | `/api/v1/settings/roles/` | GET | 8 |
| B28 | Settings | `/api/v1/settings/devices/` | GET | 8 |
| B29 | AI | `/api/v1/ai/hitl/queue/` | GET | 18 |
| B30 | Inventory | `/api/v1/inventory/reporting/` | GET | 8 |

> Semua `IsAuthenticated` → anonim **403**. Envelope ListPage = `{rows, total_count, has_more, next_cursor}`.

### 5.5 Print / WA / AI Stub

| Method | Path | Fungsi |
|---|---|---|
| POST | `/api/v1/print/bundle-tag/` | Print bundle tag ESC/POS |
| POST | `/api/v1/print/kupon/` | Print kupon piece-rate |
| POST | `/api/v1/wa/send/` | WA gateway (mock) |
| POST | `/api/v1/ai/chat` | AI chat (stub `{ok:false}`) |

### 5.6 WebSocket

| Path | Auth | Group |
|---|---|---|
| `WS /ws/events/` | Anon + cookie device | `bundle.{id}`, `work_order.{id}`, `events` |

**Event types:** `BUNDLE_STATE_CHANGED`, `WORK_ORDER_STATE_CHANGED`, `SCRAP_RECORDED`, `ERP_SYNC_COMPLETED`.

### 5.7 Beat Schedule (14 entry)

| # | Key | Jadwal WIB | Task |
|---|---|---|---|
| 1–9 | `sync-master-*` | Harian 02:00 | 9 task sync master Odoo → MES |
| 10 | `sync-sale-orders` | Tiap 5 menit | Poll SO Odoo → Order MES |
| 11 | `sync-scrap-accumulator` | 06:00, 14:00, 22:00 | Kirim scrap per shift |
| 12 | `sync-invoice` | Tiap 15 menit | Kirim customer invoice |
| 13 | `recompute-readiness` | Harian 04:00 | Refresh readiness OrderLine belum READY |
| 14 | `reconcile-stock` | Senin 03:00 | Rekonsiliasi stok MES vs Odoo + alert WA |

---

## 6. Frontend (React v3) — 47 MODE Real

### 6.1 Stack & Filosofi

- **React 18 + TypeScript strict + Tailwind v4 + Vite** (runtime: **bun 1.4.2**)
- **Hand-coded**, bukan metadata-driven (v1 metadata-driven diarsipkan)
- **Shell Odoo-style:** Sidebar + TopBar + BottomNav (mobile)
- **47 MODE real / 0 dummy** (sejak F5.4.CLOSE + F6.2)

### 6.2 Struktur Folder

```

frontend_app_v2/src/
├── app/ # config, useRole, nav-config, menu-config, RoleRoute, RootRoute,
│ # AccessDenied, AppIndexRedirect, layouts/{AppShell,TopBar,Sidebar,BottomNav}
├── core/ # useDeviceProfile, useWebSocket
├── integrations/ # api-client, offline-queue, use-offline-sync, ws-chatter,
│ # device-binding, conflict-plan, resource-data
├── lib/ # action-runner, chatter-merge, dropdown-state, sync-actions,
│ # state-display, feedback, tokens, cn, uuid, transition-rules,
│ # conflict-policy, login-form, auth-guard, user-admin, device-mode
├── types/ # api, bundle, work-order, qc, qc-row, order-line, readiness,
│ # routing, inventory, purchase, reports, settings, sales, finance, sync
├── api/ # \_adapter.ts + {resource}.ts (barrel), real/ (47), dummy/ (0)
├── hooks/ # useApiClient, useAuth, useDeviceMode, useBundles,
│ # useOperatorActions, useChatterWs, useMetadata, dll
├── components/
│ ├── atoms/ # 12 atom
│ ├── molecules/ # ~30 molecule
│ └── organisms/ # AppMenuBar, AuthGuard, RouteErrorBoundary
├── pages/ # 36 halaman
├── styles/tailwind.css # LOCKED md5: 7e65992b0d97efab12a50e803f94444b
├── App.tsx # Router + AuthProvider + AuthGuard + RootRoute + lazy per route
└── main.tsx # entry

```

### 6.3 Route Table (38 route)

| App | Route | Halaman |
|---|---|---|
| **Auth** | `/login` (publik) | LoginPage (2 tab: admin + operator) |
| **Dashboard** | `/` | RootRoute → Dashboard |
| **Master** | `/master/{products,partners,boms,locations,warehouses,work-centers,taxes,journals,currencies}` | List + Form |
| **Sales** | `/sales/orders`, `/sales/orders/new`, `/sales/orders/:id` | List + Form |
| **Production** | `/production/{scan,shop-floor/:id,bundles/:id,buffer-queue,routing,qc,qc/:id,readiness/:orderId,scrap/:id}` | 9 halaman |
| **Inventory** | `/inventory/{products,operations,reporting,config}` | 4 halaman |
| **Purchase** | `/purchase/{orders,vendors,reporting}` | 3 halaman |
| **Quality** | `/quality/{defects,aql,rework}` | 3 halaman |
| **Finance** | `/finance/invoices` | 1 halaman |
| **Reports** | `/reports/{line-efficiency,lead-time,on-time-delivery,wip,reconciliation}` | 5 halaman |
| **Settings** | `/settings/{routing,bundling,line-allocation,devices,users,audit,sync}` | 7 halaman |
| **AI** | `/ai/chat` | 1 halaman |
| **Legacy v2** | `/bundles`, `/work-orders`, `/workshop/:id`, `/dashboard` | Dipertahankan |
| **Catch-all** | `*` | NotFoundPage |

**Guard:**
- `/` → RootRoute (loading → spinner, tanpa sesi → `/login?redirect=/`, sesi → Dashboard atau app pertama role)
- App prefix (`/production`, `/inventory`, dll) → redirect ke menu pertama
- `RouteErrorBoundary` membungkus 49 route

### 6.4 Role (7 role)

`operator` · `supervisor` · `qc` · `admin` · `inventory` · `purchasing` · `owner`

**Guard khusus:**
- `SUPERVISOR_READINESS_ROLES = ['supervisor', 'owner']`
- `QUALITY_ROLES = ['qc', 'supervisor', 'admin', 'owner']`
- `PRODUCTION_ROLES = ['operator', 'supervisor', 'owner']`
- `QC_ROLES = ['qc', 'supervisor', 'operator', 'owner']`
- `BUFFER_QUEUE_ROLES` / `ROUTING_ROLES = ['supervisor', 'owner']`
- `INVENTORY_ROLES`, `PURCHASING_ROLES`, `ADMIN_ROLES`, `REPORTS_ROLES`, `SETTINGS_ROLES`, `AI_ROLES`, `FINANCE_ROLES`

### 6.5 Dua Jalur Aksi

| Halaman | Metode |
|---|---|
| BundleDetailPage | `apiClient.post` langsung |
| ShopFloorPage / QCPage | `submitAction` + `useOfflineSync` (offline-safe) |
| Form Master (Product/Partner/SO/PO) | `useEntityForm` + `apiClient` (online-only) |

### 6.6 Gate Wajib Frontend

| Gate | Target |
|---|---|
| Typecheck | 0 error |
| Lint | 0 error (1 warning lama `use-offline-sync.ts` boleh) |
| Build | Chunk < 500 kB |
| Test | Semua hijau |
| Tailwind md5 | `7e65992b0d97efab12a50e803f94444b` (LOCKED) |
| Warna | OKLCH only (0 hex/rgb/palet Tailwind) |
| Role filter | 7 role × 38 route, 0 mismatch |

---

## 7. Integrasi Odoo

### 7.1 Kontrak Terkunci (4 TX)

| TX | Model Odoo | Method | Arah |
|---|---|---|---|
| **TX-WIP-ISSUE** | `stock.move` | `create` | MES → Odoo |
| **TX-FG-RECEIPT** | `stock.move` | `create` | MES → Odoo |
| **TX-SCRAP** | `stock.scrap` | `create` + `action_validate` | MES → Odoo |
| **TX-INVOICE** | `account.move` (`out_invoice`) | `create` (draft) | MES → Odoo |

Detail di `django_app/docs/integrations/CONTRACT.md`.

### 7.2 Rantai Lokasi (Two-Stage)

```

WH/Stok (bahan) --WIP ISSUE--> Virtual Locations/Production --FG RECEIPT--> WH/Finished Goods

```

Setting `.env`: `ODOO_LOCATION_WIP_ID`, `ODOO_LOCATION_PRODUCTION_ID`, `ODOO_LOCATION_FG_ID`, `ODOO_LOCATION_SCRAP_ID`, `ODOO_UOM_ID`.

### 7.3 Adapter Pattern

- **ERPAdapter** (bisnis): `push_wip_issue`, `push_fg_receipt`, `push_scrap_wo`, `push_customer_invoice_wo`
- **ERPTransport** (master data): 10 `fetch_*` read-only
- **NullAdapter** — fail-safe kalau `ERP_ADAPTER=null`
- **OdooAdapter** — JSON-RPC via httpx
- **Factory:** `get_adapter()` fail-safe ke NullAdapter + warning

### 7.4 Idempotensi

`SyncRecord(resource, resource_id, stage)` — unique constraint DB.
- `stage ∈ {WIP, FG, SCRAP, INVOICE, MASTER_PUSH, MASTER_PULL}` (yang terakhir H1–H5)
- Push gagal → retry 3x exponential backoff (Celery)
- Replay → tidak duplikat

### 7.5 Audit

`AuditLog` action `erp_sync.push_wip|push_fg|push_scrap|push_invoice` — metadata `{status, erp_id, error, task_id}`.

---

## 8. Model Data (47 Model)

### 8.1 Garment (15 model)

```

Order, OrderLine, WorkOrder, Bundle, BundleEvent,
WorkCenter, ProcessRouting, RoutingStep, ProductionLine,
ScrapAccumulator, MaterialReadiness, StockReconciliation,
BundlingRule, LineAllocationRule, GarmentDeviceProfile

```

### 8.2 Core (11 model)

```

core_auth: User, Role
state_machine: StateMachine, State, Transition
rule_engine: Rule, RuleCondition, RuleAction
cycle_handler: CycleDefinition, CycleStep, CycleInstance
device_profile: DeviceProfile, DeviceBinding
audit: AuditLog
idempotency: IdempotencyRecord

```

### 8.3 Master (10 model)

```

Product (odoo_id, odoo_tmpl_id, code, name, is_active) + H1 fields
BOM, BOMLine, Partner, UoM, Location, Warehouse, Tax, Journal, Currency

```

### 8.4 Integrasi (6 model)

```

erp_sync: SyncRecord
printing: PrintJob
HITL: HITLRequest

- 3 model minor lainnya

```

### 8.5 Model Bawaan Django (5)

`auth.Group/Permission`, `admin.LogEntry`, `contenttypes.ContentType`, `sessions.Session`

---

## 9. Role & Permission

| Role | Akses Utama |
|---|---|
| **operator** | `/production/*` (scan, shop-floor), aksi bundle |
| **qc** | `/production/qc`, `/quality/*` |
| **supervisor** | `/dashboard`, `/production/*`, `/reports/*`, approval HITL |
| **admin** | `/settings/*`, user management, master CRUD |
| **inventory** | `/inventory/*` |
| **purchasing** | `/purchase/*` |
| **owner** | Semua (super-admin) |

**Endpoint permission:**
- `AllowAny`: `/api/health/`, `/api/schema/`, `/api/v1/garmen/<resource>/` (list/detail/schema)
- `IsAuthenticated`: SEMUA endpoint lain (termasuk `/api/v1/garmen/<resource>/<id>/<action>/`, sync, audit, admin)
- `Device cookie`: `/api/v1/devices/me`

---

## 10. Ops & Deploy

### 10.1 Artefak Deploy (F3-B Selesai)

| File | Fungsi |
|---|---|
| `docker-compose.prod.yml` | Prod compose (9 service: postgres, redis, django, celery_worker, celery_beat, nginx, certbot, backup, frontend_builder) |
| `django_app/Dockerfile.prod` | Backend image (multi-stage, non-root, ASGI/daphne) |
| `frontend_app_v2/Dockerfile` | Frontend builder |
| `nginx/nginx.conf` + `nginx/conf.d/mes.conf` | Reverse proxy + WS + static + SPA |
| `scripts/generate-ssl.sh` | Let's Encrypt via Certbot |
| `scripts/backup.sh` + `restore.sh` | pg_dump + media tar + restore |
| `.env.prod.example` | Template env produksi (semua placeholder) |

### 10.2 Dokumentasi Ops

| Dokumen | Isi |
|---|---|
| `django_app/docs/ops-readiness-audit.md` | Audit 10 blocker pra-deploy |
| `django_app/docs/onboarding-klien-baru.md` | 7 tahap onboarding (1 hari kerja) |
| `django_app/docs/runbook-operasional.md` | Harian/mingguan/bulanan + troubleshooting |
| `django_app/docs/uat-checklist.md` | UAT Klien A (5 role + cross-cutting) |
| `django_app/docs/integration-config.md` | Konfigurasi per klien |

### 10.3 Trace Bridge

- FastAPI terpisah (`trace_bridge/`) — `python -m trace_bridge.api`
- `curl http://127.0.0.1:8765/_ai/trace/<id>` → `{trace_id, duration_ms, spans[], errors}`
- Sumber: `logs/mes.jsonl` (RotatingFileHandler)

---

## 11. Status Proyek

**Progress: ~99%** (backend + frontend selesai; sisa: ops deploy + UAT)

| Komponen | Nilai |
|---|---|
| Backend endpoint | **28** (aktif) |
| Backend test | **1331** (19 pre-existing failure, bukan regresi) |
| Backend model | **47** |
| Backend migration | 11+ (dari Sprint 0–I8) |
| Frontend MODE real | **47 / 47** |
| Frontend MODE dummy | **0** |
| Frontend test | **574 passed** (74 skipped) |
| Frontend route | **38** |
| Build chunk | **309.5 kB** (< 500 kB) |
| Tailwind md5 | `7e65992b0d97efab12a50e803f94444b` (LOCKED) |
| Beat schedule | **14 entry** |

**Fase Selesai:** Sprint 0–9 · I1–I8 · F1–F16 · F2C.1–F2C.2 · F3A · F5.1–F5.4 · F6.1–F6.4 · FIX-ROUTE · F7.1

---

## 12. Roadmap H1–H5 — MES sebagai ERP

### 12.1 Konsep

MES = **ERP Produksi** (single point of input). Klien buka 1 app saja. Odoo = back-office pasif.

### 12.2 Fase

| Fase | Isi | Durasi | Endpoint Baru |
|---|---|---|---|
| **H1** | Master CRUD (Product, Partner, BOM, UoM, Warehouse, Location, WC, Line, Routing) | 1 minggu | ~25 |
| **H2** | Transaksi (SO, PO, WO, Bundle, Inventory Adjustment, Transfer) | 1.5 minggu | ~20 |
| **H3** | Finance (Invoice, Bill, Payment, Journal, Product Price, Tax) | 1 minggu | ~15 |
| **H4** | Laporan (Sales, Purchases, Stock, HPP, PnL, Production, Dashboard, Export) | 1 minggu | ~10 |
| **H5** | Settings (Company, Currency, Sequence, Permission, Audit, Integration, Printer, WA) | 1 minggu | ~15 |
| **Total** | | **~5–6 minggu** | **~85 endpoint** |

### 12.3 Urutan H1 (WAJIB)

1. H1.1 **Product** — fundamental
2. H1.2 UoM — dibutuhkan Product (`uom_id`)
3. H1.3 Warehouse — dibutuhkan Inventory
4. H1.4 Location — dibutuhkan Inventory
5. H1.5 Partner — dibutuhkan SO/PO
6. H1.6 BOM — dibutuhkan Produksi
7. H1.7 Work Center — dibutuhkan Routing
8. H1.8 Production Line — dibutuhkan Routing
9. H1.9 Process Routing — terakhir

### 12.4 Aturan Kunci (H1–H5)

- **Sync:** master dua arah, transaksi satu arah (MES → Odoo)
- **Kunci sync:** `odoo_id` (JANGAN pakai `code`/`name`)
- **Number sequence:** MES punya sendiri (`SO-2026-0001`), Odoo beda
- **Stock:** di Odoo, MES fetch on-demand (cache 5 menit)
- **Idempotency:** `SyncRecord` setiap CRUD master
- **Audit:** `AuditLog` setiap CRUD master
- **JANGAN:** bikin tabel stock, embed Odoo, hapus field lama

Detail di `docs/CHANGES-DETAIL-H1H5.md`.

---

## 13. Aturan Emas

### 13.1 Jebakan yang Harus Dihindari

| Jebakan | Kenapa Bahaya |
|---|---|
| Odoo tahu bundle/WC/routing | Odoo bukan MES |
| Routing hardcoded | Tidak portable |
| Bundle size fixed | Tidak fleksibel |
| Line allocation fixed | Tidak adaptif |
| Tanpa rework loop | Cacat tidak tertangani |
| Tanpa end-loss | Scrap tidak akurat |
| Sync tanpa idempotency | Duplikasi stock move |
| Sync tanpa aggregation | Banjiri Odoo |
| UI HP-only | Operator lini butuh kios/scanner |
| Tanpa offline-first | Lantai produksi sering putus jaringan |
| Tanpa device profile | Tiap device beda kebutuhan |
| Tanpa priority scheduler | Order fast_track tenggelam |
| Tanpa bottleneck detector | Supervisor buta |
| Tanpa admin UI | Ubah routing harus coding |
| Tanpa audit log | Tidak bisa diaudit |
| Tanpa NullAdapter | Dev tergantung Odoo |
| Tanpa Docker | Deploy ribet |
| Tanpa UAT 2 klien | Tidak terbukti portable |
| **Tambah field tanpa migration** | DB drift |
| **Hapus field lama** | Breaking change |
| **Pakai `code`/`name` sebagai kunci sync** | Duplikat data |
| **Bikin tabel stock di MES** | Rawan drift vs Odoo |

### 13.2 Slogan Inti

> **Django yang mengatur bundle, routing, rework, master CRUD, dan device; React yang bicara ke operator di HP/kios/scanner; Odoo yang mencatat dua tahap (bahan keluar, barang jadi masuk) + invoice + pajak. Routing, bundling, alokasi, rework = data, bukan kode. AI = dokumen terpisah, baca & usul, manusia eksekusi.**

### 13.3 Definisi "Selesai"

Modul dianggap selesai jika:
1. Backend endpoint hidup + test hijau (min 15 per modul)
2. Frontend halaman render + test hijau (min 8 per modul)
3. `curent_project.json` + `current-project.json` di-update
4. Laporkan 3 baris: nama modul + N test + file

### 13.4 Aturan Main AI/Cline

1. **1 modul = 1 siklus** (Backend → Frontend → JSON). Selesai baru lanjut.
2. **Baca dokumen dulu** (`REPLACE-NOTICE.md` + `CHANGES-DETAIL-H1H5.md`).
3. **Step 0 WAJIB** — recon dulu, laporkan, tunggu konfirmasi.
4. **Blocker → STOP**, tanya. Jangan asumsi.
5. **Jangan lupa** `odoo_id`, `SyncRecord`, `AuditLog` di setiap CRUD.

---

**Blueprint v5.0 — Portable, Configurable, Production-Ready, Multi-Device, Rework-Aware, Two-Stage Stock, ERP-Production Ready. AI Agent terdokumentasi terpisah.**
```
