# Known Limitations (MES Garmen)

Daftar keterbatasan yang **sudah diketahui dan diterima**. Tujuannya: tidak ada kejutan saat
UAT/go-live — hal di halaman ini **jangan** dilaporkan sebagai bug baru.

- Checklist UAT: `django_app/docs/uat-checklist.md` (bagian yang bertanda ⚠️ mengacu ke sini).
- Onboarding klien: `django_app/docs/onboarding-klien-baru.md`. · Operasional: `django_app/docs/runbook-operasional.md`.
- Status pekerjaan/rencana: `django_app/docs/curent_project.json` (nama file apa adanya di repo).

Kolom **Rencana**: `F3-B` = sudah masuk backlog berikutnya · `backlog` = belum dijadwalkan ·
`by design` = memang tidak akan diubah.

---

## 1. Backend

| # | Limitasi | Dampak ke pengguna | Workaround / perilaku sistem | Rencana |
|---|---|---|---|---|
| B1 | `BundleEvent` **tidak** menyimpan `wc_id` | Tidak bisa melaporkan "event ini terjadi di WC apa" | Atribusi WC diambil dari `bundle.current_work_center` pada saat event dicatat; kolom `wc_code` di laporan bisa `null` → UI menampilkan "—" | backlog |
| B2 | `CycleInstance` **tidak** menyimpan `metadata`/`closed_at` | Di `/quality/rework/`, kolom `from_step`/`to_step`/`closed_at` **selalu `null`** | Halaman menampilkan "—" (tidak dipaksa diisi); informasi yang tersedia: `iteration` + `is_open` + `started_at` | backlog |
| B3 | `master.Partner` hanya punya `odoo_id`/`code`/`name`/`is_active` (tanpa `email`/`phone`/`city`) | Halaman `/purchase/vendors` tidak menampilkan kontak vendor | Kolom kontak **dihapus dari UI** (bukan ditampilkan kosong) — kontak tetap tersedia di Odoo | by design |
| B4 | `CycleDefinition` untuk `QC_REWORK` **lazy-seeded** (dibuat saat pertama dipakai, bukan via migrasi data) | Di DB yang baru di-restore tetapi belum pernah rework, definisi siklus belum ada sampai rework pertama | Siklus dibuat otomatis saat percobaan rework pertama — tidak perlu tindakan ops | backlog |
| B5 | `WorkOrder` **tidak punya FK** ke `ProcessRouting` | Tidak bisa menanyakan "order ini memakai routing versi mana" | Routing ditentukan dari **routing aktif pertama** / `TwoStageAggregator().routing` | backlog |
| B6 | Nilai `BundleEvent.event_type` untuk scrap adalah **`BUNDLE_SCRAP`** (bukan `SCRAP`) | Filter sederhana yang hanya mencari `SCRAP` akan kosong | Query/filter yang ada sudah menerima **keduanya**; jangan mengubah filter menjadi exact `SCRAP` | by design |
| B7 | `SyncRecord.resource_id` bertipe **string** (bukan FK ke `Order`) | Tidak ada integrity check tingkat DB; record "orphan" mungkin ada | Aplikasi melakukan cast aman (`int(...)`, gagal → `order_no = None`) — lihat `/finance/invoices` | by design |
| B8 | Endpoint list memakai **offset cursor** (bukan keyset) | Bisa ada baris terlewat/ganda bila data berubah saat halaman berpindah | Muat ulang halaman; untuk volume besar gunakan filter (`from`/`to`/`wc`) | backlog |

---

## 2. Frontend

| # | Limitasi | Dampak ke pengguna | Workaround / perilaku sistem | Rencana |
|---|---|---|---|---|
| F1 | ~~5 MODE masih `dummy` (data fixture)~~ → **TERTUTUP di F5.4.CLOSE**: seluruh MODE kini `real` (46; bertambah `auth` di F6.2 → **47 real / 0 dummy**) | Tidak ada lagi halaman ber-data contoh | Data `/settings/users`, `/inventory/reporting`, `/settings/devices`, dan HITL kini dari backend; user dikelola di `/settings/users` (atau Django admin `/admin/`) | selesai |
| F2 | `ChatterBox` WebSocket perlu `VITE_WS_ENABLED=true` + TLS (`wss://`) di produksi | Bila lupa di-set saat **build**, chatter tidak realtime (hanya refresh manual) | Set variabel di `.env.prod` lalu **rebuild** frontend (`frontend_builder`), bukan restart | by design |
| F3 | Device binding **belum** ter-trigger otomatis saat akses pertama | Operator harus melalui bind/assignment perangkat dulu | Bind manual sekali per perangkat (cookie `device_token` tersimpan di browser) | F3-B/backlog |
| F4 | 2 app menu masih placeholder: **`master`**, **`sales`** | Menu ada, isinya halaman kosong/placeholder | Data master & SO tetap dapat dilihat lewat Order Line/list bundle; menu belum jadi jalur utama | backlog |
| F5 | AI Assistant hanya **stub** (`ok:false`) di `/ai/chat` | Chat tidak benar-benar menjawab | — | backlog (AI Agent Layer) |
| F6 | Laporan `/reports/*` menarik sampai ± 200 baris per halaman lalu dipaginasi di klien | Bukan tampilan realtime seluruh data | Persempit rentang tanggal/pencarian; export CSV per halaman | backlog |
| F7 | **F6.3: cetak badge operator DITUNDA** (ESC/POS `POST /print/badge/` + nilai `PrintJob.Resource.BADGE`) | Badge fisik operator belum bisa dicetak dari `/settings/users` | Alasan: butuh **1 migration + 2 endpoint baru**. Kolom **Kode Operator** + tombol **Regenerate** sudah jalan; badge pilot dicetak **manual di luar sistem** dari kode yang tampil. Tombol sengaja TIDAK dirender (tidak ada tombol mati); penanda `// TODO F7: cetak badge ESC/POS` ada di `UserManagementPage.tsx` | F7 / saat Klien A minta |
| F8 | **F6.4: daftar binding SEMUA perangkat belum ada** — backend hanya punya `GET /devices/me` (perangkat ini) | Di `/settings/devices`, admin melihat status/bind **perangkat yang sedang dipakai** saja, bukan tabel semua perangkat ter-bind | Bind/unbind dilakukan **di perangkat itu sendiri** (cookie `device_token` per browser); daftar lengkap menunggu endpoint read-only (`GET /settings/devices/bindings/`) yang belum disetujui | F7 |
| F9 | ~~FIX-ROUTE: app `quality` terbuka untuk `owner` di sidebar, tapi `/quality/*` dijaga `QUALITY_ROLES=[qc,supervisor,admin]`~~ **TERTUTUP F7.1** | — | `QUALITY_ROLES` kini `['qc','supervisor','admin','owner']` (owner = super-admin); diverifikasi browser: owner membuka `/quality/defects`, `/quality/aql`, `/quality/rework`, `/quality` tanpa "Akses Ditolak", sedangkan operator/purchasing tetap ditolak | Selesai |

---

## 3. Ops

| # | Limitasi | Dampak | Workaround / perilaku sistem | Rencana |
|---|---|---|---|---|
| O1 | Service `backup` menjalankan **loop `sleep` di dalam container** (bukan systemd timer host) | Backup berhenti bila container `backup` mati | Pantau §2.6 di `django_app/docs/runbook-operasional.md` (cek file harian). Alternatif: systemd timer di host memanggil `scripts/backup.sh` — mode host memerlukan akses Docker CLI (setara socket Docker = **trade-off keamanan**), jadi default tetap mode container | backlog |
| O2 | Sertifikat **pertama** dibuat manual (`./scripts/generate-ssl.sh`), bukan otomatis saat deploy | Deploy pertama tanpa langkah ini → Nginx gagal start / sertifikat self-signed | Jalankan script (butuh `DOMAIN` + `LETSENCRYPT_EMAIL`); perpanjangan **otomatis** tiap 12 jam oleh `certbot`, tetapi **reload Nginx tetap manual** (`nginx -s reload`) | backlog |
| O3 | Sentry **opsional** | Tanpa `SENTRY_DSN`, error hanya terlihat di log container | Isi `SENTRY_DSN` di `.env.prod` → recreate `django`/`celery_*` | by design |
| O4 | Trace Bridge **tidak** dijalankan sebagai container | Harus dijalankan manual (foreground) saat menelusuri request | `cd django_app && python -m trace_bridge.api` → `http://127.0.0.1:8765/_ai/trace/<id>`; bind lokal sehingga tidak terekspos internet | backlog |
| O5 | HSTS agresif bila langsung di-set 1 tahun | Kesalahan TLS sempat memaksa browser memblokir domain | Saat uji awal pakai `SECURE_HSTS_SECONDS=300`, naikkan ke `31536000` setelah stabil (`django_app/docs/onboarding-klien-baru.md` §4.11) | by design |
| O6 | Render/rebuild frontend memakai **build-arg** (`VITE_*`) | Mengubah `VITE_*` tanpa rebuild tidak berefek | Selalu `docker compose -f docker-compose.prod.yml up -d --force-recreate frontend_builder nginx` | by design |
| O7 | Postgres/Redis tidak diekspos ke host (tanpa `ports:`) | Tidak bisa `psql`/`redis-cli` langsung dari host | Selalu lewat `docker compose -f docker-compose.prod.yml exec postgres psql ...` | by design |

---

## 4. Test

| # | Limitasi | Detail | Rencana |
|---|---|---|---|
| T1 | **19 pre-existing failure** di suite backend | Penyebab: broker Celery nyata + flake registry global — **bukan regresi**. Tercatat di `django_app/docs/curent_project.json` (`project.test_pre_existing_failures`) | backlog |
| T2 | Live test **gated** `MES_LIVE=1` | Tanpa env tsb, seluruh suite live di-skip (agar CI lokal hijau tanpa backend). Contoh: `MES_LIVE=1 ~/.bun/bin/bun --bun run test tests/live` | by design |
| T3 | Test tulis (POST) tambahan gate `MES_LIVE_ALLOW_SYNC=1` | Mencegah insiden menulis ke Odoo/data nyata saat smoke test | by design |
| T4 | Load test **gated** `LOAD_TEST=1` | `django_app/tests/integration/test_load_1000.py` (1000 stock move, ± 13 detik) tidak jalan di CI normal | by design |
| T5 | Frontend: jumlah MODE diuji di `frontend_app_v2/tests/unit/api/_adapter.test.ts` | Saat ini **47 real / 0 dummy** (F5.4.CLOSE + F6.2); menambah/mengubah MODE wajib memperbarui tes ini | by design |
| T6 | UI test memakai `react-dom/server` + walker (tanpa jsdom) | Tidak ada simulasi event klik DOM penuh | by design |
| T7 | Dokumen ini tidak divalidasi otomatis | Bisa basi bila kode berubah | Review tiap rilis besar / setelah F3-B |

---

## 5. Sering disalahpahami (bukan limitasi)

| Gejala | Penjelasan |
|---|---|
| `frontend_builder` status **exit 0 / `Exited (0)`** | Normal — service one-shot pengisi volume `frontend_dist`. Yang penting `nginx` Up. |
| Login `admin` tidak bisa membuka `/production/*`, `/reports/*` | Memang by design (RBAC): app `production` milik operator/supervisor/owner, `reports` supervisor ke atas. |
| Kolom "Belum Jelas" di `/reports/on-time-delivery` | Order dengan `on_time = null` (deadline belum/`finished_at` kosong) — bukan error data. |
| `from_wc` kosong di `/production/buffer-queue` | Bundle pada step pertama memang belum punya WC asal → tampil "—". |
| Bundle demo muncul di produksi | Jangan lupa hapus data demo (`seed_demo_bundles`) sebelum go-live — lihat `django_app/docs/onboarding-klien-baru.md` §5.3. |
| Tekan [SCRAP] lalu data masuk dua tempat | Memang by design: satu transaksi ke state machine + satu `BundleEvent` scrap (Fase 4.3 audit trail). |

---

## 6. Cara menambahkan limitasi baru

1. Reproduksi & catat langkahnya (mis. dari tabel issue `django_app/docs/uat-checklist.md` §7).
2. Tambahkan baris di tabel yang tepat (§1 Backend / §2 Frontend / §3 Ops / §4 Test) dengan
   **dampak pengguna**, **workaround**, dan **rencana**.
3. Bila keputusan ini mengubah rencana sprint, catat juga di `django_app/docs/curent_project.json`
   (task terpisah) — dokumen ini hanya mencatat keterbatasan, bukan roadmap.
4. Bila ternyata bukan limitasi melainkan perilaku yang benar → masuk §5, **bukan** §1–§4.
