# Dokumentasi Backend — Index

Peta seluruh dokumentasi di **`django_app/docs/`** (backend MES Garmen).
Kalau bingung mau mulai dari mana, lompat ke **“Mulai dari mana?”** di bawah.

> ⚠️ **KONSEP BARU (2026-10-10)**: MES = ERP Produksi (**single point of input**);
> Odoo = back-office pasif (akuntansi/pajak/e-Faktur). Sync master dua arah, transaksi
> satu arah (MES → Odoo). Rujukan mengikat: [`../../docs/REPLACE-NOTICE.md`](../../docs/REPLACE-NOTICE.md).
> Bagian dokumen di folder ini yang masih menyebut "Odoo untuk input" sudah **usang**.

> Terakhir disusun ulang: **F5.3 — 2026-10-10**. Indeks ini wajib ikut diperbarui
> setiap kali ada dokumen baru/berganti nama (lihat bagian “Konvensi & perawatan”).

---

## Overview

| Dokumen | Isi |
|---|---|
| [`blueprint.md`](blueprint.md) | **Arsitektur + 23 endpoint + inventaris 47 model + struktur folder + stack** (revisi F5.3) |
| [`known-limitations.md`](known-limitations.md) | Keterbatasan yang diketahui (Backend 8 · Frontend 6 · Ops 7 · Test 7) + status `by design`/backlog |

## Status

| Dokumen | Isi |
|---|---|
| [`README-index.md`](README-index.md) | **Halaman ini** — indeks dokumentasi backend (peta + “mulai dari mana?”) |
| [`curent_project.json`](curent_project.json) | **Status JSON mesin** (ejaan file apa adanya: “curent”) — fase, jumlah test, baseline failure, ringkasan endpoint per fase. Sumber angka untuk dokumen lain |
| [`recon-f1-result.md`](recon-f1-result.md) | Hasil recon F1 awal (temuan kontrak, daftar celah, keputusan) |

## Deployment & Ops

| Dokumen | Isi |
|---|---|
| [`ops-readiness-audit.md`](ops-readiness-audit.md) | Audit kesiapan pra-deploy (blocker + status) |
| [`runbook-operasional.md`](runbook-operasional.md) | Operasional harian/mingguan/bulanan, troubleshooting, **§9 langkah deploy & maintenance window**, kontak eskalasi |
| [`onboarding-klien-baru.md`](onboarding-klien-baru.md) | Template onboarding klien baru (7 tahap, termasuk **§4 deploy** + `generate-ssl` + `createsuperuser`) |

> Catatan: tidak ada `deploy-runbook.md` terpisah — langkah deploy ada di
> `onboarding-klien-baru.md` §4 dan `runbook-operasional.md` §9.

## UAT & Onboarding

| Dokumen | Isi |
|---|---|
| [`uat-checklist.md`](uat-checklist.md) | Checklist UAT Klien A: pre-flight, 5 role walkthrough, cross-cutting, issue log, sign-off |
| [`onboarding-klien-baru.md`](onboarding-klien-baru.md) | Onboarding klien B/C/D (reusable) + lampiran ringkasan 1 halaman |

## Integrasi ERP

| Dokumen | Isi |
|---|---|
| [`integration-config.md`](integration-config.md) | Konfigurasi Odoo **per klien**: `.env`, lokasi, user API, UoM, 9 sync master, 14 beat, ringkasan 23 endpoint, frontend v3, UAT/onboarding, env produksi |
| [`integrations/CONTRACT.md`](integrations/CONTRACT.md) | Kontrak field & TX yang dikunci (**WIP / FG / SCRAP / INVOICE**) |
| [`integrations/api-signature.md`](integrations/api-signature.md) | Signature API integrasi (payload/response yang disepakati) |
| [`integrations/framework_jsonrpc_validation.md`](integrations/framework_jsonrpc_validation.md) | Alur validasi: probe → kontrak → test → adapter |

## Trace & Debugging

| Dokumen | Isi |
|---|---|
| [`trace-bridge.md`](trace-bridge.md) | Trace Bridge: menggabungkan log 1 request (HTTP → Celery → log JSONL), cara jalankan `python -m trace_bridge.api` |
| [`trace_bridge_recon.md`](trace_bridge_recon.md) | Recon awal Trace Bridge (temuan & batasan) |
| [`trace_bridge_verify.md`](trace_bridge_verify.md) | Verifikasi Trace Bridge (bukti end-to-end) |

## Performance

| Dokumen | Isi |
|---|---|
| [`perf-benchmark.md`](perf-benchmark.md) | Benchmark pre-pilot: 5 endpoint agregat di N=100/1.000/10.000, temuan N+1, optimasi yang diterapkan, rekomendasi F6 |

---

## Mulai dari mana?

| Peran / kebutuhan | Baca berurutan |
|---|---|
| **Developer baru** | `blueprint.md` (§1 mental model, §7 struktur, §7b endpoint) → `curent_project.json` → `runbook-operasional.md` |
| **Ops / SRE** | `ops-readiness-audit.md` → `onboarding-klien-baru.md` (§3–§4) → `runbook-operasional.md` |
| **Onboarding klien baru** | `onboarding-klien-baru.md` → `integration-config.md` (§1–§4) → `uat-checklist.md` |
| **UAT hari-H** | `uat-checklist.md` (+ §5–§6 `integration-config.md` untuk alur ERP) |
| **Debug integrasi ERP** | `integration-config.md` §6 + §10 → `integrations/CONTRACT.md` → `trace-bridge.md` |
| **Curiga lambat / N+1** | `perf-benchmark.md` → jalankan `tests/integration/test_perf_queries.py` |
| **“Kenapa fitur X belum ada?”** | `known-limitations.md` (+ `curent_project.json` untuk rencana fase) |

---

## Konvensi & perawatan

- **Bahasa**: Bahasa Indonesia; istilah teknis (endpoint, field) dibiarkan apa adanya.
- **Field/response**: `snake_case` sesuai backend — jangan “diterjemahkan” ke camelCase
  di dokumen, supaya bisa dicari apa adanya.
- **Nomor baris/fase**: fase memakai kode task (`F1`, `F2C.2`, `F3-A`, `F5.2`, …) yang sama
  dengan `curent_project.json`; angka di dokumen harus bisa ditelusuri ke JSON/kode.
- **Placeholder**: tidak boleh ada; setiap angka wajib hasil pengukuran/perintah yang
  ditulis di dokumen (mis. perintah hitung model/endpoint).
- Menambah dokumen baru? (1) taruh di `django_app/docs/`, (2) daftarkan di tabel yang sesuai
  di halaman ini, (3) cantumkan di “Mulai dari mana?” bila relevan untuk peran tertentu.

---

## Dokumen di luar folder ini (tetap terkait)

| Lokasi | Isi |
|---|---|
| `../frontend_app_v2/docs/current-project.json` | Status & statistik frontend (MODE real/dummy, gate, riwayat flip) |
| `../frontend_app_v2/docs/contract-gap-f1f2.md` | Kontrak UI ↔ backend per resource (hasil gap F1/F2) |
| `../frontend_app_v2/docs/blueprint.md`, `api-contract.md` | Cetak biru & kontrak frontend v3 |
| `../../.env.prod.example` (root repo) | Template env produksi (semua placeholder wajib diganti) |
| `../../docker-compose.prod.yml` | Compose produksi (9 service: postgres, redis, django, celery_worker, celery_beat, frontend_builder, nginx, certbot, backup) |
| `../../scripts/{generate-ssl,backup,restore}.sh` | Skrip operasional TLS/backup/restore |
| `../../nginx/conf.d/mes.conf` | Konfigurasi Nginx (server_name harus = `DOMAIN`) |
