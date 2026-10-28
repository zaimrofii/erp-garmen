# RECON DEEP — AI Agent MES Garmen (2026-10-23)

**Mode:** read-only. Tidak ada kode/config/data bisnis yang diubah. Artefak baru hanya di `docs/recon/`.
**Executor:** auditor eksternal (bukan penulis kode). Semua klaim dokumen dianggap belum terbukti sampai diuji.
**Metode kebenaran:** ground truth dihitung langsung via Django ORM/SQL pada DB yang sedang berjalan (query di Lampiran A). Output AI, validator, dan golden set lama **bukan** sumber kebenaran.

## Biaya probe (aktual, dari `AIDecisionLog.total_cost_usd`)

| Bagian | Run | Biaya USD |
|---|---|---|
| B flaky (11 demo + 14 transkrip + 21 parafrase) ×5 | 230 | 0.3620 |
| F determinisme (2 pertanyaan ×10) | 20 | 0.0161 |
| H memori/racun riwayat | 6 | 0.0055 |
| J.2 golden 30 pertanyaan ×3 | 90 | 0.1172 |
| D.2 breakdown 1 run | 1 | ~0.0040 |
| **Total** | **347** | **≈0.505** |
| Sisa budget | | **≈0.995 dari 1.50** |

Semua probe lewat endpoint asli `POST /api/v1/ai/chat` sebagai user **ber-role OWNER** (dipilih `User.objects.filter(role=Role(code="OWNER")).order_by("id").first()`; **bukan** `demo-supervisor` yang ber-role SUPERVISOR), `conversation_id` berawalan `recon-`, satu id baru per percobaan (kecuali H). Tidak ada probe yang dihapus.

---

# BAGIAN 0 — GROUND TRUTH LINGKUNGAN

## 0.1 Git
| Item | Nilai |
|---|---|
| Branch | `demo-ready` |
| HEAD | `83369ee` ("docs(status): tutup fase AI Agent…") |
| git status | bersih sebelum audit (tidak ada file termodifikasi/untracked saat mulai) |
| `feat/agent-tools` | `23a1ac9` |
| Selisih | `git rev-list --left-right --count demo-ready...feat/agent-tools` = **15 2** (demo-ready 15 commit di depan, 2 di belakang) |

## 0.2 Kode container == HEAD? **CONFIRMED sama**
| File | sha256 container | sha256 host |
|---|---|---|
| `integrations/ai_agent/agent/loop.py` | `c692fe35…db2407` | `c692fe35…db2407` |
| `integrations/ai_agent/agent/validator.py` | `bf231853…1c487` | `bf231853…1c487` |
| `integrations/ai_agent/tools/base.py` | `70ddd3d7…a7c8` | `70ddd3d7…a7c8` |

Image: `garmen-django:local`. **Tanggal build image: UNVERIFIED** (output `docker inspect` terpotong saat pengambilan; yang terbukti adalah isi file identik dengan HEAD, sehingga kode yang berjalan = HEAD terlepas dari tanggal build).

## 0.3 Nilai efektif di container (bukan `.env` di host)
| Variabel / nilai | Nilai efektif | Bukti |
|---|---|---|
| `AI_AGENT_ENABLED` | `true` | `docker exec garmen_django printenv` |
| `AI_AGENT_TOOLS_ENABLED` | `true` | idem; `settings.py:813` |
| `AI_LLM_PROVIDER` / `MODEL` | `deepseek` / `deepseek-chat` | idem |
| `AI_LLM_TEMPERATURE` | `0` → **AI_CONFIG 0.0** | `printenv` + `AI_CONFIG["llm"]["temperature"]==0.0` |
| `AI_LLM_MAX_TOKENS` | tidak di-set → 1000 (config), loop kirim `max_tokens=800` (`loop.py:121`) | config.py:39 |
| **MAX_ROUNDS produksi** | **5** (`settings.py:814`, dipakai `api/views.py:181`), bukan 8 | default loop 8 hanya bila config kosong |
| TTL cache respons | 300s (`config.py:49`), tapi **tidak dipakai jalur agent** (lihat 0.3b) | `semantic_cache.py:23` |
| TTL memory/pending state | 600s | `clarification/pending_state.py:20` |

**0.3b Cache:** jalur agent (`api/views.py:146-147` → `_agent_response`) **tidak** memanggil `semantic_cache` sama sekali. Pemakaian cache hanya di jalur lama `handlers/llm_pipeline.py:204,237`. Bukti empiris: dari 347 run, `cache_hit=true` = **0**.

## 0.4 Test AI agent (dijalankan berurutan, bukan paralel)
| Suite | Hasil |
|---|---|
| `tests/ai_agent/agent` | **107 passed** (6.41s) |
| `tests/ai_agent/tools` | **41 passed** (7.50s) |
| Total | **148 passed, 0 failed, 0 skipped** → klaim "107+41=148" **CONFIRMED** |

Catatan operasional: bila dua suite dijalankan paralel, keduanya membuat `test_garmen_django` bersamaan dan menghasilkan **107 error** (DB contention), bukan kegagalan test. Ini bukan bug produk, tapi jebakan operasional (lihat K).

## 0.5 Invariant data (SQL langsung)
| Invariant | Hasil |
|---|---|
| `scrap.qty > bundle.qty` | **0** |
| `bundle.qty_done > qty` | **0** |
| produk aktif `sale_price` NULL / 0 | **0 / 0** |
| order line tanpa produk | **0** |
| `bundle.qty <= 0`, `scrap.qty <= 0` | **0 / 0** |
| scrap tanpa work center, bundle tanpa WC | **0 / 0** |
| **order `deadline` NULL** | **23 dari 73** ← relevan untuk "order telat" |
| order `created_at` di Okt 2026 | 73 (semua), `deadline` di Okt = **0** |

Invariant "bebas kotor" **CONFIRMED**, tetapi ada 23 order tanpa deadline sehingga pertanyaan "order telat" secara struktural tidak bisa dijawab untuk 23/73 order.

---

# BAGIAN A — ATRIBUSI JALUR 14 TURN TRANSKRIP

Sumber: 14 baris `AIDecisionLog` (id 1811–1848) diekspor ke `raw_2026-10-23/transcript_turns.jsonl`.

## A.1 Tabel atribusi

| # | Log | Pertanyaan (ringkas) | gate | tools (ringkas) | putaran | token prompt | validator_ok / reason | latensi |
|---|---|---|---|---|---|---|---|---|
| 1 | 1811 | "produk paling mahal…" | AGENT_TOOLS | `list_records{product,sort:-sale_price,limit:5}` | 2 | 6.889 | true / match | 3.292 ms |
| 2 | 1815 | "yang beli banyak itu siapa…" | AGENT_TOOLS | `aggregate{order,sum}`, `aggregate`, `list_records` | 4 | 15.809 | true / match | 9.632 ms |
| 3 | 1821 | "yang di sewing 2 itu… ada apa aja sih" | AGENT_TOOLS | `find_entity`, `list_records`(**invalid_argument**), `list_records`, `get_record`, `list_records` | 6 | 20.307 | **null** / "" | 6.595 ms |
| 4 | 1827 | "yang di sewing 2 sekarang bundle apa aja?" | AGENT_TOOLS | `find_entity`, `list_records`, `count_records`, `aggregate`, `list_records` | 6 | 27.258 | true / match | 10.264 ms |
| 5 | 1830 | "lah kok pada scrap semua… wc mana" | AGENT_TOOLS | `aggregate{scrap,qty,sum}`, `aggregate{scrap,work_center}` | 3 | 13.961 | **false / angka 80** | 6.135 ms |
| 6 | 1832 | "scrap terbesar di work center mana?" | AGENT_TOOLS | `aggregate{scrap,work_center}` | 2 | 9.067 | **false / angka 7** | 3.449 ms |
| 7 | 1835 | "ganti topik deh. scrap terbesar…" | AGENT_TOOLS | `aggregate`, `aggregate` | 3 | 13.562 | **false / angka 80** | 6.148 ms |
| 8 | 1837 | "coba tampilkan daftar scrap per work center" | AGENT_TOOLS | `aggregate{scrap,work_center}` | 2 | 8.155 | **false / angka 7** | 4.188 ms |
| 9 | 1840 | "aku ingi tau data tentang scrap" | AGENT_TOOLS | `aggregate{scrap,qty,sum}`, `aggregate` | 3 | 12.669 | true / match | 5.836 ms |
| 10 | 1842 | "rata-rata lead time bulan ini?" | AGENT_TOOLS | `get_metric{garment.lead_time, 10-01..10-23}` | 2 | 8.898 | true / match | 4.413 ms |
| 11 | 1844 | "operator paling produktif bulan ini?" | AGENT_TOOLS | `aggregate_operator{…}` | 2 | 8.099 | true / match | 4.667 ms |
| 12 | 1845 | "apa kemampuan utamamu" | AGENT_TOOLS | — (tanpa tool) | 1 | 4.064 | true / no_tool_called | 3.332 ms |
| 13 | 1846 | "jelaskan WIP flow" | AGENT_TOOLS | — (tanpa tool) | 1 | 4.392 | true / no_tool_called | 5.227 ms |
| 14 | 1848 | "ok, beri aku data tentang WIP flow" | AGENT_TOOLS | `get_metric{garment.wip_flow, 10-01..10-23}` | 2 | 11.671 | true / match | 7.190 ms |

**Tidak ada satu pun turn** yang lewat pipeline lama, pre-flight write, atau cache (`cache_hit` semua `false`).

## A.2 "RULE_HIT" di UI — **H4 REFUTED (backend)**, sumber UI **UNVERIFIED**
- Backend menulis gate `AGENT_TOOLS`: `api/views.py:200` (log) dan `:215` (payload). Ke-14 log membuktikan itu.
- `grep -rn "RULE_HIT" frontend_app_v2/src` → **0 hasil** → label tidak mungkin dari React v2.
- `RULE_HIT` hanya ada di jalur lama: `handlers/llm_pipeline.py:138,149,215,233`, `handlers/common.py:202,209`, `orchestrator/response_synthesizer.py:188`, `decision_gate/rule_evaluator.py:37`.
- Kesimpulan: jalur lama **tidak** menjawab turn ini. Label di layar berasal dari konsumen log/gate di luar repo frontend v2 (observability/Swagger/tangkapan lama).

## A.3 Asal tiga pesan gagal
| Pesan | Sumber | Pemicu |
|---|---|---|
| "Gagal mendapatkan data terkait. Coba tanyakan lebih spesifik." | `agent/validator.py:21-23` (`BLOCKED_ANSWER`), dipakai `validator.py:339` | validator `ok=false`; jawaban asli diganti |
| "Asisten AI belum bisa menjawab. Coba lagi." | `frontend_app_v2/src/lib/ai-context.ts:195` | client-side: respons kosong/`ok=false`/error jaringan; tidak pernah ada di `response_text` backend |
| "Angka yang dihasilkan tidak konsisten…" | **tidak ada di kode produksi**; sisa di `tests/golden/validation_runner.py:107` | pesan generasi validator **sebelum** `980fe52` (teks `BLOCKED_ANSWER` diganti). Verdict: **historis** |

## A.4 Akar penyebab per turn gagal
| Turn | Gejala | Kelas | Bukti |
|---|---|---|---|
| #3 (1821) | fallback "Saya sudah mencari data…" | **(2) putaran habis** + **(1) error tool tak dipulihkan** | 5 tool / 5 putaran (`AI_AGENT_MAX_ITERATIONS=5`), `list_records: gagal (invalid_argument)`, `raw_answer=""` |
| #5 (1830) | diblokir | **(3) validator** | `angka 80 tidak ada di hasil tool` |
| #6 (1832) | diblokir | **(3) validator — FALSE POSITIVE** | jawaban asli = pertanyaan balik ("butuh periode… Bulan ini (1–23 Okt)"), diblokir karena memuat "7" ("7 hari") |
| #7 (1835) | diblokir | **(3) validator** | `angka 80` |
| #8 (1837) | diblokir | **(3) validator — FALSE POSITIVE** | idem #6 |

Kategori **(4) provider error** dan **(5) cache** tidak ditemukan (0 dari 347 run).

## A.5 "ada apa aja sih?" (gagal) vs "bundle apa aja?" (berhasil)
| Aspek | #3 gagal | #4 berhasil |
|---|---|---|
| Rute | `find_entity` → `list_records`(**invalid_argument**) → `list_records` → `get_record` → `list_records` | `find_entity` → `list_records` → `count_records` → `aggregate` → `list_records` |
| Error | `invalid_argument` tidak diperbaiki; model pindah tool, bukan memperbaiki argumen | tidak ada error; count=22 + breakdown |
| Putaran | 5/5 habis → fallback | 5/5 cukup |
| Token | 20.307 | 27.258 |
| Hasil | fallback + "list_records: gagal; get_record: 1 baris" | "22 bundle, **semuanya SCRAP**" (klaim salah: 15 SCRAP + 6 REWORK + 1 DONE) |

Akar pembeda: **tidak ada strategi pemulihan setelah `invalid_argument`**, bukan tingkat kesulitan pertanyaan.

---

# BAGIAN B — PENGUKURAN FLAKY EMPIRIS

**Set uji (46 pertanyaan):** 11 demo + 14 transkrip + 21 parafrase informal (3 per topik: scrap per WC, bundle SEWING-2, ordinal kedua, stok terbanyak, lead time, WIP per WC, order telat). Data: `raw_2026-10-23/b_*.jsonl` (230 run, conversation_id baru tiap run `recon-b-*`).
**Kebenaran** dinilai terhadap ground truth Bagian C (aturan di Lampiran B), bukan oleh validator.

## B.1–B.3 Hasil agregat
| Verdict | Jumlah | % |
|---|---|---|
| CORRECT | 80 | 34,8% |
| MISLEADING | 30 | 13,0% |
| WRONG | 95 | 41,3% |
| UNVERIFIED (stok — butuh Odoo independen) | 15 | 6,5% |
| NA (naratif) | 10 | 4,3% |
| **Lulus (CORRECT+UNVERIFIED)** | **95/230** | **41,3%** |

| Kelompok | CORRECT | MISLEADING | WRONG | lain | pass rate |
|---|---|---|---|---|---|
| Demo 11 ×5 (=55) | 34 | 10 | 11 | 0 | **61,8%** |
| Transkrip 14 ×5 (=70) | 10 | 5 | 45 | NA 10 | **14,3%** |
| Parafrase 21 ×5 (=105) | 36 | 15 | 39 | UNV 15 | **48,6%** |

**Variasi urutan tool (5 run, temp 0):** 1 varian pada 26 pertanyaan, 2 pada 4, 3 pada 3, **4 varian pada 3** (semua topik "sewing 2" & "order telat").
**Variasi set angka dalam jawaban:** 1 set pada 16 pertanyaan, 2 pada 10, 3 pada 5, **4–5 set pada 8 pertanyaan**.

## B.4 Uji H1
| Kelompok | pass rate |
|---|---|
| Tanpa periode eksplisit | **74/175 = 42,3%** |
| Dengan periode eksplisit | **21/55 = 38,2%** |

- `missing_date_range` muncul di **59/230 run (25,6%)**, tetapi **tidak** menurunkan pass rate (pertanyaan tanpa periode justru sedikit lebih baik karena model memilih klarifikasi tanpa angka → lolos validator).
- Setelah error, model **kadang** mengulang dengan tanggal eksplisit; **loop tidak** pernah menyuntikkan tanggal otomatis (tidak ada retry di `loop.py`).
- **H1: REFUTED sebagai penyebab utama.**

## B.5 Penyebab kegagalan per run (230)
| Kategori (A.4) | Jumlah | % |
|---|---|---|
| (1) error tool (mayoritas `missing_date_range`, sebagian `invalid_argument`) | 88 | 38,3% |
| (3) validator memblokir (`block:angka`) | 38 | 16,5% |
| (2) putaran habis → fallback penuh | 15 | 6,5% |
| (2b) fallback parsial ("beberapa bagian") | 5 | 2,2% |
| (4) provider error/timeout | **0** | 0% |
| (5) cache menyajikan kegagalan | **0** | 0% |
| (6) riwayat meracuni | 0 di B (lihat H) | 0% |
| (7) angka grounded tapi salah/menyesatkan (lolos validator) | **33 kandidat** | 14,3% |

**Masalah terbesar bukan loop habis (6,5%) dan bukan provider (0%).** Yang terukur: **(a) desain tool/parameter → 38% run kena error tool (59 run missing_date_range)**; **(b) validator salah memblokir 38 run, 25 di antaranya jawaban klarifikasi yang sah**; **(c) 33 run lolos validasi dengan angka menyesatkan**.

---

# BAGIAN C — AUDIT KEBENARAN SEMANTIK

Angka dihitung ulang dari DB (`raw_2026-10-23/ground_truth.jsonl`, query di Lampiran A).

## C.1 Lead time — **MISLEADING (CONFIRMED)**
- `metrics/lead_time.py:96-109` menghasilkan `value = mean(durasi hari itu)` per hari; `tools/get_metric.py:66-75` lalu `stats.avg = mean(value harian)` → **rata-rata dari rata-rata harian (unweighted)**.
- Ground truth 1–23 Okt (92 bundle punya START & FINISH):
  - mean-of-daily-means = **13,3416 jam** (= angka yang dijawab AI "13,34 jam dari 21 hari, total 280,17 jam")
  - rata-rata berbobot qty = **23,0422 jam**; **median = 0,3333 jam**
  - 19 dari 21 hari bernilai 0,33–0,38 jam; dua hari seed-driven: 20 Okt 81,48 jam (21 bundle), 21 Okt 191,86 jam (2 bundle)
- Verdict: **grounded tetapi menyesatkan** — 90% bundle selesai < 0,4 jam; rata-rata ditarik oleh 23 bundle artefak seed.

## C.2 WIP flow — **MISLEADING (CONFIRMED); H2 sebagian benar**
- `get_metric.py:64` memotong `series[:100]`. WIP flow bergranularitas **jam**: 1–23 Okt = **120 bucket**; 100 bucket pertama berakhir **18 Okt 23:00** → jawaban "bulan ini 1–23 Okt" sebenarnya **1–18 Okt**.
- Bukti dari jawaban AI sendiri: "rata-rata **0,36** unit/titik" = `sum 36 / count 100`, padahal **sum bulan penuh = 88** → **59% arus tidak terlihat**.
- Per WC (bulan penuh): SEWING-2 in 57 / out 11 (**+46**), SEWING-1 +30, QC-2 +18, PACKING in 111 / out 138 (**−27**). Kesimpulan "praktis datar, tanpa penumpukan" **bertentangan** dengan data per WC.

## C.3 Bundle SEWING-2 (10/20/22) — **H2 CONFIRMED (truncation/limit), bukan halusinasi**
- Ground truth: total **22** (SCRAP 15, REWORK 6, DONE 1); `qty_done=0` pada 21 bundle; "sedang dikerjakan" = **6**.
- Payload `list_records` yang diterima LLM: `{"data":{"rows":[…5…]},"row_count":5,"warnings":[]}`, `truncated=True`, **tanpa `total_count`** → 10/20/22 bergantung filter/limit yang dipilih model, bukan dikarang.
- 5 run: `Berapa bundle sedang dikerjakan di SEWING-2?` → 2 CORRECT (menyebut 6 aktif) + 3 WRONG; `yang di sewing 2 sekarang bundle apa aja?` → **5/5 WRONG** (menjawab "22, semuanya SCRAP").

## C.4 Customer terbanyak — **MISLEADING (CONFIRMED)**
- "Bulan ini" memakai **`Order.created_at`** (73/73 order dibuat Okt 2026), bukan `deadline` (0 order berdeadline Okt; 23 NULL).
- Termasuk **DRAFT 28**. Semua status → **Gemini Furniture 17**; tanpa DRAFT/CANCEL → **PT Retail Fashion Indonesia 8**, CV Butik 7, PT Demo Fashion 7.
- AI menjawab "Gemini Furniture 17" tanpa menyebut 28 DRAFT → lolos validator (`match`) → **MISLEADING**. Ambiguitas "jumlah order vs total qty vs nilai Rp" tidak pernah diungkap; jawaban transkrip #2 memilih basis qty sehingga menyebut nama lain dan tampak bertentangan.

## C.5 Scrap — **tiga angka sah untuk satu kata**
| Definisi | SEWING-2 | Sumber |
|---|---|---|
| Akumulasi seluruh waktu (qty) | **209** | `ScrapAccumulator` sum per WC |
| Minggu 19–23 Okt (qty) | **77** | idem, filter `created_at` |
| `scrap_rate` kohort DONE minggu ini | **70,0%** (7/10) | `scrap_rate.py:41-52,91` |
| `scrap_rate` per hari | 90/45/18/70% (den 10/20/200/20) | idem |
- Kohort DONE hanya memuat **1 bundle DONE** di SEWING-2 → 70% tidak mewakili 209 unit scrap. "209" lolos validator dan tampak meyakinkan; **tidak ada tool** yang menyatakan "209 = akumulasi semua waktu".

## C.6 Operator — **CORRECT**
`BUNDLE_FINISH` Okt: op-andi (33) **150** qty / 16 bundle; op-eka (37) **150** qty / 17 bundle; op-fajar 140; op-budi 130. Jawaban "op-andi & op-eka, 150 unit, seri" **benar** (4/5 run; 1 diblokir).

## C.7 Produk termahal — **CORRECT (catatan)**
`FG-JKT-RICH Jaket Bomber` Rp250.000 (pokok 175.000) = ground truth, 5/5 benar. Peringkat 2 `JEAN_9999` Rp180.000 dengan **`cost_price=0`** & kategori kosong (impor Odoo) → klaim "harga pokok" menyesatkan. 62 produk aktif, 21 tanpa kategori.

## C.8 Kebenaran nyata vs "tampak benar"
| Ukuran | Nilai |
|---|---|
| Tampak benar karena lolos validator | 172/230 run (74,8%) |
| Benar secara semantik (CORRECT) | **80/230 (34,8%)** |
| Benar + tidak menyesatkan (CORRECT + UNVERIFIED-stok) | **95/230 (41,3%)** |
| Transkrip 14 pertanyaan (70 run) | CORRECT **10 (14,3%)**, MISLEADING 5, WRONG 45, NA 10 |
| Demo 11 (55 run) | CORRECT **34 (61,8%)**, MISLEADING 10, WRONG 11 |

Selisih **74,8% vs 34,8%** = ukuran langsung *false negative* validator (lihat E.2).

---

# BAGIAN D — DESAIN OUTPUT TOOL & TOKEN

## D.1 Sepuluh tool: payload nyata, limit, `total_count`, statistik
Schema total **8.228 karakter ≈ 2.057 token** untuk 10 tool (`get_schemas_for_role("OWNER")`).

| Tool | Param | Contoh payload (chars ≈ token) | rows | `truncated` | `total_count`? | Statistik terlabel? |
|---|---|---|---|---|---|---|
| `list_records` | entity, filters, sort, limit, date_from, date_to | 849 ≈ 212 (limit 5) | 5 | **True** | **TIDAK** | tidak |
| `count_records` | entity, filters, date_* | 82 ≈ 20 | 1 | False | n/a | tidak |
| `get_record` | entity, id_or_code, include | 120 (error) | 0 | False | n/a | tidak |
| `aggregate` | entity, field, op, group_by, filters, date_* | 166 ≈ 41 | 1 | False | tidak | hanya op/field/group_by |
| `aggregate` scrap tanpa tanggal | — | 210 (`missing_date_range`) | 0 | False | — | — |
| `get_metric` | name, range, group_by, filters | `stats{avg,latest,min,max,count,sum}` + `series` | ≤100 | tidak | tidak | **ya, tapi avg = mean-of-series** (C.1/C.2) |
| `find_entity` | entity, text | 166 | 1 | False | tidak | matches/ambiguous/count |
| `aggregate_operator` | field, op, date_*, limit | 119 (error wajib field/op) | 0 | — | tidak | tidak |
| `get_product_orders` | product_code, limit | 614 ≈ 153 | 5 | False | tidak | tidak |
| `get_stock` | product_code/location_code/mode/limit | 262 (1 produk) / 1.071 (top_n 10) | 0/10 | False | tidak | tidak |

**Temuan D.1:** (a) `truncated=True` muncul bahkan pada limit 5 → menandakan "limit diterapkan", bukan "dipotong sistem", sehingga model salah tafsir; (b) **tidak ada tool** yang memberi `total_count` terpisah dari baris; (c) hanya `get_metric` berstatistik, dan statistiknya **unweighted**.

## D.2 Uraian token (H6) — **CONFIRMED**
Komponen statis terukur: system prompt **1.931 karakter ≈ 482 token**; schema tool **2.057 token** → **≈2.539 token baseline per panggilan LLM tanpa data apa pun**.

| Turn | Total token prompt (log) | Panggilan LLM | Rata-rata | Komposisi |
|---|---|---|---|---|
| "produk termahal" (#1) | 6.889 | 2 | 3.445 | schema ≈60%, system 482, sisa pesan+tool |
| "bundle di sewing 2" (#4) | 27.258 | 6 | 4.543 | schema ≈45%, system ≈11%, sisanya akumulasi hasil tool |

Hasil tool **tidak pernah diringkas**; 5 putaran → 27 rb token. Ini menaikkan biaya & peluang putaran habis, tetapi **bukan** penyebab utama kegagalan (B.5).

## D.3 Petunjuk perbaikan pada error tool
| Error | Teks persis yang diterima LLM | Perilaku setelahnya |
|---|---|---|
| `missing_date_range` (base) | "Pertanyaan tentang periode WAJIB menyebutkan date_from dan date_to. Contoh: 'minggu ini' = 2026-10-19 sampai 2026-10-23." | kadang mengulang dengan tanggal, kadang bertanya balik, kadang menyerah |
| `missing_date_range` (get_metric) | "Pertanyaan ini butuh rentang tanggal. Tolong sebutkan periode: 'minggu ini', 'bulan ini', atau tanggal spesifik (YYYY-MM-DD)." | idem |
| `invalid_argument` | "argumen wajib kosong: id_or_code" | **tidak diperbaiki** (#3), model pindah tool |
| `invalid_argument` | "argumen wajib kosong: name, range" | model memperbaiki (kadang) |

Pesan `invalid_argument` **ambigu** ("wajib kosong" padahal maksudnya "wajib diisi") dan tidak menyebut tipe/nilai sah.

---

# BAGIAN E — AUDIT VALIDATOR

## E.1 Blokir & false positive
- 38/230 run diblokir (16,5%), semua berpola `angka <n> tidak ada di hasil tool`.
- **25/38 (66%) FALSE POSITIVE keras**: jawaban aslinya **pertanyaan klarifikasi** ("butuh periode…"), diblokir karena memuat angka kalender ("7 hari terakhir", "1–23 Okt").
- **5/38 FP lain**: angka = jumlah baris yang ditampilkan ("berikut 5 teratas"/"8 produk") → `Stok produk paling banyak apa?` diblokir **5/5** padahal jawaban benar (Kain Pique Cotton 30s, 40.000).
- 8/38 blokir sah (angka memang tak ada di pool).

## E.2 False negative
- 172/230 run lolos validator; hanya **80 CORRECT (34,8%)**; **33 run** membawa angka/kata kunci menyesatkan dengan `validator_ok=true`:
  - `Total order aktif: 10` (GT 15) — `reason="match"`
  - `Rata-rata lead time 13,34 jam` (median 0,33) — `match`
  - `WIP flow 0,36 … tanpa penumpukan` (truncation 100 titik; SEWING-2 +46) — `match`
  - `Gemini Furniture 17` tanpa menyebut 28 DRAFT — `match`
- **H7 CONFIRMED dua arah** (FP 30/38 = 79%; FN ≥33/172 = 19%).

## E.3 Toleransi sebenarnya
- `validator.py:52-53`: `TOLERANCE=0.02`, `DERIVED_TOLERANCE=0.05`. Klaim dokumen "exact untuk count" hanya benar untuk integer; desimal 2%, subset SUM/AVG 5%.
- Angka salah yang lolos: `13,34` vs `13,3416`; `47,71` vs `47,7123`; `0,36` vs `0,3583`. Dengan toleransi 5%, `209` vs `199` juga lolos bila 199 ada di pool.
- Pool angka sah: `row_count` + semua nilai numerik + metadata + kombinasi subset (`itertools.combinations`). Untuk 5 baris × 6 field → ≥30 angka; dengan group_by → puluhan. Peluang angka acak cocok ≈1% per klaim, tetapi karena angka AI diturunkan dari data, yang lolos justru **kesalahan semantik**.

## E.4 Yang tidak diperiksa
Periode yang diklaim, klaim universal ("semua"/"tidak ada"), nama entitas, ordinal/urutan, satuan (jam vs hari), dan agregasi berbobot. Validator **hanya** angka vs pool → 33 run menyesatkan lolos.

---

# BAGIAN F — DETERMINISME

## F.1 Payload yang benar-benar dikirim (dicegat tanpa biaya)
`POST https://api.deepseek.com/v1/chat/completions`
| Field | Nilai |
|---|---|
| keys | `max_tokens, messages, model, temperature, tool_choice, tools` |
| model | `deepseek-chat` |
| temperature | **0.0** |
| max_tokens | 800 (loop) |
| tool_choice | `auto` |
| **top_p** | **tidak dikirim** |
| **seed** | **tidak dikirim** |

Tanpa `seed`, determinisme penuh tidak mungkin dijamin.

## F.2 Sepuluh run per pertanyaan (percakapan baru)
| Pertanyaan | Urutan tool berbeda | Jawaban berbeda | Angka berbeda |
|---|---|---|---|
| "Produk termahal yang aktif apa?" | 1 (`list_records` selalu) | **3 varian teks** | 3 set |
| "Apa kemampuan utamamu" | 1 (tanpa tool) | **5–6 varian teks** | 1 |

Sumber variasi: **sampling LLM** (bukan state/cache — `cache_hit=0`, DB tidak berubah selama audit). Klaim "isi sama, teks beda" **sebagian benar**: isi data tetap, isi naratif **berubah**.

## F.3 Stabilitas ORDER BY
- `list_records.py:62`: bila model mengirim `sort` → `order_by(sort_text, "code")` (tie-break aman); bila tidak → `order_by(*repo.order_by)`.
- `aggregate_operator` diurutkan di kode; `aggregate` tidak butuh urutan.
- Risiko: `sort_text` berasal dari model (string bebas) → **UNVERIFIED** apakah semua nilai dipetakan; tidak ada validasi nilai urutan selain whitelist repo.

---

# BAGIAN G — REALISME DATA DEMO

## G.1 Data yang tampak sintetis
| Item | Bukti | Sumber seed |
|---|---|---|
| Nama customer "PT BIG Customer 4…10", "PT Demo Fashion Nusantara", "Gemini Furniture" (dengan 17 order) | query ORM: 7 customer bernama `PT BIG Customer N` masing-masing 4 order | `management/commands/seed_big_test.py`, `seed_rich_garment.py` |
| 200 bundle, 73 order, 72 baris scrap, 50-ish produk | `questions.yaml:3` mencatat snapshot yang sama; DB saat ini 200/73/72/62 | `seed_big_test.py` |
| 22 bundle SEWING-2 dengan 15 SCRAP & 21 `qty_done=0` | ORM | seed menghasilkan blok bundle scrapped |
| 2 hari lead time ekstrem 81,5 & 191,9 jam | `BundleEvent` 20–21 Okt, 23 bundle | event seed (bukan produksi nyata) |
| Produk impor `ODOO-88/90`, `JEAN_9999` harga pokok 0, kategori kosong | ORM | sync Odoo demo |
| Order tanpa deadline (23) | ORM | seed |

## G.2 Mana jawaban demo yang merupakan artefak seed?
| Jawaban | Artefak atau perilaku sistem? |
|---|---|
| "SEWING-2 scrap 209" | **Artefak seed** (209 = akumulasi seluruh waktu; 77 minggu ini; 70% resmi). Insight "SEWING-2 paling buruk" tetap benar relatif, tetapi angka absolutnya artefak |
| "Lonjakan lead time 20–21 Okt" | **Artefak seed murni** (191,86 jam dari 2 bundle) — bukan insight operasional |
| "Operator 150/150/140" | Artefak seed, tetapi **konsisten** dengan DB |
| "Produk termahal Jaket Bomber 250rb" | Data master (bisa dipercaya) |
| "Total order aktif 10/15" | Perilaku sistem (pemilihan status), bukan seed |

## G.3 Syarat minimal dataset realistis (rekomendasi, tidak dikerjakan)
1. ≥3 bulan riwayat dengan pola lead time **berdistribusi wajar** (p50 4–24 jam), tanpa hari ekstrem buatan.
2. Scrap rate per WC **< 10%** dengan denominator ≥ 100 unit/hari (sekarang 70% karena 1 bundle DONE).
3. Semua order punya `deadline` & status bervariasi (DRAFT/CONFIRMED/IN_PROGRESS/DONE) termasuk **beberapa yang benar-benar telat**.
4. Nama customer/produk wajar (tanpa "BIG Customer N"), kategori terisi, `cost_price > 0` untuk FG.
5. ≥30 bundle aktif tersebar di ≥4 WC dengan `qty_done` bergerak (bukan 21 dari 22 = 0).

---

# BAGIAN H — MEMORI & RACUN RIWAYAT

Uji: 4× pertanyaan gagal (`coba tampilkan daftar scrap per work center aja`) dalam **satu** konversi `recon-h-poison`, lalu `apa itu sapi`, lalu "produk termahal".

| Urutan | Hasil | validator_reason | Catatan |
|---|---|---|---|
| poison #1 | diblokir | `angka 7 tidak ada di hasil tool` | jawaban asli = klarifikasi ("7 hari terakhir") |
| poison #2 | klarifikasi lolos | `no_numbers` | tidak terpengaruh kegagalan #1 |
| poison #3 | diblokir | `angka 7` | pola sama |
| poison #4 | klarifikasi lolos | `no_numbers` | pola sama |
| setelah racun: "apa itu sapi" | menolak sopan | `no_tool_called` | **tidak meniru kegagalan** |
| "produk termahal" (ganti topik) | benar Rp250.000 | `match` | normal |

**H5 REFUTED (untuk racun & cache):** riwayat **dikirim** (`loop.py:141-142`, `_compose` ambil 10 turn terakhir) tetapi tidak membuat model meniru kegagalan; **cache tidak menyajikan ulang kegagalan** karena jalur agent tidak memakai cache (`cache_hit=0`). Yang berulang adalah **pola blokir validator**, bukan efek riwayat.

---

# BAGIAN I — CHART

## I.1 Rantai pembentukan chart
1. `loop.py:199-202` → `_chart_from_metric(outcome.data, question)` hanya untuk tool `get_metric` dengan `series`.
2. `loop.py:330-345` (`_chart_from_metric`) → `build_chart_data(context, "ANALYTICS_QUERY", question)`.
3. `chart_builder.py:9` `CHART_INTENTS={"ANALYTICS_QUERY","DIAGNOSTIC"}`; `_requested_metric` cocokkan kata kunci ("scrap","wip","lead time", …).
4. `chart_builder.py:130` `"data": points[-MAX_POINTS:]` dengan **`MAX_POINTS = 14`** (`chart_builder.py:36`).
5. Label: `_label()` (`chart_builder.py:57-70`) memotong key menjadi **"<tanggal> <bulan>"** — jam dibuang.

## I.1 Temuan
| Aspek | Temuan | Verdict |
|---|---|---|
| Sumber data | `series` dari `get_metric`, sudah **dipotong `[:100]`** (`get_metric.py:64`) sebelum chart | **CONFIRMED** |
| Titik yang ditampilkan | **14 titik terakhir** (`points[-14:]`), bukan seluruh periode | **CONFIRMED** |
| Label "17 Okt" berulang | karena WIP flow bergranularitas **jam** → 14 titik = 14 jam; `_label` memotong semuanya menjadi tanggal yang sama ("18 Okt" ×14) | **CONFIRMED** (penjelasan) |
| Menyesatkan periode? | **Ya**: judul "Tren …" + 14 titik tanpa keterangan jam/periode; pengguna wajar membacanya sebagai tren harian | **MISLEADING** |
| Chart pada demo 11 | hanya muncul bila kata kunci metrik ada **dan** ≥2 titik; pada 55 run demo, `chart_data` jarang terisi (kebanyakan `list_records`) | CONFIRMED (chart opsional) |

---

# BAGIAN J — REALITAS TEST SUITE & GOLDEN

## J.1 Test vs LLM asli
| Pertanyaan | Jawaban | Bukti |
|---|---|---|
| Berapa test agent/tool yang memakai **LLM asli**? | **0** — semua memakai `FakeProvider`/monkeypatch | `tests/ai_agent/agent/test_loop*.py` mendefinisikan `class FakeProvider` dengan `chat()` mengembalikan `LLMResponse` buatan; tidak ada import provider nyata |
| Perilaku FakeProvider | Mengembalikan respons berurutan dari list (`index = min(calls, len-1)`), **tanpa** memanggil jaringan; tool asli tetap dieksekusi (DB) pada sebagian test | `test_loop.py`, `test_loop_fallback.py` |
| Berapa test yang menegaskan **isi jawaban akhir** vs ground truth DB? | **0 langsung**; test menegaskan struktur (reason, blocked_reason, jumlah iterasi, `validator["ok"]`), bukan kebenaran angka vs ORM | grep `assert` pada test agent |
| Konsekuensi | "148 passed" = jaminan **mekanisme**, **bukan** kebenaran jawaban. Terbukti: 41,3% run nyata lulus mekanisme tetapi salah/menyesatkan | B.1, E.2 |

## J.2 Golden 30 pertanyaan ×3 (LLM asli) — **H8 REFUTED (arah berlawanan)**
| Set | Pass (aturan `check` di yaml) |
|---|---|
| Tuning (20 q × 3) | **37/60 = 61,7%** |
| Held-out (10 q × 3) | **21/30 = 70,0%** |
| Biaya | $0,1172 |

- Held-out **lebih tinggi** dari tuning → klaim "held-out jauh lebih rendah" **tidak terbukti** pada run ini; yang terbukti: **keduanya jauh di bawah klaim 100%/90%** (demo_ready.held_out_1run=100, held_out_3run=90).
- Verifikasi independen 10 ground truth golden (ORM langsung, Lampiran A): G001 (6 REWORK/22) ✓, G002 (scrap minggu SEWING-2 = 77) ✓, G003 (0 order telat) ✓, G004 (op-eka/op-andi 150 seri) ✓, G005 (Jaket Bomber 250k) ✓, G006–G010 memakai basis yang sama dengan C.1–C.7 dan **konsisten**. **Tidak ditemukan ground truth golden yang salah hitung**; yang bermasalah adalah **definisi** (mis. G001 "aktif=REWORK" hanya 6, sementara pengguna bisa memaksudkan 22).

## J.3 Test regresi untuk 14 turn transkrip
**0**. Tidak ada test yang memakai teks transkrip (grep teks transkrip di `tests/` → tidak ada). Semua regresi yang ada berbasis pertanyaan demo/golden, bukan bahasa informal pengguna.

---

# BAGIAN K — AUDIT KLAIM DOKUMEN "Kondisi Teknis Sistem AI 2026-10-23"

| Klaim | Verdict | Bukti |
|---|---|---|
| "11/11 stabil" | **REFUTED** | 5×11 run: CORRECT 34/55 (61,8%); `Stok produk paling banyak` diblokir **5/5**; `Total order aktif` menyesatkan 5/5; `lead time` 0/5 benar |
| "Temperature 0 tidak 100% deterministik (isi sama teks beda)" | **CONFIRMED (parsial)** | F.2: 3 varian teks pada pertanyaan data; **5–6 varian** pada pertanyaan naratif (isi ikut berubah) |
| "Validator exact blocking" | **REFUTED** | toleransi 2%/5% (`validator.py:52-53`); 30/38 blokir adalah FP; 33 run menyesatkan lolos |
| "Angka selalu dihitung kode" | **CONFIRMED untuk provenance, REFUTED untuk kebenaran** | semua angka berasal dari tool, tetapi agregasi `get_metric` = mean-of-means + truncation 100 → 13,34 jam & 0,36/titik adalah "angka kode" yang menyesatkan |
| "Role kosong tidak ditolak" | **CONFIRMED (kode)** | `views.py:103` `role_code(request.user)`; role kosong → `get_tools_for_role("")==[]` → agent tanpa tool; tidak ada penolakan eksplisit. Runtime tidak diuji (bukan OWNER) |
| "Token per turn sederhana 3.000–7.000" | **CONFIRMED (sebagian)** | #1 = 6.889; tetapi turn analitik #4 = **27.258** dan baseline statis 2.539/panggilan |
| "148 passed" | **CONFIRMED** | 107 + 41 dijalankan ulang hari ini |
| "demo-ready @ 980fe52 stabil" | **REFUTED** | HEAD sekarang `83369ee`; kode container == HEAD; stabilitas 61,8% (demo) / 14,3% (transkrip) |
| "Tidak ada yang perlu diubah sebelum demo" | **REFUTED** | 6 lubang terukur di L.1, terutama blokir palsu stok 5/5 dan "Total order 10" yang menyesatkan |
| "decision_gate_result AGENT_TOOLS/TOOL" | **CONFIRMED (backend)** | 14/14 log `AGENT_TOOLS`; payload `views.py:215`; label RULE_HIT di UI tidak berasal dari backend |

---

# BAGIAN L — VONIS

## L.1 Lima masalah terbesar (dampak demo × frekuensi terukur)

| # | Masalah | Bukti angka | Kelas akar | Perbaikan tingkat desain | Estimasi | Keyakinan | Bukti yang membatalkan diagnosis |
|---|---|---|---|---|---|---|---|
| 1 | **Validator memblokir jawaban sah** | 38/230 run diblokir; **30 FP (79%)**; `Stok produk paling banyak` **5/5 diblokir**; #6/#8 diblokir karena "7 hari"/"1–23" | validator | Cek angka hanya untuk jawaban yang **mengklaim data**; kecualikan angka kalender, "n teratas", jumlah item | 3–4 jam | Tinggi | Bila reproduksi 5× identik menghasilkan blokir <5% |
| 2 | **Tool memotong senyap & tak menyatakan cakupan** | 59 run `missing_date_range`; `series[:100]` → "bulan ini" = 1–18 Okt; sum 36 vs 88; `truncated=True` walau limit 5; **tanpa `total_count`** | desain tool | Tambah `total_count`, `coverage{from,to}`, `truncated_reason`, `preset_period`, `definition` | 8–12 jam | Tinggi | Bila 5 run "WIP flow bulan ini" dengan tool baru melaporkan cakupan penuh & total 88 |
| 3 | **Statistik agregat tidak berbobot** | "13,34 jam" vs median **0,33**, berbobot 23,04; 2 hari seed menarik rata-rata | desain metrik | Laporkan median/p50/weighted + n; default rata-rata = median | 4–6 jam | Tinggi | Bila metrik diperbaiki tetapi jawaban tetap 13,34 tanpa kualifikasi |
| 4 | **Ambiguitas semantik tidak diungkap** | "Total order aktif 10" 5/5 (GT 15); Gemini 17 tanpa 28 DRAFT; scrap 209/77/70% | prompt + tool | Wajib sebut definisi/filter/status dalam jawaban; `definition` di envelope | 4–6 jam | Tinggi | Bila 5 run menyebut 15 atau memecah 10+5 |
| 5 | **Tidak ada pemulihan `invalid_argument`; putaran 5** | #3 habis 5/5 putaran; 15 fallback penuh (6,5%) + 5 parsial | loop + pesan error | Pesan error memuat skema argumen & contoh; retry sekali; max_iter 6 | 3–5 jam | Sedang–tinggi | Bila 10 run pertanyaan gagal dengan loop baru menghasilkan fallback <2/10 |

## L.2 Verdict hipotesis
| H | Verdict | Bukti ringkas |
|---|---|---|
| H1 missing_date_range → fallback | **REFUTED (bukan penyebab utama)** | 59 run kena error, tetapi pass rate tanpa-periode 42,3% > eksplisit 38,2%; fallback penuh 6,5% |
| H2 angka 10/20/22 dari limit/truncation | **CONFIRMED** | `truncated=True` pada limit 5 tanpa `total_count`; 22 total vs 6 aktif vs 10/20 limit model |
| H3 grounded tapi salah/menyesatkan | **CONFIRMED** | 13,34; 0,36; "tidak ada penumpukan" vs SEWING-2 +46; 33 run |
| H4 RULE_HIT salah catat / jalur lama | **REFUTED (backend)**, UI **UNVERIFIED** | 14/14 `AGENT_TOOLS`; string RULE_HIT tidak ada di frontend v2 |
| H5 riwayat/cache meracuni | **REFUTED** | setelah 4 kegagalan, giliran berikutnya normal; `cache_hit=0` |
| H6 token membengkak | **CONFIRMED (biaya/risiko)**, bukan penyebab utama | 27.258 token/turn; schema 2.057 token/panggilan |
| H7 validator FP **dan** FN | **CONFIRMED keduanya** | FP 30/38; FN ≥33/172 |
| H8 held-out jauh lebih rendah | **REFUTED (arah berlawanan)** | tuning 61,7% vs held-out **70,0%**; keduanya jauh di bawah 11/11 |

## L.3 Di mana masalah terbesar?
| Lapisan | Kontribusi terukur (230 run) |
|---|---|
| **Desain tool & parameter** | **38,3% run error tool**; sumber utama 33 run menyesatkan (truncation, mean-of-means, tanpa total_count) |
| **Validator** | 16,5% run; **79% di antaranya FP** |
| **Loop** | 8,7% (fallback penuh 6,5% + parsial 2,2%) |
| **Prompt/semantik** | berkontribusi pada 13,0% MISLEADING |
| **Data seed** | bukan penyebab kegagalan mekanis; menghancurkan nilai insight 2 topik analitik |
| **UI / Infra / provider** | **0%** (0 timeout/error dalam 347 run) |

## L.4 Layak masuk skrip demo (5/5 lulus DAN benar semantik)
| Pertanyaan | Bukti |
|---|---|
| "Produk termahal yang aktif apa?" / "produk paling mahal kita apa sih sekarang?" | 5/5 CORRECT (Rp250.000, Jaket Bomber) |
| "Scrap terbesar minggu ini di work center mana?" | 5/5 CORRECT (SEWING-2, 77) |
| "Berapa persen scrap SEWING-2 minggu ini?" | 5/5 CORRECT (70%) |
| "Operator dengan output terbanyak bulan ini?" | 5/5 (transkrip 4/5) CORRECT (op-andi/op-eka 150) |
| "Order mana paling telat dari deadline?" | 5/5 CORRECT ("tidak ada"; GT memang 0) |
| "Dari 3 produk termahal, mana yang kedua?" + 3 parafrase | 5/5 CORRECT (JEAN_9999 Rp180.000) |
| "Apa kemampuan utamamu" (naratif) | aman, tanpa tool |

## L.5 Stabil tetapi SALAH/menyesatkan (paling berbahaya)
| Pertanyaan | Perilaku | Bahaya |
|---|---|---|
| **"Stok produk paling banyak apa?"** | **diblokir 5/5** ("angka 5/8 tidak ada di hasil tool") padahal jawaban benar | jawaban benar berubah jadi pesan error di depan klien |
| **"Total order aktif, lalu mana yang paling lambat?"** | "10 order" 5/5 (GT 15), lolos validator | salah angka + salah simpulan |
| **"Rata-rata lead time bundle minggu ini/bulan ini"** | 13,34 / 81,48 / 91,24 antar run; median 0,33 | angka artefak seed, mudah dipatahkan |
| **"WIP flow bulan ini"** | "0,36/titik, datar, tanpa penumpukan" (data 1–18 Okt) | simpulan strategis salah |
| **"Berapa bundle sedang dikerjakan di SEWING-2?"** | 22/"semuanya SCRAP" vs 6 aktif | definisi tidak diungkap |
| **"Customer dengan order terbanyak bulan ini?"** | Gemini 17 tanpa menyebut 28 DRAFT | bisa diperdebatkan klien |

## L.6 Urutan perbaikan + gerbang angka (JANGAN dikerjakan di sesi ini)
| Langkah | Aksi | Gerbang |
|---|---|---|
| 1 | Validator: cek angka hanya untuk jawaban berbasis data | FP ≤2/230; stok lolos 5/5 |
| 2 | Tool: `total_count`, `coverage`, `truncated_reason`, `definition`, preset periode | 0 run "bulan ini" dengan cakupan < periode; sum WIP = 88 |
| 3 | Statistik berbobot + median/p50 | jawaban lead time menyebut median & n |
| 4 | Prompt wajib definisi/filter; larang "semua/tidak ada" tanpa filter | 0 MISLEADING pada 30 run |
| 5 | Loop: pesan `invalid_argument` + skema; retry sekali; max_iter 6 | fallback penuh ≤1/50 |
| 6 | Golden dinilai dari ORM + 14 turn transkrip jadi regresi | tuning & held-out ≥85% terverifikasi ORM |

---

# LAMPIRAN A — Query ground truth (dijalankan di container terhadap DB berjalan)

```python
# C.1 lead time
BundleEvent.objects.filter(bundle=b, event_type="BUNDLE_START").order_by("ts").first()
BundleEvent.objects.filter(bundle=b, event_type="BUNDLE_FINISH").order_by("-ts").first()
# 92 pasangan 1-23 Okt; mean-of-daily-means 13.3416; berbobot qty 23.0422; median 0.3333
metric.compute({"group_by": "period", "granularity": "day",
                "date_from": date(2026,10,1), "date_to": date(2026,10,23)})

# C.2 wip flow + truncation
wip.compute({"group_by": "period", "date_from": ..., "date_to": ...})   # 120 bucket
wip.compute({"group_by": "work_center", ...})                          # SEWING-2 in 57 / out 11

# C.3/C.5 bundle & scrap
Bundle.objects.filter(current_work_center__code="SEWING-2").values("state").annotate(n=Count("id"))
ScrapAccumulator.objects.values("work_center__code").annotate(q=Sum("qty")).order_by("-q")
ScrapAccumulator.objects.filter(created_at__date__gte="2026-10-19", created_at__date__lte="2026-10-23")
    .values("work_center__code").annotate(q=Sum("qty")).order_by("-q")
scrap_rate.compute({"group_by": "work_center", "date_from": ..., "date_to": ...})

# C.4 customer / order
Order.objects.values("state").annotate(n=Count("id"))
Order.objects.filter(created_at__date__gte=START, created_at__date__lte=END)
    .values("customer__name").annotate(n=Count("id")).order_by("-n")[:10]
Order.objects.filter(created_at__date__gte=START, created_at__date__lte=END)
    .exclude(state__in=["DRAFT", "CANCEL", "CANCELLED"])...   # top10 berbeda
Order.objects.filter(deadline__isnull=True).count()   # 23

# C.6 operator
BundleEvent.objects.filter(event_type="BUNDLE_FINISH", ts__date__gte=START, ts__date__lte=END)
    .values("actor").annotate(n=Count("id"), q=Sum("bundle__qty"), qd=Sum("bundle__qty_done")).order_by("-qd")

# C.7 produk
Product.objects.order_by("-sale_price").values("code","name","sale_price","cost_price","is_active","category")[:10]

# 0.5 invariant (SQL mentah)
SELECT count(*) FROM garment_scrapaccumulator s JOIN garment_bundle b ON b.id=s.bundle_id WHERE s.qty>b.qty; -- 0
SELECT count(*) FROM garment_bundle WHERE qty_done>qty;  -- 0
```

# LAMPIRAN B — Aturan penilaian otomatis (Bagian B) & batasnya
`CORRECT`/`MISLEADING`/`WRONG` per topik: `termahal` harus memuat 250.000 & Jaket Bomber; `leadtime` 13,34/91,2 → MISLEADING, 0,33/median → CORRECT; `order_aktif` 15 → CORRECT, 10 → MISLEADING; `telat` "tidak ada" → CORRECT; `stok` → UNVERIFIED (butuh Odoo independen). Skrip penilai dijalankan di container (`/tmp/audit_b_all.py`, **tidak** di-commit).
**Batas:** berbasis pola teks, bukan pemahaman penuh. Kasus "customer by qty" (transkrip #2) dinilai WRONG karena tidak memuat nama GT berbasis jumlah order; bila klien menghendaki basis qty, verdict dapat berubah. Semua jawaban mentah ada di `raw_2026-10-23/*.jsonl` untuk re-audit manual.

# LAMPIRAN C — Artefak mentah
| File | Isi |
|---|---|
| `raw_2026-10-23/transcript_turns.jsonl` | 14 log transkrip (id 1811–1848) |
| `raw_2026-10-23/b_demo.jsonl` | 55 run (11 demo ×5) |
| `raw_2026-10-23/b_transcript.jsonl` | 70 run (14 transkrip ×5) |
| `raw_2026-10-23/b_paraphrase.jsonl` | 105 run (21 parafrase ×5) |
| `raw_2026-10-23/b_summary.json` | agregat per pertanyaan + uji H1 |
| `raw_2026-10-23/f_determinism.jsonl` | 20 run determinisme |
| `raw_2026-10-23/h_history.jsonl` | 6 run memori/racun riwayat |
| `raw_2026-10-23/j_golden.jsonl` | 90 run golden 30×3 + skor |
| `raw_2026-10-23/ground_truth.jsonl` | semua angka ground truth ORM |
| `raw_2026-10-23/environment.jsonl` | hash, env efektif, hasil test |

**Tidak ada kode, konfigurasi, migrasi, atau data bisnis yang diubah.** Baris `AIDecisionLog` hasil probe dibiarkan. Skrip bantu audit dijalankan dari `/tmp` dalam container dan tidak disimpan di repo.

## Bagian yang belum tercakup (eksplisit)
- **0.2 tanggal build image**: output `docker inspect` terpotong; yang terbukti hanya kesamaan hash file.
- **A.2 sumber label "RULE_HIT" di UI**: tidak ada kode UI di repo yang merender gate → UNVERIFIED.
- **F.3** validasi nilai `sort` dari model: UNVERIFIED (perlu enumerasi).
- **G.1** pemetaan baris data → perintah seed spesifik: hanya tingkat file, bukan baris per baris.
- **Stok (15 run)**: perlu pembanding Odoo independen; belum diverifikasi.









