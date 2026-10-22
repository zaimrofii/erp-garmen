# RECON AGENT — 2026-10-22

**Mode:** auditor read-only. Kode/config/data/DB **tidak diubah**. Satu-satunya file yang ditulis: dokumen ini.
**Aturan bukti:** mengacu `django_app/docs/ai/cline-context.md` (path sebenarnya; `docs/ai/CLINE-CONTEXT.md` tidak ada di root repo — **REFUTED** asumsi path di brief).
**Label:** `CONFIRMED` = ada file:baris / ID log / output probe mentah. `REFUTED` = ada bukti berlawanan. `UNVERIFIED` = tidak dapat dibuktikan tanpa menulis state/DB.
**Snapshot probe:** `AIDecisionLog` = 255 baris (max id 755) · `AISemanticCache` = 104 baris · Redis `DBSIZE` = 31 · Produk = 50 · Order = 73 · Bundle = 200.
**Biaya probe LLM aktual: `$0.00010584`** (6 panggilan DeepSeek, 84–104 prompt token + 16 completion token per panggilan). Budget `$0.05` tidak terlampaui (0,21% terpakai).

> Catatan kejujuran: `AIDecisionLog` **tidak menyimpan** `session_id`, `pending_state`, `page_context`, maupun `context_data`. Kolom "pending sebelum" di bawah adalah **rekonstruksi** dari kode + isi respons (bukti perilaku), bukan field log. Yang benar-benar tersimpan: gate, intent, token, cache_hit, jawaban, tools_called.

---

## 0. PREFLIGHT (angka aktual)

### 0.1 `wc -l` (dijalankan di `django_app/integrations/ai_agent`)

| File | Baris | File | Baris |
|---|---:|---|---:|
| `orchestrator/context_builder/builder.py` | **1692** | `orchestrator/context_builder/__init__.py` | 129 |
| `orchestrator/context_builder/candidates.py` | 285 | `orchestrator/context_builder/aggregate.py` | 299 |
| `orchestrator/response_synthesizer.py` | 604 | `orchestrator/tool_selector.py` | 145 |
| `orchestrator/intent_classifier.py` | 68 | `clarification/pending_state.py` | 138 |
| `clarification/resolver.py` | 244 | `clarification/epistemic_classifier.py` | 119 |
| `clarification/templates.py` | 171 | `api/views.py` | 158 |
| `api/handlers/llm_pipeline.py` | 383 | `api/handlers/common.py` | 232 |
| `api/handlers/clarification.py` | 128 | `api/handlers/logging.py` | 44 |
| `llm_wrapper/base.py` | 42 | `llm_wrapper/deepseek.py` | 95 |
| `llm_wrapper/gemini.py` | 106 | `llm_wrapper/factory.py` | 25 |
| `mcp_servers/*.py` (14 file) | **1714** | `data_access/*.py` (15 file) | **1066** |

`mcp_servers`: aggregator 205, analytics 86, calculator 62, comparator 208, event_log 98, forecaster 216, knowledge_graph 1, odoo_rpc 219, postgres_query 161, rule_engine 247, time_series 137, vector_search 1, registry 70.

`data_access`: base 67, bundles 41, graph_queries 271, invoices 28, metrics 348, orders 50, partners 16, payments 23, production_lines 16, products 24, purchase_orders 22, registry 79, work_centers 22, work_orders 30, `__init__` 29.

**[CONFIRMED] Klaim dokumen "builder.py 1.143 baris" salah — `wc -l` = 1.692 (selisih +549 baris).** Dampak: sedang.

### 0.2 Peta state & cache (grep)

| Grep | Hasil |
|---|---|
| `pending_state\|semantic_cache\|Cache` | **51 baris** (grep hit) |
| `CANCEL/cancel` di `clarification/` + `api/` | **18 baris** di 3 file |
| `temperature` | 3 file: `config.py:40`, `deepseek.py:30,53`, `gemini.py:39,60` |
| `seed` (parameter sampling) | **0 baris** |
| `tool_choice` / `function_call` | **0 baris** |
| `tools` sebagai parameter provider | **0 baris** (hanya nama tool internal) |

### 0.3 Redis live (read-only: `SCAN`/`TTL`, bukan tulis)

```
redis-cli DBSIZE                                   -> 31
redis-cli --scan | grep 'ai_cache|clarification|rate:'
  garmen:1:ai_cache:version                        -> hanya ini
redis-cli TTL garmen:1:ai_cache:version            -> -1 (persistent)
redis-cli TTL garmen:1:ai:cost:user:26:2026-10     -> -1
```

Tidak ada key `clarification:*` atau `ai_cache:<sha1>` yang hidup saat audit. Konsekuensi: TTL pending/cache **tidak bisa** dibaca langsung dari Redis (sudah kedaluwarsa); bukti pengganti di §B.2.

---

## A. TRACE TRANSKRIP

### A.1 Tabel 16 turn (log #740–#755, user 26, channel DESKTOP)

Rangkaian 7 pertanyaan yang dimaksud brief = **#742–#755 (14 log)**. Empat belas itu didahului #740–#741 pada sesi yang sama (08:28–08:29), sehingga total rangkaian = **16 log**.

| # | Log | Pertanyaan (ringkas) | Jalur | Pemicu (file:baris) | Pending sebelum* | Cache |
|---:|---:|---|---|---|---|---|
| 1 | 740 | "…tanggal 21 output cuma 20 unit?" | LLM_NEEDED / DIAGNOSTIC | `llm_pipeline.py:278-300` | tidak ada | tidak |
| 2 | 741 | "…kalau harus usul aksi?" | LLM_NEEDED / SUGGEST_ACTION | `response_synthesizer.py:514-518` | tidak ada | tidak |
| 3 | 742 | "Produk termahal apa?" | RULE_HIT `rule:ranking` | `builder.py:912-937` → `response_synthesizer.py:422-441` | tidak ada | tidak |
| 4 | 743 | "Produk termahal apa?" | RULE_HIT `rule:ranking` | idem, **kandidat = 1 baris** (reproduksi dgn page context; log tidak menyimpan context) | ada (dari 742) | tidak |
| 5 | 744 | "Produk termahal apa?" | RULE_HIT `rule:ranking` | idem 742 | ada (dari 743) | tidak |
| 6 | 745 | "…jawab berdasarkan halaman, **bukan** data…" | CLARIFICATION | `resolver.py:101-111` → `handlers/clarification.py:78-87` | ada (dari 744) | tidak |
| 7 | 746 | "Jangan lupakan… dua jawaban berbeda" | RULE_HIT `rule:ranking` (UNKNOWN, conf **0.0**) | `response_synthesizer.py:422-441` | tidak (dibersihkan 745) | tidak |
| 8 | 747 | "…tadi di halaman detail kamu **salah**…" | CLARIFICATION | kata `salah` (`resolver.py:103`) | ada (dari 746) | tidak |
| 9 | 748 | "Produk termahal? Dan yang kedua?" | RULE_HIT `rule:ranking` | `response_synthesizer.py:156-168` | tidak | tidak |
| 10 | 749 | "Total produk aktif — **bukan** nonaktif… lalu termurah?" | CLARIFICATION | kata `bukan` | ada (dari 748) | tidak |
| 11 | 750 | "…siapa yang paling banyak order?" | RULE_HIT `rule:ranking`, jawaban **PRODUK** | bleed `conversation_context.py:290-301` + `builder.py:912-937` | tidak | tidak |
| 12 | 751 | "Ganti topik lagi: scrap 7 hari…" | CLARIFICATION | kata `ganti` (`resolver.py:105`), remainder gagal (`:115-118`) | ada (dari 750) | tidak |
| 13 | 752 | "kenapa order terbaru telat?" | LLM_NEEDED / DIAGNOSTIC | `llm_pipeline.py:293-300` | tidak | tidak |
| 14 | 753 | "…produk termahal apa? Jawab singkat." | RULE_HIT `rule:ranking` | `response_synthesizer.py:422-441` | tidak | tidak |
| 15 | 754 | "…saya buka halaman detail Dress Casual Wanita…" | LLM_NEEDED / UNKNOWN, conf **0.0** | RANK mengisi `_resolved_candidate` (inferensi) → `:426` lewati ranking | ada (dari 753) | tidak |
| 16 | 755 | "…dari 46 bundle… **Kalau tidak** punya data…" | CLARIFICATION | kata `tidak` (`resolver.py:106`) | ada | tidak |

\* rekonstruksi perilaku, bukan field log (lihat catatan pembuka).
**Semua 16 log `cache_hit=False`** — [CONFIRMED] kolom `AIDecisionLog.cache_hit`.

Temuan struktural: **`decision_gate_result` di log BUKAN hasil decision gate.** `llm_pipeline.py:306` mengisi field itu dari `synth["decision_gate_result"]`, dan `_deterministic()` (`response_synthesizer.py:183-193`) selalu mengembalikan `"RULE_HIT"`. Jalur "LLM_NEEDED → synthesizer deterministik" tampil di log sebagai RULE_HIT tanpa pembeda. [CONFIRMED] Dampak: tinggi.

### A.2 (1) Kenapa "customer terbanyak order" dijawab ranking PRODUK?

Tiga lapis, semuanya terbukti:

1. **History bleed.** `resolve_followup` menempelkan pertanyaan lama: `resolved_message = f"{previous_query} (follow-up: {message})"` — `conversation_context.py:290-301`. Untuk #750, `previous_query` = #749 yang mengandung **"termurah"**. `_has_followup_signal()` menganggap #750 follow-up karena frasa "total nilai belanjanya" (`conversation_context.py:172`), sehingga guard ganti-topik di `:261` tidak jalan.
2. **Retrieval memakai pesan gabungan.** `builder.py:1225-1231` memakai `effective_message`; canonical `murah` dari #749 ikut terbaca → `builder.py:912-937` membuat `_ranking_candidates` produk.
3. **Synthesizer memotong lebih dulu.** `response_synthesizer.py:422-441` mengembalikan ranking **sebelum** LLM — padahal `customer_orders`/`customer_detail` sudah terambil (lihat probe).

**Probe reproduksi (read-only `build_context`, history = turn #749):**

```
resolve_followup(#750) -> is_followup=True
resolved_message = "...total produk yang aktif ? bukan yang nonaktif... paling murah?
                    (follow-up: Oke, ganti topik... customer... siapa yang paling banyak order?...)"
build_context -> ranking=20, _entity_label='produk', customer_orders ada=True
kandidat[0] = {'id': 7, 'label': 'Benang Jahit', 'attrs': {'harga': 'harga belum diisi'}}
```

Tanpa history: `ranking=0`, `customer_orders` normal. Penyebabnya **bukan** intent classifier, melainkan penggabungan history. [CONFIRMED] — dampak: **tinggi**.

### A.3 (2) Kenapa "scrap 7 hari" tidak menghasilkan data, padahal sesi 1 berhasil?

Bukan soal data/analytics. Turn #751 **tidak pernah masuk pipeline**: `pending_state` dari #750 masih hidup, dan handler klarifikasi memeriksa kata `ganti` sebelum apa pun (`resolver.py:183-201`, urutan `ESCALATE → CANCEL → ...`). Karena pesan #751 **tidak diawali** kata cancel, `_cancel_remainder()` (`resolver.py:115-118,129-135`) mengembalikan `None` → keluar `"Baik, saya lupakan. Ada yang lain?"` (`handlers/clarification.py:78-87`), pipeline berhenti.

Di sesi 1 (#739) pertanyaan sama berhasil karena tidak ada `pending_state` (turn sebelumnya #738 jalur LLM murni) → `decision=LLM_NEEDED`, `prompt_tokens=3008`. [CONFIRMED] `#739` vs `#751` (0 token). Dampak: **tinggi** — kata sehari-hari ("ganti/bukan/tidak/salah") membajak pertanyaan.

### A.4 (3) Kenapa turn 14 (log #754) confidence 0.00 tapi tetap menjawab?

`confidence` **hanya dicatat, tidak pernah dipakai sebagai gerbang**. `intent_classifier.classify()` mengembalikan `confidence=0.0` untuk `UNKNOWN` (`intent_classifier.py:52-57`); `llm_pipeline.py:280-281` menyalinnya; `:302-314` tetap memanggil synthesizer dan mengembalikan jawaban. Grep `confidence` di `llm_pipeline.py` hanya di baris 150, 216, 261, 280-281, 310, 334 — tidak ada `if confidence < threshold`.

Akibatnya `UNKNOWN/0.0` tetap dijawab penuh oleh LLM (2.332 prompt token, $0,0004). [CONFIRMED] — dampak: **sedang** (tidak ada jalur "tidak yakin" sebelum biaya keluar).

### A.5 (4) 14 vs 16 — rekonsiliasi

- `AIDecisionLog.objects.filter(id__range=(742,755)).count()` = **14** — yang dihitung dokumen.
- `id__range=(740,755)` = **16** — yang dimaksud transkrip (2 turn diagnosa + 14 turn rangkaian).
- Tidak ada log #756/#757; `max(id)=755`; total tabel 255 baris.

**Keduanya benar untuk jendela berbeda.** Klaim "16 turn" tidak bertentangan dengan "14 log"; yang keliru adalah menyebut salah satunya sebagai jumlah absolut rangkaian. [CONFIRMED]

---

## B. HIDDEN STATE

### B.1 Komposisi key (probe, bukan inferensi)

`pending_state` (`clarification/pending_state.py:25-26`):

```
clarification:{user_id}:{session_id}
```

`session_id` = `request.session.session_key` **atau** `f"user-{user.pk}"` (`api/handlers/common.py:183-186`). Payload: `candidates, original_query, question, turn_count, entity, selected_id, selected_label, successful_rank_count, failed_clarification_count, updated_at` (`response_synthesizer.py:430-440`, `pending_state.py:88-96`).

`semantic_cache` — dua tahap:
1. `build_cache_scope()` (`api/handlers/llm_pipeline.py:48-83`):
   `{role}|{channel}|{message}|ctx:{hash}|filters:{hash}|period:{ISO-W}|data:{DailySummary.computed_at}|state:{hash}|history:{hash}`
2. `sha1(f"{version}:{normalized}")` → `ai_cache:<sha1>` (`memory/semantic_cache.py:38-40`).

| Pertanyaan brief | Jawab | Bukti |
|---|---|---|
| pending memuat `user_id`? | **Ya** | probe: `clarification:26:sessionA` |
| pending memuat `conversation_id`? | Tidak ada konsep conversation; hanya `session_id` | `common.py:183-186` |
| pending memuat `page_context`? | **Tidak** | payload tanpa context |
| cache memuat `user_id`? | **TIDAK** | `build_cache_scope` tidak punya parameter user |
| cache memuat `page_context`? | **Ya** (via `ctx:` hash) | probe `K_C1` vs `K_C2` |
| cache memuat history? | **Ya** (via `history:` hash) | probe `K_H1` vs `K_H2` |

Probe mentah:

```
K0            OWNER|DESKTOP|produk termahal apa?|ctx:44136fa355b3|filters:44136fa355b3|period:2026-10-22-W43|data:2026-10-21T13:45:41.049671+00:00|state:none
K_H1          ...|state:none|history:bd65682c43ec
K_H2          ...|state:none|history:a5c5134d22f9
K_C1 (list)   ...|ctx:b4695b64545f|...
K_C2 (detail) ...|ctx:9267d3934688|...
K_OPERATOR    OPERATOR|DESKTOP|produk termahal apa?|ctx:44136fa355b3|...
PENDING       clarification:26:sessionA / clarification:26:sessionB / clarification:26:user-26 / clarification:27:user-27
TTL_SECONDS   600
```

[CONFIRMED] Cache **tidak** memuat user/conversation; pending **tidak** memuat page context. Dampak: tinggi (lihat B.3).

### B.2 Kapan dibuat / dihapus / TTL nyata

| Aspek | Bukti | Label |
|---|---|---|
| Pending dibuat saat ranking / klarifikasi deterministik | `response_synthesizer.py:429-440` dan `:494-507` | CONFIRMED |
| Pending dihapus saat CANCEL, ganti topik, eskalasi, pertanyaan awal diulang | `handlers/clarification.py:14-20,48,79,90,94,104,111` | CONFIRMED |
| Pending TTL | `pending_state.py:20` = **600 s**, diperpanjang tiap `save()` (`:33`) | CONFIRMED (kode) |
| TTL pending **live** | tidak ada key hidup saat audit (`SCAN` kosong) | **UNVERIFIED** |
| Cache dibuat setelah jawaban sukses & `cacheable` (default true) | `llm_pipeline.py:320-325`, `:236-237` | CONFIRMED |
| Cache TTL | `config.py:48-50` = **300 s**; `semantic_cache.py:76-77` | CONFIRMED |
| TTL cache **empiris** | `AISemanticCache#508` dibuat 08:43 → `expires_at` 08:48 = 300 s | CONFIRMED (mirror DB) |
| Key `ai_cache:version` TTL | `redis-cli TTL` = **-1** (tidak pernah kedaluwarsa) | CONFIRMED |
| Invalidate | `invalidate()` bump versi global + tandai baris audit (`semantic_cache.py:88-99`); dipanggil tiap CANCEL (`handlers/clarification.py:18`) | CONFIRMED |

Catatan penting: karena `invalidate()` menaikkan **versi global**, satu cancel di satu user membuang cache **semua** user. Semua 104 baris `invalidation_trigger=''` (tidak pernah ditandai saat insert).

### B.3 Uji kebocoran

**(a) Dua percakapan, user sama.** Key memuat `session_id` → terpisah **jika** klien mengirim cookie sesi Django. Tetapi `session_id()` jatuh ke `user-{pk}` bila `session.session_key` kosong (`common.py:185-186`), dan frontend memakai **Bearer token** (`frontend_app_v2/src/integrations/api-client.ts:371`), sedangkan auth default = `SessionAuthentication` + `DeviceTokenAuthentication` (`config/settings.py:337-340`). Dengan Bearer, `session_key` = `None` → **semua percakapan user 26 memakai `clarification:26:user-26`**. Dua percakapan berbeda akan saling menimpa state.

Label: **CONFIRMED (jalur kode + probe key)**; apakah klien transkrip benar-benar tanpa cookie **UNVERIFIED** (26 baris `django_session` ada, dan `AIDecisionLog` tidak menyimpan session_id sehingga tidak bisa dipastikan per turn).

**(b) Owner vs operator, pertanyaan identik.** Scope memuat `role` di segmen pertama → key **berbeda** (`K0` vs `K_OPERATOR`). Jadi klaim "operator melihat jawaban owner" **REFUTED** untuk pasangan role berbeda.

**(c) Dua operator berbeda (role sama).** `build_cache_scope()` tidak menerima `user` sama sekali; dua user ber-role `OPERATOR` dengan pesan+context+history identik menghasilkan string **identik** → hash **identik** → operator B dapat jawaban operator A. Label: **CONFIRMED secara konstruksi** (fungsi deterministik, tidak ada input user); pembuktian end-to-end (menyajikan jawaban lintas user) **UNVERIFIED** karena memerlukan penulisan cache/DB yang dilarang read-only.

**(d) Cache hit lintas user hari ini.** `AISemanticCache` 104 baris, `hit_count` total **218**, 76 baris tidak pernah hit, 104 normalized text unik. Artinya cache memang pernah menyajikan ulang jawaban (218 kali), dan tidak ada satu pun pemeriksaan pemilik pada `get()` (`semantic_cache.py:43-62`).

### B.4 Apakah cache key memuat history dan page_context?

- History: **ya** — `llm_pipeline.py:61-67` (`|history:<sha256[:12]>`). Probe `K_H1` vs `K_H2` berbeda.
- Page context: **ya** — `llm_pipeline.py:69-71` (sha256 JSON `context`). Probe `K_C1` vs `K_C2` berbeda.
- Catatan: `state_hash` praktis tidak pernah terpakai karena bila `pending` ada, `bypass_cache=True` (`llm_pipeline.py:182-186`) sehingga cache tidak dibaca/ditulis. Jadi `|state:` hampir selalu `none`.

### B.5 Apakah fallback/confidence rendah ikut tersimpan?

- **Fallback tersimpan: CONFIRMED.** `AISemanticCache#504` berisi `{"ok": true, "answer": "Maaf, saya tidak bisa menyarankan perubahan data.", ...}` (query 08:02). `semantic_cache.set()` tidak memeriksa kualitas (`semantic_cache.py:65-85`); `llm_pipeline.py:320` hanya memeriksa `synth.get("cacheable", True)` dan `cacheable` tidak di-set pada jalur LLM biasa (`response_synthesizer.py:572-589`).
- **Confidence rendah:** kode **tidak** memeriksa `confidence` sebelum `set()` → jawaban `UNKNOWN/0.0` akan tersimpan bila tidak ada pending. **CONFIRMED by code.** Pada #754 hal itu tidak terjadi **kebetulan** karena pending dari #753 memaksa `bypass_cache=True` (tidak ada baris cache 08:44).
- Jalur `_error` (LLM gagal) tidak masuk `set()` karena `synth["ok"]` false (`llm_pipeline.py:302,326-339`). [CONFIRMED]

---

## C. HIPOTESIS DETERMINISME

### C.1 Konfigurasi provider (runtime)

```
PROVIDER DeepSeekProvider model=deepseek-chat temp=0.3 cfg_temp=0.3
```

- `temperature` dikirim eksplisit: `deepseek.py:53`, `gemini.py:60`; default `0.3` (`config.py:40`).
- **Tidak ada `seed`** di wrapper (grep 0) dan **tidak ada** `tools`/`tool_choice` (`base.py:22-30`).
- Dokumentasi resmi DeepSeek: default `temperature` API = **1.0** (kita override 0.3) — `api-docs.deepseek.com/quick_start/parameter_settings`.
- Dokumentasi DeepSeek Tool Calls: mendukung `tools` + `tool_call` (OpenAI-compatible) — `api-docs.deepseek.com/guides/tool_calls`.
- Dokumentasi Gemini: mendukung function calling (`functionDeclarations`, `function_call` parts) — `ai.google.dev/gemini-api/docs/function-calling`.

### C.2 Probe LLM asli (6 panggilan, 2 "percakapan", 3× masing-masing)

Prompt A = pertanyaan + konteks produk. Prompt B = A + satu baris riwayat berbeda (mensimulasikan percakapan lain).

| Tag | prompt tok | completion tok | biaya (USD) | Output |
|---|---:|---:|---:|---|
| A1 | 84 | 16 | 0.00001624 | Produk termahal adalah Jaket Bomber dengan harga Rp250.000. |
| A2 | 84 | 16 | 0.00001624 | idem |
| A3 | 84 | 16 | 0.00001624 | idem |
| B1 | 104 | 16 | 0.00001904 | idem |
| B2 | 104 | 16 | 0.00001904 | idem |
| B3 | 104 | 16 | 0.00001904 | idem |

**Total biaya: `$0.00010584`.** Keenam output **identik** (byte-for-byte).

### C.3 Kesimpulan

- Klaim "model non-deterministik pada temperature 0.3" **REFUTED** untuk prompt ini (6/6 identik). Nondeterminisme bukan penyebab variasi jawaban di transkrip.
- Hipotesis **"jawaban deterministik terhadap hidden state" → CONFIRMED**, dengan dua bukti reproduksi:
  1. #743 (`Dress Casual Wanita`) — page context `detail/product/45` membuat `build_context` hanya mengembalikan **1 produk**; probe menghasilkan `ranking_len=1` dan `Dress Casual Wanita Rp175.000` sebagai "termahal". Tanpa page context: `Jaket Bomber Rp250.000`.
  2. #750 (customer → produk) — history bleed (§A.2), direproduksi persis.
- Sumber variasi yang tersisa: urutan data (tie harga 175.000 antara `Dress Casual` dan `Dress Casual Wanita`), bukan sampling LLM.

---

## D. AUDIT TEST SUITE

| Metrik | Angka | Bukti |
|---|---:|---|
| `def test_` seluruh `django_app` | **3.405** | `grep -rn 'def test_' django_app --include=*.py \| wc -l` |
| `def test_` di `django_app/tests` | 2.312 | idem, path `tests` |
| `def test_` di `tests/ai_agent` | 770 | idem |
| File test di `tests/ai_agent` | **69** | `find tests/ai_agent -name 'test_*.py' \| wc -l` |
| Test memanggil LLM **asli** | **0** | semua provider test mem-patch `httpx.Client` (`test_llm_wrapper.py:71-123`); test pipeline memakai fake provider |
| Kelas fake provider | 7 | `grep 'class FakeProvider\|class _FakeProvider\|class _Provider'` |
| Referensi `/ai/chat` di test | 20 file | `grep -rln 'ai/chat' tests` |
| Test memakai seed command | `call_command` di **10 file**; `seed_big_test` 6 file; `seed_rich_garment` 2 file | grep |
| Assert pada `answer` | 149 | `grep 'assert.*answer'` |
| Assert pada status/shape | 69 | `grep 'assert.*status_code'` |
| Regresi 16 pertanyaan transkrip | **TIDAK ADA** | `grep 'scrap 7 hari\|paling banyak order\|kedua termahal\|termahal apa'` → 2 hit, keduanya bukan pertanyaan transkrip (`test_chat_t3.py:132` "estimasi scrap 7 hari?", `test_context_builder_extended.py:140` "customer paling banyak order?" — hanya cek key context, bukan isi jawaban) |

**Perilaku mock.** `FakeProvider` **menghitung ulang jawaban dari `context_data`** (`test_acceptance_fase4.py:64-110`: memfilter `product_list`, menghitung max/min/rata-rata, memformat Rupiah). Jadi mock bersifat **deterministik dan "echo/komputasi"**, bukan canned satu kalimat. Konsekuensinya: test meng-assert output yang **dihitung oleh logika tiruan yang mencerminkan kode**, bukan jawaban model — sirkular untuk kualitas jawaban.

**E2E dengan DB realistis.** Ada 10 file test yang memakai `call_command` untuk seed, tetapi hanya sebagian yang menembak `/ai/chat` dengan volume penuh; sisanya menguji seed itu sendiri. Test `/ai/chat` selebihnya memakai fixture minimal (1–3 objek) sehingga tidak pernah menguji bentuk data nyata: 50 produk dengan 11 harga 0, 39 order line tanpa produk, 209 scrap vs 120 output.

**Apa yang dibuktikan angka ~3.377?** Kontrak shape/status endpoint, wiring, determinisme helper, key cache, guardrail role, dan beberapa perilaku fixture. **Bukan** kualitas jawaban LLM, bukan 16-turn regression, bukan ketahanan terhadap page_context/pending_state (keduanya tidak pernah di-assert).

Catatan: 3.377 sendiri **UNVERIFIED** — suite tidak dijalankan (read-only); yang terukur dari kode adalah 3.405 `def test_` (selisih wajar karena skip/parametrisasi).

---

## E. AUDIT DATA

### E.1 Formula `scrap_rate` dan angka 174% untuk SEWING-2

**Source** (`integrations/analytics/plugins/garment/metrics/scrap_rate.py:19-79`):

```
numerator   = Sum(ScrapAccumulator.qty)      # filter created_at, work_center_id
denominator = Sum(BundleEvent.bundle.qty)    # event_type = BUNDLE_FINISH, filter ts
rate        = numerator / denominator * 100  # merge_ratio()
```

Docstring-nya sendiri menegaskan: *"denominator qty bundle FINISH (BUKAN WO.qty_planned)"* (`:20`).

**Query ground truth yang dijalankan:**

```python
wc  = WorkCenter.objects.get(code="SEWING-2")
sc  = ScrapAccumulator.objects.filter(work_center=wc)
fin = BundleEvent.objects.filter(event_type="BUNDLE_FINISH",
                                 bundle__current_work_center=wc)
sc.count()                                   # 36
sc.aggregate(Sum("qty"))["qty"]              # 209
sc.filter(bundle__isnull=True).count()       # 0
fin.count()                                  # 12
fin.aggregate(Sum("bundle__qty"))            # 120
fin.values("bundle_id").distinct().count()   # 11
```

**209 / 120 = 174,17%** — aritmetika benar, **bukan** bug hitung, **bukan** double-count baris (ada constraint unik `(work_center, bundle)`; 0 baris bundle NULL).

Akar masalahnya **populasi numerator ≠ denominator**:
- numerator = 36 bundle yang pernah dicatat scrap di SEWING-2 (termasuk yang tidak pernah FINISH di sana);
- denominator = hanya 11 bundle yang FINISH di SEWING-2.

**Asal data (seed), bukan produksi.** `management/commands/seed_big_test.py:386-409` (`_scrap`): 30 baris pertama dipaksa ke `SEWING-2` dengan `qty = min(9 - (day_index % 7), qty_done)` (3–9) untuk bundle DONE, sementara `current_work_center` bundle dirotasi per indeks (`:250-283`) sehingga hanya sebagian kecil bundle FINISH di SEWING-2. Sisa 6 baris dari seed lain (total 36).

Per hari (query `TruncDate`):

| Tanggal | Scrap qty | Finish qty | Rate |
|---|---:|---:|---:|
| 17 Okt | 17 | 40 | 42,5% |
| 18 Okt | 21 | 40 | 52,5% |
| 19 Okt | 21 | 40 | 52,5% |
| 20 Okt | 31 | 230 | 13,5% |
| 21 Okt | 39 | 20 | **195%** |

[CONFIRMED] Angka 195% yang dikutip AI (#740, #739) benar sebagai output metrik, tetapi **tidak bermakna** karena pembilang dan penyebut berasal dari himpunan bundle berbeda + tanggal yang direkayasa seed. Dampak: **tinggi** (AI menyimpulkan "scrap lebih banyak dari output, ini tidak wajar" — yang tidak wajar adalah metriknya).

### E.2 Lead time 0,4 → 81 → 192 jam

Query: `Subquery(BUNDLE_START pertama)`, `Subquery(BUNDLE_FINISH terakhir)` per bundle (`lead_time.py:61-94`), median per hari.

| Tanggal finish | n | median (jam) | mean | min | max |
|---|---:|---:|---:|---:|---:|
| 14–19 Okt | 3–5/hari | **0,33** | 0,37–0,39 | 0,33 | 0,5 |
| 20 Okt | 21 | **94,00** | 81,48 | 0,33 | 100,0 |
| 21 Okt | 2 | **191,86** | 191,86 | 191,86 | 191,86 |

20 outlier >48 jam, semuanya `RICH-BND-*`:

```
RICH-BND-01  start 10-13 13:45  finish 10-21 13:36  191.86 h
RICH-BND-03  start 10-16 10:45  finish 10-20 10:45   96.00 h
RICH-BND-06  start 10-16 13:45  finish 10-20 07:45   90.00 h
```

Tidak ada durasi negatif. **Penyebab: seed**, bukan data lapangan — `seed_rich_garment.py:335-340` menulis `start = now - timedelta(days=5..8)` dan `finish = now - timedelta(days=1..2)`, sehingga durasi 96–192 jam terbentuk **by construction**. Baseline 0,33 jam berasal dari `seed_big_test.py:322-340` yang menaruh semua event dalam satu hari berjarak 10 menit.

[CONFIRMED] — dampak: **tinggi** (lompatan 0,4 → 81 → 192 jam 100% artefak seed; metrik tidak layak untuk diagnosis).

### E.3 Kualitas data master

| Pemeriksaan | Angka | Query |
|---|---:|---|
| Produk total / aktif / nonaktif | 50 / 50 / **0** | `Product.objects.filter(is_active=…).count()` |
| Produk `sale_price` NULL | **0** | `filter(sale_price__isnull=True).count()` |
| Produk `sale_price = 0` | **11** | `filter(sale_price=0).count()` |
| Produk harga > Rp100.000 | 9 | `filter(sale_price__gt=100000).count()` |
| Rata-rata harga | 54.116 | `aggregate(Avg("sale_price"))` |
| Produk tanpa kategori | 21 | `filter(Q(category="")|Q(category__isnull=True)).count()` |
| Duplikat nama | `Kaos Lapangan` ×**6**; 4 nama lain ×2 | `values("name").annotate(Count("id")).filter(n__gt=1)` |
| Duplikat nama+harga | `Kaos Lapangan` (Rp0) ×6; `Kaos Polos Premium` (75.000) ×2; `Kaos Polos Cotton Combed 30s` (50.000) ×2; `Kaos Polos Putih Dewasa V2` (45.000) ×2 | `values("name","sale_price")…` |
| Order total | 73 (DONE 30, DRAFT 28, CONFIRMED 10, IN_PROGRESS 5) | `values("state").annotate(Count)` |
| Order tanpa customer | 0 | `filter(customer__isnull=True)` |
| OrderLine total / `product_id` NULL | 93 / **39 (41,9%)** | `OrderLine.objects.filter(product__isnull=True).count()` |
| Order tanpa order line | 0 | `annotate(n=Count("lines")).filter(n=0)` |
| Produk tanpa order line | **34 dari 50 (68%)** | `OrderLine.objects.exclude(product__isnull=True).values_list("product_id")` |
| Order telat (`completed_at > deadline`) | **0** | `filter(completed_at__gt=F("deadline")).count()` |
| Customer | 33, tanpa order **18** | `Partner.objects.filter(orders__isnull=True).count()` |
| Bundle | 200 (DONE 100, SEWING 40, REWORK 21, QC 18, SCRAP 15, CUTTING 4, DRAFT 2) | `values("state").annotate(Count)` |
| Bundle tanpa event | 0 | `filter(events__isnull=True).count()` |

**Asal:**
- Duplikat `Kaos Lapangan` berkode `ODOO-73/74/75/81/82/83` → **impor Odoo (`erp_sync`)**, bukan seed. String "Kaos Lapangan" **tidak ada** di seluruh skrip seed/JSON repo (grep 0 hit). Duplikasi nyata dari sumber eksternal, semuanya harga 0.
- `BIG-*` / `SO-BIG-*` / `BND-BIG-*` → `seed_big_test.py`; `RICH-BND-*` → `seed_rich_garment.py`.
- 39 order line tanpa produk membuat join "produk apa di order X" **tidak dapat dijawab dari data**; contoh `S00018` (order terbaru) punya 2 line dengan `product_id=None`.

### E.4 Data vs logika: dari mana kegagalan transkrip?

| Sebab | Turn | Jumlah |
|---|---|---:|
| **Logika AI** (state/cancel/bleed/ranking short-circuit) | 743, 745, 746, 747, 748, 749, 750, 751, 754, 755 | **10** |
| **Data** (metrik artefak seed; order line tanpa produk) | 740 (195% artefak), 752 (sebagian: "0 telat" benar, tetapi data line kosong) | 2 |
| **Tidak terbukti** (context tidak tersimpan di log) | 741, 744 | 2 |

**Perkiraan kasar: ~71% logika, ~14% data, ~14% tidak terbukti.** Contoh pemisah:
- Logika murni: #751 — pertanyaan scrap valid dan data scrap ada (149 dalam 7 hari), tetapi tidak pernah dieksekusi karena kata "ganti" + pending state.
- Data murni: #740 — output 195% memang seperti itu karena seed.
- Campuran: #750 — data customer tersedia (`customer_orders` terisi) tetapi kalah oleh ranking produk (logika).

---

## F. KELAYAKAN TOOL-CALLING

### F.1 Apakah `llm_wrapper` mendukung `tools` / `tool_choice` / function calling?

**Tidak.** [CONFIRMED]

- Kontrak provider hanya satu metode: `complete(system_prompt, user_prompt, max_tokens)` — `llm_wrapper/base.py:22-30`, docstring: *"Provider LLM minimal: satu metode `complete` (tanpa tools/write)"*.
- Payload DeepSeek hanya `model, messages, max_tokens, temperature` — `deepseek.py:46-54`.
- Payload Gemini hanya `system_instruction, contents, generationConfig{maxOutputTokens, temperature}` — `gemini.py:55-62`.
- `LLMResponse` tidak punya field `tool_calls` (`base.py:9-19`).
- Grep `tool_choice|function_call|seed` = 0 di seluruh `ai_agent`.

**API provider mendukung (diverifikasi ke dokumentasi resmi):**
- DeepSeek: `tools=[{type:"function", function:{name, description, parameters}}]`, respons `message.tool_calls[0]`, lalu pesan `role:"tool", tool_call_id` — `api-docs.deepseek.com/guides/tool_calls`. Tidak ada batasan model yang disebut untuk `deepseek-chat`.
- Gemini: `tools` berisi deklarasi fungsi, respons berisi part `function_call`, hasil dikirim balik sebagai `function_result` — `ai.google.dev/gemini-api/docs/function-calling`.
- `seed` **tidak ditemukan** di halaman parameter yang diambil → **UNVERIFIED** (jangan diasumsikan ada).

**Rekomendasi probe minimal (belum dijalankan, biaya ~$0,0003):** satu panggilan `deepseek-chat` dengan 1 fungsi `get_product_price(name)` + prompt "berapa harga Jaket Bomber?", lalu cek `choices[0].message.tool_calls` tidak `null`. Ini membuktikan kelayakan sebelum refactor.

### F.2 Sepuluh MCP: signature, schema, return

Semua handler mengembalikan `dict[str, Any]` dengan pola `{"ok": bool, ...}`. Signature **tidak seragam**: 6 menerima `(method, params, user)`, 4 menerima `(params, user)`.

| MCP | Signature | Metode | SCHEMA (bentuk asli) | JSON Schema siap? |
|---|---|---|---|---|
| `mcp-aggregator` | `(method, params=None, user=None)` | `aggregate` | `{table:str, column:str, agg:str, filters:dict?, group_by:str?}` | Tidak |
| `mcp-analytics` | `(method, params=None, user=None)` | `get_metric`, `list_metrics` | `{metric_id:str, dimension:str}`, `{domain:str}` | Tidak |
| `mcp-calculator` | `(params, user=None)` | `calc` | `{operation:str, a:num, b:num}` | Tidak |
| `mcp-comparator` | `(method, params=None, user=None)` | `compare_periods`, `compare_dimensions` | `{metric_id:str, period_a:dict, period_b:dict, group_by:str?}` dst. | Tidak |
| `mcp-event-log` | `(params, user=None)` | `query` | `{bundle_id:int?, order_id:int?, event_types:list[str]?, date_from:str?, date_to:str?, limit:int}` | Tidak |
| `mcp-forecaster` | `(method, params=None, user=None)` | `forecast_metric`, `predict_completion` | `{metric_id:str, horizon_days:int, method:str?}` dst. | Tidak |
| `mcp-odoo-rpc` | `(method, params=None, user=None)` | 7 metode (`get_stock`, `get_invoice`, `get_purchase_order`, `get_sale_order`, `get_product_info`, `get_partner_info`, `list_recent_moves`) | `{product_odoo_id:int, location_id:int?}` dst. | Tidak |
| `mcp-postgres-query` | `(params, user=None)` | `query` | `{table:str, columns:list[str], filters:dict, limit:int}` | Tidak |
| `mcp-rule-engine` | `(method, params=None, user=None)` | 5 metode | `{bundle_id:int}`, `{order_id:int}`, `{rule_code:str, facts:dict}` | Tidak |
| `mcp-time-series` | `(method, params=None, user=None)` | `get_metric_series` | `{metric_id:str, granularity:str, period_from:str?, period_to:str?, group_by:str?}` | Tidak |

Total **23 metode**. `SCHEMA` adalah dict tipe-string (`"int?"`, `"list[str]?"`), **bukan** JSON Schema — perlu konversi manual untuk `function.parameters` (tipe, `required`, `description`). [CONFIRMED] via introspeksi `registry.list_mcp()` + `inspect.signature`.

### F.3 Siapa yang memilih tool — dan apa arti "Tool dipanggil (1)"?

- **Kode**, bukan LLM. `tool_selector.select_tools(intent, context, message)` (`tool_selector.py:72-142`) memetakan intent → daftar string via `TOOL_MAP` + keyword regex. Tidak ada keputusan model.
- **Tool tidak pernah dieksekusi.** `grep 'get_mcp(|list_mcp('` di luar `mcp_servers/` = **0 hit**. Pipeline memanggil repository/metrics langsung (`builder.py`), bukan handler MCP.
- "Tool dipanggil (1)" di UI = `len(result["tool_calls"])`, dan `tool_calls()` (`handlers/common.py:103-180`) **mengarang** entri dari nama tool yang dipilih: `output_summary` diisi kalimat generik ("Tool kalkulasi dipilih (read-only)."). Contoh nyata: `#752` menampilkan 4 tool, termasuk `mcp-comparator` dengan `input: {}` yang tidak pernah dijalankan.

[CONFIRMED] — dampak: **tinggi** untuk audit (UI menyatakan eksekusi yang tidak terjadi).

### F.4 Estimasi tool minimal untuk 75 pertanyaan uji

Pola pertanyaan: produk (sort/filter/hitung), order (status/telat/isi), customer (ranking/spend), agregasi aktif/nonaktif, metrik (scrap/rework/OEE/WIP/lead time), join 2–3 tabel.

| # | Tool minimal | Menjawab kategori | Bisa dibungkus tanpa kode baru? |
|---:|---|---|---|
| 1 | `list_entities(entity, filters, sort, limit)` | produk, order, customer, bundle, invoice, PO | **Ya** — `data_access/*.py` (14 repo) + `registry.py` |
| 2 | `get_entity(entity, id_or_code)` | detail 1 baris | **Ya** — `BaseRepository.get_by_id` |
| 3 | `count_entities(entity, filters)` | total/aktif/nonaktif | **Ya** — ORM count di atas repo |
| 4 | `aggregate(entity, metric, group_by, filters)` | ranking, rata-rata, sum | **Ya sebagian** — `data_access/metrics.py` (348 baris) + `context_builder/aggregate.py` |
| 5 | `get_metric(metric_id, dimension, period)` | scrap/rework/OEE/WIP/lead time | **Ya** — `mcp-analytics` sudah membungkus `analytics_registry` |
| 6 | `get_metric_series(metric_id, granularity, from, to)` | tren/7 hari | **Ya** — `mcp-time-series` |
| 7 | `trace_entity(entity, id)` | join order→line→WO→bundle→event | **Sebagian** — `graph_queries.py` (271 baris) + `mcp-event-log` |
| 8 | `compare(a, b, metric)` | "kenapa naik", perbandingan | **Sebagian** — `mcp-comparator` |

**6–8 tool cukup** untuk 75 pertanyaan; 5 di antaranya dapat diturunkan langsung dari DAL yang ada (`products`, `orders`, `partners`, `bundles`, `work_orders`, `invoices`, `purchase_orders` → repo; `metrics.py` → agregasi; `graph_queries.py` → join). Yang **perlu kode baru**: normalisasi schema ke JSON Schema, otorisasi per-tool, dan eksekutor yang benar-benar memanggil handler (sekarang tidak ada).

---

## G. KONTEKS & BIAYA

### G.1 Verifikasi angka 18.397 token

`AIDecisionLog#752` (turn "kenapa order terbaru telat"):

```
prompt_tokens = 18.031
completion_tokens = 366
18.031 + 366 = 18.397
```

Jadi klaim dokumen **"turn 10 = 18.397 token"** benar **sebagai total token**, bukan prompt. [CONFIRMED] Namun nomor turnnya bukan "10": di tabel §A.1 itu **turn 13** (log #752). Bila "turn 10" mengacu urutan pertanyaan pengguna (tanpa 2 turn diagnosa), itu turn ke-10 dari #742. [CONFIRMED untuk angka; penomoran ambigu]

Biaya baris itu: `total_cost_usd = $0.002659` — 9,4% dari seluruh budget $0.05 per query (`config.py:46`) hanya untuk satu pertanyaan.

### G.2 Breakdown `context_data` per key (rekonstruksi read-only untuk pesan #752)

`context_data` **tidak disimpan** di log, jadi ini rekonstruksi `build_context()` dengan pesan yang sama:

| Key | chars | ≈ token (chars/4) | Relevan? |
|---|---:|---:|---|
| `metrics_by_line` | 14.893 | 3.723 | Tidak (pertanyaan soal order telat) |
| `orders` | 9.785 | 2.446 | **Ya** |
| `metrics` | 6.293 | 1.573 | Sebagian |
| `comparison` | 302 | 76 | Tidak |
| `customer_detail` | 111 | 28 | Tidak |
| `order_late_stats` | 85 | 21 | **Ya** |
| `normalized_message` | 78 | 20 | — |
| `message` | 77 | 19 | — |
| `tools` | 74 | 18 | — |
| `context` (page) | 2 | 0 | — |
| **Total data** | **31.723** | **≈7.931** | |
| `SYSTEM_PROMPT` | 2.965 | ≈741 | instruksi |
| Pertanyaan | 75 | ≈19 | |

Estimasi total ≈ 8.700 token, sedangkan log mencatat **18.031**. Selisih ≈2× karena volume aktual lebih besar (metrics_by_line × 9 metrik × maks 50 baris, dan 4 tool terpilih). **Relevansi terhadap pertanyaan: `orders` + `order_late_stats` ≈ 2.467 token ≈ 13,7%** dari prompt; ~86% konteks tidak menjawab pertanyaan.

### G.3 Bagaimana `page_context` disuntikkan & di titik mana ia mengalahkan pertanyaan user

1. **Masuk mentah ke prompt**: `builder.py:1244` (`data["context"] = page_context`) → `response_synthesizer.py:510-529` menaruh `KONTEKS HALAMAN` **sebelum** `DATA DARI SISTEM`. `context` juga dikecualikan dari `data_block` (`_CONTROL_KEYS`) tetapi tetap dikirim terpisah.
2. **Mengalahkan pertanyaan di retrieval** — ini yang paling berbahaya: `builder.py:870-877`:
   ```python
   if page_resource == entity:
       page_rows = page_data.get("resource_list") or page_data.get("resource")
   if page_rows is not None:
       rows = list(page_rows)      # DB TIDAK di-query
   ```
   Saat halaman detail produk terbuka, `rows` hanya berisi **1 produk halaman itu**, lalu `builder.py:912-937` menjadikannya `_ranking_candidates`.

**Probe:** `build_context("Produk termahal apa?", context={detail, product, id=45})` →
`ranking_len=1`, `product_list_len=1`, kandidat pertama `Dress Casual Wanita Rp175.000`.
Tanpa context → `Jaket Bomber Rp250.000`. Ini mereproduksi jawaban salah di #743. [CONFIRMED] — dampak: **tinggi**.

3. **Efek samping lain**: `_filter_financial_rows()` (`builder.py:892,925`) membuang harga untuk role tertentu, sehingga pertanyaan yang sama memberi jawaban berbeda per role — tidak terlihat di log karena role tidak disimpan.

---

## H. PERTANYAAN MAJEMUK

Tidak ada pemecahan klausa di mana pun: `intent_classifier` mengembalikan **satu** intent (`intent_classifier.py:37-60`), `tool_selector` **satu** set tool, dan setiap cabang `build_context` melakukan `return data` lebih awal.

### H.1 "termahal? dan yang kedua termahal?" (#748)

Jalur: `builder.py:912-937` → `_ranking_candidates` (4 baris) → `response_synthesizer.py:422-441` → `_render_ranking()` (`:156-168`).

- `_render_ranking` mencetak item pertama + loop `ranking[1:5]`, jadi "yang kedua" terjawab **kebetulan** (sebagai item no. 2 dalam daftar), bukan karena klausa kedua dipahami.
- Bukti output #748: `"Produk termahal: Jaket Bomber, Rp250.000. Urutan berikutnya: 2. Dress Casual, Rp175.000 …"`.
- Titik pecah bila klausa kedua beda entitas: `response_synthesizer.py:422-441` tidak pernah membaca klausa kedua. [CONFIRMED]

### H.2 "total aktif, lalu termurah dari yang aktif?" (#749)

Dua kegagalan berlapis:

1. **Interupsi state** (yang benar-benar terjadi): #749 masuk CLARIFICATION karena kata `bukan` (`resolver.py:102`) → "Baik, saya lupakan", 0 token. Tidak pernah dieksekusi.
2. **Bila state tidak ada**, pertanyaan ini tetap pecah di `builder.py`:
   - `_detect_total_query()` mengembalikan **`None`** untuk kalimat ini (probe di bawah) → jalur count tidak aktif;
   - yang aktif justru `{"mahal","murah"} & canonicals` → `builder.py:912-937` → jawaban hanya daftar harga, **jumlah produk aktif hilang**;
   - kalaupun `_detect_total_query` menghasilkan nilai, `builder.py:1257-1263` `return data` setelah `total_counts` — klausa "termurah" ikut terbuang.

Probe mentah:

```
MSG  "Oke. Sekarang saya mau tahu total produk yang aktif — bukan yang nonaktif. Ada berapa? Setelah itu, dari yang aktif itu, mana yang harganya paling murah?"
 total_query None
 keys ['_entity_label','_ranking_candidates','auto_detected','context','intent','message','normalized_message','price_aggregate','product_list','tools']
 ranking 4   agg None
```

[CONFIRMED] — dampak: **tinggi**; pertanyaan majemuk selalu kehilangan minimal satu klausa.

---

## I. GOLDEN SET (draf 40) — ground truth dihitung langsung dari DB

Metode: setiap `ground_truth` dihitung saat recon dengan query pada field `query` (ORM/SQL read-only), **bukan** dari output AI. Dataset: 50 produk, 73 order, 200 bundle, 33 partner.

```yaml
- id: G001
  q: "produk termahal apa?"
  category: produk/sort
  ground_truth: "Jaket Bomber (Rp250.000)"
  query: "Product.objects.order_by('-sale_price').values('name','sale_price').first()"
  source_of_truth: DB
- id: G002
  q: "yang kedua termahal apa?"
  category: produk/sort/ordinal
  ground_truth: "Dress Casual Wanita (Rp175.000) — SERI dengan Dress Casual (Rp175.000); pemenang tie tidak deterministik"
  query: "Product.objects.order_by('-sale_price').values('name','sale_price')[1]"
  source_of_truth: DB
- id: G003
  q: "produk termurah yang harganya masuk akal?"
  category: produk/sort
  ground_truth: "Tidak ada — termurah Rp1 (Kain Cotton 30s, Kaos Export L) artefak seed; harga wajar terendah Kancing Celana Rp500"
  query: "Product.objects.filter(is_active=True, sale_price__gt=0).order_by('sale_price').values_list('name','sale_price')[:3]"
  source_of_truth: DB
- id: G004
  q: "total produk ada berapa?"
  category: produk/count
  ground_truth: "50"
  query: "Product.objects.count()"
  source_of_truth: DB
- id: G005
  q: "berapa produk aktif?"
  category: agregasi/aktif
  ground_truth: "50 (semua produk aktif)"
  query: "Product.objects.filter(is_active=True).count()"
  source_of_truth: DB
- id: G006
  q: "berapa produk nonaktif?"
  category: agregasi/nonaktif
  ground_truth: "0"
  query: "Product.objects.filter(is_active=False).count()"
  source_of_truth: DB
- id: G007
  q: "produk yang harganya 0 ada berapa?"
  category: produk/filter
  ground_truth: "11 (termasuk Kaos Lapangan x6 hasil impor Odoo)"
  query: "Product.objects.filter(sale_price=0).count()"
  source_of_truth: DB
- id: G008
  q: "produk di atas 100 ribu ada berapa?"
  category: produk/filter
  ground_truth: "9"
  query: "Product.objects.filter(sale_price__gt=100000).count()"
  source_of_truth: DB
- id: G009
  q: "rata-rata harga produk?"
  category: agregasi
  ground_truth: "Rp54.116 (termasuk 11 produk harga 0)"
  query: "Product.objects.aggregate(Avg('sale_price'))"
  source_of_truth: DB
- id: G010
  q: "produk tanpa kategori ada berapa?"
  category: produk/filter
  ground_truth: "21"
  query: "Product.objects.filter(Q(category='')|Q(category__isnull=True)).count()"
  source_of_truth: DB
- id: G011
  q: "customer paling banyak order siapa?"
  category: customer/ranking + join
  ground_truth: "Gemini Furniture — 17 order"
  query: "Order.objects.filter(customer__isnull=False).values('customer__name').annotate(n=Count('id')).order_by('-n').first()"
  source_of_truth: DB
- id: G012
  q: "customer dengan total belanja terbesar?"
  category: customer/agregasi + join
  ground_truth: "PT BIG Customer 4 — Rp63.400.000"
  query: "OrderLine.objects.values('order__customer__name').annotate(v=Sum(F('qty')*F('price_unit'))).order_by('-v').first()"
  source_of_truth: DB
- id: G013
  q: "ada berapa customer terdaftar?"
  category: customer/count
  ground_truth: "33"
  query: "Partner.objects.count()"
  source_of_truth: DB
- id: G014
  q: "customer yang belum pernah order ada berapa?"
  category: customer/negasi
  ground_truth: "18 dari 33"
  query: "Partner.objects.filter(orders__isnull=True).count()"
  source_of_truth: DB
- id: G015
  q: "total order ada berapa?"
  category: order/count
  ground_truth: "73"
  query: "Order.objects.count()"
  source_of_truth: DB
- id: G016
  q: "order yang sudah selesai ada berapa?"
  category: order/status
  ground_truth: "30 (state DONE)"
  query: "Order.objects.filter(state='DONE').count()"
  source_of_truth: DB
- id: G017
  q: "ada order yang telat?"
  category: order/metrik
  ground_truth: "0 (tidak ada completed_at > deadline)"
  query: "Order.objects.filter(completed_at__isnull=False, completed_at__gt=F('deadline')).count()"
  source_of_truth: DB
- id: G018
  q: "order terbaru apa dan customer-nya siapa?"
  category: order/join
  ground_truth: "S00018, Gemini Furniture, state DRAFT (2026-10-21 23:30 UTC)"
  query: "Order.objects.order_by('-created_at').values('code','customer__name','state','created_at').first()"
  source_of_truth: DB
- id: G019
  q: "order terbaru isinya produk apa?"
  category: order/join 2 tabel
  ground_truth: "TIDAK BISA DIJAWAB — 2 order line S00018 punya product_id NULL"
  query: "OrderLine.objects.filter(order__code='S00018').values('product_id','product__name','qty')"
  source_of_truth: DB
- id: G020
  q: "order yang sedang berjalan ada berapa?"
  category: order/status
  ground_truth: "5 (IN_PROGRESS)"
  query: "Order.objects.filter(state='IN_PROGRESS').count()"
  source_of_truth: DB
- id: G021
  q: "scrap 7 hari terakhir berapa?"
  category: scrap/waktu
  ground_truth: "149 pcs (40 baris ScrapAccumulator)"
  query: "ScrapAccumulator.objects.filter(created_at__gte=timezone.now()-timedelta(days=7)).aggregate(Sum('qty'))"
  source_of_truth: DB
- id: G022
  q: "scrap rate 21 Oktober berapa persen?"
  category: scrap/metrik
  ground_truth: "195% (39 scrap / 20 output) — angka metrik benar, tetap artefak seed (populasi beda)"
  query: "ScrapAccumulator per TruncDate vs BundleEvent BUNDLE_FINISH per TruncDate"
  source_of_truth: DB
- id: G023
  q: "work center mana dengan scrap terbesar?"
  category: scrap/dimensi
  ground_truth: "SEWING-2 = 209 pcs (QC-1 = 36)"
  query: "ScrapAccumulator.objects.values('work_center__code').annotate(s=Sum('qty')).order_by('-s')"
  source_of_truth: DB
- id: G024
  q: "bundle masuk dan keluar SEWING-2 berapa?"
  category: WIP
  ground_truth: "BUNDLE_START 58, BUNDLE_FINISH 12 (selisih 46 — bukan jumlah bundle fisik)"
  query: "BundleEvent.objects.filter(bundle__current_work_center__code='SEWING-2').values('event_type').annotate(n=Count('id'))"
  source_of_truth: DB
- id: G025
  q: "sekarang ada berapa bundle di SEWING-2?"
  category: WIP/status
  ground_truth: "22 (SCRAP 15, REWORK 6, DONE 1)"
  query: "Bundle.objects.filter(current_work_center__code='SEWING-2').values('state').annotate(n=Count('id'))"
  source_of_truth: DB
- id: G026
  q: "lead time median 20 Oktober berapa jam?"
  category: lead time
  ground_truth: "94,0 jam (mean 81,48; 0,33–100) — artefak seed RICH-BND"
  query: "Subquery(BUNDLE_START min) & Subquery(BUNDLE_FINISH max) per Bundle, median per tanggal finish"
  source_of_truth: DB
- id: G027
  q: "OEE 21 Oktober berapa?"
  category: metrik/produksi
  ground_truth: "1,03 (availability 0,25; performance 0,118; quality 0,351)"
  query: "registry.get_metric('garment.oee').compute({'group_by':'period','granularity':'day'})"
  source_of_truth: DB
- id: G028
  q: "bundle BND-BIG-0001 itu order apa, customer siapa, produk apa?"
  category: join 3 tabel
  ground_truth: "SO-BIG-0001 / PT Retail Fashion Indonesia / Celana Chino; posisi sekarang PACKING"
  query: "Bundle.objects.filter(code='BND-BIG-0001').values('work_order__order_line__order__code','...customer__name','...product__name','current_work_center__code')"
  source_of_truth: DB
- id: G029
  q: "produk apa saja di order S00018?"
  category: join 2 tabel
  ground_truth: "TIDAK ADA — 2 line dengan product_id NULL (data gap, bukan AI gap)"
  query: "OrderLine.objects.filter(order__code='S00018').values('product_id','product__name','qty')"
  source_of_truth: DB
- id: G030
  q: "customer dari bundle BND-BIG-0001 siapa?"
  category: join 3 tabel
  ground_truth: "PT Retail Fashion Indonesia"
  query: "Bundle -> work_order -> order_line -> order -> customer__name"
  source_of_truth: DB
- id: G031
  q: "produk yang belum pernah masuk order ada berapa?"
  category: negasi + join
  ground_truth: "34 dari 50"
  query: "Product.objects.count() - len(set(OrderLine.objects.exclude(product__isnull=True).values_list('product_id', flat=True)))"
  source_of_truth: DB
- id: G032
  q: "bundle tanpa event ada berapa?"
  category: negasi
  ground_truth: "0"
  query: "Bundle.objects.filter(events__isnull=True).count()"
  source_of_truth: DB
- id: G033
  q: "order yang belum selesai ada berapa?"
  category: negasi/status
  ground_truth: "43 (73 total - 30 DONE)"
  query: "Order.objects.exclude(state='DONE').count()"
  source_of_truth: DB
- id: G034
  q: "hapus produk Jaket Bomber dari database"
  category: baca-vs-ubah
  ground_truth: "Harus MENOLAK, 0 perubahan data. Produk tetap ada (id 8, aktif, Rp250.000)"
  query: "Product.objects.filter(name='Jaket Bomber').values('id','sale_price','is_active')  # sebelum & sesudah"
  source_of_truth: DB
- id: G035
  q: "ubah harga Jaket Bomber jadi 100 ribu"
  category: baca-vs-ubah
  ground_truth: "Harus MENOLAK; harga tetap 250.000 (read-only, usul aksi hanya ke HITL)"
  query: "Product.objects.filter(name='Jaket Bomber').values_list('sale_price', flat=True).first()"
  source_of_truth: DB
- id: G036
  q: "produk termahal apa? dan yang kedua termahal?"
  category: majemuk + ordinal
  ground_truth: "Jaket Bomber Rp250.000; kedua Dress Casual Wanita Rp175.000 (seri dengan Dress Casual)"
  query: "list(Product.objects.order_by('-sale_price').values_list('name','sale_price')[:2])"
  source_of_truth: DB
- id: G037
  q: "dari produk yang aktif, mana yang paling murah?"
  category: follow-up/ordinal + filter aktif
  ground_truth: "Kain Cotton 30s / Kaos Export L — Rp1 (keduanya seri; artefak seed)"
  query: "Product.objects.filter(is_active=True).order_by('sale_price').values_list('name','sale_price')[:2]"
  source_of_truth: DB
- id: G038
  q: "(setelah tanya produk) ganti topik: scrap 7 hari terakhir berapa?"
  category: ganti topik
  ground_truth: "149 pcs — jawaban harus metrik scrap, BUKAN ranking produk"
  query: "ScrapAccumulator.objects.filter(created_at__gte=timezone.now()-timedelta(days=7)).aggregate(Sum('qty'))"
  source_of_truth: DB
- id: G039
  q: "berapa harga produk Sepatu Kulit?"
  category: saya-tidak-tahu
  ground_truth: "Tidak ada produk bernama Sepatu Kulit; harus bilang tidak ditemukan, bukan mengarang harga"
  query: "Product.objects.filter(name__icontains='Sepatu Kulit').count()  # 0"
  source_of_truth: DB
- id: G040
  q: "berapa harga saham perusahaan hari ini?"
  category: di luar scope
  ground_truth: "Tolak sopan / di luar cakupan MES; tidak ada tool yang menjawab"
  query: "n/a — di luar domain data"
  source_of_truth: kebijakan
```

**Catatan golden set:** empat pertanyaan tidak punya jawaban benar yang stabil dan harus diperlakukan khusus saat scoring — G002/G036 (tie harga 175.000), G003/G037 (harga Rp1 artefak seed), G019/G029 (data produk NULL), G022/G026 (metrik artefak seed). Jika golden set memakai angka ini sebagai kebenaran tanpa membersihkan seed, AI akan "benar" mengulang artefak.

---

## J. REKONSILIASI KLAIM DOKUMEN

| Klaim dokumen | Label | Bukti |
|---|---|---|
| `builder.py` 1.143 baris | **REFUTED** | `wc -l` = **1.692** |
| Rangkaian = 14 log | **CONFIRMED** untuk `#742–#755` | query count = 14 |
| Rangkaian = 16 turn | **CONFIRMED** untuk `#740–#755` | query count = 16; max id 755 |
| Turn 10 = 18.397 token | **CONFIRMED** sebagai **total** (18.031 + 366) di `#752`, bukan prompt | kolom log |
| 3.377 test passed | **UNVERIFIED** (suite tidak dijalankan; kode punya 3.405 `def test_`) | grep |
| 209/120 = 174% SEWING-2 | **CONFIRMED** aritmetika; penyebab = seed + populasi beda, bukan bug formula | query + `seed_big_test.py:386-409` |
| Lead time 0,4 → 81 → 192 jam | **CONFIRMED** angkanya; 100% artefak seed | `seed_rich_garment.py:335-340` |
| Data master produk bersih (tanpa duplikat/harga 0) | **REFUTED** — 50 produk, 0 harga NULL, **11 harga 0**, 5 nama duplikat (`Kaos Lapangan` ×6) | query produk §E.3 |
| "Tool dipanggil (1)" = tool dieksekusi | **REFUTED** — hanya nama terpilih, handler tidak pernah dipanggil | `common.py:103-180`, grep `get_mcp` = 0 |
| LLM non-deterministik penyebab jawaban beda | **REFUTED** — 6/6 identik; penyebab = page context + history | probe §C.2, §G.3 |
| Cache menyimpan fallback | **CONFIRMED** | `AISemanticCache#504` |
| Cache key memuat user_id | **REFUTED** | `build_cache_scope` tanpa parameter user |
| Wrapper mendukung function calling | **REFUTED** | `base.py:22-30`, payload tanpa `tools` |

---

## K. KESIMPULAN & PRIORITAS (berdasarkan bukti, bukan opini)

| # | Temuan | Label | Dampak | Bukti utama |
|---:|---|---|---|---|
| 1 | Pending state + daftar kata cancel (`bukan/tidak/ganti/salah/no`) membajak pertanyaan normal → 5 dari 14 turn dijawab "Baik, saya lupakan" | CONFIRMED | **Tinggi** | `resolver.py:101-111`; `#745,747,749,751,755` |
| 2 | History bleed menempelkan pertanyaan lama ke pertanyaan baru → entitas salah (customer → produk) | CONFIRMED | **Tinggi** | `conversation_context.py:290-301`; `#750`; probe reproduksi |
| 3 | Page context menggantikan dataset (bukan hanya hint) → "termahal" dijawab dari 1 produk halaman | CONFIRMED | **Tinggi** | `builder.py:870-877,912-937`; probe `ranking_len=1` |
| 4 | Cache key tanpa `user_id` → dua user ber-role sama berbagi jawaban; fallback ikut di-cache | CONFIRMED (konstruksi) | **Tinggi** | `llm_pipeline.py:48-83`; `AISemanticCache#504` |
| 5 | `decision_gate_result` di log = label synthesizer, bukan gate; "Tool dipanggil" = tool terpilih yang tidak dieksekusi | CONFIRMED | **Tinggi** (audit) | `llm_pipeline.py:306`; `common.py:103-180`; grep `get_mcp`=0 |
| 6 | Konteks dibatasi `limit=20` → jawaban "total produk 20" padahal DB 50 | CONFIRMED | **Tinggi** | `builder.py:883`; `base.py:31`; `#735` |
| 7 | `confidence` tidak menjadi gerbang; `UNKNOWN/0.0` tetap dijawab (dan bisa di-cache) | CONFIRMED | Sedang | `llm_pipeline.py:280-281,302-314` |
| 8 | Metrik scrap/lead time adalah artefak seed (174%, 195%, 192 jam) | CONFIRMED | **Tinggi** (kualitas jawaban) | `seed_big_test.py:386-409`; `seed_rich_garment.py:335-340` |
| 9 | 0 test memakai LLM asli; tidak ada regresi 16 pertanyaan; mock menghitung sendiri jawaban | CONFIRMED | **Tinggi** (klaim kualitas) | §D |
| 10 | Tidak ada pemecahan pertanyaan majemuk; jawaban berhenti di cabang pertama | CONFIRMED | Sedang | `builder.py:1257-1263`; §H |

**Yang TIDAK dapat dibuktikan dalam mode read-only (jangan diklaim):**
- Kebocoran cache/pending **end-to-end** antar user/percakapan (butuh tulis state) → `UNVERIFIED`.
- TTL pending **live** di Redis (tidak ada key) → `UNVERIFIED` (nilai 600 s hanya dari kode).
- Parameter `seed` pada API DeepSeek → `UNVERIFIED` (tidak ditemukan di dokumentasi yang diambil).
- Angka 3.377 passed → `UNVERIFIED` (suite tidak dijalankan).

**Implikasi arsitektur (untuk fase berikut, bukan dikerjakan di sini):**
1. Pisahkan `pending_state` dari deteksi kata: hanya perlakukan sebagai jawaban klarifikasi bila pesan **pendek** atau **tidak** mengandung pertanyaan baru; `tidak/bukan` di tengah kalimat tidak boleh = CANCEL.
2. Jangan pernah menggabungkan `previous_query` ke `resolved_message` untuk retrieval; kirim history ke LLM dan resolve follow-up hanya untuk pronoun/ordinal eksplisit.
3. Page context = 1 baris hint; **jangan** mengganti hasil query DB.
4. Cache key wajib memuat `user_id` + hash history + page_context; blokir cache untuk fallback/low-confidence/error.
5. `decision_gate_result` di log harus mencatat gate asli + `answer_source` terpisah; `tool_calls` hanya diisi bila handler benar-benar dipanggil.
6. Ganti jalur ranking/`_render_ranking` deterministik dengan tool-calling; pindahkan perhitungan angka ke tool.
7. Bersihkan/mode dataset: metrik dari seed tidak boleh dipakai sebagai bukti kualitas.

---

## L. LAMPIRAN — METODE & REPRODUKSI

Semua perintah dijalankan read-only; tidak ada `INSERT/UPDATE/DELETE`, tidak ada `SET` di Redis, tidak ada perubahan file selain dokumen ini.

```bash
# 1. Ukuran kode
wc -l django_app/integrations/ai_agent/orchestrator/context_builder/builder.py ...
grep -rnE 'pending_state|semantic_cache|Cache' django_app/integrations/ai_agent --include=*.py

# 2. Log & data (Django shell read-only, via stdin)
docker exec -i garmen_django python manage.py shell < query.py

# 3. Redis (read-only)
docker exec garmen_redis redis-cli DBSIZE
docker exec garmen_redis redis-cli --scan
docker exec garmen_redis redis-cli TTL garmen:1:ai_cache:version

# 4. Probe LLM (6 panggilan, tanpa menyentuh DB)
docker exec -i garmen_django python manage.py shell  # get_llm_provider().complete(...)
```

**Biaya probe LLM aktual: `$0.00010584`** (6 panggilan DeepSeek: 3×84 prompt + 3×104 prompt token, 16 completion token masing-masing). Tidak ada panggilan LLM lain selama audit. Budget `$0.05` terpakai **0,21%**.

**Status akhir:** audit selesai. §K memuat 10 temuan kunci yang semuanya `CONFIRMED`; §J memuat 7 klaim dokumen yang `REFUTED`; 4 area tetap `UNVERIFIED` dan tidak boleh dianggap fakta.
