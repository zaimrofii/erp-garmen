# DEMO AGENT LOOP — Ulang Demo dengan Flag Aktif (2026-10-23)

- **Branch:** `demo-ready` (HEAD awal `36ed204`; baseline fungsional `a4520a8`).
- **Tujuan:** mengaktifkan agent loop, mem-port write detection, dan mengulang 10 pertanyaan demo.
- **Batasan:** tidak mengubah pipeline lama (`context_builder`, `llm_pipeline`, `response_synthesizer`);
  MCP lama tetap ada; tidak ada koreksi skor post-hoc.

## 1. Flag aktif — CONFIRMED

- `django_app/.env:80` → `AI_AGENT_TOOLS_ENABLED=true` (file di-ignore: `.gitignore:11`).
- Restart `django`, `celery_worker`, `celery_beat`; verifikasi:
  `docker compose exec -T django python -c "from django.conf import settings; print(settings.AI_AGENT_TOOLS_ENABLED)"` → **True**.

## 2. Write detection — CONFIRMED (diport ke `demo-ready`)

- `integrations/ai_agent/agent/loop.py:21-39` — `WRITE_PATTERNS` + `_is_write_intent`.
- `loop.py:121-126` — pre-flight: `AgentResult(answer=WRITE_REFUSAL, blocked_reason="write_intent",
  tool_calls=[], cost_usd=0)` sebelum LLM dipanggil.
- `AgentResult` kini punya `blocked_reason` dan `agent_mode` (`loop.py:33-34`), dan
  `api/views.py:223` meneruskan `blocked_reason` ke response.
- Test: `tests/ai_agent/agent/test_write_intent.py` — **12/12 hijau**; suite agent **46 passed**.

## 3. Smoke test 3 pertanyaan (endpoint `/ai/chat`)

| # | Pertanyaan | agent_mode | Gate | Tool produksi | Hasil |
|---|---|---|---|---|---|
| 1 | Produk paling mahal apa? | tools | AGENT_TOOLS | `aggregate`, `list_records` | ✓ Jaket Bomber Rp250.000 |
| 2 | Ubah harga Jaket Bomber jadi 100rb | tools | AGENT_TOOLS | — (0 token) | ✓ **ditolak** (write_intent) |
| 3 | Berapa bundle aktif di SEWING-2? | tools | AGENT_TOOLS | `find_entity`, `count_records` | ✓ **22 bundle** (DB: 22) |

Smoke **3/3 sesuai ekspektasi**; biaya $0.00441400.

## 4. Demo 10 pertanyaan (endpoint `/ai/chat`, agent loop)

| # | Pertanyaan | Tool | Hasil | Konsistensi DB |
|---|---|---|---|---|
| 1 | Produk termahal yang aktif | aggregate, list_records ×2 | ✓ Jaket Bomber Rp250.000 | ✓ (FG-JKT-RICH 250000) |
| 2 | Customer order terbanyak | aggregate | ✗ diblokir validator | DB: Gemini Furniture 17 |
| 3 | Bundle di SEWING-2 | find_entity, count_records ×2 | ✓ **22 bundle** | ✓ (Bundle SEWING-2 = 22) |
| 4 | Scrap terbesar minggu ini | aggregate | ✓ **SEWING-2 = 77 unit** | ✓ (DB 19–23 Okt SEWING-2 = 77) |
| 5 | % scrap SEWING-2 minggu ini | find_entity, get_metric ×2 | ✓ rata-rata 55,75% | ✓ (metrik, bukan qty mentah) |
| 6 | Rata-rata lead time minggu ini | get_metric | ✓ 91,24 jam | ✓ (stats.avg metrik) |
| 7 | Operator output terbanyak | aggregate_operator | ✗ diblokir validator | DB: op-eka 17 event |
| 8 | Order paling telat | list_records ×5 | ✗ jawaban kosong (max_iterations=5) | DB: 0 order telat (deadline NULL/DRAFT) |
| 9 | Dari 3 termahal, mana kedua | list_records ×2 | ✗ diblokir validator | DB: harga seri 175.000 (2 produk) |
| 10 | Total order aktif + paling lambat | count/aggregate/list_records ×7 | ✗ jawaban kosong (max_iterations=5) | DB: 15 order aktif |

**Hasil: 5/10 bersih**, 3 diblokir validator, 2 kosong karena batas 5 putaran.
Biaya demo **$0.01701600**; total putaran **$0.02143000** (cap $0.03).

## 5. Perbandingan dengan demo pipeline lama (RECON_CHAT_DEMO_2026-10-23)

| Aspek | Demo lama (flag off) | Demo sekarang (flag on) |
|---|---|---|
| Tool | `mcp-analytics`, `mcp-postgres-query`, `mcp-event-log`, `mcp-comparator` | **tool produksi**: `aggregate`, `list_records`, `count_records`, `find_entity`, `get_metric`, `aggregate_operator` |
| Gate log | `RULE_HIT` / `LLM_NEEDED` | **`AGENT_TOOLS`** (+ `TOOL` per eksekusi) |
| "Tool dipanggil" | jumlah tool legacy yang dipilih (tanpa status eksekusi) | tool produksi yang benar-benar dieksekusi; setiap eksekusi punya baris log `TOOL` dengan `executed` |
| Confidence | 0.80/0.00 hardcoded (`intent_classifier.py:57`) | **null** (tidak diisi; `views.py:218`) — tidak lagi angka palsu |
| Scrap | 37 (Q6) vs 14 (Q12) dengan 70% yang sama | definisi tunggal dari tool: SEWING-2 minggu = **77** (DB 77), rate dari `get_metric` (14/20 → 70% hanya untuk 21 Okt) → **konsisten** |
| Stok | disimpulkan "3 produk 0" dari konteks | **belum diuji**: tidak ada pertanyaan stok di 10 demo; `get_stock` belum dipanggil di sesi ini |

## 6. Temuan baru (dari sesi ini)

1. **[CONFIRMED] `max_iterations=5` terlalu kecil** untuk pertanyaan majemuk: Q8 (5 tool) dan Q10
   (7 tool) berakhir tanpa jawaban (`answer=""`). Perbaikan sudah ada di branch `feat/agent-tools`
   (default 8), belum diport ke `demo-ready`.
2. **[CONFIRMED] Validator memblokir jawaban benar** pada Q2/Q7/Q9 (angka berasal dari agregasi
   multi-baris atau harga seri). Pesan blokir generik menghapus jawaban yang sebenarnya benar.
3. **[CONFIRMED] Query "bundle aktif"** dijawab 22 tanpa filter status — model menyebut keterbatasan
   ("filter status aktif tidak tersedia untuk entity bundle"), jadi 22 = semua bundle di SEWING-2.
4. **[CONFIRMED] Observability membaik tapi belum lengkap**: `AIDecisionLog` punya baris `TOOL`
   per eksekusi (tool, args, row_count, executed, duration_ms), tetapi UI masih memakai
   `tool_calls` dari `_agent_response` (ringkasan). Perlu agregasi "N dipanggil / M berhasil".

## 7. Rekomendasi: PERBAIKI DULU (belum siap demo)

1. Port `DEFAULT_MAX_ITERATIONS = 8` ke `demo-ready` (Q8/Q10 kosong).
2. Longgarkan validator: terima angka hasil agregasi yang sah (Q2/Q7/Q9) — atau tampilkan alasan blokir
   yang spesifik, bukan mengganti seluruh jawaban.
3. Tambah tie-break harga (`ORDER BY sale_price DESC, code ASC`) untuk Q9.
4. Uji `get_stock` pada sesi berikutnya (belum tersentuh di demo ini).

Estimasi: 3 item pertama tidak menambah biaya LLM signifikan (1 run demo ~$0.017).
