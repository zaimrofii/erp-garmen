# DEMO SCRIPT — Analytics + AI (5 menit)

**Persiapan (di luar durasi demo):**
1. `docker compose up -d`
2. `docker exec -w /app garmen_django python manage.py seed_demo_llm`
3. Buka `http://localhost:5173` dan login sebagai **admin/owner**.
4. Pastikan `AI_AGENT_ENABLED=true` dan backend AI sehat (`/api/health/`).

> Data demo memakai marker `DEMO LLM 2026-10` dan aman dijalankan ulang
> (idempoten).

---

## Skenario 1 — Analytics (2 menit)

**Klik:** menu **Analytics** → buka `/analytics`.

**Yang muncul:** 3 kartu metrik: **Scrap Rate**, **Rework Rate**, **Lead Time**.

**Presenter mengatakan:**
> “Ini adalah kondisi produksi hari ini. Scrap dan rework dihitung dari
> event lantai produksi, bukan input manual. Perhatikan rework di QC-1 dan
> scrap di SEWING-2.”

**Klik:** kartu **Scrap Rate** → pilih filter **Work Center = SEWING-2**.

**Yang muncul:** nilai scrap SEWING-2 naik (data demo), dengan numerator dan
denominator yang bisa diaudit.

**Klik:** **Settings → Analytics** (`/settings/analytics`).

**Yang muncul:** `enabled=true`, domain `garment`, status readiness sudah
di-acknowledge.

**Presenter mengatakan:**
> “Analytics aktif untuk domain garment; AI hanya boleh membaca metrik yang
> sudah diaktifkan.”

---

## Skenario 2 — AI Chat (2 menit)

**Klik:** menu **AI Chat** (`/ai/chat`).

**Ketik:** `kenapa scrap naik minggu ini?` → **Kirim**.

**Yang muncul (expected):**
- Jawaban natural berbahasa Indonesia.
- Menyebut **SEWING-2** dan angka scrap/rework dari data demo.
- Badge **LLM_NEEDED**; tokens > 0 (LLM nyata).
- Tidak ada saran write action.

**Presenter mengatakan:**
> “AI tidak mengarang. Ia menerima konteks dari metrik dan event produksi,
> lalu menyimpulkan penyebabnya. Semua angka berasal dari database.”

**Ketik:** `bundle mana paling lambat?` → **Kirim**.

**Yang muncul (expected):**
- Jawaban menyebut bundle dengan lead time panjang
  (`DEMO-LLM-LATE-01`, ~5 hari) dan metrik lead time.
- Token/cost bertambah; tidak crash.

**Fallback bila LLM/API key bermasalah:** tampil pesan rapi
`llm_failed` — demo lanjut ke Observability dan jelaskan fallback-nya.

---

## Skenario 3 — Floating Icon (1 menit)

**Klik:** **Master → Produk** → buka detail produk demo
(`DEMO-LLM-FG-01`).

**Klik:** ikon **AI mengambang** di kanan bawah.

**Yang muncul:** panel samping (drawer), **tidak redirect**, header
**“Produk: Kaos Demo Fashion”**.

**Ketik:** `produk ini kategorinya apa?` → **Kirim**.

**Yang muncul (expected):** jawaban dari `visible_fields_snapshot` produk
(kategori Kaos), tanpa membocorkan field sensitif.

**Presenter mengatakan:**
> “Konteks halaman otomatis terkirim. Field sensitif seperti password,
> API key, token, NPWP, dan credit limit disaring sebelum sampai ke LLM.”

---

## Skenario 4 — Observability (30 detik)

**Klik:** **Settings → AI Observability** (`/settings/ai-observability`).

**Yang muncul:**
- KPI requests, tokens, cost, cache hit.
- Grafik biaya per hari.
- Tabel `by_tool` dan `by_decision_gate`.

**Presenter mengatakan:**
> “Setiap keputusan AI tercatat: gate, tool, token, biaya, dan latency.
> Budget per user dibatasi; rate limit 60 request/menit.”

---

## Skenario 5 — HITL (30 detik)

**API (bukan UI):**
1. `GET /api/v1/ai/hitl/queue/` → **1 PENDING** dari seed demo
   (SUPERVISOR, MEDIUM).
2. `POST /api/v1/ai/hitl/<id>/approve/` → status **APPROVED**.

**Presenter mengatakan:**
> “AI hanya mengusulkan. Perubahan data tetap menunggu persetujuan manusia
> lewat HITL; audit trail mencatat approver dan waktunya.”

---

## Penutup (10 detik)

> “Semua berjalan read-only: analytics, context injection, guardrail, cost
> tracking, observability, dan HITL. Tidak ada write action dari LLM.”
