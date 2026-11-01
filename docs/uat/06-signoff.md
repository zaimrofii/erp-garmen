# 06 — Sign-off UAT

> Gate keputusan per sesi + keputusan akhir deploy. Satu tabel per sesi, lalu keputusan akhir.

## Gate per Sesi

| Sesi | Tanggal | PASS | FAIL | BLOCKED | CRITICAL open | Keputusan | TTD |
|---|---|---|---|---|---|---|---|
| 0 Smoke | | 4/4 | 0 | 0 | 0 | ✅ LANJUT | |
| 1 Master | | 17/18 | 1 | 0 | 0 | ✅ LANJUT | |
| 2 Transaksi | | 22/22 | 0 | 0 | 0 | ✅ LANJUT | |
| 3 Lantai | | 15/16 | 1 | 0 | 0 | ✅ LANJUT | |
| 4 Laporan | | 16/16 | 0 | 0 | 0 | ✅ LANJUT | |
| 5 AI & WA | | 10/12 | 2 | 0 | 0 | ⚠️ CONDITIONAL | |
| 6 Cross-cutting | | 8/8 | 0 | 0 | 0 | ✅ LANJUT | |

**Keterangan keputusan:**
- ✅ LANJUT — gate lulus
- ❌ PERBAIKI DULU — ada CRITICAL/HIGH open atau PASS < gate
- ⏸ TUNDA — ada BLOCKED yang butuh eskalasi
- ⚠️ CONDITIONAL — lulus dengan syarat (mis. AI di-flag OFF)

---

## Gate Akhir — Layak Deploy?

- [ ] Sesi 0–6 dijalankan semua
- [ ] 0 BUG-CRITICAL open
- [ ] 0 BUG-HIGH open
- [ ] PASS ≥95% Sesi 1–4, ≥80% Sesi 5
- [ ] Invariants data A–E=0
- [ ] `stock.group_stock_manager` CLOSED (D-002)
- [ ] Verifikasi manual 1 angka per laporan H4.1–H4.7 cocok
- [ ] Backup + restore diuji di staging
- [ ] Smoke test staging (health, docs, login, 1 alur SO→Invoice, 1 pertanyaan AI, 1 print)
- [ ] `ERP_ADAPTER` ≠ null saat UAT
- [ ] `AI_LLM_TEMPERATURE=0` + `AI_AGENT_TOOLS_ENABLED=true` terverifikasi
- [ ] Keputusan AI produksi: ⬜ ON (label beta) / ⬜ OFF

---

## Keputusan Akhir

**Deploy produksi:**
- ⬜ ✅ **DIIZINKAN** — semua gate hijau
- ⬜ ⚠️ **DIIZINKAN DENGAN SYARAT** — sebutkan: ______________________
- ⬜ ❌ **DITOLAK** — alasan: ______________________

**Sisa temuan yang diterima (backlog pasca-deploy):**
- D-XXX: <1 baris>
- D-YYY: <1 baris>

**Rencana pasca-deploy:**
- Smoke test produksi: <tanggal>
- UAT formal 2 klien: <tanggal>
- Backlog fix: <sprint>

---

## Tanda Tangan

| Peran | Nama | TTD | Tanggal |
|---|---|---|---|
| Pemilik proyek | | | |
| UAT Lead | | | |
| Backend Lead | | | |
| Frontend Lead | | | |
| AI Lead | | | |
| Klien A (bila formal) | | | |
| Klien B (bila formal) | | | |