# Ops Readiness Audit — MES Garmen (v4.3 backend + v3 frontend)

> **F3B.1 — READ-ONLY audit.** Tidak ada perubahan kode/docker/config dalam tugas ini.
> Sumber bukti: `docker-compose.yml`, `django_app/Dockerfile`, `django_app/config/settings.py`,
> `django_app/requirements.txt`, `django_app/.env.example`, `django_app/config/urls.py`,
> `.gitignore`, `django_app/.dockerignore`, `frontend_app_v2/dist/`, `frontend_app_v2/.env(.example)`.
> Tanggal audit: 2026-10-09. Status acuan: **backend v4.3 + frontend v3 (F2C.2 hijau)**.

---

## 1. Ringkasan

- **Total item diperiksa: 55** (A Docker 14, B Settings 13, C Nginx 7, D Frontend 6, E Backup/Monitoring 8, F Secret 7).
- **Sudah siap: 25** ✅ (dev-ready; sebagian besar sudah prod-safe).
- **Sebagian / ⚠️: 6** (jalan tapi belum aman/konsisten untuk prod).
- **Belum: 24** ❌ (⚠️ 6 dicatat terpisah).
- **Blocking (harus selesai sebelum deploy): 10.**
- Kesimpulan singkat: **backend settings sudah matang** (DEBUG fail-safe, whitenoise, logging JSON,
  `CONN_MAX_AGE`, Redis cache) tetapi **lapisan deploy belum ada sama sekali** — tidak ada
  `docker-compose.prod.yml`, tidak ada Nginx/SSL, tidak ada backup, tidak ada monitoring.
- Compose yang ada **100% dev**: `runserver`, port DB/Odoo terbuka ke host, kredensial `odoo/odoo` hardcode.
- `django_app/.dockerignore` sudah benar (`.env` tidak masuk image), tetapi **root `.gitignore` TIDAK
  mengabaikan `.env`** → risiko commit kredensial (repo belum di-`git init`, lihat F4).

---

## 2. Tabel Per Kategori

### A. Docker & Compose

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| `docker-compose.yml` root ada (db, odoo, django, celery_worker, celery_beat, redis) | ✅ | `docker-compose.yml:12-128` | — (dipakai sebagai basis prod) |
| `docker-compose.prod.yml` ada | ❌ | tidak ditemukan (`find *compose*` → hanya root) | **BUAT di F3-B.2** |
| Dockerfile multi-stage, base `python:3.11-slim` | ✅ | `Dockerfile:13,39` | — |
| Non-root user (`appuser`, UID/GID 1000) | ✅ | `Dockerfile:55-69` | — |
| `CMD` image = `gunicorn config.wsgi` (WSGI) | ⚠️ | `Dockerfile:75` | WS `/ws/` butuh **ASGI** → tambah service `daphne`/`uvicorn config.asgi` di prod |
| Compose dev menimpa command jadi `runserver` | ❌ | `docker-compose.yml:62` | prod: hapus override, pakai gunicorn/daphne |
| Volume Postgres/odoo/media/static/logs | ⚠️ | `docker-compose.yml:21-22,41-45,63-65` | hanya **bind mount** (`./postgres_data`, `./django_app`); belum ada named volume khusus `media/`+`staticfiles/`+`logs/` |
| Named volume Redis | ✅ | `docker-compose.yml:125-126,134-135` | — |
| Network service-name (django→db/redis/odoo) | ✅ | `docker-compose.yml:130-132` (`garmen_net`) | — |
| Healthcheck Django (`/api/health/`) | ✅ | `docker-compose.yml:73-78` | — |
| Healthcheck db/redis | ❌ | tidak ada di compose | tambah `pg_isready` / `redis-cli ping` + `depends_on.condition: service_healthy` |
| Port DB/Odoo/Django expose ke host | ❌ | `:24,36,67,123` (5432/8069/8000/6380) | prod: jangan publish; cukup Nginx 80/443 |
| Kredensial db/odoo hardcode `odoo/odoo` | ❌ | `docker-compose.yml:18-19,38-40,48-49` | prod: `env_file`/secret, password kuat |
| Service ASGI/WebSocket (daphne/uvicorn) | ❌ | tidak ada | tambah di prod compose |

### B. Django Production Settings

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| `DEBUG` dari env, **default `False`** (fail-safe) | ✅ | `settings.py:106` | prod: pastikan `DJANGO_DEBUG=False` |
| `ALLOWED_HOSTS` dari env | ✅ | `settings.py:107` (default `localhost,127.0.0.1`) | prod: isi domain nyata |
| `SECRET_KEY` dari env | ⚠️ | `settings.py:105` | **fallback `django-insecure-dev-only-change-me`** → prod wajib diisi / fail-fast |
| `CSRF_TRUSTED_ORIGINS` dari env (default `""`) | ✅ | `settings.py:284` | prod: isi `https://<domain>` |
| `CORS_ALLOWED_ORIGINS` dari env (default `""`) | ✅ | `settings.py:268` | prod single-domain: boleh kosong / domain frontend |
| `CORS_ALLOW_CREDENTIALS` default `False` | ✅ | `settings.py:281` | prod: biarkan default (satu domain) |
| `SECURE_*` (HSTS, `SECURE_SSL_REDIRECT`, cookie secure, `SECURE_PROXY_SSL_HEADER`) | ❌ | **tidak ada** (`grep -e SECURE_` → nihil) | **tambah blok security prod** |
| `STATIC_ROOT` + manifest storage | ✅ | `settings.py:247-266` | prod: jalankan `collectstatic` saat deploy |
| whitenoise serve static | ✅ | `requirements.txt:11`, `settings.py:258` | — |
| `MEDIA_ROOT` (`BASE_DIR/media`) | ✅ | `settings.py:250` | pastikan volume persisten di prod (F: `media/` belum ada di disk) |
| Logging JSON + rotating `logs/mes.jsonl` (10MB×5) | ✅ | `settings.py:504-547`; `django_app/logs/mes.jsonl` ada | prod: pastikan `logs/` volume + rotation host |
| `DB_CONN_MAX_AGE` = 60 (pooling, bukan 0) | ✅ | `settings.py:223-224` (+`CONN_HEALTH_CHECKS`) | — |
| Cache throttle pakai Redis (bukan LocMem) | ✅ | `settings.py:585-591` | — |

### C. Nginx & Reverse Proxy

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| Config Nginx di repo | ❌ | `find -iname *nginx*` → nihil | **BUAT** `deploy/nginx/` (F3-B.3) |
| Route `/api/*` → `django:8000` | ❌ | belum ada | `proxy_pass` + header `X-Forwarded-For/Proto` |
| Route `/ws/*` → `daphne:8000` (Upgrade) | ❌ | belum ada | `proxy_http_version 1.1` + `Upgrade`/`Connection` |
| Static/media via Nginx (volume) | ❌ | belum ada | alias ke volume `staticfiles/` & `media/` |
| Frontend (`dist/`) di-serve | ❌ | belum ada | Nginx root ke volume dist / `try_files ... /index.html` |
| SSL (Let's Encrypt/Certbot/Cloudflare) | ❌ | belum disiapkan | Certbot + auto-renew; atau Cloudflare Tunnel |
| `SECURE_PROXY_SSL_HEADER` untuk TLS terminasi | ❌ | tidak ada di settings | tambah saat Nginx SSL (bagian B) |

### D. Frontend Build

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| `dist/` pernah di-build | ✅ | `frontend_app_v2/dist/index.html` (assets `index-DFYubiBh.js`, `index-B3hJ6PoT.css`) | build ulang saat deploy |
| Script build tersedia | ✅ | `package.json` → `build: bun x --bun vite build` | jalankan di CI/deploy |
| Serving dist (Nginx/container) | ❌ | tidak ada config | lihat C — Nginx `root`/volume |
| Env prod `VITE_API_BASE_URL` | ❌ | hanya `.env` dev (`http://localhost:8000/api/v1`) | **BUAT `.env.production`** (`https://<domain>/api/v1`) |
| Env prod `VITE_WS_URL` | ❌ | `.env` dev `ws://localhost:8000/ws` | prod: `wss://<domain>/ws` |
| `VITE_WS_ENABLED` | ✅ | `.env:4` = `true` | — |

### E. Backup & Monitoring

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| Script `pg_dump` + cron | ❌ | tidak ada (`grep -rln pg_dump` → nihil; tanpa `scripts/` di root) | **BUAT** `backup/pg_dump.sh` + crontab/systemd timer |
| Backup volume media | ❌ | tidak ada | `rsync`/`tar` terjadwal + retensi |
| Sentry (dependency) | ❌ | tidak ada di `requirements.txt` | tambah `sentry-sdk[django]` + `SENTRY_DSN` |
| Prometheus/Grafana | ❌ | tidak ada | opsional: `django-prometheus` + exporter |
| Health endpoint `/api/health/` | ✅ | `config/urls.py:75` (+ dipakai healthcheck compose) | sambungkan ke uptime monitor |
| Log terpusat (file JSONL berotasi) | ✅ | `logs/mes.jsonl` + `settings.py:528-540` | kirim ke Loki/ELK bila perlu |
| Restore drill (uji restore backup) | ❌ | belum pernah | jadwalkan uji restore sebelum go-live |
| Celery beat schedule terdefinisi | ⚠️ | service `celery_beat` ada; jadwal di `config/celery.py` | pastikan task housekeeping (purge log/retensi) terjadwal |

### F. Secret Management

| Item | Status | File/Bukti | Aksi |
|---|---|---|---|
| `.env.example` ada & lengkap | ✅ | `django_app/.env.example:1-48` | jadikan checklist prod |
| Placeholder rahasia (bukan nilai nyata) | ⚠️ | `DJANGO_SECRET_KEY=change-me-in-production`, `ODOO_API_KEY=change-me`, `DB_PASSWORD=odoo` | ganti di prod + rotate |
| `.env` tidak masuk **image** | ✅ | `django_app/.dockerignore:7` (`.env`) | — |
| `.env` tidak masuk **git** | ⚠️ | root `.gitignore` hanya `simulator/*` (baris 1-5); **tidak ada `.env`** | tambah `.env` + `*.env` ke `.gitignore` |
| `django_app/.gitignore` | ❌ | file tidak ada | boleh digabung ke root `.gitignore` |
| Repo ter-`git init` | ❌ | `git rev-parse` → *not a git repository*; hanya ada `.gitignore` | init sebelum F3-B.2 agar ignore berlaku |
| Default aman utk prod satu-domain (CORS creds false, CSRF kosong) | ✅ | `settings.py:281,284` | — |

---

## 3. Blocker (harus diselesaikan sebelum deploy)

1. **`docker-compose.prod.yml` belum ada** — masih memakai compose dev (`runserver`, bind mount, port terbuka).
2. **Nginx / reverse proxy belum ada** — tidak ada routing `/api`, `/ws`, static, maupun `dist/` frontend.
3. **SSL/TLS belum disiapkan** — tidak ada Certbot/Cloudflare; WebSocket pun butuh `wss://`.
4. **`SECURE_*` settings kosong** — tanpa HSTS, `SECURE_SSL_REDIRECT`, secure cookie, `SECURE_PROXY_SSL_HEADER` (TLS terminasi).
5. **Runtime prod belum benar** — command `runserver` (dev) & `CMD` gunicorn **WSGI**; WebSocket butuh service **ASGI (daphne/uvicorn)**.
6. **Eksposur jaringan & kredensial** — port 5432/8069/8000/6380 dipublish ke host + kredensial `odoo/odoo` hardcode di compose.
7. **Backup belum ada** — tidak ada `pg_dump` terjadwal, tidak ada backup media, tidak ada uji restore.
8. **Monitoring belum ada** — tanpa Sentry/Prometheus; `/api/health/` belum tersambung ke uptime monitor.
9. **Frontend prod belum siap** — `dist/` ada tetapi belum di-serve dan `.env.production` (`VITE_API_BASE_URL`/`VITE_WS_URL`) belum dibuat.
10. **Manajemen secret** — `SECRET_KEY` punya fallback insecure, root `.gitignore` tidak mengabaikan `.env`, repo belum di-`git init`.

---

## 4. Rekomendasi Urutan Kerja

1. **F3-B.2 — `docker-compose.prod.yml`** (blocker #1, #5, #6): service `django` (gunicorn) + `daphne` (ASGI/WS) + `nginx` + `celery_worker`/`celery_beat`/`redis`/`db`; **tanpa** publish port DB/Odoo (hanya Nginx 80/443); named volume `media/`, `staticfiles/`, `logs/`, `postgres_data`; `env_file: .env.prod`; healthcheck `pg_isready`/`redis-cli ping` + `depends_on.service_healthy`; jalankan `migrate` + `collectstatic` saat start.
2. **Hardening `settings.py`** (blocker #4, #10): tambah blok `SECURE_*` (HSTS, SSL redirect, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`), `SECRET_KEY` **fail-fast** bila kosong saat `DEBUG=False`.
3. **Nginx + SSL** (blocker #2, #3, #9): `deploy/nginx/mes.conf` (`/api`→django, `/ws`→daphne w/ Upgrade, static/media alias, `dist` SPA fallback) + Certbot auto-renew; set `ALLOWED_HOSTS`/`CSRF_TRUSTED_ORIGINS` ke domain.
4. **Frontend prod** (blocker #9): buat `frontend_app_v2/.env.production`, build di pipeline, salin `dist/` ke volume Nginx.
5. **Backup** (blocker #7): `backup/pg_dump.sh` + retensi 7/30 hari, backup media incremental, jadwalkan, lalu **uji restore** ke DB staging.
6. **Monitoring** (blocker #8): `sentry-sdk[django]` + `SENTRY_DSN`, uptime check `/api/health/`, alert disk/DB; (opsional) `django-prometheus` + Grafana.
7. **Secret & repo hygiene** (blocker #10): `git init` + `.gitignore` (`.env`, `*.env`, `logs/`, `media/`, `postgres_data/`), putar ulang kredensial dev, isi `.env.prod` di secret store (bukan di repo).

---

## 5. Estimasi F3-B.2

- Penulisan `docker-compose.prod.yml` + entrypoint (`migrate`/`collectstatic`) + named volume/healthcheck: **± 4–6 jam**.
- Termasuk smoke test `docker compose -f docker-compose.prod.yml up` (DB up → migrate → health 200): **≈ 0,5–1 hari kerja**.
- Bila digabung Nginx + SSL (langkah 3 pada rekomendasi): total jalur deploy ≈ **1,5–2 hari**.

> **Catatan cakupan:** audit ini READ-ONLY. Tidak ada file kode/config/docker yang diubah; satu-satunya
> artefak baru adalah dokumen ini (`django_app/docs/ops-readiness-audit.md`).
