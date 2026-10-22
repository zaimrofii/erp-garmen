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
  # Angka jawaban dianggap sah bila:
  #  (i) cocok angka hasil tool (toleransi 2%), atau
  #  (ii) sama dengan rata-rata / jumlah angka hasil tool (toleransi 2%), atau
  #  (iii) berada dalam rentang [min,max] angka hasil tool.
  angka_salah_tolerance_pct: 2.0
  angka_salah_allow_range: true
  angka_salah_allow_mean_sum: true
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
