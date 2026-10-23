# RECON — Q4 "Scrap per work center" FLAKY (2026-10-23)

- **Mode:** read-only (tanpa ubah kode/config/data). Satu file dibuat: ini.
- **Basis:** branch `demo-ready`, HEAD `f78af80`.
- **Sumber bukti:** kode (file:baris), `AIDecisionLog` hari ini, 1 probe agent loop (Q3→Q4).
- **Biaya probe:** ≈$0.0035 (Q3 butuh 2 request, Q4 butuh 2). Melebihi target "2 panggilan" karena satu pertanyaan butuh >1 request; tidak ada retry.

**Pertanyaan:** Q4 gagal 3× di satu sesi tetapi berhasil di sesi lain dengan redaksi & konteks sama.

---

## A. Reproduksi terkontrol

| Uji | Hasil | Bukti |
|---|---|---|
| **A1 — Q4 tanpa history** | **TIDAK KONSISTEN**: berhasil di satu run, diblokir di run lain | `#1605` (07:39) answer "SEWING-2 … 77" (lulus); `#1680` (08:05) answer "Angka yang dihasilkan tidak konsisten…". Keduanya dari runner demo yang mengirim `history=[]` (`views.py:185`, `tests/golden/demo_agent_loop.py`). |
| **A2 — Q3 lalu Q4 (history 1 turn)** | **LULUS 1/1** | Probe: Q3 → `find_entity` + `count_records` (22 bundle); Q4 → `aggregate{scrap,qty,sum,group_by:work_center,date 19..23}`, verdict `{'ok': True, 'reason': 'match'}`, jawaban 77/6/5/1/1/1 + total 91. |
| **A3 — ulangan 3×** | **UNVERIFIED** | Hanya 1 probe dijalankan (batas biaya). |
| **A4 — apa yang berbeda** | **Tool args IDENTIK** pada kasus lulus vs blokir | `#1605` dan `#1680` sama-sama `aggregate{entity:scrap, field:qty, op:sum, group_by:work_center, date_from:2026-10-19, date_to:2026-10-23}`. |

**A4 lanjutan:** perbedaan yang TERBUKTI = teks jawaban LLM (mental tidak tersimpan; yang tersimpan hanya hasil setelah validator). Temperature **0.3** (`config.py:40`, `deepseek.py:59,86`) → sampling non-deterministik.

---

## B. Analisis tool

- **B1 gagal:** `aggregate` scrap/qty/sum/group_by=work_center — kadang **tanpa** `date_from/date_to` (`#1635`: row_count=8 = all-time) → angka beda dari "minggu ini".
- **B2 berhasil:** `aggregate` args sama + `date_from=2026-10-19,date_to=2026-10-23` (`#1605`, `#1647`, probe A2).
- **B3 perbedaan args:** ya pada sebagian kegagalan (`#1635` all-time), tetapi `#1680` memakai args **sama** dengan `#1605` → args bukan satu-satunya penyebab.
- **B4 tool error:** tidak ada (`output_summary: row_count=6 error=None`).
- **B5 path rawan:** `aggregate.run()` (`tools/aggregate.py:38-60`) tanpa tanggal = **all-time** (tanpa default 7 hari); `date_criteria` hanya untuk entity ber-`DATE_FIELD` (`tools/base.py`). "Minggu ini" sepenuhnya bergantung argumen model.

---

## C. Analisis validator

- **C1:** untuk Q4 yang diblokir, validator melihat `tool_calls[].result` + `metadata` (`validator.py:256-298`). Pool = angka di data + `metadata.row_count`. Tidak ada akses ke teks pra-validator di log.
- **C2 — nondeterministik?** **REFUTED.** `_ordered` mengurutkan hasil (`validator.py:210`), pool `sorted(...)` (`:298`), tanpa `random`; `test_validator_deterministic.py` lulus 10× identik. Blokir selalu karena "ada angka jawaban di luar pool" (mekanisme `:298-310`), bukan acak.
- **C3 — log validator?** Tidak ada. `AIDecisionLog.response_text` menyimpan jawaban **setelah** diblokir; `validator.reason` tidak dipersist. **Akibat: kasus gagal tidak bisa didiagnosis dari DB** (root masalah observability).

---

## D. Analisis konteks/history

- **D1:** history dikirim bila ada: `views.py:185` → `run_agent(..., history=...)`; `loop.py:138` (ringkas bila >10 turn); `loop.py:323-331` (`_compose`: system + ≤10 turn + pesan baru, tanpa merge).
- **D2:** **CONFIRMED** history dapat mengubah perilaku: `#1676` (08:04) "Kalau soal scrap…" → `tools_called []` dan diblokir; `#1637/#1638` (07:58) model menolak memberi laporan scrap **tanpa** memanggil tool.
- **D3:** mekanismenya murni prompt (history ikut sebagai pesan); tidak ada logika yang memaksa tool dipanggil untuk pertanyaan lanjutan.
- **D4 — cache:** **REFUTED** sebagai penyebab. Agent path tidak memakai `semantic_cache` (grep kosong). `memory.summarize_history` hanya aktif bila history >10 turn, cache per conversation + hash (`memory.py:17-57`); pada sesi ini history ≤2 turn.

---

## E. Probe LLM

- **E1:** probe dengan history Q3 (pola sesi) → **Q4 LULUS 1/1**. Tidak 2× karena batas biaya.
- **E2:** dibanding A1, args tool sama; perbedaan hanya teks jawaban → konsisten dengan variasi sampling, bukan konteks.

---

## Kesimpulan berbukti

1. **CONFIRMED** — Flaky **bukan** validator nondeterministik (deterministik, unit-test) dan **bukan** cache (agent path tanpa semantic cache).
2. **CONFIRMED** — Penyebab langsung: **teks jawaban LLM bervariasi** untuk pertanyaan & tool-result yang sama; sebagian varian memuat angka di luar pool → validator memblokir. Bukti: `#1605` lulus vs `#1680` diblokir dengan args identik.
3. **CONFIRMED** — Pemicu kedua: model kadang **tidak mengirim rentang tanggal** (`#1635` all-time) atau **tidak memanggil tool** (`#1676`, `#1637`, `#1638`), terutama saat ada history.
4. **REFUTED** — "Konteks percakapan satu-satunya pemicu": kegagalan juga terjadi **tanpa history** (`#1680`, runner `history=[]`).
5. **UNVERIFIED** — Angka spesifik yang memicu blokir `#1680` (jawaban mentah tidak tersimpan); konsistensi 3× tidak diukur.

## Rekomendasi

1. `config.py:40` → set `AI_LLM_TEMPERATURE=0` untuk demo (sampling deterministik).
2. Simpan jawaban mentah + `validator.reason` di `AIDecisionLog` (`api/views.py:_agent_response`) — tanpa ini diagnosis mustahil.
3. Perkuat aturan tanggal: prompt aturan 6 sudah ada, tetapi tidak dipatuhi konsisten; opsi tegas = `aggregate` menolak `missing_date_range` untuk entity berperiode (seperti `get_metric`).
4. **Tidak perlu diperbaiki:** validator (deterministik) dan cache ringkasan (tidak relevan untuk Q4).

