# Spike-3 — 5 Perbaikan + Anti-Koreksi-Post-Hoc (STATUS: **BLOCKED**)

**Model:** `deepseek-chat`. **Aturan skor:** `spike_scoring_rules.md` (ditulis sebelum run).
**Run yang dipakai:** 1 (run ini) — **INVALID untuk gerbang** karena dua hal:
1. Skenario B **abort di G008** (budget $0.0097 habis; 8/15 pertanyaan).
2. Ditemukan **bug parser** `ignore_years` (dibaca sebagai daftar 2 nilai, bukan
   rentang 2000–2100) sehingga tahun "2026" dihitung sebagai angka salah.

Sesuai aturan anti-koreksi: bug **diperbaiki di kode** (bukan hasil), tetapi
**run ulang belum dilakukan** karena budget tidak cukup. Karena itu angka di
bawah adalah angka mentah run #1, bukan angka final.

## Perbaikan (P1–P6)

| # | Perbaikan | Status |
|---|---|---|
| P1 | `definition_system` dikirim ke system prompt | **Ya** — G001 pulih (6 bundle) |
| P2 | `completed_at` di `OrderRepository.serialize_fields` (1 field) | **Ya** — 24 test data-access/DAL hijau |
| P3 | Label dimensi metrik = kode (bukan id) | **Ya** — output "SEWING-2" (bukan 56) |
| P4 | `aggregate` ≡ `get_metric` untuk G002 | **Ya** — G002 lulus di A dan B |
| P5 | Prompt: jawab semua klausa + rata-rata tegas | **Ya** — G008/G009 masih gagal (lihat diagnosis) |
| P6 | G004 & G008 dikecualikan dari e2e | **Ya** — e2e_dari_13 dilaporkan terpisah |

## Hasil run #1 (mentah)

| Skenario | Cakupan | Tool | Param | e2e/13 | e2e/15 | Angka salah |
|---|---|---:|---:|---:|---:|---:|
| A single-turn | 15/15 | 93,3% | 86,7% | **61,5%** (8/13) | 53,3% (8/15) | 6,7% |
| B multi-turn | **8/15 (abort)** | 100% | 87,5% | 66,7% (6/8*) | 50,0% (4/8*) | 12,5% |

\* Denominator B bukan 13/15 karena run berhenti; tidak sebanding dengan A.

Biaya run: **$0.00944706**. Kumulatif: **$0.04651276** dari $0.05 (sisa $0.00349).

## Per pertanyaan

| ID | Kategori | Tool A | Tool B | Lulus A | Lulus B |
|---|---|---|---|---|---|
| G001 | wip | count_records | count_records | ✓ | ✓ |
| G002 | scrap | get_metric→aggregate | get_metric→aggregate | ✓ | ✓ |
| G003 | order_telat | list_records | list_records×2 | ✗ | ✗ |
| G004 | produktivitas | get_metric | get_metric | ✗ (excl) | ✗ (excl) |
| G005 | harga | list_records | list_records | ✓ | ✓ |
| G006 | stok | get_stock | get_stock | ✗* | ✗* |
| G007 | customer | count_records→aggregate | aggregate | ✗* | ✓ |
| G008 | scrap_rate | get_metric | get_metric | ✗ (excl) | ✗ (excl) |
| G009 | lead_time | get_metric | — (abort) | ✗ | n/a |
| G010 | followup_ordinal | list_records | — | ✓ | n/a |
| G011 | negasi | count_records | — | ✓ | n/a |
| G012 | out_of_scope | — | — | ✓ | n/a |
| G013 | data_kosong | aggregate→count | — | ✓ | n/a |
| G014 | safety | — | — | ✓ | n/a |
| G015 | majemuk | count_records→list | — | ✗ | n/a |

\* **G006 & G007-A jawabannya benar** (30 unit; Gemini 17 order) tetapi gagal
karena aturan skor: G006 diekspektasikan memuat token "kaos" padahal model
memakai kode `ODOO-65`; G007-A menghitung tool pertama (`count_records`) padahal
jawaban benar diperoleh dari tool kedua. Ini kelemahan **desain skor**, bukan
jawaban — dicatat, tidak dikoreksi post-hoc.

## Kegagalan yang masih ada

| Sebab | Pertanyaan | Bukti |
|---|---|---|
| Model mengeluarkan markup `<｜｜DSML｜｜>` alih-alih tool-call | G004 (A/B), G003 (B) | jawaban mentah berisi tag, bukan angka |
| Definisi "aktif" belum dipakai model saat memfilter | G015 | menjawab 0 order (filter `state` salah nilai) |
| Sintesis agregasi | G009 | memakai nilai hari terakhir (191,86) bukan rata-rata mingguan (77,64) |
| Formula metrik masih lama (di luar scope) | G008 | 192,5% vs GT 70% (Fase 0.4) |
| Metrik operator belum ada (Fase 1) | G004 | `metric_not_available` |
| Skor/ekspektasi token | G006, G007-A | lihat catatan di atas |

## Kesimpulan

- P1–P5 terbukti menaikkan mutu: **G001 pulih**, **G002 lulus di A**, label
  metrik benar, dan B mengalahkan A pada pertanyaan yang butuh tool kedua.
- Angka gerbang **belum sah**: B tidak selesai dan parser punya bug yang sudah
  diperbaiki tetapi belum dijalankan ulang.
- **Keputusan: BLOCKED.** Untuk menyelesaikan gerbang dibutuhkan run ulang penuh
  (A+B, 15 pertanyaan) ≈ **$0.013–0.014**; sisa budget $0.00349 tidak cukup.
- Rekomendasi sementara (indikatif, bukan gerbang): e2e 61,5% (A) / 66,7%
  (B-parsial) → di bawah 70% → **jangan lanjut Fase 1** sebelum run ulang.
