# Onboarding Klien Baru (Template Reusable)

Panduan **meng-onboard 1 klien baru** (B, C, D, …) ke instance MES Garmen sendiri:
1 instance MES = 1 database Odoo klien. Target: **selesai dalam 1 hari kerja**.

- Checklist UAT yang dijalankan di akhir proses: `django_app/docs/uat-checklist.md`.
- Detail per-variabel & per-lokasi Odoo: `django_app/docs/integration-config.md` (baca §1–§3).
- Operasional setelah live: `django_app/docs/runbook-operasional.md`.
- Hal yang memang belum ada (jangan dijanjikan ke klien): `django_app/docs/known-limitations.md`.

Ganti seluruh `<...>` di dokumen ini dengan nilai klien. Estimasi waktu per tahap:

| Tahap | Estimasi |
|---|---|
| 0. Pre-flight | 1 hari sebelum (paralel, tidak dihitung) |
| 1. Setup Odoo | 30 menit |
| 2. Sync master data | 30 menit |
| 3. Konfigurasi `.env.prod` | 20 menit |
| 4. Deploy | 30 menit |
| 5. Seed data | 10 menit |
| 6. UAT | 90 menit (lihat `django_app/docs/uat-checklist.md`) |
| 7. Go-live | 30 menit |

---

## 0. Pre-flight (1 hari sebelum)

| # | Item | Detail | Selesai |
|---|---|---|---|
| 0.1 | VPS siap | 4 vCPU / 8 GB RAM / 100 GB SSD; Docker + Compose plugin terpasang | ☐ |
| 0.2 | Domain | A record `<mes.klien-x.com>` → IP VPS (`dig +short <domain>` = IP VPS) | ☐ |
| 0.3 | Port 80/443 terbuka | firewall VPS mengizinkan ACME + HTTPS | ☐ |
| 0.4 | Odoo klien | **Punya klien sendiri** (produksi) atau disediakan MES → putuskan & catat di berita acara | ☐ |
| 0.5 | Akses Odoo | admin Odoo klien siap membuat user API + membaca ID lokasi | ☐ |
| 0.6 | PIC klien | nama, WA, email (untuk UAT & eskalasi); daftar peserta per role | ☐ |
| 0.7 | Peserta UAT | minimal: 1 operator, 1 QC, 1 supervisor, 1 admin/owner | ☐ |
| 0.8 | Perangkat | HP operator, tablet kios, barcode gun (uji di §UAT) | ☐ |

> **Keputusan penting**: bila klien memakai Odoo sendiri, pastikan **jaringan Odoo bisa
> diakses dari VPS** (bukan hanya dari jaringan kantor klien) — cek dengan
> `curl -sI https://<odoo-klien>` dari VPS.

---

## 1. Setup Odoo (30 menit)

| # | Langkah | Detail | Selesai |
|---|---|---|---|
| 1.1 | Buat **user API khusus** (bukan admin personal) | mis. `api_bot@klien-x.com`; login: `api_bot` | ☐ |
| 1.2 | Generate API key user tsb | Odoo → Preferences → Account Security → New API Key | ☐ |
| 1.3 | Set hak akses minimal | lihat tabel model+hak di `django_app/docs/integration-config.md` §2.2 | ☐ |
| 1.4 | Pastikan lokasi `stock.location` ada | `WH/Stok` (internal) · `Virtual Locations/Production` (usage `production`) · `WH/Finished Goods` (internal) · `Virtual Locations/Scrap` (usage `inventory`) | ☐ |
| 1.5 | Catat **ID** 4 lokasi tsb dari UI Odoo | Inventory → Configuration → Locations (kolom ID) | ☐ |
| 1.6 | Verifikasi UoM | cari `uom.uom` untuk **PCS/Units** (dev: `33`); catat id-nya | ☐ |
| 1.7 | Catat hasil ke lembar klien | `ODOO_LOCATION_PRODUCTION_ID`, `ODOO_LOCATION_FG_ID`, `ODOO_LOCATION_WIP_ID`, `ODOO_LOCATION_SCRAP_ID`, `ODOO_UOM_ID` | ☐ |
| 1.8 | Pastikan ada ≥1 journal bertipe sale | dipakai invoice draft (`django_app/docs/integration-config.md` §2.4) | ☐ |
| 1.9 | Uji kredensial dari VPS | `curl -s -X POST https://<odoo>/jsonrpc` + `common.login` (atau langsung ke tahap 2) | ☐ |

Referensi lengkap: `django_app/docs/integration-config.md` **§2 Setup Odoo (per klien)**.

---

## 2. Sync Master Data (30 menit)

Master data wajib terisi sebelum fitur apa pun berguna (rekonsiliasi & readiness
mencocokkan lewat `Product.odoo_id`). Urutan 9 entity ada di
`django_app/docs/integration-config.md` **§3.1** (products → boms → partners → locations → taxes →
uoms → warehouses → journals → currencies).

| # | Langkah | Perintah | Selesai |
|---|---|---|---|
| 2.1 | SSH ke VPS | `ssh <user>@<ip>` lalu `cd /opt/garmen` (lokasi project) | ☐ |
| 2.2 | Jalankan 9 task sync master | contoh: `docker compose -f docker-compose.prod.yml exec django python manage.py shell -c "from integrations.erp_sync.tasks_master import sync_master_products as t; print(t())"` — ulangi untuk `boms`, `partners`, `locations`, `taxes`, `uoms`, `warehouses`, `journals`, `currencies` | ☐ |
| 2.3 | Alternatif via HTTP | `POST /api/v1/sync/master/<entity>/` dengan sesi login (auth wajib) | ☐ |
| 2.4 | Verifikasi isi DB | `python manage.py shell -c "from master.models import Product, BOM, Partner, Location; print(Product.objects.count(), Product.objects.filter(odoo_id__isnull=False).count(), BOM.objects.count(), Partner.objects.count(), Location.objects.count())"` | ☐ |
| 2.5 | Kriteria lulus | `Product.objects.filter(odoo_id__isnull=False).count() > 0`, `BOM > 0`, `Location > 0`; produk tersisa tanpa `odoo_id` → cek `django_app/docs/integration-config.md` §6 | ☐ |
| 2.6 | (Opsional) audit di UI | `/settings/audit` harus **kosong** bila semua produk punya `odoo_id` | ☐ |

## 3. Konfigurasi Klien (`.env.prod`) — 20 menit

> Catatan §2: master sync juga terjadwal otomatis tiap hari 02:00 WIB (lihat
> `django_app/docs/integration-config.md` §4), tetapi onboarding **wajib** menjalankannya manual sekali
> supaya tidak menunggu jadwal.

| # | Langkah | Perintah / detail | Selesai |
|---|---|---|---|
| 3.1 | Salin template | `cp .env.prod.example .env.prod` | ☐ |
| 3.2 | Isi blok Django | `DJANGO_SECRET_KEY=$(openssl rand -hex 32)` (unik per klien), `DJANGO_DEBUG=False`, `DJANGO_ALLOWED_HOSTS=<domain>` | ☐ |
| 3.3 | Isi blok database | `DB_NAME`/`DB_USER`/`DB_PASSWORD` **dan** `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD` (harus sama) | ☐ |
| 3.4 | Isi blok Odoo | `ERP_ADAPTER=odoo`, `ODOO_URL`, `ODOO_DB`, `ODOO_USER=api_bot`, `ODOO_API_KEY=<dari 1.2>` | ☐ |
| 3.5 | Isi pemetaan ID | `ODOO_LOCATION_*_ID` (4 baris) + `ODOO_UOM_ID` dari tahap 1 | ☐ |
| 3.6 | Isi CORS/CSRF/TLS | `CORS_ALLOWED_ORIGINS=https://<domain>`, `CSRF_TRUSTED_ORIGINS=https://<domain>`, `SECURE_SSL_REDIRECT=True`, `DJANGO_SECURE_PROXY_SSL_HEADER=True`, cookie `*_COOKIE_SECURE=True`; saat uji awal pakai `SECURE_HSTS_SECONDS=300` dulu | ☐ |
| 3.7 | Isi blok Nginx/Certbot | `DOMAIN=<domain>` (harus sama dengan `server_name` di `nginx/conf.d/mes.conf`), `LETSENCRYPT_EMAIL=<email ops>` | ☐ |
| 3.8 | Isi blok frontend build | `VITE_API_BASE_URL=https://<domain>/api/v1`, `VITE_WS_URL=wss://<domain>/ws`, `VITE_WS_ENABLED=true` (dipakai saat build, bukan runtime!) | ☐ |
| 3.9 | Isi backup & Sentry | `BACKUP_DIR=./backups`, `RETENTION_DAYS=7`; `SENTRY_DSN=` (opsional — kosong = nonaktif) | ☐ |
| 3.10 | Verifikasi tidak ada placeholder | `grep -n "__" .env.prod` → **kosong** | ☐ |
| 3.11 | Pastikan tidak ter-commit | `.gitignore` memuat `.env.prod`; catat salinan ke password manager klien | ☐ |

Referensi tiap variabel: `django_app/docs/integration-config.md` §1 + komentar di `.env.prod.example`.

---

## 4. Deploy — 30 menit

| # | Langkah | Perintah | Selesai |
|---|---|---|---|
| 4.1 | Sertifikat TLS | `DOMAIN=<domain> LETSENCRYPT_EMAIL=<email> ./scripts/generate-ssl.sh` (tanpa email → self-signed bootstrap; lokal: `--self-signed-only`) | ☐ |
| 4.2 | Build image | `docker compose -f docker-compose.prod.yml build` | ☐ |
| 4.3 | Jalankan stack | `docker compose -f docker-compose.prod.yml up -d` | ☐ |
| 4.4 | Cek status | `docker compose -f docker-compose.prod.yml ps` → 8 service `Up` (`frontend_builder` exit 0 = normal) | ☐ |
| 4.5 | Migrasi DB | **sudah otomatis** di command service `django` (`migrate --noinput && collectstatic`). Verifikasi manual: `docker compose -f docker-compose.prod.yml exec django python manage.py migrate --check` → exit 0 | ☐ |
| 4.6 | Superuser admin MES | `docker compose -f docker-compose.prod.yml exec django python manage.py createsuperuser` | ☐ |
| 4.7 | Cek Nginx config | `docker compose -f docker-compose.prod.yml exec nginx nginx -t` lalu (bila baru ubah) `... exec nginx nginx -s reload` | ☐ |
| 4.8 | Health check | `curl -fsS https://<domain>/api/health/` → `{"status":"ok"}` / 200 | ☐ |
| 4.9 | Uji WebSocket | buka `/` di browser, devtools → WS `wss://<domain>/ws/events/` status **101** | ☐ |
| 4.10 | Uji login + role | login 1x per role, pastikan tidak ada redirect aneh | ☐ |
| 4.11 | Aktifkan HSTS penuh | ubah `SECURE_HSTS_SECONDS=31536000` lalu `docker compose -f docker-compose.prod.yml up -d --force-recreate django` | ☐ |

Rollback cepat bila 4.8 gagal: `docker compose -f docker-compose.prod.yml logs --tail=200 django nginx`
(lihat `django_app/docs/runbook-operasional.md` §5 Troubleshooting).

---

## 5. Seed Data Awal (opsional, untuk demo/UAT) — 10 menit

| # | Pilihan | Perintah | Catatan |
|---|---|---|---|
| 5.1 | Bundle demo | `docker compose -f docker-compose.prod.yml exec django python manage.py seed_demo_bundles --count 5` | Membuat bundle `DRAFT` untuk uji scan/aksi |
| 5.2 | Tunggu beat sync | — | Beat otomatis menarik SO/PO dari Odoo (± 5 menit sekali sesuai jadwal) |
| 5.3 | Bersihkan demo sebelum go-live | hapus bundle demo via Django admin (`/admin/`) | jangan biarkan data demo pada produksi nyata |

---

## 6. UAT — 90 menit

| # | Langkah | Detail | Selesai |
|---|---|---|---|
| 6.1 | Jalankan checklist | buka `django_app/docs/uat-checklist.md`, kerjakan §0 pre-flight → §6 cross-cutting | ☐ |
| 6.2 | Walkthrough per role | operator HP → kios → QC → supervisor → admin/owner | ☐ |
| 6.3 | Catat issue | isi tabel §7 di checklist (severity + screenshot) | ☐ |
| 6.4 | Tutup blocker | perbaiki/musyawarahkan; blocker terbuka = **jangan** go-live | ☐ |
| 6.5 | Sign-off | tanda tangan §8 checklist (klien + dev + ops) | ☐ |

---

## 7. Go-Live — 30 menit

| # | Item | Cara cek | Selesai |
|---|---|---|---|
| 7.1 | Backup harian hidup | `docker compose -f docker-compose.prod.yml logs --tail=50 backup` + `ls -lh ./backups/postgres` | ☐ |
| 7.2 | Restore drill (staging) | `./scripts/restore.sh --list` → `./scripts/restore.sh --yes ./backups/postgres/<file>.dump` di instance uji | ☐ |
| 7.3 | Monitoring Sentry | `SENTRY_DSN` terisi; kirim 1 error uji → muncul di dashboard Sentry | ☐ |
| 7.4 | Certbot auto-renew | `docker compose -f docker-compose.prod.yml exec certbot certbot certificates` | ☐ |
| 7.5 | Jalur eskalasi | isi kontak di `django_app/docs/runbook-operasional.md` §8 (dev/ops/PIC klien/Odoo admin) | ☐ |
| 7.6 | Serah terima akses | admin MES + PIC klien punya kredensial; password manager klien terisi | ☐ |
| 7.7 | Sign-off go-live | berita acara (tanggal, versi, siapa hadir) | ☐ |

---

## 8. Lampiran — ringkasan 1 halaman

```text
1. Odoo   : user API + 4 lokasi + UoM → catat ID
2. Sync   : 9 task master → Product.odoo_id > 0
3. .env   : cp .env.prod.example .env.prod → grep "__" harus kosong
4. Deploy : generate-ssl → build → up -d → health 200 → WS 101
5. Seed   : seed_demo_bundles --count 5 (opsional)
6. UAT    : django_app/docs/uat-checklist.md (5 role + cross-cutting) → sign-off
7. Live   : backup + Sentry + certbot + kontak eskalasi
```

Klien berikutnya (C, D, …): ulangi dokumen ini **tanpa mengubah kode** — semua perbedaan
klien wajib berada di `.env.prod`/data Odoo (aturan: tidak ada id klien hardcode di kode,
lihat `django_app/docs/integration-config.md` pembuka).
