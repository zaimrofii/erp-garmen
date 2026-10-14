# ⚠️ NOTICE UNTUK AI/DOKUMEN SELANJUTNYA

## BERLAKU SEJAK: 2026-10-10

---

## KONSEP LAMA (DEPRECATED — JANGAN DIPAKAI)

❌ "Odoo = tempat input master (Product/BOM/Partner/SO/PO)"
❌ "MES = hanya view + scan QR"
❌ "Klien buka 2 app: Odoo (input) + MES (monitor)"
❌ "Odoo = active, MES = passive monitor"

---

## KONSEP BARU (BERLAKU — GUNAKAN INI)

✅ "MES = ERP Produksi (single point of input)"
✅ "Klien buka 1 app saja: MES"
✅ "Semua input master & transaksi DI MES"
✅ "Odoo = back-office pasif (akuntansi, pajak, e-Faktur saja)"
✅ "Sync: dua arah master, satu arah transaksi (MES → Odoo)"

---

## ARSITEKTUR FINAL
┌─────────────────────────────────────────────────────────────┐
│ FRONTEND (MES) — Single Point of Input │
│ Semua form CRUD: Product, BOM, Order, PO, WO, Partner, │
│ WC, Line, Routing, Bundle, User, Device, dst. │
└──────────────────────┬──────────────────────────────────────┘
│ REST API
▼
┌─────────────────────────────────────────────────────────────┐
│ DJANGO (Source of Truth Produksi) │
│ - Master data: Product, BOM, Partner, WC, Line, Routing │
│ - Transaksi: Order, PO, WO, Bundle, Scrap, QC, Invoice │
│ - Sync engine: push ke Odoo saat event │
└──────────────────────┬──────────────────────────────────────┘
│ JSON-RPC (async via Celery)
▼
┌─────────────────────────────────────────────────────────────┐
│ ODOO (Back-office Pasif) │
│ - Akuntansi, pajak, e-Faktur, laporan keuangan │
│ - Stock move, journal, invoice (final) │
│ - User Odoo = akuntan saja, tidak untuk produksi │
└─────────────────────────────────────────────────────────────┘

text

**Prinsip:**
- Klien buka MES saja — untuk semua operasi produksi & bisnis
- Odoo = back-office (akuntan/pajak), opsional dibuka
- Sync dua arah di master, satu arah (MES → Odoo) untuk transaksi

---

## YANG HARUS DIIKUTI

1. **Setiap form baru** → buat di MES, JANGAN arahkan user ke Odoo
2. **Setiap CRUD master** → endpoint MES dulu, sync Odoo kedua
3. **Setiap laporan bisnis** → sediakan di MES, Odoo hanya formal
4. **Setiap UI** → single app, JANGAN embed Odoo/iframe
5. **Setiap dokumentasi baru** → pakai konsep baru ini

---

## MIGRASI FASE LAMA

| Fase Lama | Status | Catatan |
|---|---|---|
| F1–F7 (frontend track v3) | ✅ Valid | Fokus backend produksi & integrasi |
| I1–I8 (integrasi ERP) | ✅ Valid | Sync master & transaksi |
| Blueprint v4.3 §1 "Mental Model" | ❌ **DIGANTI** | Ganti dengan konsep baru di atas |

**Semua dokumen lama yang bertentangan:** abaikan, ikuti dokumen ini.

---

## FASE SELANJUTNYA (H1–H5)

| Fase | Isi | Estimasi |
|---|---|---|
| **H1** | Master CRUD (Product, Partner, BOM, UoM, Warehouse, WC, Line, Routing) | 1 minggu |
| **H2** | Transaksi (SO, PO, WO, Bundle, Inventory) | 1.5 minggu |
| **H3** | Finance (Invoice, Bill, Payment, Journal) | 1 minggu |
| **H4** | Laporan (Sales, Purchases, Stock, HPP, PnL) | 1 minggu |
| **H5** | Settings (Company, Currency, Sequence, Permission, Audit) | 1 minggu |
| **TOTAL** | **MES = ERP produksi lengkap** | **~5–6 minggu** |

**Target:** MES = ERP produksi lengkap, 1 app untuk semua operasi. Odoo opsional untuk akuntansi formal.

---

## CATATAN UNTUK AI

Kalau ada dokumen lama (current_project.json, blueprint.md, api-contract.md, dll) yang masih menyebut **"Odoo untuk input"** → **abaikan**. Ikuti dokumen ini.

**File yang sudah deprecated (jangan dibaca):**
- `anti-pattern-audit.md` (root) → pindah ke arsip
- `api-contract.md` (root) → pindah ke arsip
- `blueprint.md` (root) → pindah ke arsip, ganti dengan `docs/blueprint-v4.md` (baru)
- `contract-gap-f1f2.md` (root) → pindah ke arsip
- `current-project.json` (root) → pindah ke arsip

**File yang berlaku (baca ini):**
- `docs/REPLACE-NOTICE.md` (dokumen ini)
- `docs/CHANGES-DETAIL-H1H5.md` (detail perubahan)
- `django_app/docs/curent_project.json` (status backend)
- `frontend_app_v2/docs/current-project.json` (status frontend)

---

## KONTAK

Kalau ada keraguan tentang konsep → STOP, tanya ke pemilik proyek. Jangan asumsi.

**Dokumen ini berlaku sampai ada notice resmi pengganti.**