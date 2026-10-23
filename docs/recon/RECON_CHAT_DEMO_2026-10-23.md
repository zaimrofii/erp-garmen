# RECON — Chat Demo AI Agent (2026-10-23)

- **Mode:** auditor read-only. Tidak ada perubahan kode/config/data. Tidak ada panggilan LLM.
- **Basis:** branch `demo-ready`, commit `a4520a8` (HEAD saat audit: `36ed204`, hanya docs).
- **Sumber bukti:**
  1. Kode repo (`django_app/...`, nomor baris).
  2. `AIDecisionLog` sesi demo **#1162–#1180** (2026-10-23 04:24–04:30 UTC) — transkrip mesin.
  3. Query ORM mentah ke DB `garmen_django` (dikutip apa adanya).
- **Keterbatasan:** transkrip UI mentah tidak tersimpan di repo; yang ada adalah `AIDecisionLog`
  (query_text, response_text, tools_called, confidence, model). Nomor Q reviewer dipetakan ke ID log
  berdasarkan isi pertanyaan.

**Temuan kunci:** demo TIDAK berjalan di agent loop Fase 2. `AI_AGENT_TOOLS_ENABLED` default `False`
(`config/settings.py:813`) dan `.env:78` hanya berisi `AI_AGENT_ENABLED=true`, sehingga `/ai/chat`
memakai pipeline LAMA (`api/views.py:146-149` → `run_pipeline`). Semua `RULE_HIT`, template legacy, dan
`confidence 0.80` berasal dari `orchestrator/` + `clarification/` lama, bukan dari `agent/loop.py`.

---

## A. Verifikasi 4 temuan reviewer

### A1. [CONFIRMED] Write request tidak dikenali sebagai write

- **Klaim:** "Ubah harga Jaket Bomber jadi 100rb" dijawab "Tidak ada produk untuk 'Ubah harga…'".
- **Bukti:**
  - `AIDecisionLog#1172` — gate `RULE_HIT`, model `rule:empty`, `confidence 0.0`, `prompt_tokens 0`,
    `tools_called []`, answer `Tidak ada produk untuk 'Ubah harga Jaket Bomber jadi 100rb.' di data saat ini.`
  - Deteksi write di agent: `grep -n 'preflight_refusal|REFUSAL_WRITE' integrations/ai_agent/agent/loop.py`
    → **kosong** (fitur ini hanya ada di branch `feat/agent-tools`, tidak di `demo-ready`).
  - Deteksi write di legacy: `grep -rni 'hapus|delete|write' integrations/ai_agent/decision_gate/*.py
    integrations/ai_agent/api/handlers/llm_pipeline.py` → **kosong**.
  - Jalur yang menangani: `run_pipeline` (`api/views.py:149`) → context_builder menghasilkan
    `_candidates` kosong → `response_synthesizer.py:470-478` (`rule:empty`) →
    `clarification/templates.py:131-132` (`text = f" untuk '{query}'"`).
- **Kenapa bukan LLM_NEEDED:** `rule:empty` menang sebelum LLM (0 token). Tidak ada rule yang
  mengklasifikasikan kalimat imperatif ("ubah/hapus") sebagai write-intent, baik di legacy maupun
  agent loop pada `demo-ready`.
- **Dampak:** TINGGI (keamanan/persepsi) — jawaban terbaca "data kosong", bukan "saya tidak boleh mengubah".
- **Perbaikan di:** `integrations/ai_agent/agent/loop.py` (pre-flight) **dan** legacy
  `api/handlers/llm_pipeline.py` sebelum `rule:empty` (flag masih off).

### A2. [CONFIRMED] Inkonsistensi angka scrap 21 Okt: 37 vs 14, dua-duanya "70%"

- **Bukti log:**
  - `AIDecisionLog#1165` ("Scrap 7 hari terakhir…"): `"output hanya 20 unit tapi scrap 37 unit"`,
    tools = `mcp-analytics (scrap_rate, rework_rate, lead_time, oee, wip_flow)`.
  - `AIDecisionLog#1171` ("Kenapa scrap naik?"): `"Puncaknya di 21 Oktober: scrap 70% (14 dari 20 unit)"`.
- **Bukti DB (2026-10-21):**
  ```
  SCRAP21_ROWS 8 baris (PACKING 3+3, QC-1 1, SEWING-1 1, SEWING-2 9+9+9+4)
  SCRAP21_SUM  {'s': 39, 'c': 8}            # SUM(qty)=39, COUNT=8
  BY_WC        PACKING s=6; QC-1 s=1 r=4; SEWING-1 s=1; SEWING-2 s=31 r=3 e=1
  METRIC_WEEK  {'2026-10-21': value=70.0, numerator=14, denominator=20}
  ```
- **Interpretasi:** `14` = numerator metrik `garment.scrap_rate` (kohort bundle DONE) —
  `integrations/analytics/plugins/garment/metrics/scrap_rate.py:30-34,71-85`; `70%` = 14/20.
  Angka `37` **tidak dapat direproduksi** (SUM qty = 39, COUNT = 8, numerator = 14).
- **Label rinci:** inkonsistensi **CONFIRMED**; asal `37` **UNVERIFIED**.
- **Dampak:** TINGGI (akurasi: satu metrik ditampilkan dua nilai absolut berbeda dalam satu sesi).
- **Perbaikan di:** `orchestrator/context_builder` + `response_synthesizer` (jalur aktif): satu sumber
  angka (numerator/denominator), larang mencampur angka dari tool lain tanpa label definisi.

### A3. [CONFIRMED] Template "tidak ditemukan" mengutip seluruh kalimat user

- **Bukti kode:** `clarification/templates.py:129-132`
  ```python
  def empty_response(entity_label: str, query: str) -> str:
      text = f" untuk '{query}'" if query else ""
      return f"Tidak ada {entity_label}{text} di data saat ini."
  ```
- **Bukti log:** `AIDecisionLog#1180` — query `"Kasih saya data bundle BND-XYZ-9999"` → answer
  `Tidak ada bundle untuk 'Kasih saya data bundle BND-XYZ-9999' di data saat ini.`
  `#1175`/`#1176` (BND-DEMO-01) memakai template identik.
- **Ekstraksi kode sudah ada tetapi tidak dipakai:** `orchestrator/context_builder/builder.py:800
  _extract_specific_code(...)` (dipanggil `builder.py:862`), bukan oleh `empty_response`.
- **Dampak:** SEDANG (kredibilitas; jawaban terlihat seperti error mesin).
- **Perbaikan di:** `clarification/templates.py:129-132` — pakai kode hasil `_extract_specific_code`.

### A4. [CONFIRMED] "Produk di atas 100rb ada 7" tetapi daftar 8

- **Bukti log:** `AIDecisionLog#1162` — `"Produk jadi (FG) dengan harga di atas Rp100.000 ada 7:"`
  lalu menulis **8** butir (Jaket Bomber 250k, Celana Jean China 180k, Dress Casual Wanita 175k,
  Dress Casual 175k, Kemeja Lengan Panjang 165k, Celana Chino 160k, Kemeja Formal Lengan Panjang 150k,
  Kemeja Formal 150k).
- **Bukti DB:**
  ```
  P100_COUNT 10   UNIQ_NAMES 10
  FG-JKT-RICH 250000 Jaket Bomber | JEAN_9999 180000 Celana Jean China |
  FG-DRS-RICH 175000 Dress Casual | FG-DRS-001 175000 Dress Casual Wanita |
  FG-KMJ-BIG-2 165000 Kemeja Lengan Panjang | FG-CHN-RICH 160000 Celana Chino |
  FG-KMJ-RICH 150000 Kemeja Formal | FG-KMJ-001 150000 Kemeja Formal Lengan Panjang |
  ODOO-90 110000 Kain Rib | ODOO-88 105000 Kain Cotton Combed 30S
  ```
- **Kesimpulan:** angka `7` salah relatif DB (10 produk > 100rb; 8 bila hanya FG ≥ 150rb). Angka ini
  dihasilkan **LLM**, bukan `count` tool (tidak ada count di `tools_called` #1162); tidak ada validator
  angka di jalur legacy. **Sub-klaim duplikat REFUTED:** "Kemeja Formal" (`FG-KMJ-RICH`) dan "Kemeja
  Formal Lengan Panjang" (`FG-KMJ-001`) adalah dua produk berbeda.
- **Dampak:** SEDANG (jumlah tidak cocok dengan daftar pada kalimat yang sama).
- **Perbaikan di:** hitung dari daftar yang dirender (`response_synthesizer`) atau arahkan ke
  `count_records`/`list_records` di agent.

---

## B. Temuan BARU dari transkrip

### B1. [REFUTED] "AI tidak menjawab nyangkut di WC mana" (Q7)

- **Bukti:** `AIDecisionLog#1166` menjawab dua klausa: `"belum telat — statusnya masih DRAFT, deadline
  kosong … Soal 'nyangkut di WC mana': data tidak punya info bundle/proses per order … SEWING-2 paling
  bermasalah: scrap 70%, WIP menumpuk"`. DB: `S00018 {'state': 'DRAFT', 'deadline': None,
  'completed_at': None}`.
- **Catatan:** premis "telat" tidak valid (`deadline = NULL`); model menyatakannya dengan benar. Risiko:
  data WIP global disisipkan seolah relevan untuk order spesifik.
- **Dampak:** RENDAH (jawaban benar) / SEDANG untuk risiko generalisasi.
- **Perbaikan di:** context_builder — bila `deadline` NULL, kembalikan `no_lateness_data` eksplisit.

### B2. [CONFIRMED] "Yang kedua?" ambigu karena harga seri (Q8)

- **Bukti:** DB punya dua produk 175.000: `FG-DRS-RICH` (Dress Casual) dan `FG-DRS-001`
  (Dress Casual Wanita). `AIDecisionLog#1168` → `"Yang kedua: Dress Casual — harga Rp175.000"`;
  `#1167` (RULE_HIT `rule:ranking`) menampilkan urutan 2 = Dress Casual.
- **Analisis:** urutan dari list `ranking` context_builder (ORDER BY harga DESC) lalu dirender
  `response_synthesizer.py:156-168` (`_render_ranking`) tanpa tie-break eksplisit; tie-break efektif =
  urutan baris DB.
- **Dampak:** SEDANG (jawaban tidak deterministik antar-run).
- **Perbaikan di:** `ORDER BY sale_price DESC, code ASC` + sebut tie-break di jawaban.

### B3. [CONFIRMED] "Stok cuma 3 produk, semuanya 0" (Q10)

- **Bukti:** `AIDecisionLog#1170` → `"Data stok yang tersedia cuma 3 produk, dan semuanya menunjukkan
  jumlah 0: Celana Jean China, Kaos Polos Putih Dewasa V2, dan Customizable Desk"`;
  `tools_called` = 1 (`mcp-postgres-query`), `get_stock` tidak dipanggil.
- **Akar:** tidak ada tabel stok lokal; stok dibaca on-demand dari Odoo
  (`apps_industry/garment/models/inventory_adjustment.py:16`). Jalur legacy hanya menyertakan 3 produk
  ke konteks, sehingga klaim "semua stok 0" tidak mewakili 62 produk.
- **Dampak:** TINGGI (kesimpulan bisnis salah).
- **Perbaikan di:** route ke `get_stock` (agent) atau tarik stok semua produk di context_builder.

### B4. [CONFIRMED] BND-DEMO-01 memang tidak ada, tetapi jawabannya tidak konsisten

- **Bukti DB:** `Bundle.objects.filter(code__in=['BND-DEMO-01','BND-BIG-0001'])` → hanya
  `{'code': 'BND-BIG-0001', 'state': 'DONE', 'current_work_center__code': 'PACKING'}`.
- **Inkonsistensi (pertanyaan sama, 3 jawaban):** `#1175` RULE_HIT → "Tidak ada bundle untuk 'Baca
  bundle BND-DEMO-01'…"; `#1176` RULE_HIT → template sama untuk "Detail bundle…"; `#1177` LLM_NEEDED →
  "Data bundle BND-DEMO-01 kosong…". `#1179` (BND-BIG-0001) membuktikan tool bisa menemukan bundle
  yang ADA.
- **`find_entity` vs `list_records`:** keduanya query DB (`tools/find_entity.py` `icontains` pada
  code/name; `tools/list_records.py` filter exact `code`); untuk kode yang tidak ada keduanya kosong —
  tidak ada perbedaan yang menyebabkan kegagalan.
- **Dampak:** SEDANG (frasa tidak konsisten, bukan salah data).
- **Perbaikan di:** satu jalur "tidak ditemukan" (lihat A3).

### B5. [CONFIRMED] Confidence 0.80 / 0.00 hardcoded

- **Bukti kode:** `orchestrator/intent_classifier.py:57` → `"confidence": 0.8 if intent != "UNKNOWN" else 0.0`.
- **Bukti log:** mayoritas #1163–#1180 `0.8`; `0.0` di #1168, #1172, #1173, #1174.
- **Inkonsistensi internal:** dua jawaban `rule:empty`: #1172 = **0.0**, #1175/#1176 = **0.8**.
- **Dampak:** SEDANG (observability palsu).
- **Perbaikan di:** `intent_classifier.py:57` — hapus angka tetap atau isi skor nyata.

### B6. [CONFIRMED] Chart dari jalur legacy, bukan dari tool agent

- **Bukti:** `grep -rln 'chart' integrations/ai_agent/agent` → kosong; chart ada di
  `api/handlers/llm_pipeline.py:317` (`chart_data`) dan `orchestrator/chart_builder.py`.
- **Implikasi:** "Tren Scrap" dibangun dari context legacy, bukan `series` tool `get_metric`; jika flag
  dinyalakan, chart hilang.
- **Dampak:** SEDANG (fitur demo bergantung pada jalur yang akan dihapus di Fase 5).
- **Perbaikan di:** port `chart_builder` ke agent (`get_metric.series`).

---

## C. Audit observability

### C1. [CONFIRMED] "Tool dipanggil (N)" = jumlah tool yang DIPILIH, bukan yang dieksekusi

- **Bukti model:** `models.py:82` hanya `tools_called = models.JSONField(...)`; tidak ada field
  `tool_executed`/`status` per tool.
- **Bukti penulis:** `api/handlers/common.py:106-160` membentuk entri `{tool, input, output_summary}`
  tanpa flag eksekusi; ringkasan diambil dari context (mis. `"Tidak ada data resource yang dikembalikan."`).
- **Bukti log:** `#1166` menampilkan 4 tool, dua di antaranya berisi "Tidak ada …"; `#1172`
  menampilkan **0** tool walau jawaban tetap dihasilkan.
- **Dampak:** TINGGI (angka N tidak bisa dipakai untuk audit).
- **Perbaikan di:** tambah `executed` + `error` per entri (registry agent sudah punya `executed`;
  `common.py` legacy belum) dan tampilkan "N dipanggil / M berhasil".

### C2. [CONFIRMED] RULE_HIT masih jalur lama; demo tidak memakai agent loop

- **Bukti kode:** `grep -n 'RULE_HIT' integrations/ai_agent/agent/loop.py` → kosong; RULE_HIT hanya di
  `api/handlers/llm_pipeline.py:138,149,229,233` dan `orchestrator/response_synthesizer.py:188`
  (model `rule:ranking`/`rule:empty`/`rule:safety`).
- **Bukti konfigurasi:** `config/settings.py:813` (`AI_AGENT_TOOLS_ENABLED = env_bool(..., False)`) dan
  `.env:78` hanya `AI_AGENT_ENABLED=true`.
- **Bukti log:** seluruh #1163–#1180 `tools_called` berisi `mcp-*` (legacy), **tidak satu pun** tool
  produksi (`count_records`, `aggregate`, `get_metric`, `aggregate_operator`, …).
- **Kesimpulan:** arsitektur **BELUM** tool-calling murni pada demo; jalur lama yang aktif.
- **Dampak:** TINGGI (hasil demo tidak merepresentasikan Fase 2).
- **Perbaikan di:** nyalakan flag khusus sesi demo (bukan default) atau hentikan klaim Fase 2 untuk demo.

### C3. [CONFIRMED] Confidence 0.80/0.00 bukan dari model

- Sama dengan B5 (`intent_classifier.py:57`). Agent loop tidak menulis `confidence`
  (`grep -n 'confidence' agent/loop.py` → kosong); `_agent_response` mengirim `validator` tetapi tidak
  mengisi `confidence_score`, sehingga jatuh ke default `1.0` (`api/handlers/common.py:79`).
- **Dampak:** SEDANG.
- **Perbaikan di:** `api/handlers/common.py:79` + `_agent_response` (isi dari provider atau `null`).

---

## D. Prioritas perbaikan (urut dampak)

| # | Kategori | Temuan | Dampak | Aksi |
|---|---|---|---|---|
| 1 | Keamanan | A1 write tidak dikenali | TINGGI | pre-flight write di `agent/loop.py` + `llm_pipeline.py` (aktif walau flag off) |
| 2 | Akurasi data | A2 37 vs 14 untuk 70% | TINGGI | satu sumber angka (numerator/denominator metrik) |
| 3 | Akurasi data | B3 stok hanya 3 produk | TINGGI | pakai `get_stock` / tarik stok semua produk |
| 4 | Kejujuran demo | C2 demo di jalur lama | TINGGI | nyalakan flag untuk demo atau hentikan klaim Fase 2 |
| 5 | Observability | C1 "Tool dipanggil (N)" | TINGGI (audit) | tambah `executed`/`error` per tool |
| 6 | Akurasi data | A4 count 7 vs list 8 | SEDANG | hitung dari daftar yang dirender |
| 7 | Observability | B5/C3 confidence palsu | SEDANG | hapus hardcode 0.8 |
| 8 | Polish | A3 template mengutip kalimat | SEDANG | pakai `_extract_specific_code` |
| 9 | Polish | B4 frasa tidak konsisten | SEDANG | satu template "tidak ditemukan" |
| 10 | Determinisme | B2 tie-break harga | SEDANG | `ORDER BY harga DESC, code ASC` |
| 11 | Fitur | B6 chart hanya legacy | SEDANG | port chart ke `get_metric.series` |
| 12 | Polish | B1 WIP global untuk order DRAFT | RENDAH | tandai `no_lateness_data` |

---

## E. Pertanyaan yang harus dijawab sebelum demo

1. **UNVERIFIED — asal angka 37** (`AIDecisionLog#1165`). Tidak ada query/jejak yang menghasilkannya
   (DB: SUM qty = 39, COUNT = 8, numerator metrik = 14). Reproduksi manual context_builder diperlukan,
   atau hapus angka absolutnya.
2. **UNVERIFIED — jalur mana yang dipakai saat demo?** Flag `False` → pipeline lama (bukan Fase 2);
   flag `True` → chart hilang (B6) dan template legacy tidak dipakai. Harus diputuskan eksplisit.
3. **UNVERIFIED — daftar 10 pertanyaan demo** yang "dijamin lulus" tidak ada di repo pada branch
   `demo-ready` (`docs/demo/AI-DEMO-SCRIPT.md` hanya di `feat/agent-tools`).
4. **UNVERIFIED — apakah `ODOO-88`/`ODOO-90` (kain, > 100rb) sengaja dikecualikan** dari "produk di atas
   100rb" (#1162); tanpa aturan tertulis, angka 7/8/10 semuanya bisa dianggap benar oleh pembaca berbeda.




