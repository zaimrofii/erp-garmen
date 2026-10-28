# 01 — Environment UAT

> **Berlaku:** 2026-10-27 · **Versi:** 1.0
> **Prinsip:** Staging menyerupai produksi. Jangan UAT di produksi.

---

## 1. Topologi

```
┌─────────────────────────────┐     ┌─────────────────────────────┐
│ STAGING MES (VPS 4GB)       │────▶│ ODOO STAGING (klien A/B)    │
│ docker-compose.yml (dev)    │     │ copy dari Odoo prod         │
│ uat.mes-klien-a.local       │     │ tanpa akses internet publik │
└─────────────────────────────┘     └─────────────────────────────┘
         ▲
         │ SSH / VPN
    Tester (lokal)
```

- **BUKAN** `docker-compose.prod.yml` — staging pakai dev compose + self-signed SSL.
- 1 environment per klien (data tidak campur). Klien B spin up terpisah setelah Sesi 1 klien A hijau.
- **Odoo staging wajib** untuk Sesi 2 & 4. Sesi 1/3/5/6 boleh jalan dengan `ERP_ADAPTER=null`.

---

## 2. Prasyarat

| Item | Cek |
|---|---|
| Docker 24+ & Docker Compose v2 | `docker --version` |
| bun 1.4.2 (frontend test) | `bun --version` |
| SSH ke staging + VPN | `ssh uat@staging` |
| Akses Odoo staging (admin) | `curl https://odoo-staging/web/database/selector` |
| Kunci API LLM (DeepSeek) | `AI_LLM_DEEPSEEK_API_KEY` |
| Domain internal + self-signed SSL | `uat.mes-klien-a.local` |

---

## 3. Setup (1 jam)

```bash
# 1. Clone & checkout
git clone <repo> && cd odoo-garmen-project
git checkout demo-ready   # @ 980fe52 untuk AI Agent
# atau: git checkout main @ 201e306 untuk backend/frontend

# 2. Env staging
cp .env.uat.example .env
# edit .env — lihat §4

# 3. Up
docker compose up -d
docker compose ps          # semua service hijau

# 4. Migrate + seed
docker compose exec django python manage.py migrate
docker compose exec django python manage.py seed_big_test
docker compose exec django python manage.py aggregate_daily

# 5. Verifikasi (lihat §5)
```

**Reset penuh:**
```bash
docker compose down -v && docker compose up -d
docker compose exec django python manage.py migrate
docker compose exec django python manage.py seed_big_test
docker compose exec django python manage.py aggregate_daily
```

---

## 4. Env Wajib (`.env` staging)

| Var | Nilai UAT | Catatan |
|---|---|---|
| `DJANGO_DEBUG` | `true` | staging, bukan prod |
| `ERP_ADAPTER` | `odoo` | **wajib untuk Sesi 2 & 4**; `null` hanya Sesi 1/3/5 |
| `ODOO_URL` / `ODOO_DB` / `ODOO_USER` / `ODOO_API_KEY` | dari Odoo staging | `health_check()` harus OK |
| `ODOO_LOCATION_WIP_ID` / `_PRODUCTION_ID` / `_FG_ID` / `_SCRAP_ID` / `ODOO_UOM_ID` | ID Odoo staging | dari `integration-config.md` §1.3 |
| `ODOO_PICKING_TYPE_INTERNAL_ID` | ID picking internal | untuk stock transfer |
| `ODOO_PAYMENT_JOURNAL_ID` | kosong (opsional) | Odoo pilih sendiri |
| `AI_AGENT_ENABLED` | `true` | Sesi 5 |
| `AI_AGENT_TOOLS_ENABLED` | `true` | Sesi 5 |
| `AI_LLM_TEMPERATURE` | `0` | **wajib** — stabilitas demo |
| `AI_LLM_DEEPSEEK_API_KEY` | kunci | biaya ~$0.02/sesi |
| `WA_BACKEND` | `mock` | Sesi 5 WA |
| `PRINTER_BACKEND` | `mock` | print test |

**Verifikasi env terbaca:**
```bash
docker compose exec django python -c "
from django.conf import settings
print('ERP_ADAPTER:', settings.ERP_ADAPTER)
print('AI_TEMP:', settings.AI_CONFIG['llm']['temperature'])
print('AI_TOOLS:', settings.AI_AGENT_TOOLS_ENABLED)
"
```

---

## 5. Verifikasi Sebelum Sesi 0

Semua harus ✅:

- [ ] `docker compose ps` — 6 service hijau (`django`, `celery_worker`, `celery_beat`, `postgres`, `redis`, `nginx`)
- [ ] `curl /api/health/` → 200 `{status:"ok"}`
- [ ] `/api/docs/` (Swagger) terbuka
- [ ] `migrate` bersih (0 unapplied)
- [ ] `seed_big_test` sukses + idempoten (run 2x → count sama)
- [ ] **Invariants A–E = 0, F=4** (diketahui):
  ```bash
  docker compose exec django python manage.py shell -c \
    "from ai_agent.data_access.invariants import check_all; print(check_all())"
  # harapan: {'A':0,'B':0,'C':0,'D':0,'E':0,'F':4}
  ```
- [ ] 7 akun role login OK (lihat `02-test-data.md` §3)
- [ ] Device binding minimal 1 (HP/kios/scanner)
- [ ] **Odoo `health_check()` OK** (`server_version=17.0`, bukan `erp_not_configured`)
- [ ] `logs/mes.jsonl` ada & terisi (sumber bukti)
- [ ] Frontend: `bun install` selesai (Recharts ada di `bun.lock`), `bun --bun run dev` render `/login`
- [ ] Trace bridge (opsional): `curl http://127.0.0.1:8765/_ai/trace/<id>` → JSON
- [ ] **Bukan** jendela 00:00–07:00 WIB (flake timezone aggregate/cost_tracker)

---

## 6. Akun & Device UAT

### 6.1 Akun 7 Role
Dibuat oleh `seed_big_test`. Kredensial lengkap di `02-test-data.md` §3.

| Role | Login | Dipakai di Sesi |
|---|---|---|
| admin | username+password | 1, 2, 4 |
| owner | username+password | 1, 4, 5, 6 |
| supervisor | username+password | 3, 4, 5, 6 |
| qc | username+password | 3 |
| operator | kode 4 digit | 3 |
| inventory | username+password | 2 |
| purchasing | username+password | 2 |

### 6.2 Device
- **Device 1 (HP)** — bind untuk operator (Sesi 3 offline test)
- **Device 2 (Kios/tablet)** — bind untuk QC (Sesi 3 rework)
- **Device 3 (scanner USB)** — opsional, bind untuk supervisor (Sesi 3 kanban)

Bind via `/settings/devices` atau `POST /api/v1/devices/bind`.

---

## 7. Reset Antar-Sesi

```bash
# Opsi A — reset penuh (bersih, lambat ~3 mnt)
docker compose down -v && docker compose up -d
docker compose exec django python manage.py migrate
docker compose exec django python manage.py seed_big_test
docker compose exec django python manage.py aggregate_daily

# Opsi B — reset seed saja (cepat ~30 dtk, data lain tetap)
docker compose exec django python manage.py seed_big_test  # idempoten
docker compose exec django python manage.py aggregate_daily
```

**Setelah reset, verifikasi invariants lagi** (§5). Jangan lanjut bila A–E ≠ 0.

---

## 8. Troubleshooting Cepat

| Gejala | Penyebab | Fix |
|---|---|---|
| `erp_not_configured` di Sesi 2 | `ERP_ADAPTER=null` | set `odoo` + restart `django celery_worker` |
| `stock.group_stock_manager` FAILED | tech debt Odoo | admin Odoo set grup untuk `api_bot` |
| AI chat 500 | `AI_LLM_DEEPSEEK_API_KEY` kosong | isi kunci + recreate django |
| AI jawaban bervariasi | `AI_LLM_TEMPERATURE=0.3` | set `0` + recreate |
| `bulk_create` lambat | seed jalan 2x bersamaan | tunggu selesai |
| Recharts error | `bun install` belum | `cd frontend_app_v2 && bun install` |
| Aggregate flake 00–07 WIB | timezone | jalankan UAT di luar jendela |
| 2 sesi pytest bersamaan | test-DB sama | 1 sesi pada satu waktu |
| `.env` berubah tak terbaca | container cache | `docker compose up -d --force-recreate django celery_worker celery_beat` |
| `frontend` 502 | build belum | `cd frontend_app_v2 && bun --bun run build` |

---

## 9. Referensi

| Dokumen | Kegunaan |
|---|---|
| `django_app/docs/integration-config.md` | Konfigurasi Odoo per klien (ID lokasi, UOM, journal) |
| `django_app/docs/runbook-operasional.md` | Operasional harian + troubleshooting |
| `02-test-data.md` | Seed, kredensial, invariants |
| `.env.example` / `.env.prod.example` | Template env |
| `current_project.json` `known_tech_debt` | Tech debt yang harus dicek |

---
