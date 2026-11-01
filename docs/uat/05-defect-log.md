# 05 — Defect Log UAT

> Register semua temuan. Update status: OPEN → IN_PROGRESS → FIXED → CLOSED / WONTFIX.

## Legenda
- **Tipe:** BUG / SPEC-GAP / MISUNDERSTANDING / IMPROVEMENT / DATA
- **Severity:** CRITICAL / HIGH / MEDIUM / LOW
- **Status:** OPEN / IN_PROGRESS / FIXED (belum retest) / CLOSED (retest lulus) / WONTFIX

## Register

| ID | Sesi | Skenario | Tipe | Sev | Judul | Dampak operasional | Bukti | PIC | Status | Retest |
|---|---|---|---|---|---|---|---|---|---|---|
| D-001 | 3 | SK-3.4 | BUG | CRITICAL | Offline queue kirim event 2x | Bundle dobel di laporan | `logs/mes.jsonl` L1234 | BE dev | CLOSED | PASS 2026-10-27 |
| D-002 | 2 | SK-2.12 | BUG | CRITICAL | Inventory adj FAILED (Odoo group) | Operator tidak bisa adjust stok | SyncRecord id 501 | Admin Odoo | CLOSED | PASS (S2-05 rerun) |
| D-003 | 5 | SK-5.1 | SPEC-GAP | MEDIUM | Q6 lead time jam→hari diblokir validator | AI jawab "tidak ada data" | demo_results.json q6 | AI eng | OPEN | — |

## Aturan
- **CRITICAL** → block gate sesi; wajib CLOSED + retest sebelum lanjut
- **HIGH** → boleh lanjut sesi, wajib CLOSED sebelum deploy
- **MEDIUM/LOW** → masuk backlog, tidak block gate
- **SPEC-GAP/MISUNDERSTANDING** → update blueprint, bukan fix kode
- **DATA** → keputusan bisnis (data owner), bukan bug

## Rekap
| Status | Jumlah |
|---|---|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| FIXED (belum retest) | 0 |
| CLOSED | 0 |
| WONTFIX | 0 |
| **CRITICAL open** | **0** ← wajib 0 sebelum deploy |
| **HIGH open** | **0** ← wajib 0 sebelum deploy |