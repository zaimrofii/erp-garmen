# Backlog Migrasi — Fase Berat-Lite → Fase Berat Penuh

## Status: Fase Berat-Lite (SEMENTARA)

**Berlaku sejak:** 2026-10-21
**Ganti:** Neo4j (KG) + ChromaDB (vector)

## Alasan Sementara

- Dependency berat (~3-4 GB Docker), RAM +2-4 GB.
- Ops rumit (cluster, backup, monitoring baru).
- Data relasi & dokumen belum siap.
- Validasi pasar belum (belum 2 klien live).

## Komponen Sementara

| Komponen | Ganti | Kapan Upgrade |
|---|---|---|
| PostgreSQL recursive CTE (`graph_queries.py`) | Neo4j (KG) | Setelah 2 klien + butuh graph traversal |
| PostgreSQL full-text search (`document_search.py`) | ChromaDB (vector) | Setelah 2 klien + butuh semantic search |
| SQL korelasi (`MetricsRepository.quality_*`) | mcp-quality-correlation | Setelah data relasi lengkap |
| Rule-based explainer (`anomaly_explainer.py`) | mcp-anomaly-explainer (KG) | Setelah KG |
| DailySummary (`summary.py` + task) | Summary Store L2/L3 | Bisa tetap (tidak perlu upgrade) |

## Kapan Upgrade ke Fase Berat Penuh?

- 2+ klien live + bayar.
- Butuh semantic search (bukan full-text).
- Data relasi & dokumen siap.
- Ops siap (sysadmin, RAM, monitoring).

## Catatan

- Setiap modul sementara ditandai `TEMPORARY` di docstring.
- Migrasi ke Neo4j/ChromaDB: implementasi adapter baru, switch via flag
  `USE_GRAPH_DB=true` / `USE_VECTOR_DB=true`.
- Interface tetap sama (`graph_queries.py`, `document_search.py`) — ganti
  implementasi, bukan kontrak.
- Full-text memakai PostgreSQL `SearchVector`/`SearchRank` (tanpa ekstensi
  wajib); fallback kemiripan `SequenceMatcher` menangani typo. `pg_trgm`
  opsional bila ekstensi tersedia.
- Seed demo: `python manage.py seed_documents` (8 SOP/QC).
