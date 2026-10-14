# 📄 `docs/NEW-CLIENT-TEMPLATE.md` — v2.0 (dengan 4 Perbaikan Kritis)

Simpan di **root repo**: `odoo-garmen-project/docs/NEW-CLIENT-TEMPLATE.md`

````markdown
# Panduan Duplikasi Proyek untuk Klien Baru — v2.0

**Untuk:** Onboarding klien ke-2, ke-3, dst.
**Tujuan:** Menyalin basis proyek ke klien baru **tanpa membangun ulang dari nol**, lalu modifikasi sesuai preferensi klien.
**Prinsip:** Klien baru = **80% reuse, 20% custom**. Jangan redesign; sesuaikan config + tambah modul yang belum ada.
**Versi:** v2.0 (2026-10-12) — revisi dengan Versioning, Update Strategy, Data Readiness, Exit Strategy.

> ⚠️ **Baca juga:** `docs/REPLACE-NOTICE.md`, `docs/CHANGES-DETAIL-H1H5.md`, `docs/blueprint.md`.

---

## 📋 Daftar Isi

1. [Ringkasan: Apa yang Disalin vs Disesuaikan](#1-ringkasan-apa-yang-disalin-vs-disesuaikan)
2. [Versioning Strategy](#2-versioning-strategy) ⭐ **BARU**
3. [Yang DISALIN 100% (Jangan Dimodifikasi)](#3-yang-disalin-100-jangan-dimodifikasi)
4. [Yang DIMODIFIKASI (Wajib per Klien)](#4-yang-dimodifikasi-wajib-per-klien)
5. [Data Readiness Assessment](#5-data-readiness-assessment) ⭐ **BARU**
6. [Yang DIBANGUN BARU (Hanya Kalau Perlu)](#6-yang-dibangun-baru-hanya-kalau-perlu)
7. [Proses Onboarding Klien Baru (7 Tahap)](#7-proses-onboarding-klien-baru-7-tahap)
8. [Update & Patch Klien Existing](#8-update--patch-klien-existing) ⭐ **BARU**
9. [Exit & Handover Strategy](#9-exit--handover-strategy) ⭐ **BARU**
10. [Hal yang TIDAK Disalin (Wajib Baru)](#10-hal-yang-tidak-disalin-wajib-baru)
11. [Checklist Sebelum Menyalin ke Klien Baru](#11-checklist-sebelum-menyalin-ke-klien-baru)
12. [Estimasi Onboarding Klien Baru](#12-estimasi-onboarding-klien-baru)
13. [Yang Boleh Dihilangkan (Feature Flag, Bukan Fork)](#13-yang-boleh-dihilangkan-feature-flag-bukan-fork)
14. [Yang WAJIB Ada (Meski Klien Kecil)](#14-yang-wajib-ada-meski-klien-kecil)
15. [Slogan](#15-slogan)

---

## 1. Ringkasan: Apa yang Disalin vs Disesuaikan

| Kategori                                                                             | Aksi                                       | Porsi |
| ------------------------------------------------------------------------------------ | ------------------------------------------ | ----- |
| **Core Engine** (auth, event bus, state machine, rule engine, cycle handler, device) | ✅ **Salin 100%**                          | 15%   |
| **Backend Framework** (config, settings, DRF, ASGI, Celery, logging)                 | ✅ **Salin 100%**                          | 10%   |
| **Garment Plugin** (bundle, routing, rework, scrap, WC, allocator)                   | ✅ **Salin 100%**                          | 20%   |
| **Integrasi Odoo** (adapter, transport, task, 4 TX contract)                         | ✅ **Salin 100%**                          | 15%   |
| **Frontend v3** (React, integration engine, 47 MODE real)                            | ✅ **Salin 100%**                          | 20%   |
| **Artefak Deploy** (Docker, Nginx, SSL, backup)                                      | ✅ **Salin 100%**                          | 5%    |
| **Dokumentasi** (blueprint, UAT, onboarding, runbook)                                | ⚠️ **Salin + adaptasi**                    | 5%    |
| **Master Data** (Product, BOM, Partner, UoM, dll)                                    | ❌ **Jangan salin** — sync dari Odoo klien | 0%    |
| **Config Klien** (env, lokasi, UoM, tax, user)                                       | ❌ **Wajib baru** — spesifik klien         | 10%   |
| **Modul Tambahan** (kalau klien punya kebutuhan khusus)                              | ❌ **Bangun baru**                         | 0–20% |

---

## 2. Versioning Strategy ⭐ BARU

### 2.1 Prinsip

**Klien baru ≠ fork. Klien baru = instance dari codebase yang sama, dengan versi core yang tercatat.**

Kalau ada bug di core → fix **sekali** di codebase utama → deploy ke semua klien. **Jangan** fork per klien.

### 2.2 Core Version

**File:** `django_app/config/settings.py`

```python
# Versioning
CORE_VERSION = "1.0.0"           # SemVer: MAJOR.MINOR.PATCH
CORE_BUILD = "2026-10-12"        # tanggal build
CLIENT_ID = env("CLIENT_ID", default="dev")  # 'klien-a', 'klien-b', dst
```
````

**Format SemVer:**

- **MAJOR** — breaking change (migrasi besar, field dihapus)
- **MINOR** — fitur baru (backward compatible)
- **PATCH** — bug fix

### 2.3 Tabel Versi Klien

**File:** `docs/CLIENT-VERSIONS.md`

| Klien   | CORE_VERSION | CORE_BUILD | Deployment | Status         | Catatan                |
| ------- | ------------ | ---------- | ---------- | -------------- | ---------------------- |
| Klien A | 1.0.0        | 2026-10-12 | 2026-10-15 | ✅ Live        | Pilot awal             |
| Klien B | 1.0.0        | 2026-10-12 | 2026-10-20 | ✅ Live        | Beda alur (fast-track) |
| Klien C | 1.1.0        | 2026-10-25 | 2026-11-01 | 🔄 Rolling     | Multi-plant            |
| Dev     | main (HEAD)  | —          | —          | 🔧 Development | —                      |

**Update setiap kali:**

- Klien baru onboard → tambah baris
- Core update → update kolom `CORE_VERSION` semua klien yang di-update

### 2.4 Kebijakan Update

| Tipe Update            | Klien Dapat Notifikasi  | Wajib Update?          |
| ---------------------- | ----------------------- | ---------------------- |
| **MAJOR** (breaking)   | ✅ +3 bulan sebelumnya  | ⚠️ Terjadwal           |
| **MINOR** (fitur baru) | ✅ +2 minggu sebelumnya | ❌ Opsional            |
| **PATCH** (bug fix)    | ✅ Langsung             | ✅ Ya (untuk keamanan) |
| **Security patch**     | ✅ Instan               | ✅ **Segera**          |

### 2.5 Git Tag

Setiap rilis core:

```bash
git tag -a v1.0.0 -m "Release 1.0.0 — stable core"
git push --tags
```

Klien A, B deploy dari tag `v1.0.0`.
Klien C deploy dari tag `v1.1.0`.

**Jangan pakai branch `main` di produksi** — selalu pakai tag stabil.

---

## 3. Yang DISALIN 100% (Jangan Dimodifikasi)

### 3.1 Backend Core (Jangan Disentuh)

```
django_app/
├── config/                    # settings, urls, asgi, celery, logging, middleware
├── core/                      # 100% salin
│   ├── auth/                  # User, Role (7 role + PURCHASING)
│   ├── event_bus/
│   ├── state_machine/
│   ├── rule_engine/
│   ├── cycle_handler/
│   ├── device_profile/
│   ├── audit/
│   └── idempotency/
├── apps_industry/garment/     # 100% salin (plugin garmen)
│   ├── models/                # 15 model
│   ├── services/              # 11 service
│   ├── api/                   # views, urls, resources, actions, schema, chatter, settings
│   └── management/commands/   # seed_demo_bundles, seed_benchmark_data
├── integrations/
│   ├── erp_sync/              # 100% salin (adapter + transport + task)
│   ├── printing/              # ESC/POS
│   ├── wa_bot/                # WA gateway
│   └── ai/                    # AI stub
└── trace_bridge/              # FastAPI trace
```

**Alasan:** Engine generik — sudah diuji di 2 klien (A + B), stabil, portabel.

### 3.2 Frontend Core (Jangan Disentuh)

```
frontend_app_v2/
├── src/
│   ├── app/                   # nav-config, menu-config, RoleRoute, RootRoute, layouts
│   ├── core/                  # useDeviceProfile, useWebSocket
│   ├── integrations/          # api-client, offline-queue, use-offline-sync,
│   │                          #   ws-chatter, device-binding, conflict-plan
│   ├── lib/                   # action-runner, chatter-merge, sync-actions,
│   │                          #   state-display, feedback, tokens, uuid, dll
│   ├── types/                 # API types
│   ├── api/                   # _adapter.ts + 47 real adapter
│   ├── hooks/                 # useApiClient, useAuth, useDeviceMode, dll
│   ├── components/            # atoms, molecules, organisms
│   ├── pages/                 # 36 halaman
│   ├── styles/tailwind.css    # LOCKED md5
│   ├── App.tsx
│   └── main.tsx
├── tests/                     # unit + live
├── package.json
├── vite.config.ts
└── tsconfig.json
```

**Alasan:** Integration engine (12 sabuk) sudah matang. Frontend shell Odoo-style konsisten.

### 3.3 Artefak Deploy (Jangan Disentuh)

```
docker-compose.yml
docker-compose.prod.yml
django_app/Dockerfile
django_app/Dockerfile.prod
django_app/requirements.txt
frontend_app_v2/Dockerfile
nginx/nginx.conf
nginx/conf.d/mes.conf
scripts/generate-ssl.sh
scripts/backup.sh
scripts/restore.sh
.env.prod.example
.gitignore
```

**Alasan:** Production-ready. Cukup ubah `.env.prod` per klien.

### 3.4 Dokumentasi (Salin + Adaptasi)

```
django_app/docs/
├── blueprint.md               # ⚠️ Update nama project + client info
├── curent_project.json        # ⚠️ Reset status ke "fresh client"
├── integration-config.md      # ⚠️ Update per klien (env, lokasi)
├── known-limitations.md       # ✅ Salin as-is
├── onboarding-klien-baru.md   # ✅ Salin as-is
├── ops-readiness-audit.md     # ✅ Salin as-is
├── perf-benchmark.md          # ✅ Salin as-is
├── README-index.md            # ✅ Salin as-is
├── runbook-operasional.md     # ⚠️ Update kontak darurat
├── trace-bridge.md            # ✅ Salin as-is
└── uat-checklist.md           # ⚠️ Update nama klien
```

---

## 4. Yang DIMODIFIKASI (Wajib per Klien)

### 4.1 Konfigurasi Klien (`.env.prod`)

**File:** `.env.prod`

| Variabel                      | Nilai Klien Baru                      |
| ----------------------------- | ------------------------------------- |
| `CLIENT_ID`                   | `klien-b` ⭐ **BARU**                 |
| `DJANGO_SECRET_KEY`           | Generate baru: `openssl rand -hex 32` |
| `DJANGO_ALLOWED_HOSTS`        | `mes.klien-b.com`                     |
| `DB_*` + `POSTGRES_*`         | Database baru                         |
| `ODOO_URL`                    | `https://odoo.klien-b.com`            |
| `ODOO_DB`                     | `klien_b_db`                          |
| `ODOO_USER`                   | `api_bot@klien-b.com`                 |
| `ODOO_API_KEY`                | API key dari Odoo klien               |
| `ODOO_LOCATION_WIP_ID`        | ID dari Odoo klien                    |
| `ODOO_LOCATION_PRODUCTION_ID` | ID dari Odoo klien                    |
| `ODOO_LOCATION_FG_ID`         | ID dari Odoo klien                    |
| `ODOO_LOCATION_SCRAP_ID`      | ID dari Odoo klien                    |
| `ODOO_UOM_ID`                 | ID UoM PCS dari Odoo klien            |
| `CORS_ALLOWED_ORIGINS`        | `https://mes.klien-b.com`             |
| `CSRF_TRUSTED_ORIGINS`        | `https://mes.klien-b.com`             |
| `DOMAIN`                      | `mes.klien-b.com`                     |
| `LETSENCRYPT_EMAIL`           | Email PIC klien                       |
| `VITE_API_BASE_URL`           | `https://mes.klien-b.com/api/v1`      |
| `VITE_WS_URL`                 | `wss://mes.klien-b.com/ws`            |
| `RECONCILIATION_ALERT_WA_TO`  | Nomor WA PIC klien                    |

### 4.2 Branding Frontend (Opsional)

**File:** `frontend_app_v2/src/app/config.ts`

```typescript
export const APP_CONFIG = {
  appName: "MES Klien B",
  appShortName: "MES-B",
  primaryColor: "oklch(...)",
  logo: "/logo-klien-b.svg",
};
```

⚠️ `tailwind.css` md5 LOCKED — jangan ubah tanpa rebuild token.

### 4.3 Company Profile (Database)

- `/admin/core_auth/...` → buat user owner
- Login owner → `/settings/company` → isi nama PT, alamat, NPWP
- Atau via migration data-only

### 4.4 Role & User (Database)

**Setup pertama:**

1. `python manage.py createsuperuser` — buat owner
2. Login → `/settings/users` → buat:
   - Admin (1–2 user)
   - Supervisor (2–3 user)
   - QC (2–3 user)
   - Purchasing (1 user)
   - Inventory (1 user)
   - Operator: **tidak perlu user** — pakai device binding + kode operator

### 4.5 Master Data (Sync dari Odoo) — **BACA §5 DULU**

⚠️ **Jangan sync sebelum Odoo klien lulus Data Readiness Assessment (§5).**

---

## 5. Data Readiness Assessment ⭐ BARU

**Tujuan:** Cegah onboarding gagal karena data Odoo klien kacau.

### 5.1 Checklist Odoo Klien (Wajib Lulus Sebelum Sync)

| #   | Item                       | Kriteria Lulus                                                                          | Cek |
| --- | -------------------------- | --------------------------------------------------------------------------------------- | --- |
| 1   | **Product master lengkap** | Semua produk yang akan diproduksi punya kode + nama + UoM                               | ☐   |
| 2   | **UoM konsisten**          | Semua produk pakai UoM yang sama untuk kategori yang sama (PCS, M, KG)                  | ☐   |
| 3   | **BOM lengkap**            | Setiap produk jadi punya BOM dengan komponen + qty per unit                             | ☐   |
| 4   | **BOM tidak siklik**       | Tidak ada BOM yang jadi bahan dirinya sendiri                                           | ☐   |
| 5   | **Lokasi gudang benar**    | 4 lokasi ada: WIP (internal), Production (production), FG (internal), Scrap (inventory) | ☐   |
| 6   | **Partner terisi**         | Semua customer/vendor punya nama + (email/phone opsional)                               | ☐   |
| 7   | **User API siap**          | User `api_bot@klien` dengan hak baca/tulis terbatas sudah dibuat                        | ☐   |
| 8   | **Journal ada**            | Minimal 1 journal tipe sale (untuk invoice)                                             | ☐   |
| 9   | **Tax config**             | PPN 11% ada (atau sesuai kebutuhan klien)                                               | ☐   |
| 10  | **Currency**               | IDR ter-set di company                                                                  | ☐   |

### 5.2 Keputusan: Lanjut atau Tunda?

| Kondisi         | Keputusan                                               |
| --------------- | ------------------------------------------------------- |
| **10/10 lulus** | ✅ Lanjut onboarding                                    |
| **7–9 lulus**   | ⚠️ Lanjut dengan catatan — perbaiki paralel             |
| **< 7 lulus**   | 🛑 **TUNDA onboarding** — bantu klien rapikan Odoo dulu |

### 5.3 Siapa yang Bertanggung Jawab?

| Peran                      | Tugas                                |
| -------------------------- | ------------------------------------ |
| **Klien PIC (admin Odoo)** | Menyediakan data + akses Odoo        |
| **MES Dev**                | Verifikasi data, jalankan assessment |
| **MES Ops**                | Konfigurasi env + deploy             |
| **Klien Owner**            | Keputusan go/no-go                   |

**Aturan:** Kalau < 7 lulus, **MES tidak go-live**. Klien harus rapikan Odoo dulu. Ini **melindungi reputasi** — jangan sampai MES go-live dengan data kacau lalu dibilang "MES tidak berguna".

### 5.4 Kalau Odoo Klien Tidak Bisa Dirapikan

**Opsi:**

1. **Manual input di MES** — untuk data yang belum ada di Odoo (khusus 1-2 produk, jangan massal)
2. **Tunda go-live** — beri klien waktu rapikan Odoo
3. **Bantuan data cleanup** — jasa tambahan (billing terpisah)

**JANGAN** sync data kacau → MES kacau → reputasi rusak.

### 5.5 Cara Cek Cepat (Read-Only)

```bash
# Cek jumlah product + BOM
docker compose -f docker-compose.prod.yml exec django python manage.py shell -c "
from integrations.erp_sync.transport import get_transport
t = get_transport()
products = t.fetch_products()
boms = t.fetch_boms()
print(f'Products: {len(products)}, BOMs: {len(boms)}')
t.close()
"
```

Kalau `Products = 0` atau `BOMs = 0` → tunda onboarding.

---

## 6. Yang DIBANGUN BARU (Hanya Kalau Perlu)

### 6.1 Modul Tambahan

| Kebutuhan Klien       | Aksi                         | Estimasi          |
| --------------------- | ---------------------------- | ----------------- |
| Multi-plant           | Tambah `Site`/`Plant` model  | 3–5 hari          |
| COGS per order (H4.4) | Sudah ada di roadmap H4      | Sesuai H4         |
| Export Excel          | Sudah ada di roadmap H4.8    | Sesuai H4         |
| Multi-currency        | Tambah `Currency` conversion | 2–3 hari          |
| Accurate (bukan Odoo) | Bikin `AccurateAdapter`      | 3–5 hari          |
| AI Agent (Fase J)     | Sudah ada dokumen terpisah   | Sesuai roadmap AI |
| Workflow khusus       | Konfigurasi di rule engine   | 1–2 hari          |

**Prinsip:** Bangun baru hanya kalau perlu. **Jangan redesign core.**

### 6.2 Customisasi Kecil

| Custom                 | File                                  | Estimasi |
| ---------------------- | ------------------------------------- | -------- |
| Ganti nama app sidebar | `src/app/nav-config.ts`               | 30 menit |
| Ganti warna tema       | `src/app/config.ts`                   | 1 jam    |
| Ganti logo             | `frontend_app_v2/public/logo.svg`     | 10 menit |
| Urutan menu TopBar     | `src/app/menu-config.ts`              | 30 menit |
| Field baru di Product  | `master/models.py` + migration        | 2–3 jam  |
| Endpoint baru          | `master/api.py`                       | 3–5 jam  |
| Halaman baru           | `src/pages/` + route + adapter        | 4–8 jam  |
| Report baru            | `integrations/erp_sync/monitoring.py` | 4–6 jam  |

---

## 7. Proses Onboarding Klien Baru (7 Tahap)

**Referensi:** `django_app/docs/onboarding-klien-baru.md`

| #     | Tahap                                                                     | Estimasi         | Output                        | ⚠️ Gate            |
| ----- | ------------------------------------------------------------------------- | ---------------- | ----------------------------- | ------------------ |
| **0** | Pre-flight + **Data Readiness Assessment**                                | 1 hari (paralel) | Checklist + verdict Odoo      | **Wajib lulus §5** |
| **1** | Setup Odoo (user API, 4 lokasi, UoM, journal)                             | 30 menit         | ID lokasi + API key           | —                  |
| **2** | Sync master data (9 entity)                                               | 30 menit         | `Product.odoo_id > 0`         | —                  |
| **3** | Konfigurasi `.env.prod` + `CLIENT_ID`                                     | 20 menit         | Placeholder kosong            | —                  |
| **4** | Deploy (Docker + SSL + migrate)                                           | 30 menit         | Health check 200              | —                  |
| **5** | Seed data awal (opsional demo)                                            | 10 menit         | Bundle demo                   | —                  |
| **6** | UAT (5 role walkthrough)                                                  | 90 menit         | Sign-off                      | —                  |
| **7** | Go-live (backup + monitoring + kontak) + **daftar di CLIENT-VERSIONS.md** | 30 menit         | Serah terima + versi tercatat | **Update §2.3**    |

**Total:** ~1 hari kerja efektif.

---

## 8. Update & Patch Klien Existing ⭐ BARU

**Tujuan:** Update klien yang sudah live tanpa ganggu produksi.

### 8.1 Prinsip

- **1 core, banyak klien** — fix sekali, deploy ke semua
- **Rolling update** — klien satu per satu, bukan serentak
- **Maintenance window** — 21:00–23:00 WIB (di luar shift produksi)
- **Rollback plan** — siap restore kalau gagal

### 8.2 Klasifikasi Update

| Tipe      | Isi             | Test Wajib            | Downtime    | Notifikasi             |
| --------- | --------------- | --------------------- | ----------- | ---------------------- |
| **PATCH** | Bug fix kecil   | Smoke test + 1 role   | < 5 menit   | 1 jam sebelum          |
| **MINOR** | Fitur baru      | Full UAT checklist    | 15–30 menit | 2 minggu sebelum       |
| **MAJOR** | Breaking change | Full UAT + regression | 1–2 jam     | 3 bulan + migrasi plan |

### 8.3 Prosedur Update (per klien)

```bash
# 1. Persiapan (H-1)
git checkout v1.0.1              # tag rilis baru
docker compose -f docker-compose.prod.yml build --pull

# 2. Backup (H-0, sebelum maintenance)
./scripts/backup.sh
ls -lh ./backups/postgres/       # verifikasi file terbaru ada

# 3. Maintenance window (21:00 WIB)
git pull                          # tarik kode baru (bila pakai branch)
# ATAU: git checkout v1.0.1
docker compose -f docker-compose.prod.yml up -d --force-recreate django celery_worker celery_beat
# Migrasi otomatis jalan via command service django

# 4. Smoke test
curl -fsS https://<domain>/api/health/           # 200
curl -fsS https://<domain>/api/schema/ | head    # 200
# Login 1x (via browser atau curl) → dashboard muncul

# 5. Update CLIENT-VERSIONS.md
# Klien A: 1.0.0 → 1.0.1

# 6. Notifikasi klien
# WA: "Update selesai, sistem normal kembali"
```

### 8.4 Rollback Plan

```bash
# Kalau update gagal:

# 1. Cek log error
docker compose -f docker-compose.prod.yml logs --tail=200 django

# 2. Rollback kode
git checkout v1.0.0              # kembali ke versi sebelumnya
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d --force-recreate django celery_worker celery_beat

# 3. Kalau migrasi bermasalah → restore backup
./scripts/restore.sh --list
./scripts/restore.sh --yes ./backups/postgres/<file>.dump
# ⚠️ HANYA setelah konfirmasi tertulis dari klien

# 4. Laporkan insiden
```

### 8.5 Checklist Update

**Sebelum:**

- [ ] Tag rilis sudah di-push (`v1.0.1`)
- [ ] Test di dev hijau (pytest + frontend test)
- [ ] Test di staging hijau (end-to-end 1 skenario)
- [ ] Backup klien sudah jalan
- [ ] Klien sudah dinotifikasi
- [ ] Rollback plan siap

**Saat maintenance:**

- [ ] Backup manual (double safety)
- [ ] Build image baru
- [ ] Recreate container
- [ ] Cek migrasi sukses (`migrate --check` → 0)
- [ ] Smoke test (health + login + 1 aksi)

**Setelah:**

- [ ] Update `CLIENT-VERSIONS.md`
- [ ] Monitor error 24 jam (Sentry + log)
- [ ] Notifikasi klien "normal kembali"
- [ ] Cek feedback klien 1 minggu

---

## 9. Exit & Handover Strategy ⭐ BARU

**Tujuan:** Kalau klien berhenti berlangganan, handover data jelas — reputasi Anda aman.

### 9.1 Prinsip

**Data klien = milik klien.** Bukan milik Anda. Bukan hostage.

### 9.2 Kontrak Klien (Klausul Wajib)

- ✅ **Kepemilikan data:** Data produksi, order, inventory = milik klien
- ✅ **Hak export:** Klien bisa minta export kapan saja (CSV/Excel/dump)
- ✅ **Hak migrasi:** Klien bisa migrasi ke ERP lain (dokumentasi disediakan)
- ✅ **Retensi:** Data disimpan 30 hari setelah kontrak berakhir, lalu dihapus
- ✅ **Backup terakhir:** 1 dump database final saat handover

### 9.3 Prosedur Handover (Saat Klien Berhenti)

**Timeline: 30 hari sebelum penutupan**

| #   | Aktivitas                                                 | PIC          | Hari |
| --- | --------------------------------------------------------- | ------------ | ---- |
| 1   | Konfirmasi tertulis penutupan kontrak                     | Klien + Anda | H-30 |
| 2   | Generate export lengkap:                                  | Anda         | H-25 |
|     | - Master: Product, BOM, Partner, UoM, Location            |              |      |
|     | - Transaksi: Order, WO, Bundle, Invoice                   |              |      |
|     | - Config: Role, User, Settings                            |              |      |
| 3   | **Database dump final** (SQL + media tar)                 | Anda         | H-20 |
| 4   | Dokumentasi migrasi ke Odoo/ERP lain                      | Anda         | H-15 |
| 5   | Serah terima file ke klien (via aman: SFTP/Google Drive)  | Anda + Klien | H-10 |
| 6   | Verifikasi klien sudah terima + restore sukses (opsional) | Klien        | H-5  |
| 7   | Matikan instance MES klien                                | Anda         | H-0  |
| 8   | Hapus data setelah 30 hari (retensi)                      | Anda         | H+30 |

### 9.4 Format Export

**A. Master Data (CSV)**

- `products.csv` — code, name, category, uom, sale_price, cost_price
- `partners.csv` — name, type (customer/vendor), email, phone, address
- `boms.csv` — parent product, component, qty
- `uoms.csv`, `locations.csv`, `taxes.csv`

**B. Transaksi (CSV)**

- `orders.csv` — order_no, customer, deadline, state
- `order_lines.csv` — order_no, product, qty, price
- `work_orders.csv` — wo_no, order, state, qty_planned, qty_done
- `bundles.csv` — bundle_code, wo, size, qty, state
- `bundle_events.csv` — bundle_code, event_type, ts, actor, payload
- `invoices.csv` — inv_no, order, amount, state

**C. Config (JSON)**

- `settings.json` — company, taxes, currencies, printers
- `roles_permissions.json` — role + akses

**D. Database Dump (SQL)**

- `klien_b_YYYYMMDD.dump` — full PostgreSQL dump
- `media_YYYYMMDD.tar.gz` — foto, logo, dll

### 9.5 Dokumentasi Migrasi

**File:** `docs/migration-to-odoo.md` (template)

Berisi:

- Cara import CSV ke Odoo (Product, Partner, SO)
- Mapping field MES → Odoo
- Catatan: apa yang tidak bisa di-import (mis. BundleEvent — di-export sebagai CSV arsip saja)

### 9.6 Checklist Handover

- [ ] Konfirmasi tertulis penutupan kontrak
- [ ] Export 4 kategori file (master, transaksi, config, dump)
- [ ] Dokumentasi migrasi (opsional, tapi disarankan)
- [ ] Serah terima via kanal aman (SFTP/Google Drive terenkripsi)
- [ ] Verifikasi klien terima (bukti tanda terima)
- [ ] Backup final disimpan 30 hari (retensi)
- [ ] Hapus data klien setelah retensi
- [ ] Update `CLIENT-VERSIONS.md` → status "terminated"

### 9.7 Slogan Exit

> **Data klien = milik klien. Handover bersih, reputasi aman, referensi tetap positif.**

---

## 10. Hal yang TIDAK Disalin (Wajib Baru)

| Data                            | Alasan                      |
| ------------------------------- | --------------------------- |
| Database klien lama             | Data spesifik, bukan schema |
| User + Role                     | Struktur organisasi sendiri |
| Master data (Product, BOM, dst) | Sync dari Odoo klien        |
| Log + AuditLog                  | Data historis               |
| SyncRecord                      | Status sync spesifik        |
| Bundle + BundleEvent            | Data produksi               |
| Seed demo                       | Hapus sebelum go-live       |
| Sentry DSN                      | Kredensial monitoring klien |
| WA API key                      | Nomor WA klien              |
| Node_modules / venv / dist      | Regenerate via build        |

---

## 11. Checklist Sebelum Menyalin ke Klien Baru

**Persiapan (1 hari sebelum):**

- [ ] Clone repo ke direktori baru: `git clone <repo> klien-b`
- [ ] Hapus `.env` lama
- [ ] Hapus folder `postgres_data/`, `logs/`, `runs/`
- [ ] Reset `frontend_app_v2/dist/`
- [ ] Hapus `django_app/docs/curent_project.json` → reset
- [ ] Update `frontend_app_v2/docs/current-project.json` → reset
- [ ] Update `package.json` (nama project)
- [ ] Update `django_app/config/settings.py` (nama project + `CLIENT_ID`)

**Customisasi (30 menit):**

- [ ] Copy `.env.prod.example` → `.env.prod`
- [ ] Isi semua placeholder + `CLIENT_ID`
- [ ] Update `src/app/config.ts` (appName, logo)
- [ ] Taruh logo di `frontend_app_v2/public/`

**Data Readiness (§5):**

- [ ] Assessment Odoo klien (10 poin)
- [ ] Verdict lulus/tunda
- [ ] Kalau tunda → komunikasi ke klien

**Build & Deploy (30 menit):**

- [ ] `docker compose -f docker-compose.prod.yml build`
- [ ] `./scripts/generate-ssl.sh`
- [ ] `docker compose -f docker-compose.prod.yml up -d`
- [ ] `python manage.py createsuperuser`
- [ ] `curl -fsS https://<domain>/api/health/` → 200

**Sync & Setup (1 jam):**

- [ ] Sync 9 master dari Odoo klien
- [ ] Verifikasi `Product.odoo_id > 0`
- [ ] Buat user + role di `/settings/users`
- [ ] Bind device untuk operator
- [ ] Generate operator code untuk operator HP

**UAT (90 menit):**

- [ ] `docs/uat-checklist.md` — 5 role walkthrough
- [ ] Sign-off

**Pasca Deploy:**

- [ ] Tambah baris di `docs/CLIENT-VERSIONS.md`
- [ ] Backup harian sudah jalan
- [ ] Monitoring (Sentry) aktif
- [ ] Kontak darurat terisi

---

## 12. Estimasi Onboarding Klien Baru

| Skenario                     | Durasi     | Biaya   |
| ---------------------------- | ---------- | ------- |
| Klien identik dengan Klien A | 1 hari     | Minimal |
| Klien beda alur sedikit      | 2–3 hari   | Sedang  |
| Klien beda device            | 3–5 hari   | Sedang  |
| Klien butuh modul baru       | 1–2 minggu | Lebih   |
| Klien butuh adapter ERP lain | 1 minggu   | Lebih   |
| Klien butuh AI Agent         | 2–3 bulan  | Besar   |

**Range realistis:** 1 hari – 1 minggu.

---

## 13. Yang Boleh Dihilangkan (Feature Flag, Bukan Fork)

⚠️ **PENTING:** Skip = **matikan fitur** (feature flag), **BUKAN hapus kode**.

### 13.1 Prinsip

- **Jangan fork codebase** per klien
- **Jangan hapus file** untuk klien kecil
- **Pakai feature flag** di `.env.prod` + settings

### 13.2 Contoh Feature Flag

**File:** `django_app/config/settings.py`

```python
# Feature flags per klien
FEATURE_ROUTING_DAG_EDITOR = env_bool('FEATURE_ROUTING_DAG_EDITOR', True)
FEATURE_AI_HITL = env_bool('FEATURE_AI_HITL', True)
FEATURE_TRACE_BRIDGE = env_bool('FEATURE_TRACE_BRIDGE', True)
FEATURE_RECONCILIATION = env_bool('FEATURE_RECONCILIATION', True)
```

**File:** `.env.prod` (klien sederhana)

```bash
# Klien kecil — matikan fitur lanjutan
FEATURE_ROUTING_DAG_EDITOR=false
FEATURE_AI_HITL=false
FEATURE_TRACE_BRIDGE=false
FEATURE_RECONCILIATION=false
```

**Di view/page:**

```python
if not settings.FEATURE_ROUTING_DAG_EDITOR:
    return HttpResponseNotAllowed(['GET'])  # hanya read-only
```

### 13.3 Modul yang Boleh di-Flag

| Modul                 | Default | Boleh Off?        | Catatan               |
| --------------------- | ------- | ----------------- | --------------------- |
| Routing DAG editor    | ON      | ⚠️ Opsional       | Read-only masih jalan |
| AI HITL               | ON      | ✅ Boleh off      | Untuk klien kecil     |
| Trace Bridge          | ON      | ⚠️ Opsional       | Debug tool            |
| Reconciliation report | ON      | ⚠️ Opsional       | Audit tool            |
| Multi-device          | ON      | ❌ **Jangan off** | Fundamental           |
| Offline-first         | ON      | ❌ **Jangan off** | Fundamental           |
| Rework loop           | ON      | ❌ **Jangan off** | Fundamental           |
| Two-stage sync        | ON      | ❌ **Jangan off** | Fundamental           |

**Prinsip:** Skip yang opsional, jangan skip yang fundamental.

---

## 14. Yang WAJIB Ada (Meski Klien Kecil)

| Fitur                         | Kenapa Wajib                         |
| ----------------------------- | ------------------------------------ |
| Scan QR bundle                | Inti MES — tanpa ini bukan MES       |
| Login operator (kode 4 digit) | Operator tidak boleh ribet           |
| Device binding                | Kiosk + HP harus bisa dipakai        |
| Offline-first                 | Jaringan lantai produksi sering mati |
| Auth & Role                   | Keamanan data                        |
| Audit log                     | Traceability                         |
| Idempotency sync              | Cegah duplikasi stok                 |
| Two-stage sync (WIP + FG)     | Stok akurat                          |
| Docker deploy                 | Portable                             |
| Backup harian                 | Data safety                          |

---

## 15. Slogan

> **Klien baru = 80% reuse (engine stabil) + 20% custom (config + modul). Versioning tertata, data readiness diverifikasi, update rolling, exit bersih. Jangan fork codebase — pakai feature flag. Onboarding 1 hari – 1 minggu, tergantung kompleksitas.**

---

## 📌 Ringkasan Perubahan v2.0

| #       | Section                                            | Status      |
| ------- | -------------------------------------------------- | ----------- |
| **§2**  | Versioning Strategy (SemVer, tabel klien, git tag) | ⭐ BARU     |
| **§5**  | Data Readiness Assessment (10 poin Odoo)           | ⭐ BARU     |
| **§8**  | Update & Patch Klien Existing (rolling, rollback)  | ⭐ BARU     |
| **§9**  | Exit & Handover Strategy (data milik klien)        | ⭐ BARU     |
| **§13** | Feature Flag (bukan fork)                          | ⭐ DIREVISI |

**Dokumen ini mengikat. Update jika ada klien baru yang butuh custom unik — tapi update di codebase utama, bukan fork.**

````

---

## ✅ Simpan & Verifikasi

```bash
cd odoo-garmen-project
nano docs/NEW-CLIENT-TEMPLATE.md
# paste isi di atas → Ctrl+O → Enter → Ctrl+X

# Verifikasi
wc -l docs/NEW-CLIENT-TEMPLATE.md
ls -la docs/
````

---

## 🎯 Ringkasan 4 Perbaikan Kritis (Sesuai Feedback)

| #         | Sebelum                       | Sesudah                                                                         |
| --------- | ----------------------------- | ------------------------------------------------------------------------------- |
| **1**     | Tidak ada versioning          | **§2 Versioning Strategy** — SemVer + tabel klien + git tag                     |
| **2**     | Tidak ada update strategy     | **§8 Update & Patch Klien Existing** — rolling + rollback + maintenance window  |
| **3**     | Sync diserahkan manual        | **§5 Data Readiness Assessment** — 10 poin checklist Odoo + verdict lulus/tunda |
| **4**     | Tidak ada exit strategy       | **§9 Exit & Handover** — data milik klien + timeline 30 hari + format export    |
| **Bonus** | §9 "boleh dihilangkan" ambigu | **§13 Feature Flag** — matikan fitur, bukan fork                                |

**Estimasi dokumen naik dari 85% → 95%.** Sisanya 5% = pengalaman lapangan.

**Sekarang onboarding klien pertama teruji, update dokumen jika ada temuan baru.**
