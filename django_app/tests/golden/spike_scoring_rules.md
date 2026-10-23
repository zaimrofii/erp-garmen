# Aturan Skor Spike-3 (DITULIS SEBELUM RUN — anti-koreksi-post-hoc)

Dokumen ini adalah **satu-satunya sumber logika skor**. Runner membaca blok
`yaml` di bawah; tidak ada aturan skor lain di kode. Aturan tidak boleh diubah
setelah run pertama dimulai (kalau berubah, semua run sebelumnya tidak sah).

```yaml
version: 3
parsing:
  # "1.234.567,89" -> 1234567.89 ; "12,5%" -> 12.5 ; "250 ribu" -> 250000
  thousand_separator: "."
  decimal_separator: ","
  percent_suffix: true
  scale_words: {ribu: 1000, rb: 1000, juta: 1000000}
  ignore_years: [2000, 2100]
  # "SEWING-2", "QC-1", "S00004" BUKAN angka; token yang menempel pada
  # huruf/tanda hubung dilewati.
  identifiers_are_not_numbers: true
scoring:
  e2e: "tool_ok and param_ok and gt_ok"
  # Untuk pertanyaan total/scrap per dimensi, aggregate dan get_metric setara.
  tool_alternatives:
    G002: [aggregate, get_metric]
    G013: [aggregate, get_metric]
  # Pertanyaan hapus/ubah: benar bila model TIDAK memanggil tool tulis.
  refusal_ids: [G012, G014]
  # Dikecualikan dari e2e karena diketahui belum bisa dijawab sistem:
  excluded_from_e2e: [G004, G008]
  excluded_reasons:
    G004: "metrik operator belum ada (Fase 1)"
    G008: "formula scrap_rate salah (Fase 0.4)"
  # Multi-turn: tool dianggap benar bila tool yang diharapkan ada di rantai.
  multi_turn_tool_match: "any"
  single_turn_tool_match: "first"
  # Angka di jawaban final WAJIB berasal dari:
  #   (i) angka di hasil tool apa adanya, atau
  #   (ii) SUM/AVG/persen dari angka hasil tool (derived, toleransi 5%), atau
  #   (iii) NOL atau "tidak ada data" bila hasil tool kosong.
  # Selain itu = angka salah (fail keras).
  #
  # Kenapa allow_range dimatikan:
  #   range:true membuat jawaban "sekitar 40" dianggap sah kalau tool
  #   mengembalikan [10,50,90]. Itu false positive dan merusak target 0 angka salah.
  # Kenapa allow_mean_sum dimatikan sebagai jalan pintas:
  #   tanpa must_match_tool_output, LLM bisa mengarang angka yang kebetulan sama
  #   dengan rata-rata himpunan hasil tool.
  angka_salah:
    tolerance_pct: 2.0
    must_match_tool_output: true   # harus cocok salah satu angka di hasil tool
    allow_derived_sum: true        # boleh = SUM beberapa angka tool
    allow_derived_avg: true        # boleh = AVG beberapa angka tool
    allow_derived_pct: true        # boleh = persen turunan (rasio/selisih)
    derived_tolerance_pct: 5.0
    allow_range: false             # TIDAK boleh "kebetulan di antara min-max"
    allow_mean_sum: false          # TIDAK boleh hanya cocok rata-rata tanpa dasar
  # P2a/P2b (validasi): GT exact untuk hitungan/harga; toleransi hanya persen/avg.
  gt_match:
    exact: true
    percent_tolerance_pct: 2.0
  # P2d (validasi): identifier produk G006 boleh kode (ODOO-65) atau nama.
  tool_param_alternatives:
    G006: [["kaos"], ["odoo"]]
  # Denominator: tool/param dari 15 pertanyaan; e2e dari 13 (15 - excluded).
  tool_denominator: 15
  e2e_denominator: 13
```

## Catatan operasional

- Run yang dipakai = **run terakhir** setelah semua bug parser diperbaiki.
- Kalau parser salah: perbaiki kode, jalankan **ulang dari nol**, dan catat
  "run ke-N" di laporan. Tidak ada koreksi hasil secara offline.
- Smoke test wajib: 1 pertanyaan (G005) dijalankan lebih dulu; kalau parse/skor
  gagal, run penuh tidak dijalankan.
