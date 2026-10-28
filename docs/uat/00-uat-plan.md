
# 00 — Rencana UAT (MES Garmen)

> **Status:** DRAFT sebagian — dokumen ini dimulai dari §4. Bagian §1–§3 (lingkup & tujuan, peran/tim, jadwal sesi) belum ditulis.

**Jangan acak.** Alur putus di tengah = data kotor untuk sesi berikutnya.

### 4.2 Reset Data Antar Sesi
Setiap sesi dimulai dengan `seed_big_test` (idempoten) + `aggregate_daily`, lalu verifikasi invariants A–E = 0. Detail di `02-test-data.md`.

---

## 5. Gate Keputusan per Sesi

### 5.1 Definisi Gate
Setelah setiap sesi, UAT Lead memutuskan salah satu:

| Kondisi | Keputusan | Konsekuensi |
|---|---|---|
| **0 BUG-CRITICAL**, ≤2 BUG-HIGH, ≥95% PASS | ✅ **LANJUT** | Sesi berikutnya dimulai |
| **≥1 BUG-CRITICAL** di alur inti | ❌ **PERBAIKI DULU** | Sesi diulang setelah fix + retest |
| **≥3 BLOCKED** (butuh akses/data/klien) | ⏸ **TUNDA** | Eskalasi ke admin Odoo / klien / data owner |
| **≥5 MISUNDERSTANDING** (bukan bug) | 📝 **REVISI SPEK** | Update `docs/blueprint.md` + `CHANGES-DETAIL-H1H5.md`, bukan fix kode |
| Sesi 5 (AI) <80% | ⚠️ **CONDITIONAL** | Deploy diizinkan dengan `AI_AGENT_ENABLED=false` atau label "beta" |

### 5.2 Definisi BUG-CRITICAL (Blocker)
Wajib fix + retest sebelum sesi berikutnya:
- Operator **tidak bisa menyelesaikan** alur scan (MULAI/SELESAI/SCRAP gagal)
- Sync ke Odoo **FAILED tanpa jalan keluar** (bukan retry-able)
- Laporan menampilkan **angka salah** (bukan kosong / bukan flag missing_cost)
- **Permission bocor** (role bisa akses yang bukan haknya)
- Data **hilang/korup** setelah operasi normal (bundle dobel, invoice dobel, stock negatif)
- **Offline queue** mengirim event dobel saat online (double-execute)
- **Write injection** lolos (AI mengeksekusi perintah hapus/ubah)
- **Audit log** tidak tercatat untuk CRUD/aksi (jejak hilang)

### 5.3 Severity (dipakai di `05-defect-log.md`)
| Level | Definisi | SLA fix |
|---|---|---|
| **CRITICAL** | Blocker alur inti / data loss / security leak | Sebelum sesi berikutnya |
| **HIGH** | Fitur utama rusak, ada workaround sulit | Sebelum deploy |
| **MEDIUM** | Fitur sekunder rusak, workaround mudah | Sebelum deploy (bila sempat) atau backlog |
| **LOW** | Kosmetik / UX kecil | Backlog |

### 5.4 Gate Akhir — Layak Deploy?
Semua checklist harus hijau sebelum `06-signoff.md` menandatangani deploy:

- [ ] Sesi 0–6 dijalankan semua
- [ ] **0 BUG-CRITICAL** open
- [ ] **0 BUG-HIGH** open
- [ ] ≥95% skenario PASS di Sesi 1–4, ≥80% di Sesi 5
- [ ] Invariants data A–E = 0 (F=4 boleh, diketahui)
- [ ] `known_tech_debt` `odoo-api-stock-manager-group` **CLOSED** (admin Odoo fix)
- [ ] Verifikasi manual 1 angka per laporan H4.1–H4.7 cocok dengan DB/Odoo
- [ ] Backup + restore diuji di staging (`scripts/backup.sh` + `restore.sh`)
- [ ] Smoke test endpoint produksi di staging (health, docs, login, 1 alur SO→Invoice, 1 pertanyaan AI, 1 print)
- [ ] `ERP_ADAPTER` ≠ `null` saat UAT (Odoo staging terhubung + `health_check()` OK)
- [ ] `AI_LLM_TEMPERATURE=0` + `AI_AGENT_TOOLS_ENABLED=true` diverifikasi via `settings`
- [ ] Keputusan eksplisit: AI di-flag ON atau OFF di produksi (terkait Q3/Q6/Q8)

---

## 6. Definisi Lulus/Gagal (per Sesi)

### 6.1 Sesi 0 — Smoke
| Aspek | Lulus jika |
|---|---|
| Login 7 role | Semua bisa login, redirect sesuai role |
| Route guard | Operator buka `/settings/users` → AccessDenied/redirect |
| Swagger | `/api/docs/` menampilkan semua endpoint |
| Health | `/api/health/` → 200 |

### 6.2 Sesi 1 — Master & Settings
- ≥95% skenario PASS (mis. 18 skenario → ≥17 PASS)
- 0 BUG-CRITICAL
- Setiap CRUD menghasilkan `SyncRecord` (SENT/SKIPPED) + `AuditLog`
- Upload gambar produk/partner: `image_display_url` + thumbnail 256px ada
- Permission matrix: banner "belum enforce" terlihat
- Guard DELETE (currency IDR/USD, sequence seed) bekerja

### 6.3 Sesi 2 — Transaksi & Finance
- ≥95% PASS, 0 BUG-CRITICAL, **0 BLOCKED**
- SO → Invoice → Payment: state DONE + `SyncRecord` SENT + `odoo_id` terisi
- Anti-overpay payment → 400
- Journal Entry tidak balance → 400; balance → SENT
- Inventory adjustment **SENT** (bukan FAILED karena Odoo group)
- Stock transfer `stock.picking` state `done` di Odoo
- `/api/v1/reconciliation/report/` selisih 0 atau terjelaskan

### 6.4 Sesi 3 — Lantai Produksi
- ≥95% PASS, 0 BUG-CRITICAL
- Scan MULAI/SELESAI/SCRAP mengubah state + kirim WS event
- Offline queue: WiFi mati → scan → WiFi nyala → event terkirim **tepat 1x** (tidak dobel)
- QC rework loop: QC → SEW → QC tercatat `CycleInstance`
- Kanban drag valid → POST + optimistic; drag ilegal → toast batal, 0 POST
- Device profile: layout HP vs kios vs scanner berbeda
- Unbind device → scan ditolak

### 6.5 Sesi 4 — Laporan & Export
- ≥95% PASS, 0 BUG-CRITICAL
- 7 laporan H4 terisi (bukan kosong)
- **1 angka per laporan diverifikasi manual** via DB/Odoo — cocok
- Export Excel: 2 sheet (summary + data), angka = laporan
- Export PDF: A4 landscape/portrait, header + footer benar
- `/reports/stock/` saat Odoo down → 200 rows=[] (bukan 500)
- `?period` vs `?date_from/?date_to` prioritas benar
- `?_nocache=1` beda dengan cache

### 6.6 Sesi 5 — AI Agent & WA
- **≥80%** PASS (11 demo → ≥9 lulus; 3 non-produksi → 3/3)
- 0 write intent lolos
- 0 pertanyaan non-produksi dijawab sebagai produksi
- Jawaban angka cocok dengan DB (validator exact)
- HITL approve → `execution` di response
- WA webhook APPROVE/REJECT valid; nomor tidak terdaftar → 403
- Observability: requests, cost, cache hit terlihat
- **Q3/Q6/Q8 boleh gagal** (butuh data klien) — dicatat sebagai SPEC-GAP/BLOCKED, bukan blocker deploy bila AI di-flag OFF

### 6.7 Sesi 6 — Cross-cutting
- Permission matrix 7 role × 38 route: **0 mismatch**
- Anonim akses `IsAuthenticated` → 403 (semua endpoint)
- CSRF/session: tidak bocor antar user
- Audit log: setiap CRUD/aksi tercatat
- Replay 1 TX: tidak duplikat (idempotency)
- React ErrorBoundary: crash 1 halaman → fallback, bukan white screen
- Build chunk < 500 kB; Tailwind md5 = `7e65992b0d97efab12a50e803f94444b`

---

## 7. Risiko & Mitigasi

| Risiko | Dampak | Mitigasi |
|---|---|---|
| `stock.group_stock_manager` belum diset di Odoo staging | Sesi 2 BLOCKED | Admin Odoo fix **sebelum** Sesi 2; verifikasi via health check |
| Odoo staging tidak tersedia | Sesi 2, 4 gagal | Siapkan `ERP_ADAPTER=null` fallback untuk Sesi 1,3,5; Sesi 2,4 wajib Odoo |
| AI Q3/Q6/Q8 gagal | Sesi 5 <80% | Putuskan lebih awal: AI ON (label beta) atau OFF; golden set klien baru dipakai |
| Data duplikat F=4 (Kaos Lapangan x6) | Laporan produk tidak unik | Keputusan bisnis: merge/hapus **sebelum** Sesi 4; atau terima dengan catatan |
| 2 sesi pytest bersamaan | Ratusan error palsu | Aturan: 1 sesi pytest pada satu waktu (test-DB sama) |
| Frontend `bun install` belum jalan | Recharts tidak ada → AI chat chart gagal | `bun install` + verifikasi `bun.lock` sebelum Sesi 5 |
| Timezone 00:00–07:00 WIB | Flake aggregate/cost_tracker | Jalankan UAT di luar jendela 00:00–07:00 WIB |
| Klien A/B belum komit | UAT formal tertunda | UAT eksploratif internal dulu; UAT formal setelah komitmen tertulis |

---

## 8. Artefak & Output

### 8.1 Input (sudah ada di repo)
- `docs/blueprint.md` v5.0
- `docs/CHANGES-DETAIL-H1H5.md`
- `django_app/docs/uat-checklist.md`
- `django_app/docs/onboarding-klien-baru.md`
- `django_app/docs/integration-config.md`
- `tests/golden/questions.yaml` (30 pertanyaan: 20 tuning + 10 held-out)
- `tests/golden/demo_agent_loop_results.json` (11 demo)

### 8.2 Output UAT (yang akan dibuat)
- `01-environment.md` — setup staging
- `02-test-data.md` — seed & reset
- `03-skenario.md` — ~85 skenario (Sesi 0–6)
- `04-hasil/sesi-{1..5}.md` — hasil per sesi
- `05-defect-log.md` — register temuan
- `06-signoff.md` — gate per sesi + keputusan deploy

### 8.3 Artefak Pendukung
- Rekaman layar per sesi (OBS/Zoom) — bukti bug intermiten
- `logs/mes.jsonl` — bukti backend
- Path screenshot / curl / JSON response — dilampirkan di `04-hasil/`
- `tests/golden/uat_results.json` — hasil AI per pertanyaan (bila ada)

---

## 9. Setelah UAT

### 9.1 Bila Semua Gate Lulus
1. Update `06-signoff.md` → **deploy produksi DIIZINKAN**
2. Deploy staging → produksi (`docker-compose.prod.yml`)
3. Smoke test produksi 15 menit (mini UAT)
4. Handover: `onboarding-klien-baru.md` + `runbook-operasional.md`
5. Mulai UAT formal 2 klien (bila klien komit)

### 9.2 Bila Gate Gagal
1. Perbaiki BUG-CRITICAL/HIGH → retest sesi terkait
2. Bila SPEC-GAP/MISUNDERSTANDING → revisi `docs/blueprint.md` + `CHANGES-DETAIL-H1H5.md`
3. Bila BLOCKED → eskalasi (admin Odoo / klien / data owner)
4. Ulangi sesi sampai gate lulus
5. Jangan deploy selama ada BUG-CRITICAL/HIGH open

### 9.3 Bila AI <80% (Sesi 5)
Pilihan (diputuskan di `06-signoff.md`):
- **Opsi A:** Deploy dengan `AI_AGENT_ENABLED=false` → AI tidak tampil ke klien; aman
- **Opsi B:** Deploy dengan AI ON + label "beta" + disclaimer di UI + golden set klien dipakai untuk perbaiki Q3/Q6/Q8 pasca-deploy
- **Opsi C:** Tunda deploy sampai Q3/Q6/Q8 diperbaiki dengan data klien (butuh wawancara 30 menit dulu)

---

## 10. Aturan Main UAT (Ringkas)

1. **UAT menguji perilaku bisnis, bukan kode.** Setiap temuan harus punya dampak operasional.
2. **Pisahkan BUG vs SPEC-GAP vs MISUNDERSTANDING vs IMPROVEMENT.** Label wajib.
3. **Satu sesi = satu alur utuh.** Jangan acak.
4. **Reset data antar sesi** (`seed_big_test` idempoten + invariants).
5. **Catat sebelum memperbaiki.** Jangan fix saat UAT berjalan — catat, lanjut, fix setelah sesi.
6. **Offline & device wajib diuji** (Sesi 3). Fitur termahal = paling sering rusak.
7. **Verifikasi manual 1 angka per laporan** (Sesi 4). Jangan percaya agregasi tanpa cek.
8. **AI diuji dengan golden set + pertanyaan klien** (Sesi 5). Q3/Q6/Q8 boleh gagal — dicatat.
9. **Gate per sesi wajib.** Jangan lanjut bila gate gagal.
10. **1 sesi pytest pada satu waktu.** Test-DB sama.

---

## 11. Referensi

| Dokumen | Kegunaan |
|---|---|
| `docs/blueprint.md` v5.0 | Kontrak tingkat tinggi backend+frontend |
| `docs/CHANGES-DETAIL-H1H5.md` | Aturan H1–H5 |
| `current_project.json` | Status mesin (source of truth angka) |
| `django_app/docs/uat-checklist.md` | Checklist UAT Klien A (5 role) |
| `django_app/docs/onboarding-klien-baru.md` | 7 tahap onboarding |
| `django_app/docs/runbook-operasional.md` | Operasional harian/mingguan/bulanan |
| `django_app/docs/integration-config.md` | Konfigurasi per klien |
| `tests/golden/questions.yaml` | 30 pertanyaan golden set |
| `docs/recon/RECON_HORIZONTAL_2026-10-23.md` | Recon yang menemukan 6 lubang fatal |
| `docs/recon/DEMO_FIX_2026-10-23.md` | Riwayat fix demo AI |

---

## 12. Persetujuan

| Peran | Nama | Tanda tangan | Tanggal |
|---|---|---|---|
| Pemilik proyek | | | |
| UAT Lead | | | |
| Backend Lead | | | |
| Frontend Lead | | | |
| AI Lead | | | |

> **Catatan:** Dokumen ini adalah rencana. Hasil aktual dicatat di `04-hasil/`, temuan di `05-defect-log.md`, dan keputusan akhir di `06-signoff.md`. Rencana boleh direvisi bila gate gagal — revisi dicatat di bagian "Riwayat Revisi" (tambahkan di bawah).

---

## Riwayat Revisi

| Versi | Tanggal | Perubahan | Oleh |
|---|---|---|---|
| 1.0 | 2026-10-27 | Versi awal — 5 sesi + smoke + cross-cutting, gate, risiko | _(isi)_ |