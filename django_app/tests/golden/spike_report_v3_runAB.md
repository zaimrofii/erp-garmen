# Spike-3 Run A+B Final (2026-10-23)

## 1. Konfirmasi pra-run

- Parser **v3-fixed-3** (commit `8a0373f`): **45/45 PASS** (64/64 seluruh `tests/golden/`).
- Aturan skor: **strict** terkunci (`allow_range=false`, `must_match_tool_output=true`, derived 5%).
- Tool: **7 generik**, tidak berubah. Model `deepseek-chat`, temperature 0.

## 2. Skor A — single-turn (15/15 selesai)

| Metrik | Nilai |
|---|---|
| tool_selection | **86,7%** |
| parameter | **80,0%** |
| e2e dari 13 | **61,5%** (8/13) |
| e2e dari 15 | **53,3%** (8/15) |
| angka_salah | **0,0%** (0/15) |
| latensi p50 / p95 | **2.510,6 ms / 3.444,7 ms** |
| biaya | $0.00503454 |

## 3. Skor B — multi-turn ≤2 putaran (15/15 selesai)

| Metrik | Nilai |
|---|---|
| tool_selection | **100,0%** |
| parameter | **93,3%** |
| e2e dari 13 | **61,5%** (8/13) |
| e2e dari 15 | **53,3%** (8/15) |
| angka_salah | **13,3%** (2/15) |
| latensi p50 / p95 | **2.665,7 ms / 4.205,8 ms** |
| biaya | $0.00752038 |

## 4. Per pertanyaan

| ID | Kategori | Tool A | Tool B | Lulus A | Lulus B | Salah A | Salah B | Sebab |
|---|---|---|---|---|---|---|---|---|
| G001 | wip | count_records | count_records | ✓ | ✓ | 0 | 0 | — |
| G002 | scrap | get_metric→aggregate | aggregate | ✓ | ✗ | 0 | 0 | (b) tanpa filter periode → 209 vs 77 |
| G003 | order_telat | list_records | list_records | ✗ | ✗ | 0 | 2* | (c) menjawab deadline terdekat, bukan "tidak ada" |
| G004 | produktivitas | get_metric | get_metric | ✗ (excl) | ✗ (excl) | 0 | 0 | (a) metrik operator tidak ada; B: DSML unparseable |
| G005 | harga | list_records | list_records | ✓ | ✓ | 0 | 0 | — |
| G006 | stok | get_stock | get_stock | ✗ | ✗ | 0 | 1* | (b/e) param token "kaos"; B: "2 produk" di luar tool |
| G007 | customer | count_records→aggregate | aggregate | ✗ | ✓ | 0 | 0 | (e) skenario A hanya menghitung tool pertama |
| G008 | scrap_rate | find_entity→get_metric | get_metric | ✗ (excl) | ✗ (excl) | 0 | 0 | (d) formula scrap_rate (Fase 0.4) |
| G009 | lead_time | get_metric | get_metric | ✗ | ✗ | 0 | 0 | (c) memakai nilai hari terakhir (191,86) bukan rata-rata (77,64) |
| G010 | followup_ordinal | list_records | list_records | ✓ | ✓ | 0 | 0 | — |
| G011 | negasi | count_records | count_records | ✓ | ✓ | 0 | 0 | — |
| G012 | out_of_scope | — | — | ✓ | ✓ | 0 | 0 | — |
| G013 | data_kosong | aggregate→count | aggregate→count | ✓ | ✓ | 0 | 0 | — |
| G014 | safety | list_records | — | ✓ | ✓ | 0 | 0 | — |
| G015 | majemuk | count_records→list | count_records→list | ✗ | ✗ | 0 | 0 | (c/d) klausa "paling lambat" tidak terjawab |

\* Artefak angka (tidak diperbaiki mid-run): G003-B memuat pecahan tanggal/jam
("1", "3"); G006-B menyebut "2 produk lokal" yang tidak berasal dari tool.

## 5. Diagnosis 3 kegagalan terbesar

1. **Sintesis agregasi (G009, G015)** — model menyalin nilai terakhir/daftar
   harian, tidak menghitung rata-rata atau menjawab klausa kedua.
   → bisa diselamatkan **Fase 2** (prompt synthesizer + validator angka).
2. **Periode/parameter (G002)** — `aggregate` tanpa filter tanggal → total
   sepanjang waktu (209) bukan minggu ini (77). → **Fase 2** (schema hint periode
   + validator), bukan tool baru.
3. **Definisi/skor (G006, G003)** — jawaban 30 benar tetapi gagal aturan token;
   G003 memilih interpretasi "deadline terdekat". → **Fase 2** (perbaiki
   ekspektasi skor & prompt definisi), G008 tetap **Fase 0.4**.

Ringkas: 4 dari 5 kegagalan yang dihitung bisa diperbaiki di **Fase 2**
(prompt/validator), 0 butuh tool baru mendesak, 1 menunggu **Fase 0.4**.

## 6. Biaya

A = $0.00503454 · B = $0.00752038 · **total = $0.01255492** ·
kumulatif **$0.05906768** dari $0.080. **Runs used: 1** (tidak ada run ulang).

## 7. Perbandingan

| Sumber | Angka | Catatan |
|---|---|---|
| spike-2 | e2e_13 B 60,0% | tidak valid (koreksi post-hoc) |
| spike-3 run #1 | e2e_13 A 61,5% | parser rusak |
| spike-3 A-only | e2e_13 A 61,5% | parser 2 bug |
| **run A+B ini** | **A 61,5% · B 61,5%** | parser 45/45, aturan ketat |

Tidak ada kenaikan e2e dibanding run sebelumnya (+0,0 poin); yang naik adalah
**kualitas pengukuran** (angka_salah A 0%, tool selection B 100%). Multi-turn
tidak lagi menambah e2e karena kegagalan tersisa bersifat sintesis/definisi,
bukan jumlah putaran.

## 8. Keputusan gerbang

e2e_13(B) = **61,5% < 70%** → **BERHENTI**: jalur tool-calling dengan 7 tool
generik belum layak masuk Fase 1; fokus dulu ke Fase 2 (prompt + validator
angka) dan Fase 0.4 (formula), lalu ulangi pengukuran ini.
