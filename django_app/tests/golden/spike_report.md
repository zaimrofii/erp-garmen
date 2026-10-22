# Spike Function Calling — STATUS: BLOCKED (2026-10-22)

**Tidak ada panggilan LLM yang dijalankan. Biaya aktual: $0.000000.**

## Mengapa blocked

Gerbang G.4 (invariant data) **FAIL**, dan prompt melarang melanjutkan ke Fase S
sebelum data bersih:

| # | Invariant | Hasil |
|---|---|---|
| A | Bundle DONE dengan SUM(scrap) > qty_done | **PASS** — 0 pelanggaran |
| B | Produk di OrderLine dengan sale_price 0/NULL | **FAIL** — 1 produk: `Kaos Lapangan` id 16 (`ODOO-74`, Rp0) dipakai di order `S00029` |
| C | Order tanpa OrderLine | **PASS** — 0 |
| D | OrderLine tanpa product_id | **FAIL** — 39 dari 93 baris (19 order; terbanyak `S00004` 4 baris, `S00007` 4 baris) |

Data diperbaiki di Fase 0.4/0.5 (bukan di sini). Sesudah itu spike dijalankan ulang.

## Yang sudah selesai (Fase G)

- `tests/golden/questions.yaml` — 15 pertanyaan, **15/15 verified** (`manual_orm`).
- `tests/golden/baseline_old_path.json` — baseline jalur lama, biaya $0:
  - mode `deterministic` (pipeline asli + NullProvider): **3/15 = 20,0%**
    (lulus: harga G005, follow-up ordinal G010, safety G014).
  - mode `stub` (`AI_AGENT_ENABLED=False`, default repo): **0/15 = 0,0%**.
- Semua kategori lain 0%: wip, scrap, order_telat, produktivitas, stok, customer,
  scrap_rate, lead_time, negasi, out_of_scope, data_kosong, majemuk.

## Cek statis S.5 (tanpa LLM)

```
$ grep -n "tools\|tool_choice\|function_call" django_app/integrations/ai_agent/llm_wrapper/*.py
integrations/ai_agent/llm_wrapper/base.py:23:    """Provider LLM minimal: satu metode `complete` (tanpa tools/write)."""
```

Hasil: **tidak ada** parameter `tools`, `tool_choice`, atau `function_call` di wrapper —
sesuai recon F.1. Ini hanya konfirmasi statis; bukan hasil spike.

## Rencana setelah unblock (S.1–S.4)

1. `tests/golden/spike_tools.py`: 3 tool generik di atas DAL (`list_records`,
   `count_records`, `get_metric`), throwaway.
2. `tests/golden/spike_deepseek.py`: 15 pertanyaan → DeepSeek function calling,
   catat tool terpilih, parameter, hasil, kecocokan ground truth, token, biaya.
3. Hitung akurasi tool / parameter / end-to-end, bandingkan dengan baseline 20,0%.
4. Gate biaya: abort jika total > $0.05.

**Kriteria unblock:** invariant B = 0 dan D = 0, diverifikasi ulang lewat ORM.
