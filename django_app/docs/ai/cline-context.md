# CLINE-CONTEXT.md — Aturan Kerja AI Agent Refactor

## Sumber kebenaran

1. Kode di repo (baca langsung, `wc -l`, `grep`, `git log`).
2. Output probe LLM asli (dengan biaya tercatat).
3. Query DB langsung (ORM/SQL) untuk angka ground truth.
4. Dokumen proyek (`current-project.json`, blueprint, dll) = HIPOTESIS, bukan fakta.
   Kalau dokumen bilang X, verifikasi X dulu. Kalau beda, kode menang.

## Larangan keras

- DILARANG menebak. Kalau tidak bisa dibuktikan, tulis `UNVERIFIED`.
- DILARANG menyalin klaim dokumen tanpa verifikasi (contoh: "builder.py 1.143 baris" — cek `wc -l`).
- DILARANG mengubah kode di luar file yang diizinkan prompt.
- DILARANG menjalankan LLM asli tanpa mencatat biaya (cap per prompt).
- DILARANG "fix" tanpa golden set. Kalau bug ditemukan, catat dulu; perbaikan di fase berikut.

## Label bukti (wajib di setiap temuan)

- `CONFIRMED` — ada bukti file:baris, ID log, atau output probe mentah.
- `REFUTED` — ada bukti yang menyangkal klaim.
- `UNVERIFIED` — tidak bisa dibuktikan dalam batas waktu/biaya prompt.

## Format output laporan

Setiap temuan: `[LABEL] klaim — bukti: <file:baris | ID | probe output> — dampak: <tinggi/sedang/rendah>`.

## Konteks bisnis (jangan dilanggar)

- MES = ERP produksi (single point of input). Odoo = back-office pasif.
- AI read-only. Tidak ada write ke Odoo dari AI. `propose_action` hanya ke HITL queue.
- Angka dihitung kode, bukan LLM.
- RULE_HIT/BLOCKED = 0 token LLM (wajib dipertahankan).
- Stack: Django + DRF, React 18 + TS strict, DeepSeek default LLM (wrapper bisa ganti model), Redis untuk cache/pending_state.

## Prinsip arsitektur target (arahan, bukan fakta)

- LLM memilih tool bertipe via function calling; kode deterministik mengeksekusi.
- Tool sedikit (8-10), generik, read-only, di atas DAL + analytics yang sudah ada.
- Otorisasi di lapisan tool (role + allowlist), bukan di prompt/regex.
- History asli dikirim ke LLM; halaman aktif = 1 baris hint.
- Cache key memuat user_id + role + hash(history) + page_context; fallback/error/low-confidence TIDAK di-cache.
- Loop agent: temperature 0, maks 5 putaran, budget token + timeout.
- Tidak ada fitur baru (Neo4j, vector search, forecaster) sebelum golden set ≥90% & 0 angka salah.

## Aturan test

- Mock LLM membuktikan pipa tersambung, BUKAN jawaban benar.
- Bukti akurasi = golden set dengan LLM asli, dijalankan otomatis.
- Satu fase satu prompt. Setiap fase berakhir dengan gerbang angka. Tidak lanjut sebelum gerbang lolos.
- Jalur lama TIDAK dihapus sampai golden set membuktikan jalur baru lebih baik.

## Saat selesai satu fase

Update `current-project.json`:

- tambah entri `fase_ai_refactor_rN` dengan status, tanggal, ringkasan, test delta, gerbang hasil, link laporan.
- jangan ubah entri lama; tambah field `superseded_by` bila entri lama basi.
