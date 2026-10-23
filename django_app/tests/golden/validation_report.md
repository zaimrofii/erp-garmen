# Putaran Validasi — Desain Tool, Scorer, Golden 30, 2 Model (2026-10-23)

## 1. Langkah 1–4 (tanpa LLM)

| Langkah | Status | Bukti |
|---|---|---|
| 1. Desain 7 tool | **PASS** | `pytest tests/golden/test_tools_v3.py` → **11/11** |
| 2. Scorer (exact vs toleransi, G006) | **PASS** | `pytest tests/golden/test_scoring_v4.py` → **9/9** |
| 3. Golden 30 (20 tuning + 10 held-out) | **PASS** | `grep -c '^- id:'` = **30**; held_out = **10**; verified = **30** |
| 4. scrap_rate v2 (kohort DONE) | **PASS** | `pytest tests/analytics/` → **205 passed** |

Perubahan yang dikunci:
- `get_metric` kini mengembalikan `stats {avg, latest, min, max, count, sum}` + `series` + `warnings`.
- `list_records`/`get_record` order menambah `is_late`, `days_late`, `days_remaining`.
- `date_from`/`date_to` ada di schema list/count/aggregate (default: tanpa filter bila kosong —
  deviasi sadar dari "default 7 hari" karena akan merusak pertanyaan snapshot).
- `find_entity` → `{matches, ambiguous, count}`; `get_stock` → envelope lengkap.
- GT: exact untuk count/harga; toleransi 2% hanya `approx` (persen/avg/durasi).
- `scrap_rate` v2: numerator & denominator kohort bundle DONE, denominator 0 → 0, clamp ≤100,
  `formula_version = 2.0`.

## 2. Langkah 5 — Tuning (20 pertanyaan × 3 run)

| Model | Tool | Param | E2E (20) | E2E (18) | Angka salah | Biaya |
|---|---:|---:|---:|---:|---:|---:|
| DeepSeek | **100,0%** | **88,3%** | **58,3%** | **61,1%** | **6,7%** | $0.04619818 |
| Gemini | — | — | — | — | — | **tidak tersedia** |

Gemini tidak dijalankan: `AI_LLM_GEMINI_API_KEY` berisi kredensial non-Google
(bukan `AIza...`), percobaan pertama menghasilkan HTTP 400.

## 3. Langkah 6 — Held-out (10 pertanyaan × 3 run, DeepSeek)

| Metrik | Nilai | Target |
|---|---:|---:|
| Tool selection | **80,0%** | ≥90% ✗ |
| Parameter | **93,3%** | — |
| E2E | **60,0%** | ≥80% ✗ |
| Angka salah | **16,7%** | 0% ✗ |
| Biaya | $0.02201626 | — |

Gagal e2e: G024 (operator), G027 (produk tanpa order line), G028 (scrap Des 2025),
G022 (2 dari 3 run), G029 (1 run).

## 4. Diagnosis kegagalan (held-out)

1. **Tool kurang (nyata)**: G024 butuh agregasi per operator (tidak ada entity/metrik);
   G027 butuh relasi produk→order_line (tidak ada di allowlist filter). 2/10 pertanyaan
   mustahil dijawab dengan 7 tool saat ini.
2. **Artefak skor**: G027 dijawab benar (34) tetapi `expected_tool=None` sehingga tool
   dianggap salah; G022/G001 memakai `find_entity` lebih dulu sehingga parameter dinilai
   dari tool pertama.
3. **Sintesis/prompt**: G009 memakai `stats.latest` (191,86) walau `stats.avg` tersedia;
   G028 menyebut 0 tanpa penanda "tidak ada data".
4. **Definisi/wording**: G013/G028 bergantung pada daftar kata no_data yang sempit.

## 5. Perbandingan dengan spike-3 B

| Sumber | E2E | Angka salah |
|---|---:|---:|
| spike-3 B (15 pertanyaan) | 61,5% | 13,3% |
| Validasi tuning (20) | 58,3% (18: 61,1%) | 6,7% |
| Validasi held-out (10) | **60,0%** | 16,7% |

Tidak ada kenaikan e2e yang berarti; angka salah tuning turun, tetapi held-out masih 16,7%.
Perbaikan desain tool menaikkan tool selection tuning ke 100% dan parameter ke 93,3%,
namun belum menutup gap sintesis dan dua tool yang hilang.

## 6. Biaya

| Tahap | Biaya |
|---|---:|
| Tuning run #1 (crash sebelum simpan) | $0.046349 (estimasi dari log) |
| Tuning run #2 (final) | $0.04619818 |
| Held-out run #1 (mapping salah) | $0.021113 (estimasi dari log) |
| Held-out run #2 (final) | $0.02201626 |
| **Total putaran** | **≈$0.13567644** |
| **Kumulatif proyek** | **≈$0.19474412** dari $0.66 |

## 7. Rekomendasi (dari held-out)

**PERBAIKI DESAIN TOOL**, spesifik:
1. Tambah metrik/entity `operator_output` (G024) dan relasi `product.order_lines` di filter (G027).
2. Nilai parameter pada tool yang benar di seluruh rantai, bukan tool pertama (artefak G001/G019/G022).
3. Prompt+validator: wajib memakai `stats.avg` untuk "rata-rata"; wajib menyebut
   "tidak ada data" saat `stats.count == 0`.
4. Perluas definisi no_data (mis. "0 record", "kosong") sebelum run berikutnya.

Gate held-out belum lolos (tool 80% <90, e2e 60% <80, angka salah 16,7% >0). Jangan masuk Fase 1.
