# Spike Function Calling — LAPORAN FINAL (2026-10-22)

**Model diuji:** `deepseek-chat` (DeepSeek) — **hanya satu model**.
`AI_LLM_GEMINI_API_KEY` tidak ada di environment (hanya `AI_LLM_API_KEY`),
jadi Gemini tidak bisa diuji tanpa menambah kredensial. Tidak ada key yang
di-hardcode.

**Setup:** 3 tool throwaway (`list_records`, `count_records`, `get_metric`),
temperature 0, loop maks 3 putaran, 15 pertanyaan golden, masing-masing
percakapan baru.

## Hasil (run final)

| Metrik | Nilai |
|---|---|
| Akurasi tool selection | **73,3%** (11/15) |
| Akurasi parameter | **66,7%** (10/15) |
| Akurasi end-to-end (strict) | **33,3%** (5/15) |
| End-to-end longgar (refusal benar dihitung) | 40,0% (6/15) |
| Biaya run final | **$0.00577458** |
| Biaya seluruh spike (4 run) | **$0.023135** |
| Token | 36.625 prompt / 2.311 completion |
| Latensi | p50 2.105 ms · p95 3.616 ms · max 5.311 ms |

Lulus e2e: G005 (harga), G010 (ordinal), G011 (negasi), G012 (out-of-scope),
G014 (safety).

| ID | Tool dipilih | Param | GT | E2e | Catatan |
|---|---|---|---|---|---|
| G001 | count_records | ✓ | ✗ | ✗ | Jawab 22 (semua bundle di SEWING-2), GT 6 (REWORK) — ambiguitas "sedang dikerjakan" |
| G002 | get_metric | ✗ | ✗ | ✗ | Tidak ada tool scrap per work center |
| G003 | list_records | ✓ | ✗ | ✗ | Urutkan deadline, tidak mendeteksi "tidak ada yang telat" |
| G004 | get_metric | ✗ | ✗ | ✗ | Tidak ada metrik output operator |
| G005 | list_records | ✓ | ✓ | ✓ | Jaket Bomber Rp250.000 |
| G006 | list_records | ✗ | ✗ | ✗ | Stok bukan entity yang diizinkan |
| G007 | list_records | ✗ | ✗ | ✗ | 50 baris terpotong; model bilang butuh tool agregasi |
| G008 | get_metric | ✓ | ✗ | ✗ | Metrik hanya level pabrik/harian, bukan per WC |
| G009 | get_metric | ✓ | ✗ | ✗ | Menyajikan per hari (satuan hari), tidak menghitung rata-rata |
| G010 | list_records | ✓ | ✓ | ✓ | Peringkat FG benar |
| G011 | count_records | ✓ | ✓ | ✓ | 0 produk nonaktif |
| G012 | — | ✓ | ✓ | ✓ | Menolak, di luar cakupan |
| G013 | get_metric | ✗ | ✓ | ✗ | Jawaban benar ("tidak tersedia") tapi memanggil tool (ekspektasi: tanpa tool) |
| G014 | — | ✓ | ✓ | ✓ | Menolak hapus, 0 write |
| G015 | count_records | ✓ | ✗ | ✗ | Jawab 5 (IN_PROGRESS), GT 43 (state != DONE) — ambiguitas "aktif" |

Kategori dengan **e2e 0%**: wip, scrap, order_telat, produktivitas, stok,
customer, scrap_rate, lead_time, data_kosong, majemuk.
Kategori 100%: harga, followup_ordinal, negasi, out_of_scope, safety.

## Diagnosis (kenapa e2e rendah padahal tool selection 73%)

1. **Cakupan tool (4 kasus):** stok, output operator, scrap per WC, dan
   agregasi per customer tidak bisa diekspresikan oleh 3 tool.
2. **Tidak ada tool agregasi/group-by (2):** G007, G008 — model benar
   menyatakan butuh agregasi, tetapi jawaban akhir jadi tidak ada.
3. **Ambiguitas definisi di golden set (2):** G001 "sedang dikerjakan"
   (REWORK vs semua state) dan G015 "order aktif" (IN_PROGRESS vs != DONE).
   Perlu definisi eksplisit di pertanyaan/GT.
4. **Sintesis jawaban (2):** G003 salah membaca "telat", G009 salah satuan.
5. **Artefak skoring (1):** G013 benar menolak tetapi tetap memanggil tool.

Jadi **bottleneck utama = desain tool/skema, bukan kemampuan memilih tool.**
Tool selection 73% menunjukkan model memahami intent Bahasa Indonesia informal.

## Rekomendasi (sesuai aturan gerbang)

**BERHENTI** — e2e 33,3% < 60% (baseline jalur lama 20,0%; tool selection
73,3%). Aturan menyebut eskalasi model, tetapi bukti menunjukkan penyebabnya
**cakupan tool**, sehingga mengganti model tidak akan menutup gap:
4 dari 10 kegagalan tidak punya tool yang cocok sama sekali.

Urutan perbaikan yang disarankan sebelum mengulang spike (sekali):
1. Tambah parameter dimensi ke metrik (`work_center`, `line`, `group_by`,
   rentang tanggal bebas) — menutup G002, G008.
2. Tambah entity `inventory_item`/`stock` dan metrik `operator_output` —
   menutup G006, G004.
3. Tambah tool agregasi (`aggregate(entity, group_by, metric, filters)`) —
   menutup G007.
4. Enumerasi field yang boleh difilter per entity di JSON Schema (sudah
   ditambahkan sebagian) + larang sort field tak dikenal — mengurangi
   percobaan tool yang gagal.
5. Perjelas definisi GT: "sedang dikerjakan" dan "order aktif".

Kalau setelah perbaikan itu e2e masih <60%, baru eskalasi model
(Gemini belum bisa diuji: kredensial tidak tersedia).

## Catatan metodologi

- Run #1 (14 pertanyaan) gagal di G015 karena runner hanya menangani satu
  `tool_call`; run #2/#3 memperbaiki loop; run #4 memperbaiki bug validator
  filter (`current_work_center__code` selalu ditolak) + menambah hint field.
  Angka run #2/#3 = run #4 (73,3/66,7/33,3); bug validator tidak mengubah
  agregat karena G001 tetap gagal pada definisi GT.
- Semua tool read-only; tidak ada perubahan data selama spike selain baris
  audit yang tidak dibuat (spike memanggil DAL langsung, bukan endpoint).
- Biaya dihitung dari `usage` respons DeepSeek dengan tarif di `AI_CONFIG`
  ($0,00014/1K prompt, $0,00028/1K completion).

