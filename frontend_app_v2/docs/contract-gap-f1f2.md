frontend_app_v2/docs/contract-gap-f1f2.md
Catatan: File ini sudah BASYI — semua 19 TUNDA sudah teratasi di F2C.2 + F3A.CLOSE + F5.4.CLOSE. Kalau mau arsip, ganti dengan versi ini:

markdown

# Contract Gap F1/F2 — ARSIP (selesai 2026-10-10)

> **STATUS: ARSIP** — Semua 19 TUNDA sudah **TERATASI** di F2C.2 + F3A.CLOSE + F5.4.CLOSE.
> Dokumen ini disimpan sebagai referensi historis saja.

- **Tanggal asli:** 2026-10-09
- **Selesai:** 2026-10-10
- **Sumber backend asli:** `django_app/integrations/erp_sync/monitoring.py` (B1–B16 + B10/B11)

## Hasil Akhir

**Semua field UI kini punya sumber backend.** Frontend MODE = **47 real / 0 dummy**.

| Resource              | Status Akhir                                                              |
| --------------------- | ------------------------------------------------------------------------- |
| dashboard             | ✅ Flip (F2C.2) — `line_efficiency` + `trend[]` ditambah                  |
| bufferQueue           | ✅ Flip (F2C.2) — `from_wc`/`to_wc`/`status` ditambah                     |
| routing               | ✅ Flip (F2C.1) — DROP `capability`/`smv`/`maxWip`/`status` + auto-layout |
| qcLog                 | ✅ Flip (F2C.2 + F3A) — `defect_entries`/`action` ditambah                |
| qcRework              | ✅ Flip (F2C.2) — `from_step`/`to_step` masih null (limitasi backend)     |
| inventoryProducts     | ✅ Flip (F2C.1) — DROP `type`/`uom`                                       |
| inventoryOperations   | ✅ Flip (F2C.2) — beda domain diterima                                    |
| purchaseVendors       | ✅ Flip (F2C.2) — email/phone/city DIBUANG                                |
| purchaseOrders        | ✅ Flip (F2C.2) — `vendor_code`/`lines[]` ditambah                        |
| reportsLineEfficiency | ✅ Flip (F2C.2) — `label`/`unit`/`trend`/`series` ditambah                |
| reportsWIP            | ✅ Flip (F2C.2) — idem                                                    |
| purchaseReporting     | ✅ Flip (F2C.2) — `monthly_series`/`top_vendors` ditambah                 |

## Known Limitations yang Tetap Ada

Lihat `django_app/docs/known-limitations.md`:

- `BundleEvent` tidak punya `wc_id` → atribusi dari `bundle.current_work_center`
- `CycleInstance` tidak punya metadata → `from_step`/`to_step` selalu null
- `master.Partner` tanpa email/phone/city

**Dokumen lengkap versi asli** ada di Repomix / history git.
