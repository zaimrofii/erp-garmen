# Backlog T4 — MCP Kognitif (DITUNDA)

**Status:** Deferred (Sprint H T2+T3 DONE, 2026-10-20)
**Alasan:** Butuh Neo4j + ChromaDB (dependency berat), data dokumen belum siap.

## MCP yang ditunda
- mcp-knowledge-graph (Neo4j ISA-95)
- mcp-vector-search (ChromaDB + embedding)
- mcp-quality-correlation (korelasi cacat-operator-mesin)
- mcp-anomaly-explainer (jelaskan penyebab anomali)
- mcp-scheduler (jadwal produksi, kapasitas WC)

## Prasyarat sebelum mulai
1. Neo4j container (~1 GB) + ChromaDB (~500 MB) + sentence-transformers
   (~2 GB) — image Docker naik ~3–4 GB.
2. Dokumen SOP/QC di-upload (vector search butuh dokumen).
3. Data relasi lengkap (order → bundle → WC → operator) untuk KG.
4. Ops siap: sysadmin, monitoring, backup, RAM +2–4 GB.

## Kemampuan yang hilang (tanpa T4)
- "Apa akar masalah scrap di SEWING-2?" (KG)
- "SOP rework apa?" (vector)
- "Kenapa cacat naik di shift 2?" (quality-correlation)
- "Kapasitas WC besok?" (scheduler)

## Kemampuan yang sudah ada (T1–T2)
- Data dasar: produk, stok, invoice, PO (T1)
- Aturan bisnis: boleh lanjut? cukup stok? (T2)
- Agregat: total, rata-rata, p50/p90 (T2)
- Tren historis: 30 hari, per jam (T2)
- Banding: 2 periode, 2 line/WC (T3)
- Prediksi: kapan selesai? (T3)

## Kapan mulai?
- Setelah 2 klien live (bukti kebutuhan).
- Setelah dokumen SOP/QC di-upload.
- Setelah ops siap (sysadmin, RAM, monitoring).
