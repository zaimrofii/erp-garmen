# Spike-3 Final — STATUS: **BLOCKED** (run tidak sah, B tidak dijalankan)

## 1. Alat ukur

| Komponen | Status |
|---|---|
| Parser | **v3-fixed-2** — `ignore_years` (rentang), desimal "0.375" tidak lagi jadi 375, rentang tanggal "1–31 Januari" diabaikan. 19 test hijau. |
| Aturan skor | **strict** (allow_range=false, allow_mean_sum=false, must_match_tool_output=true, derived 5%) |
| `<｜｜DSML｜｜>` | aktif (strip + recover JSON/invoke) |
| Tool | tetap 7 generik (tidak ada tool baru) |

## 2. Skor (run #2, A saja)

| Skenario | Tool | Param | e2e/13 | e2e/15 | Angka salah |
|---|---:|---:|---:|---:|---:|
| A single-turn (15/15) | **100,0%** | **93,3%** | **61,5%** (8/13) | **53,3%** (8/15) | **13,3%** (2 baris) |
| B multi-turn | **n/a** | n/a | n/a | n/a | n/a |

B **tidak dijalankan** (aturan: jangan mulai B bila budget tidak cukup).

## 3. Per pertanyaan (A)

| ID | Kategori | Tool A | Lulus A | Angka salah A |
|---|---|---|---|---|
| G001 | wip | count_records | ✓ | 0 |
| G002 | scrap | aggregate | ✗ | 0 |
| G003 | order_telat | list_records | ✗ | 0 |
| G004 | produktivitas | get_metric | ✗ (excl) | 0 |
| G005 | harga | list_records | ✓ | 0 |
| G006 | stok | get_stock | ✗ (param) | 0 |
| G007 | customer | aggregate | ✓ | 0 |
| G008 | scrap_rate | get_metric | ✗ (excl) | 0 |
| G009 | lead_time | get_metric | ✗ | 1* |
| G010 | followup_ordinal | list_records | ✓ | 0 |
| G011 | negasi | count_records | ✓ | 0 |
| G012 | out_of_scope | — | ✓ | 0 |
| G013 | data_kosong | aggregate→count | ✓ | 1* |
| G014 | safety | — | ✓ | 0 |
| G015 | majemuk | count_records→list | ✗ | 0 |

\* Keduanya **cacat parser**: "0.375" (JSON desimal) terbaca 375; "1–31 Januari"
terbaca 31. Parser sudah diperbaiki **setelah** run, jadi angka_salah run ini
tidak sah (e2e tidak terpengaruh karena tidak memakai aturan angka_salah).

## 4. Run yang dipakai

2 run total: run #1 (9e82186, invalid), run #2 (ini, A saja) — **tidak ada angka
final yang sah**. Tidak ada koreksi post-hoc.

## 5. Diagnosis kegagalan tersisa

| Sebab | Pertanyaan | Bukti |
|---|---|---|
| (b) parameter | G006 | `must` mengharapkan token "kaos", model memakai kode `ODOO-65` → jawaban 30 sebenarnya benar |
| (c) sintesis | G009 | memakai nilai hari terakhir (191,86) bukan rata-rata mingguan (77,64) |
| (d) definisi | G015 | filter state salah → 0 order (GT 15) |
| (a/e) lain | G002, G003 | agregat tanpa filter periode; G003 tidak menyimpulkan "tidak ada" |
| excluded | G004, G008 | metrik operator belum ada; formula scrap_rate salah |

## 6. Perbandingan spike-2

Spike-2 (B, setelah koreksi) e2e_13 = 60,0%; spike-3 A = 61,5% — praktis setara
(+1,5 poin), jadi 5 perbaikan belum mengubah e2e secara material pada skenario A.

## 7. Biaya

- Run ini: **$0.00475608** (A saja).
- Kumulatif: **$0.05126884** dari $0.065 (sisa **$0.01373116**).
- Untuk run ulang bersih A+B dibutuhkan ≈ $0.0135 — **melebihi** sisa hard-cap
  $0.015 tugas ini (sudah terpakai $0.00476) meski masih di dalam budget proyek.

**Keputusan: BLOCKED.** Butuh tambahan ~$0.004–0.005 untuk satu run bersih A+B
dengan parser v3-fixed-2; atau terima angka A-only (e2e_13 61,5%) sebagai
indikatif.

---

## 8. Verifikasi parser (2026-10-23, $0, tanpa LLM)

- **45 test parser komprehensif** (`tests/golden/test_parser_comprehensive.py`):
  **45/45 PASS** (64/64 PASS untuk seluruh `tests/golden/`).
- Bug parser yang ditemukan & diperbaiki saat penulisan test:
  1. `2 rb` → 2000 dianggap "tahun" (filter tahun 2000–2100) → **fixed**: filter
     tahun tidak berlaku bila ada kata skala.
  2. `1,234.56` (ribuan Inggris) → 123456 → **fixed**: cabang ribuan Inggris.
  3. `5-10 unit` → hanya 5 → **fixed**: rentang angka dipecah.
  4. `22/10/2026` & `22 Oktober 2026` → 22 (dan 10) terbaca → **fixed**:
     tanggal ISO/slash/naratif dibuang.
  5. `SO-2026-0040` berisiko terbaca 40 setelah pemecahan rentang → **fixed**:
     token kode (huruf+digit) dibuang lebih dulu.
  6. Pool angka hasil tool kini dibaca dari **struktur JSON**
     (`numbers_in_results`), bukan regex teks → `0.375` tidak lagi jadi 375.
- **Verifikasi jawaban nyata** (spike-2, dijalankan ulang tool-nya dengan
  parameter tersimpan, tanpa LLM): G005, G010, G014 → **3/3 ground truth cocok**
  dan **angka_salah = 0** untuk ketiganya.

