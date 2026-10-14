frontend_app_v2/docs/blueprint.md
Catatan: File ini juga panjang (~400 baris). Salin dari Repomix yang kau kirim tadi — cari blok <file path="blueprint.md">. Tapi kalau rusak, pakai versi ini (sudah saya update sesuai kondisi terbaru):

markdown

# Blueprint Frontend v3 — MES Garmen (Final)

**Status:** ✅ LOCKED | **Berlaku untuk:** `frontend_app_v2/src/` + Backend v4.3 + Integrasi Odoo
**Prinsip:** Blueprint = kontrak tingkat tinggi. Detail implementasi ada di dokumen referensi.
**Update terakhir:** F7.1 (2026-10-10)

---

## 1. Prinsip Utama

**Frontend v3 = React hand-coded** dengan shell Odoo-style. Bukan metadata-driven.

| Lapis                  | Isi                                                                                                                                                  |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Integration Engine** | `api-client`, `offline-queue`, `action-runner`, `conflict-policy`, `device-binding`, `useWebSocket`, `uuid`, `transition-rules` — REUSE 100% dari v1 |
| **Shell & Navigasi**   | Sidebar + TopBar Odoo-style, 3 mode device (HP/Kios/Scanner), form full-page per entity                                                              |
| **Halaman & UI**       | 36 halaman hand-coded + 38 route, atoms/molecules/organisms                                                                                          |

**Filosofi:** Integration engine tetap. Shell Odoo-style. Halaman per role. Operator 3 tombol. Supervisor lihat antrean. QC form visual. Admin konfigurasi.

---

## 2. Arsitektur

┌──────────────────────────────────────────────────┐
│ APP SHELL (Odoo-Style) │
│ ┌─────────┬──────────────────────────────────┐ │
│ │ SIDEBAR │ TOP BAR (kontekstual per app) │ │
│ │ [Apps] ├──────────────────────────────────┤ │
│ │ Dashboard│ MAIN CONTENT │ │
│ │ Master │ (36 halaman hand-coded) │ │
│ │ Sales │ │ │
│ │ Production│ │ │
│ │ Inventory│ │ │
│ │ Purchase│ │ │
│ │ Quality │ │ │
│ │ Finance │ │ │
│ │ Reports │ │ │
│ │ Settings│ │ │
│ │ AI │ │ │
│ └─────────┴──────────────────────────────────┘ │
└──────────────────────────────────────────────────┘
│
┌────────────┼────────────┐
▼ ▼ ▼
Operator Supervisor Admin
HP/Kios/ Desktop Desktop
Scanner
│
▼
┌──────────────────────────┐
│ INTEGRATION ENGINE │
│ (reuse — 12 sabuk) │
└──────────────────────────┘
│
▼
┌──────────────────────────┐
│ DJANGO BACKEND v4.3 │
│ + Integrasi Odoo │
└──────────────────────────┘

text

**Alur data:**

- **Odoo → MES:** master (product, partner, BOM, location, tax, journal) + order (SO, PO)
- **MES → Odoo:** transaksi (WIP Issue, FG Receipt, Scrap, Invoice)
- **Tidak di-sync:** MO/WO Odoo, planning, OEE, bundle/WC/routing/rework

---

## 3. 12 Sabuk Pengaman (Tidak Berubah)

1. `api-client` — satu-satunya fetch, header kondisional, 409 union
2. `offline-queue` — IndexedDB, atomic flush, 3-mode conflict
3. `use-offline-sync` — orkestrasi queue + network listener
4. `action-runner` — `submitAction` + idempotency + optimistic lock
5. `transition-rules` — `TRANSITION_MODE`
6. `conflict-policy` — `CONFLICT_POLICY` per aksi
7. `uuid` — `generateUUID` fallback non-HTTPS
8. `device-identity` — cookie + localStorage
9. `device-binding` — bind/unbind
10. `useDeviceProfile` — 5-level resolver
11. `useWebSocket` + `ws-chatter` — real-time event
12. `ConflictResolver` — UI resolve 409

---

## 4. Struktur Folder

frontend_app_v2/src/
├── app/ # config, useRole, nav-config, menu-config, RoleRoute, RootRoute,
│ # AccessDenied, AppIndexRedirect, layouts/ (AppShell, TopBar, Sidebar, BottomNav)
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
│ ├── atoms/ # 12: Button, Input, Select, Badge, Card, Spinner, Toast, Modal,
│ │ # Textarea, Checkbox, Tabs, Tooltip, Dropdown
│ ├── molecules/ # ~30: ActionButton, ApiActionButton, BindDeviceModal, BundleCard,
│ │ # ChatterBox, DenseTable, EntityFormLayout, PrintTagButton,
│ │ # ProfileMenu, ReadinessTable, SmartButtonBar, SyncActionsCard, dll
│ └── organisms/ # AppMenuBar, AuthGuard, RouteErrorBoundary
├── pages/ # 36 halaman (production, quality, inventory, purchase, reports,
│ # settings, master, sales, finance, ai, dashboard, auth/login)
├── styles/tailwind.css # LOCKED md5
├── App.tsx # Router + AppShell + RoleRoute + AuthGuard + RootRoute + lazy per route
└── main.tsx # StrictMode + QueryClientProvider + BrowserRouter + AppRuntimeProvider

text

---

## 5. Route Table (38 route)

| App            | Route                                                                                                       | Halaman                            |
| -------------- | ----------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| **Auth**       | `/login` (publik)                                                                                           | LoginPage                          |
| **Dashboard**  | `/`                                                                                                         | RootRoute → Dashboard              |
| **Master**     | `/master/{products,partners,boms,locations,warehouses,work-centers,taxes,journals,currencies}`              | List + Form                        |
| **Sales**      | `/sales/orders`, `/sales/orders/new`, `/sales/orders/:id`                                                   | List + Form                        |
| **Production** | `/production/{scan,shop-floor/:id,bundles/:id,buffer-queue,routing,qc,qc/:id,readiness/:orderId,scrap/:id}` | 9 halaman                          |
| **Inventory**  | `/inventory/{products,operations,reporting,config}`                                                         | 4 halaman                          |
| **Purchase**   | `/purchase/{orders,vendors,reporting}`                                                                      | 3 halaman                          |
| **Quality**    | `/quality/{defects,aql,rework}`                                                                             | 3 halaman                          |
| **Finance**    | `/finance/invoices`                                                                                         | 1 halaman                          |
| **Reports**    | `/reports/{line-efficiency,lead-time,on-time-delivery,wip,reconciliation}`                                  | 5 halaman                          |
| **Settings**   | `/settings/{routing,bundling,line-allocation,devices,users,audit,sync}`                                     | 7 halaman                          |
| **AI**         | `/ai/chat`                                                                                                  | 1 halaman                          |
| **Legacy v2**  | `/bundles`, `/bundles/:id`, `/work-orders`, `/workshop/:id`, `/dashboard`                                   | Dipertahankan + `PRODUCTION_ROLES` |
| **Catch-all**  | `*`                                                                                                         | NotFoundPage                       |

**Guard anti-loop:** `/` → RootRoute (loading → spinner, tanpa sesi → `/login?redirect=/`, sesi → Dashboard atau app pertama role).

**App prefix redirect:** `/production`, `/inventory`, `/purchase`, `/quality`, `/reports`, `/settings`, `/finance` → redirect ke menu pertama app.

---

## 6. App Shell, Role & Navigasi

### 6.1 App Shell

- **Sidebar** (`w-16`): ikon app, filter per role, tooltip hover, avatar user
- **TopBar**: judul app + menu kontekstual (`AppMenuBar`) + dark toggle + badge online/offline + `ProfileMenu` (user) atau badge device
- **BottomNav**: muncul < `lg`
- **Immersive mode**: halaman operator (Scan, ShopFloor, QC) → TopBar hidden < `lg`
- **OfflineBanner**: global
- **RouteErrorBoundary**: 49 route dibungkus — 1 crash = 1 halaman fallback, bukan putih

### 6.2 Role (7 Role)

`operator` · `supervisor` · `qc` · `admin` · `inventory` · `purchasing` · `owner`

Sidebar difilter per `ROLE_APPS`. App yang tidak boleh → tidak muncul + URL tidak bisa diakses (redirect via `RoleRoute` → `AccessDenied`).

**Guard khusus:**

- `SUPERVISOR_READINESS_ROLES = ['supervisor', 'owner']`
- `QUALITY_ROLES = ['qc', 'supervisor', 'admin', 'owner']` (F7.1 — owner ikut)
- `PRODUCTION_ROLES = ['operator', 'supervisor', 'owner']`
- `QC_ROLES = ['qc', 'supervisor', 'operator', 'owner']`
- `BUFFER_QUEUE_ROLES`/`ROUTING_ROLES = ['supervisor', 'owner']`
- `INVENTORY_ROLES`, `PURCHASING_ROLES`, `ADMIN_ROLES`, `REPORTS_ROLES`, `SETTINGS_ROLES`, `AI_ROLES`, `FINANCE_ROLES`

### 6.3 Master Data & Form

- Klik entity → navigate form full-page (`EntityFormLayout`)
- CRUD: Create (`/new`) + Edit (`/:id`) + Delete (soft delete)
- Chatter di setiap entity
- Sync status badge di header (Synced/Pending/Failed/Not Synced)

---

## 7. Design System

| Elemen            | Aturan                                                                     |
| ----------------- | -------------------------------------------------------------------------- |
| **Warna**         | OKLCH only — token `tailwind.css` (md5 LOCKED)                             |
| **Dark mode**     | Token swap — nol `dark:` utility                                           |
| **Kartu**         | `glass-card rounded-card`                                                  |
| **Tombol**        | `rounded-pill` + `shadow-pill` + `transition-colors`. HP ≥48px, Kios ≥56px |
| **Badge**         | Token `BADGE` + tone blue/coral/muted/default                              |
| **Tabel**         | `DenseTable` + `TABLE_HEAD` + `TABLE_CELL` + hover row + `key={id}`        |
| **Ikon**          | lucide-react — `h-3`/`h-4`/`h-5`                                           |
| **Feedback**      | Setiap aksi → `playBeep` + `haptic` + flash                                |
| **Aksesibilitas** | `aria-label` icon-only, `focus-visible:ring`                               |
| **Animasi**       | Framer Motion: `whileTap` scale 0.97                                       |

---

## 8. Dua Jalur Aksi

| Halaman                                 | Metode                            | Alasan                                |
| --------------------------------------- | --------------------------------- | ------------------------------------- |
| **BundleDetailPage**                    | `apiClient.post` langsung         | Lihat + aksi sesekali                 |
| **ShopFloorPage / QCPage**              | `submitAction` + `useOfflineSync` | Operator & QC di lantai, offline-safe |
| **Form Master (Product/Partner/SO/PO)** | `useEntityForm` + `apiClient`     | Create/edit online-only               |

**Jangan diseragamkan.** Trade-off: Detail = simple, Workshop/QC = offline-safe + `ConflictResolver`.

---

## 9. Gate Wajib

| Gate            | Cara                                                                  |
| --------------- | --------------------------------------------------------------------- |
| Typecheck       | `bun run typecheck` → 0 error                                         |
| Lint            | `bun run lint` → 0 error (1 warning lama `use-offline-sync.ts` boleh) |
| Build           | `bun x --bun vite build` → `dist/` + chunk > 500 kB = 0               |
| Test            | `bun --bun run test` → hijau                                          |
| Tailwind        | `md5 src/styles/tailwind.css` → `7e65992b0d97efab12a50e803f94444b`    |
| Warna           | grep hex/rgb/palet Tailwind di `src/` → nol (kecuali engine tema)     |
| Role filter     | 7 role × 38 route, 0 mismatch                                         |
| Feedback        | Setiap aksi punya feedback visual + audio/haptic                      |
| Dummy isolation | 0 dummy (F5.4.CLOSE)                                                  |
| Idempotency     | Setiap POST punya `Idempotency-Key`                                   |

---

## 10. Status Track v3

**Track v3 (F1–F7.1):** ✅ DONE — 36 halaman, 12 atoms, ~30 molecules, 3 organisms, 38 route, chunk utama **309.5 kB**, MODE **47 real / 0 dummy**.

| Fase                                   | Deliverable                                                        | Status            |
| -------------------------------------- | ------------------------------------------------------------------ | ----------------- |
| F1                                     | Selaraskan kontrak & tipe (D1–D7)                                  | ✅ done           |
| F1.5                                   | CORS credentials dev                                               | ✅ done           |
| F1.6                                   | Fix credentials guard lintas origin                                | ✅ done           |
| F2                                     | Adapter real selektif (qc, sync, readiness)                        | ✅ done           |
| F3                                     | Metadata wiring                                                    | ⏭️ skipped        |
| F4                                     | Chatter & WS real-time                                             | ✅ done           |
| F5                                     | Menu bar Odoo-style                                                | ✅ done           |
| F6                                     | Sync manual + print kupon                                          | ✅ done           |
| F7                                     | Device binding UI                                                  | ✅ done           |
| F8                                     | Material readiness                                                 | ✅ done           |
| F9                                     | Reconciliation + audit                                             | ✅ done           |
| F10                                    | Invoice queue + sync monitor                                       | 🔄 revived by F15 |
| F11                                    | Scrap form + QC lengkap                                            | ✅ done           |
| F12                                    | Audit final + hardening                                            | ✅ done           |
| F13                                    | Role route cleanup                                                 | ✅ done           |
| F14                                    | Print legacy cleanup                                               | ✅ done           |
| F15                                    | Monitoring pages (revive F10)                                      | ✅ done           |
| F16                                    | TopBar menu fix                                                    | ✅ done           |
| F2C.1 / F2C.2 / F3A.CLOSE / F5.4.CLOSE | Flip MODE dummy → real (12+11+5)                                   | ✅ done           |
| F6.1–F6.4                              | Auth hybrid + login UI + user mgmt + device binding                | ✅ done           |
| FIX-ROUTE                              | Perbaiki 3 bug routing (login redirect, app prefix, ErrorBoundary) | ✅ done           |
| F7.1                                   | Owner ikut QUALITY_ROLES                                           | ✅ done           |

---

## 11. Roadmap Berikutnya

| Item                  | Prioritas | Catatan                                                     |
| --------------------- | --------- | ----------------------------------------------------------- |
| **Live ops**          | Wajib     | Deploy prod (Docker + Nginx + SSL + backup + monitoring)    |
| **UAT 2 klien**       | Wajib     | Garmen A + B (alur & device beda)                           |
| **H1–H5 (MES = ERP)** | Roadmap   | Master CRUD → Transaksi → Finance → Laporan → Settings      |
| **AI Agent Layer**    | Roadmap   | Decision Gate, MCP tools, KG+Vector, HITL, observability    |
| **Backlog**           | Opsional  | Widget renderer, list cursor keyset, server-side pagination |

---

## 12. Kalimat Kunci

> **Frontend v3 = React hand-coded dengan shell Odoo-style (sidebar + top bar + menu dropdown per app), 36 halaman + form penuh per entity, 38 route per role, memakai ulang 100% integration engine v1. Operator 3 tombol, Supervisor lihat antrean, QC form visual, Admin konfigurasi DAG, Master data = form + chatter + smart button + sync badge. 12 sabuk pengaman tetap aktif. Backend v4.3 production-grade (auth, seed, audit, monitoring). Zero dummy (47 real / 0 dummy).**
