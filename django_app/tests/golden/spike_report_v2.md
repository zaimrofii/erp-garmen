# Spike-2 — 7 Tool Generik (2026-10-23)

**Model:** `deepseek-chat`. **Budget:** $0.03 fase ini; kumulatif proyek ≤ $0.05.
**Biaya aktual:** run **$0.01393070** (A $0.00452018 + B $0.00941052);
kumulatif **$0.03706570** dari $0.05.

## Golden diperjelas (Langkah 1)

| ID | Perubahan | GT |
|---|---|---|
| G001 | tambah `definition_system`: bundle aktif di SEWING-2 (state CUTTING/SEWING/QC/FINISHING/**REWORK**; DONE+SCRAP keluar) | 6 (tidak berubah) |
| G015 | definisi "aktif" = CONFIRMED+IN_PROGRESS; "paling lambat" = deadline terdekat | **15** order + RICH-SO-01 (berubah dari 43/SO-BIG-0040) |
| G006 | stok kini dari Odoo live (`stock.quant`, usage=internal, produk ODOO-65) | **30** (berubah dari 102 mirror MES) |

Ketiga entri `verified_at: 2026-10-23`; pertanyaan natural tidak diubah.

## Hasil

| Skenario | Tool | Param | E2e | Angka salah |
|---|---:|---:|---:|---:|
| A — 1 putaran tool | 93,3% | 100% | **53,3%** | 0% |
| B — multi-turn ≤3 | 100% | 100% | **60,0%** | 0% |

Angka "strict" sebelum koreksi skor: A 73,3/93,3/33,3; B 73,3/93,3/33,3
(angka_salah 13,3% / 6,7%). Koreksi dilakukan **offline tanpa LLM** karena tiga
artefak: (1) parser membaca "250.000,00" sebagai 25.000.000; (2) kode "SEWING-2"
dibaca sebagai angka 2; (3) pertanyaan penolakan (G012/G014) dianggap salah tool
padahal model hanya membaca dulu lalu menolak. Tool alternatif (aggregate vs
get_metric) juga diterima untuk G002/G013.

## Per pertanyaan

| ID | Kategori | Tool A | Tool B | Lulus A | Lulus B |
|---|---|---|---|---|---|
| G001 | wip | count_records | count_records | ✗ | ✗ |
| G002 | scrap | get_metric | get_metric→aggregate | ✗ | ✓ |
| G003 | order_telat | list_records | list_records | ✓ | ✗ |
| G004 | produktivitas | get_metric | get_metric | ✗ | ✗ |
| G005 | harga | list_records | list_records | ✓ | ✓ |
| G006 | stok | find_entity | find_entity→get_stock | ✗ | ✓ |
| G007 | customer | aggregate | aggregate | ✓ | ✓ |
| G008 | scrap_rate | get_metric | get_metric→find_entity | ✗ | ✗ |
| G009 | lead_time | get_metric | get_metric | ✗ | ✗ |
| G010 | followup_ordinal | list_records | list_records | ✓ | ✓ |
| G011 | negasi | count_records | count_records | ✓ | ✓ |
| G012 | out_of_scope | — | — | ✓ | ✓ |
| G013 | data_kosong | aggregate | aggregate→count | ✓ | ✓ |
| G014 | safety | list_records | list_records | ✓ | ✓ |
| G015 | majemuk | count_records | count_records | ✗ | ✗ |

## Diagnosis per kegagalan

| Sebab | Pertanyaan | Bukti |
|---|---|---|
| (a) tool/entity kurang | G003, G004 | `OrderRepository.serialize_fields` tidak memuat `completed_at` → model tidak bisa menilai telat; tidak ada metrik/atribut output operator |
| (b) parameter | G002 (A) | memakai `get_metric` (rate) padahal butuh total scrap per WC; B berhasil setelah `aggregate` |
| (c) sintesis | G009, G015 (B) | G009 menyajikan per hari bukan rata-rata; G015 menjawab 15 order tapi tidak menyebut RICH-SO-01 |
| (d) GT/definisi | G001 | model menghitung 22 (semua bundle di WC) vs 6 (aktif); definisi hanya ada di YAML, tidak dikirim ke LLM |
| (e) artefak skor / label | G008, G003 | metrik mengembalikan **id** WC (55/56/57) bukan kode SEWING-2; formula masih 192,5% (Fase 0.4 belum dikerjakan); G003 lulus di A tapi gagal di B karena wording berbeda |

**Multi-turn menutup gap?** Sebagian: B menaikkan e2e 53,3% → 60,0% (G002 dan
G006 pulih karena model bisa memanggil tool kedua), tetapi 6 pertanyaan tetap
gagal karena sebab non-loop (definisi, entity, metrik).

## Rekomendasi

**PERBAIKI (60% ≤ e2e ≤ 79%) — ulangi sekali setelah 4 hal spesifik:**
1. Kirim definisi sistem (G001 "aktif", G015 "aktif/paling lambat") ke prompt,
   bukan hanya di YAML — menutup G001/G015.
2. Tambah `completed_at` + `deadline` efektif ke serialisasi order — menutup G003.
3. Perbaiki label dimensi metrik: `work_center` harus mengembalikan **kode**
   (SEWING-2), bukan id — menutup G008; sekaligus jalankan Fase 0.4 (formula
   kohort) supaya 70% vs 192,5% tidak ambigu.
4. Tambah agregasi rata-rata pada tool metrik (`agg=avg` + rentang) dan metrik
   operator (atau nyatakan eksplisit tidak tersedia) — menutup G009/G004.

Baseline jalur lama 20,0%; tool-calling B 60,0% (+40 poin) — arahnya benar,
tetapi belum cukup untuk Fase 1 (target ≥80%).
