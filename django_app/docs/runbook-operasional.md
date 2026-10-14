# Runbook Operasional (MES Garmen — Produksi)

Panduan tugas rutin + penanganan gangguan untuk instance produksi
(`docker-compose.prod.yml`, project name **`garmen-prod`**).

- Setup awal/klien baru: `django_app/docs/onboarding-klien-baru.md`.
- UAT: `django_app/docs/uat-checklist.md`.
- Yang **memang** belum ada (jangan dikejar sebagai bug): `django_app/docs/known-limitations.md`.
- Audit kesiapan ops (basis runbook ini): `django_app/docs/ops-readiness-audit.md`.

> Semua contoh memakai `docker compose -f docker-compose.prod.yml ...` dari direktori
> project di VPS. Ganti `<domain>` dengan domain klien.

---

## 1. Ringkasan service & port

| Service | Container | Port | Fungsi |
|---|---|---|---|
| `nginx` | `garmen_prod_nginx` | **80, 443** (satu-satunya publik) | reverse proxy API + WS + SPA + static/media + TLS |
| `django` | `garmen_prod_django` | internal 8000 (daphne/ASGI) | REST API `/api/v1/...`, WebSocket `/ws/...`, health `/api/health/` |
| `celery_worker` | `garmen_prod_celery_worker` | — | queue `default,erp_sync` (sync Odoo, rekonsiliasi) |
| `celery_beat` | `garmen_prod_celery_beat` | — | 14 jadwal (`config/settings.py`, TZ Asia/Jakarta) |
| `postgres` | `garmen_prod_postgres` | internal 5432 | DB utama (volume `postgres_prod_data`) |
| `redis` | `garmen_prod_redis` | internal 6379 | cache + broker Celery + channel layer WS |
| `certbot` | `garmen_prod_certbot` | — | renew Let's Encrypt tiap 12 jam |
| `backup` | `garmen_prod_backup` | — | loop harian `scripts/backup.sh` → `./backups` |
| `frontend_builder` | `garmen_prod_frontend_builder` | — | one-shot `bun run build` → volume `frontend_dist` (exit 0 = normal) |

Log aplikasi (JSONL) ada di volume `logs_prod` → `/app/logs/mes.jsonl` (dipakai Trace Bridge).

---

## 2. Cek harian (± 5 menit)

| # | Cek | Perintah | Normal | Aksi bila tidak |
|---|---|---|---|---|
| 2.1 | Health API | `curl -fsS https://<domain>/api/health/` | 200 | §5 baris "502 / health gagal" |
| 2.2 | Error terbaru | `docker compose -f docker-compose.prod.yml logs --since=24h django celery_worker \| grep -i "ERROR" \| tail -50` | kosong/terbatas | catat + cek `logs/mes.jsonl` |
| 2.3 | Status service | `docker compose -f docker-compose.prod.yml ps` | semua `Up` | `... restart <service>` |
| 2.4 | Sync gagal | UI `/settings/sync` atau `curl -s "https://<domain>/api/v1/sync/records/?stage=&status=FAILED"` | 0 baris FAILED | §5 baris "Odoo sync gagal" |
| 2.5 | Antrean invoice | UI `/finance/invoices` | tidak menumpuk `PENDING` | cek `celery_worker` |
| 2.6 | Backup terbaru | `ls -lh ./backups/postgres \| tail -3` | ada file hari ini | §5 baris "backup tidak jalan" |

---

## 3. Cek mingguan (± 15 menit)

| # | Cek | Perintah | Ambang/aksi |
|---|---|---|---|
| 3.1 | Disk | `df -h` | pakai < 80%; > 80% → bersihkan backup lama / naikkan volume |
| 3.2 | Memori & CPU container | `docker stats --no-stream` | postgres/django < 80%; kalau terus tinggi → cek §6 trace query lambat |
| 3.3 | Redis | `docker compose -f docker-compose.prod.yml exec redis redis-cli info \| grep -E "used_memory\|connected_clients"` | `used_memory_human` stabil (puluhan MB); lonjakan = antrean Celery menumpuk |
| 3.4 | Celery queue | `docker compose -f docker-compose.prod.yml logs --since=168h celery_worker \| grep -i "retry\|failed" \| tail -30` | tidak ada retry berulang |
| 3.5 | Pertumbuhan DB | `docker compose -f docker-compose.prod.yml exec postgres psql -U <DB_USER> -d <DB_NAME> -c "select pg_size_pretty(pg_database_size(current_database()));"` | catat tren; lonjakan tak wajar → cek audit/event log |
| 3.6 | Rotasi log | `ls -lh ./logs` / volume `logs_prod` (`.jsonl.1`, `.2`, …) | rotasi berjalan (`max_backups` di settings) |
| 3.7 | Sertifikat | `docker compose -f docker-compose.prod.yml exec certbot certbot certificates` | sisa > 30 hari |
| 3.8 | Audit produk | UI `/settings/audit` | kosong (semua produk punya `odoo_id`) |

---

## 4. Cek bulanan

| # | Kegiatan | Perintah | Catatan |
|---|---|---|---|
| 4.1 | **Drill restore** (wajib) | `./scripts/restore.sh --list` lalu di staging: `./scripts/restore.sh --yes ./backups/postgres/<file>.dump` | script tanpa `--yes` = dry-run; **jangan** ke DB produksi |
| 4.2 | Update OS | `sudo apt update && sudo apt upgrade -y` | butuh reboot → §9 jendela maintenance |
| 4.3 | Update image base | `docker compose -f docker-compose.prod.yml pull && ... build --pull && ... up -d` | uji di staging dulu |
| 4.4 | Rotasi kredensial | ganti `ODOO_API_KEY` + `DJANGO_SECRET_KEY` (hati-hati: SECRET_KEY baru = sesi login lama invalid) | catat ke password manager |
| 4.5 | Review kapasitas | `df -h`, `free -h`, `docker system df` | bersihkan image/volume tak terpakai: `docker system prune` (hati-hati volume) |
| 4.6 | Review alert | cek dashboard Sentry + `RECONCILIATION_ALERT_WA_TO` | nonaktifkan kalau spam |

---

## 5. Troubleshooting cepat

| Gejala | Langkah cek | Fix |
|---|---|---|
| **502 Bad Gateway** | `docker compose -f docker-compose.prod.yml ps` → `django` running? Cek dari dalam: `... exec django curl -fsS http://localhost:8000/api/health/` | `... restart django` (lalu `... logs --tail=100 django`) |
| **Health 200 tapi UI putih/kosong** | `... logs frontend_builder` (harus exit 0) | `... up -d --force-recreate frontend_builder nginx` |
| **WS tidak connect** (chatter tidak realtime) | `... exec nginx nginx -t`; devtools → WS `wss://<domain>/ws/events/` | `... exec nginx nginx -s reload`; pastikan `VITE_WS_ENABLED=true` **saat build**, lalu rebuild frontend |
| **DB lambat / timeout** | `docker stats --no-stream` (CPU postgres), `... logs django \| grep -iE "slow\|timeout"` | cari trace panjang di `logs/mes.jsonl` (§6); naikkan `DB_CONN_MAX_AGE`/resource; tambah index |
| **SSL expired** | `... exec certbot certbot certificates` | `... exec certbot certbot renew --force-renewal` lalu `... exec nginx nginx -s reload` |
| **Celery stuck / task menumpuk** | `... logs --tail=100 celery_worker`; `... exec redis redis-cli llen celery` | `... restart celery_worker`; kalau berulang → cek kredensial Odoo |
| **Beat tidak menjalankan jadwal** | `... logs --tail=50 celery_beat` | `... restart celery_beat`; pastikan hanya **satu** beat (jangan dobel) |
| **Odoo sync gagal** | `/settings/sync` filter `FAILED`, atau `curl -s "https://<domain>/api/v1/sync/records/?stage=&status=FAILED"` | cek `last_error`; verifikasi `ODOO_*` + `ODOO_LOCATION_*_ID`; trigger ulang dari UI |
| **Scrap/WIP ditolak "Location … belum dikonfigurasi"** | `grep ODOO .env.prod` | isi `ODOO_LOCATION_WIP_ID/PRODUCTION_ID/FG_ID/SCRAP_ID` + `ODOO_UOM_ID`, lalu `... up -d --force-recreate django celery_worker celery_beat` |
| **Backup tidak jalan** | `... logs --tail=50 backup`; `ls -lh ./backups` | pastikan `./backups` writable + `BACKUP_INTERVAL_SECONDS` wajar; jalankan manual `./scripts/backup.sh` |
| **Disk penuh** | `df -h`, `du -sh ./backups/*`, `docker system df` | turunkan `RETENTION_DAYS`, hapus backup lama, `docker system prune -f` (hindari `--volumes` kecuali yakin) |
| **Sertifikat belum ada saat deploy pertama** | `ls certbot/conf/live/<domain>` | `DOMAIN=<domain> LETSENCRYPT_EMAIL=<email> ./scripts/generate-ssl.sh` (bootstrap: `--self-signed-only`) |
| **Login berhasil lalu ter-logout sendiri** | `DJANGO_SECURE_PROXY_SSL_HEADER=True`? `SECURE_SSL_REDIRECT=True`? | perbaiki `.env.prod` → `... up -d --force-recreate django` |

---

## 6. Trace satu request (tanpa OTel)

Berguna saat "kenapa request ini lambat / task-nya jalan tidak?".

```bash
# 1) kirim request dengan id sendiri (klien browser juga mengirim X-Request-ID otomatis)
curl -s -H "X-Request-ID: uat-001" https://<domain>/api/v1/health/ > /dev/null

# 2) baca jejaknya (dijalankan dari direktori django_app)
cd django_app && python -m trace_bridge.api        # http://127.0.0.1:8765
curl -s http://127.0.0.1:8765/_ai/trace/uat-001 | python -m json.tool
```

Output: `{trace_id, duration_ms, spans[{name, ms, error?}], errors}`. Detail +
troubleshooting (log kosong, `request_id = "-"`, gap aksi bundle) ada di `django_app/docs/trace-bridge.md`.

---

## 7. Monitoring & alert

| Sumber | Isi | Cara lihat |
|---|---|---|
| Health endpoint | `{"status": "ok"}` | `curl https://<domain>/api/health/` (juga dipakai healthcheck container `django`) |
| Log JSONL | 1 baris = 1 JSON per request/task | volume `logs_prod` → `/app/logs/mes.jsonl` (§6) |
| `SyncRecord` | status sinkronisasi ERP (`stage`, `status`, `attempts`, `last_error`) | `/settings/sync` |
| Rekonsiliasi stok | selisih MES vs Odoo di luar toleransi | `/reports/reconciliation` + alert WA (`RECONCILIATION_ALERT_WA_TO`) |
| Bottleneck | WC dengan `queue_depth > 10` atau avg wait > 60 menit (default `BottleneckDetector`) | `alerts[]` di `/dashboard` dan `/production/buffer-queue` |
| Sentry (opsional) | exception + performance | isi `SENTRY_DSN` di `.env.prod` (kosong = nonaktif) |
| Log per service | stdout container | `docker compose -f docker-compose.prod.yml logs -f <service>` |

Ambang alert yang disarankan untuk klien: health ≠ 200 (1 menit) · ada `SyncRecord` FAILED
(15 menit) · disk > 80% (harian) · backup harian tidak terbentuk (harian).

---

## 8. Kontak darurat & eskalasi

| Peran | Nama | WA | Email | Jam kerja |
|---|---|---|---|---|
| Dev PIC (MES) | _________________ | ______________ | ______________ | ______________ |
| Ops PIC (VPS) | _________________ | ______________ | ______________ | ______________ |
| Klien PIC | _________________ | ______________ | ______________ | ______________ |
| Odoo admin (klien) | _________________ | ______________ | ______________ | ______________ |

Urutan eskalasi:
1. **Ops PIC** — gangguan infra (VPS/disk/SSL/container).
2. **Dev PIC** — bug aplikasi, data tidak sesuai, sync gagal berulang.
3. **Klien PIC** — keputusan bisnis (data master, hak akses, jadwal UAT).
4. **Odoo admin klien** — masalah di sisi Odoo (kredensial, kuota, user API).

Kontak ini juga dipakai pada §8 `django_app/docs/uat-checklist.md` (sign-off) dan §7
`django_app/docs/onboarding-klien-baru.md` (go-live).

---

## 9. Jendela maintenance (deploy update)

```bash
cd /opt/garmen                                  # direktori project di VPS

./scripts/backup.sh                             # 0) simpan kondisi terakhir
git pull                                        # 1) kode baru (atau rsync artefak rilis)
docker compose -f docker-compose.prod.yml build # 2) bangun ulang
docker compose -f docker-compose.prod.yml up -d # 3) naikkan (migrasi otomatis di service django)

curl -fsS https://<domain>/api/health/          # 4) verifikasi
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs --tail=100 django
```

Rollback bila verifikasi gagal:
1. `git checkout <tag-sebelumnya>` → `docker compose -f docker-compose.prod.yml build && ... up -d`;
2. bila migrasi bermasalah → restore dump terakhir (`./scripts/restore.sh --list`, lalu
   `./scripts/restore.sh --yes <dump>`) — **hanya** setelah konfirmasi tertulis dari klien.

Jendela disarankan di luar jam produksi (klien garmen umumnya 2 shift → pilih 21:00–23:00 WIB)
dan diumumkan minimal 1 hari sebelumnya. Ingat: setelah `VITE_*` berubah, frontend **harus**
di-rebuild (`frontend_builder`), bukan sekadar restart.
