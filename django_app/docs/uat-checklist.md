# UAT Checklist — Klien A (MES Garmen)

Dokumen ini dipakai saat **UAT (User Acceptance Test) Klien A** di VPS produksi.
Estimasi total: **± 90 menit** (5 role). Prasyarat: instance sudah ter-deploy
(lihat `django_app/docs/onboarding-klien-baru.md`).

- Dokumen terkait: `django_app/docs/onboarding-klien-baru.md` (cara deploy), `django_app/docs/runbook-operasional.md`
  (jika ada yang merah), `django_app/docs/known-limitations.md` (**hal yang memang belum ada** — jangan
  dilaporkan sebagai bug).
- Legenda hasil: ✅ lulus · ⚠️ lulus dengan catatan (tulis di kolom Catatan) · ❌ gagal (buat issue).

> **Koreksi route penting** (supaya tidak salah halaman):
> aksi QC = `/production/qc` · log defect = `/quality/defects` · AQL = `/quality/aql` ·
> rework = `/quality/rework` · monitor sync = `/settings/sync` (bukan `/settings/sync-monitor`).

---

## 0. Persiapan (pre-flight) — sebelum klien datang

| # | Item | Cara cek | Hasil |
|---|---|---|---|
| 1 | VPS aktif (spec **4 vCPU / 8 GB RAM / 100 GB SSD**) | `free -h`, `df -h` | ☐ |
| 2 | DNS A record domain → IP VPS | `dig +short <domain>` (harus = IP VPS) | ☐ |
| 3 | Odoo produksi klien hidup + API key valid | login Odoo → Preferences → API Keys | ☐ |
| 4 | `.env.prod` terisi lengkap (semua placeholder `__...__` diganti) | `grep -n "__" .env.prod` → kosong | ☐ |
| 5 | `docker compose -f docker-compose.prod.yml up -d` sukses | `docker compose -f docker-compose.prod.yml ps` (9 service up) | ☐ |
| 6 | SSL terpasang | `DOMAIN=<domain> LETSENCRYPT_EMAIL=<email> ./scripts/generate-ssl.sh` lalu `docker compose -f docker-compose.prod.yml exec nginx nginx -t` | ☐ |
| 7 | Health check 200 | `curl -fsS https://<domain>/api/health/` | ☐ |
| 8 | Master data tersync | `Product.objects.filter(odoo_id__isnull=False).count() > 0` (lihat `django_app/docs/integration-config.md` §3.3) | ☐ |
| 9 | Data demo (opsional) | `docker compose -f docker-compose.prod.yml exec django python manage.py seed_demo_bundles --count 5` | ☐ |
| 10 | Akun per role siap (operator/qc/supervisor/inventory/purchasing/admin/owner) | Login 1x tiap role → tidak ada redirect ke `/` | ☐ |

Service yang harus `Up`: `postgres`, `redis`, `django`, `celery_worker`, `celery_beat`,
`nginx`, `certbot`, `backup` (`frontend_builder` selesai/exit 0 — itu normal).

---

## 1. Operator HP (Cutting) — 15 menit (`operator`)

Alur: scan → mulai → selesai → scrap.

| # | Langkah | Ekspektasi | Hasil |
|---|---|---|---|
| 1.1 | Buka `/production/scan` di HP | Halaman siap (device bind aktif — cookie `device_token`) | ☐ |
| 1.2 | Scan QR bundle | Terbuka `/production/shop-floor/<id>`, detail bundle tampil (code, qty, WC saat ini) | ☐ |
| 1.3 | Tekan **[MULAI]** | State `DRAFT → CUTTING`, tombol aksi berubah sesuai `allowed_actions` | ☐ |
| 1.4 | Tekan **[SELESAI]** | State `CUTTING → SEWING`, ada baris `BundleEvent` baru | ☐ |
| 1.5 | Tekan **[SCRAP]** | Form defect terbuka (`/production/scrap/<id>`), isi `qty` + `reason` → submit sukses | ☐ |
| 1.6 | Lihat Chatter bundle | Update muncul **< 5 detik** tanpa refresh (WebSocket) | ☐ |
| 1.7 | Aksi tidak sah (mis. [SELESAI] dari DRAFT) | Tombol tidak tersedia / ditolak pesan jelas (guard `allowed_actions`) | ☐ |

---

## 2. Operator Kios (Sewing) — 10 menit (`operator`)

Device stasioner di lini; alur sama, beda ergonomi input.

| # | Langkah | Ekspektasi | Hasil |
|---|---|---|---|
| 2.1 | Buka `/production/scan` di tablet kios | Layout kios (target sentuh lebih besar) | ☐ |
| 2.2 | Scan via kamera tablet | Sama seperti HP: membuka shop floor bundle | ☐ |
## 3. QC (Quality Control) — 15 menit (`qc`)

Halaman yang dipakai role ini: `/production/qc`, `/quality/defects`, `/quality/aql`,
`/quality/rework`.

| # | Langkah | Ekspektasi | Hasil |
|---|---|---|---|
| 3.1 | Buka `/production/qc` | Layar scan bundle (siap menerima QR) | ☐ |
| 3.2 | Scan QR bundle → `/production/qc/<id>` | Form defect tampil: siluet cacat, jenis cacat, multi-qty | ☐ |
| 3.3 | Tekan **[LULUS QC]** (`BUNDLE_QC`) | State `SEWING → QC → DONE` (2 langkah tercatat) | ☐ |
| 3.4 | Tekan **[REWORK]** + isi defect → submit | `POST /api/v1/quality/defects/` sukses; siklus `QC_REWORK` terbuka | ☐ |
| 3.5 | Tekan **[SCRAP]** + qty + reason → submit | Bundle `→ DONE`, scrap tercatat (terpisah dari rework) | ☐ |
| 3.6 | Buka `/quality/defects` | Daftar defect: `bundle_code`, `wc_code`, `defect_entries[]` (type/qty/location), `action`, `recorded_at` | ☐ |
| 3.7 | Buka `/quality/aql` | KPI sampel/defect + bar per WC; chip status `pass` / `warn` / `fail` | ☐ |
| 3.8 | Buka `/quality/rework` | Daftar siklus rework (`iteration`, `started_at`, `is_open`) | ☐ |
| 3.9 | Cek kolom `from_step`/`to_step` di rework | Bernilai **"—"** → ini **limitasi backend** yang diketahui, bukan bug | ☐ |

---

## 4. Supervisor — 20 menit (`supervisor`)

| # | Langkah | Halaman | Ekspektasi | Hasil |
|---|---|---|---|---|
| 4.1 | Dashboard supervisor | `/dashboard` | KPI: `bundles{draft,cutting,sewing,qc,done}`, `wip_qty`, `fg_qty`, `orders{open,overdue}`, `scrap_qty_today`, `alerts[]`, `line_efficiency{pct,delta}`, `trend[]` | ☐ |
| 4.2 | Antrean buffer | `/production/buffer-queue` | Baris per WC: `queue_depth`, `avg_wait_min`, `bundles[]` (`from_wc`/`to_wc`/`status`); `from_wc` kosong → tampil "—" | ☐ |
| 4.3 | Visualisasi routing | `/production/routing` | DAG node + edge; edge rework putus-putus (coral) | ☐ |
| 4.4 | Kesiapan material | `/production/readiness/<orderId>` | Tabel komponen BOM vs stok (`ready`/`short`) | ☐ |
| 4.5 | Laporan WIP | `/reports/wip` | KPI `label/unit/trend` + `series[]` + tabel WIP | ☐ |
| 4.6 | Laporan lead time | `/reports/lead-time` | `avg_hours`, tabel `bundle_code` + `hours_total` + jumlah stage | ☐ |
| 4.7 | Laporan OTD | `/reports/on-time-delivery` | KPI `otd_pct`, tabel order (`on_time` null → "Belum Jelas") | ☐ |
| 4.8 | Laporan efisiensi lini | `/reports/line-efficiency` | Efisiensi + `label/unit/trend/series` dari backend | ☐ |
| 4.9 | (Opsional) Rekonsiliasi stok | `/reports/reconciliation` | Daftar selisih MES vs Odoo di luar toleransi | ☐ |
| 4.10 | Export CSV salah satu tabel | semua tabel | File CSV terunduh & isinya sesuai filter layar | ☐ |

> Role `admin` **tidak** boleh membuka `/production/*` (termasuk readiness) — uji cepat:
> login admin → buka `/production/readiness/1` → harus dialihkan ke `/`.

---

## 5. Admin (Owner) — 20 menit (`admin` / `owner`)

| # | Langkah | Halaman | Ekspektasi | Hasil |
|---|---|---|---|---|
| 5.1 | Produk + stok | `/inventory/products` | Daftar produk (`ProductRow`) + `stock_qty` | ☐ |
| 5.2 | Operasi inventory | `/inventory/operations` | Baris operasi WIP/FG/SCRAP (qty bisa "—" bila null) | ☐ |
| 5.3 | Reporting inventory | `/inventory/reporting` | ⚠️ **masih DUMMY** (fixture) — lihat `django_app/docs/known-limitations.md` | ☐ |
| 5.4 | Purchase order | `/purchase/orders` | Daftar PO + `vendor_code` ("—" bila null) + `lines[]` | ☐ |
| 5.5 | Vendor | `/purchase/vendors` | Daftar vendor; `email`/`phone`/`city` **sengaja tidak ada** (kolom tak ditampilkan) | ☐ |
| 5.6 | Purchase reporting | `/purchase/reporting` | KPI + `monthly_series[]` (6 bulan) + `top_vendors[]` | ☐ |
| 5.7 | Routing | `/settings/routing` | Editor DAG: tambah node, geser, simpan → `POST /settings/routing/` sukses | ☐ |
| 5.8 | Bundling | `/settings/bundling` | Daftar rule (`name`, matriks ukuran, default/bundle) + tambah rule baru | ☐ |
| 5.9 | Line allocation | `/settings/line-allocation` | Daftar alokasi + tambah aturan (`wc_type` + `Line ID` angka) | ☐ |
| 5.10 | Invoice queue | `/finance/invoices` | Daftar invoice (`invoice_status`, `attempts`, `last_error`) | ☐ |
| 5.11 | Monitor sync | `/settings/sync` | Daftar `SyncRecord` (`stage`, `status`, `attempts`, `last_error`) | ☐ |
| 5.12 | Audit produk | `/settings/audit` | Produk tanpa `odoo_id` (harus kosong di produksi) | ☐ |
| 5.13 | Device profiles | `/settings/devices` | 4 profil (`OPERATOR_HP`, `KIOSK_TABLET`, `SCANNER_USB`, `DESKTOP`) — ⚠️ masih DUMMY | ☐ |
| 5.14 | User management | `/settings/users` | ⚠️ **masih DUMMY** — jangan dipakai untuk kelola user nyata | ☐ |
| 5.15 | (Opsional) AI chat | `/ai/chat` | Balasan stub (`ok:false`) → memang belum aktif | ☐ |

---

## 6. Cross-Cutting Tests (wajib, ± 15 menit)

| # | Uji | Cara | Ekspektasi | Hasil |
|---|---|---|---|---|
| 6.1 | WebSocket realtime | Buka bundle di 2 perangkat, ubah state di satu perangkat | Chatter perangkat lain update **< 5 detik** (`VITE_WS_ENABLED=true`, `wss://`) | ☐ |
| 6.2 | Offline mode | Matikan WiFi → tekan [SELESAI]/isi defect | Aksi masuk antrean lokal (badge pending), UI tidak error | ☐ |
| 6.3 | Sinkron offline | Nyalakan WiFi | Antrean terkirim otomatis, badge pending kembali 0 | ☐ |
| 6.4 | Device profile beda | Bandingkan tampilan HP vs Kios vs Scanner | Layout/perilaku beda sesuai profil device | ☐ |
| 6.5 | Priority scheduler | Order `FAST_TRACK` di tengah antrean | Naik ke depan di `/production/buffer-queue` | ☐ |
| 6.6 | Bottleneck alert | Siapkan WC dengan `queue_depth > 10` (default `BottleneckDetector`; alternatif: avg wait > 60 menit) | Muncul entri di `alerts[]` dashboard (`/dashboard`) | ☐ |
| 6.7 | Trace satu request | Kirim request apa pun, ambil `X-Request-ID`, lalu di VPS: `cd django_app && python -m trace_bridge.api` + `curl -s http://127.0.0.1:8765/_ai/trace/<id>` | JSON `{trace_id, duration_ms, spans[], errors}` (lihat `django_app/docs/trace-bridge.md`) | ☐ |
| 6.8 | Backup harian | `ls -lh ./backups` setelah 24 jam / jalankan `./scripts/backup.sh` manual | File dump baru + hasil `gzip` wajar | ☐ |
| 6.9 | Restore (opsional, staging!) | `./scripts/restore.sh --list` → `./scripts/restore.sh --yes <file.dump>` di instance uji | Data kembali, aplikasi tetap jalan | ☐ |
| 6.10 | RBAC | Login tiap role, coba buka halaman role lain lewat URL | Dialihkan ke `/` (tanpa error putih) | ☐ |

---

## 7. Daftar Issue (diisi saat UAT)

| # | Role | Halaman | Langkah | Gejala | Severity (Blocker/Major/Minor) | Screenshot | Status |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | ☐ | |
| 2 | | | | | | ☐ | |
| 3 | | | | | | ☐ | |
| 4 | | | | | | ☐ | |
| 5 | | | | | | ☐ | |

Definisi severity:
- **Blocker** — alur inti tidak bisa diselesaikan (scan/aksi/state tidak berubah).
- **Major** — data salah tampil, tetapi workaround ada.
- **Minor** — kosmetik/teks/UX.

---

## 8. Sign-off

| Pihak | Nama | Jabatan | Tanda tangan | Tanggal |
|---|---|---|---|---|
| Klien A PIC | _________________ | ______________ | ______________ | ________ |
| Klien A QC | _________________ | ______________ | ______________ | ________ |
| Dev PIC | _________________ | ______________ | ______________ | ________ |
| Ops PIC | _________________ | ______________ | ______________ | ________ |

**Keputusan UAT**: ☐ DITERIMA (go-live) · ☐ DITERIMA DENGAN CATATAN · ☐ ULANG (blocker terbuka)

Pasca UAT: lanjutkan ke §7 di `django_app/docs/runbook-operasional.md` (monitoring harian) dan
catat setiap keterbatasan yang muncul ke `django_app/docs/known-limitations.md` bila belum tercatat.

| 2.3 | Scan via barcode gun (USB/Bluetooth) | Input terisi otomatis (Enter = submit) | ☐ |
| 2.4 | Jalankan **BUNDLE_QC** | State `SEWING → QC` tercatat + `BundleEvent` | ☐ |
| 2.5 | Cek `/production/shop-floor/<id>` di kios | WC saat ini = `QC` | ☐ |

> Catatan kios: perangkat kios biasanya **sudah ter-bind** (satu tablet = satu lini).
> Device binding otomatis saat akses pertama belum aktif (lihat `django_app/docs/known-limitations.md`).

---
