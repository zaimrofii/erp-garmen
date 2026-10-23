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

---

# Putaran Perbaikan A — Fix Skor, 2 Tool Baru, Prompt + Validator (2026-10-23)

Basis: HEAD `72334bd`; tree bersih; DeepSeek saja; hard cap $0.05.

## 1. Langkah 1–3 (tanpa LLM) — PASS

| Langkah | Status | Bukti |
|---|---|---|
| 1. Fix skor (param lintas-rantai, `expected: null`) | **PASS** | `pytest tests/golden/test_scoring_v5.py` → **8/8** |
| 2. Tool 8 `aggregate_operator` + tool 9 `get_product_orders` | **PASS** | `pytest tests/golden/test_tools_v4.py` → **8/8** |
| 3. Prompt synthesizer + validator angka | **PASS** | `pytest tests/golden/test_validator_v1.py` → **6/6** |
| Regresi suite golden | **PASS** | `pytest tests/golden` → **107 passed** |

Perubahan:
- Parameter dinilai dari **seluruh rantai tool** (ada satu tool yang cocok → LULUS).
- `expected: null` (G012/G014/G027/G029): baca dulu lalu menolak = LULUS; tidak ada tool tulis.
- Prompt: `stats` → field sesuai pertanyaan, `count = 0` → "Tidak ada data", multi-klausa, tool kurang.
- Validator: setiap angka jawaban harus ada di hasil tool (exact integer, 2% desimal);
  jika minta rata-rata → wajib `stats.avg`; pelanggaran → jawaban diganti + `validator_blocked`.

## 2. Held-out (DeepSeek, mode B, 3 run × 10) — TIDAK dipakai untuk tuning

| Metrik | Sebelum | Sekarang | Δ |
|---|---|---|---|
| Tool selection | 80,0% | **100,0%** | +20,0 |
| Parameter | 93,3% | **83,3%** | −10,0 |
| E2E | 60,0% | **56,7%** | −3,3 |
| Angka salah | 16,7% | **0,0%** | −16,7 |
| Validator blocked | — | **5/30 (16,7%)** | — |

Kegagalan (semua sebelum validator, tidak dikoreksi):
- **G024** 0/3: parameter dinilai `must:["operator"]` padahal tool tidak punya field itu
  (artefak skor), dan GT 17 (qty) vs jawaban model (jumlah event) — semantik tool ambigu.
- **G027** 0/3: jawaban benar 34 **diblokir validator** karena 34 hasil turunan, bukan angka mentah tool.
- **G028** 0/3: scrap Des 2025 dijawab 262 (nilai all-time) — tidak ada deteksi periode kosong.
- **G030** 1/3: 2 run diblokir validator untuk angka turunan (100/15).
- **G022** 1/3 gagal parameter (artefak: filter memakai id, bukan teks "qc-1").

## 3. Tuning (DeepSeek, 1 run × 20) — regresi

E2E **40,0%** (sebelumnya 58,3%), angka salah **0,0%**, `validator_blocked` **6/20**.
Regresi terutama dari validator yang memblokir angka turunan yang sah (G010/G016/G017/G020)
dan DSML bocor di G003. Perbandingan 1 run vs 3 run sebelumnya = derau, bukan tren.

## 4. Biaya

| Item | USD |
|---|---|
| Held-out (30 panggilan) | 0,02560978 |
| Tuning (20 panggilan) | 0,01542898 |
| **Total putaran** | **0,04103876** (cap 0,05) |
| **Kumulatif proyek** | **0,23578290** dari 0,66 |

## 5. Rekomendasi: BERHENTI

Gate held-out: e2e 56,7% < 60% (tool 100%, angka salah 0%). Sesuai aturan gerbang → **BERHENTI**;
jangan masuk Fase 1. Bukti pendukung: validator menaikkan presisi angka (16,7% → 0%) tetapi
menurunkan e2e (blokir palsu 16,7% held-out, 30% tuning), dan 2 tool baru tidak menutup
G024/G027 karena masalahnya semantik tool + artefak penilaian, bukan kelengkapan tool.

