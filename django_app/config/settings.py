"""
Django settings untuk project `garmen` (integrasi Django <-> Odoo 17).

Struktur project (Modular Monolith):
  * `config/`               — settings, urls, wsgi/asgi, celery
  * `core/`                 — library generik (state machine, cycle handler,
                              device profile, event bus)
  * `apps_industry/`        — Django app domain industri:
                              apps_industry.garment
  * `integrations/`         — adaptor pihak ketiga (ERP multi-vendor):
                              integrations.erp_sync (+ adapters:
                              odoo, accurate, sap, ...)
  * `master/`               — master data dari Odoo
  * `scripts/`              — script utilitas manual
  * `manage.py`

SEMUA konfigurasi sensitif dibaca dari environment variable
(lihat `django_app/.env.example`). Tidak ada kredensial hardcode di file ini.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from celery.schedules import crontab
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Folder `apps_industry/` = rumah semua Django app domain industri.
APPS_DIR = BASE_DIR / "apps_industry"

# Pastikan root project selalu bisa di-import walau proses dijalankan dari
# working directory lain (mis. gunicorn/celery dijalankan dari `/`).
# Dengan ini `config.*`, `apps_industry.*`, `integrations.*`, `master.*`
# (dotted path di INSTALLED_APPS) dikenali.
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Saat dijalankan di luar Docker (venv lokal) file .env di-load manual.
# Di Docker variabel sudah di-inject lewat `env_file:` dan `load_dotenv`
# tidak menimpa variabel yang sudah ada (override=False).
load_dotenv(BASE_DIR / ".env")


# ---------------------------------------------------------------------------
# Helper pembaca environment
# ---------------------------------------------------------------------------
def env(name: str, default: str = "") -> str:
    """Ambil nilai string dari environment; string kosong dianggap tidak diisi."""
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value


def env_bool(name: str, default: bool = False) -> bool:
    """Ambil nilai boolean dari environment ("1"/"true"/"yes"/"on")."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """Ambil nilai list yang dipisah koma dari environment."""
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def env_int(name: str, default: int) -> int:
    """Ambil nilai integer dari environment."""
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_int_or_none(name: str) -> int | None:
    """Ambil integer opsional dari environment.

    Dipakai untuk konfigurasi yang **belum tentu ada** (mis. id lokasi Odoo):
    kosong atau bukan angka -> ``None`` supaya kode pemanggil bisa membedakan
    "belum dikonfigurasi" dari nilai 0.
    """
    value = env(name, "")
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def env_float(name: str, default: float) -> float:
    """Ambil nilai float dari environment."""
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
# ASGI server + Channels (Fase E). `daphne` HARUS lebih dulu dari
# `django.contrib.staticfiles` supaya perintah `manage.py runserver` memakai
# implementasi ASGI milik Daphne — tanpa itu WebSocket tidak hidup di
# dev/docker (yang menjalankan `runserver`, bukan `daphne` langsung).
ASGI_APPS = [
    "daphne",
    "channels",
]

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "drf_spectacular",  # OpenAPI/Swagger (Fase 6)
]

LOCAL_APPS = [
    "apps_industry.garment",   # domain garmen
    "integrations.erp_sync",  # adapter Odoo + Celery task
    "integrations.printing",  # printer thermal ESC/POS: bundle tag + kupon — label: printing
    "integrations.wa_bot",    # WhatsApp gateway (stub, mock-first) — label: wa_bot
    "master",                  # master data dari Odoo
    # Core engine generik (Fase 0: registrasi app saja, belum ada logika
    # bisnis). Dipisah per sub-folder supaya modul core bisa tumbuh tanpa
    # menambah entri INSTALLED_APPS lagi di fase berikutnya.
    #
    # NB: app `core.auth` memakai `label = "core_auth"` (didefinisikan di
    # `core/auth/apps.py`) karena label default-nya "auth" bentrok dengan
    # `django.contrib.auth` (Django menolak: "Application labels aren't unique").
    "core.auth",               # auth & role (custom user model)
    "core.event_bus",          # event bus (Django signals + Celery)
    "core.state_machine",      # state machine engine generik
    "core.rule_engine",        # rule engine (routing/bundling/alokasi) — label: rule_engine
    "core.cycle_handler",      # cycle handler (rework loop) — label: cycle_handler
    "core.device_profile",     # device profile manager (multi-device) — label: device_profile
    "core.idempotency",        # idempotency key endpoint aksi (Kontrak §5.1) — label: idempotency
    "core.audit",              # audit trail aksi penting (Fase 6) — label: audit
]

INSTALLED_APPS = ASGI_APPS + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ---------------------------------------------------------------------------
# Custom user model (Sprint 1.1)
# ---------------------------------------------------------------------------
# Dotted path di sini memakai **app_label**, BUKAN path folder. App
# `core/auth/` memakai label "core_auth" (lihat `core/auth/apps.py`), jadi
# nilainya HARUS "core_auth.User" — bukan "auth.User" (bentrok dengan
# `django.contrib.auth`) dan bukan "core.auth.User".
#
# PENTING: karena model user diganti, database harus dibuat dari nol
# (migration `auth` bawaan sudah terlanjur diterapkan pada user model lama).
AUTH_USER_MODEL = "core_auth.User"

MIDDLEWARE = [
    # CorsMiddleware harus paling atas (dan sebelum CommonMiddleware)
    "corsheaders.middleware.CorsMiddleware",
    # RequestIDMiddleware setelah CORS & sebelum CommonMiddleware (Fase 6):
    # memberi request id untuk korelasi log + header response X-Request-ID.
    "config.middleware.RequestIDMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database — Postgres yang sama dengan Odoo, tapi database terpisah
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "garmen_django"),
        "USER": env("DB_USER", "odoo"),
        "PASSWORD": env("DB_PASSWORD", ""),
        # `db` = nama service postgres di docker-compose.yml (hostname di garmen_net)
        "HOST": env("DB_HOST", "db"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": env_int("DB_CONNECT_TIMEOUT", 5)},
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = env("DJANGO_LANGUAGE_CODE", "id-id")
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Jakarta")
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media (whitenoise untuk serve static di production)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Manifest/compressed storage hanya dipakai di production (setelah
    # `collectstatic`). Di DEBUG pakai storage sederhana agar runserver aman.
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# ---------------------------------------------------------------------------
# CORS (frontend terpisah; origin dibaca dari env)
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", False)

# F1.5 (DEV-ONLY — blokir #1 laporan F1 §5): frontend dev (:5173) mengirim
# `credentials: "include"` (cookie `sessionid`) + `X-CSRFToken` (cookie `csrftoken`)
# ke backend (:8000) — lihat `frontend_app_v2/src/integrations/api-client.ts` (D5).
# Tanpa dua setting ini preflight lintas origin DITOLAK browser:
#   * `CORS_ALLOW_CREDENTIALS` -> header `Access-Control-Allow-Credentials: true`
#     (wajib; saat credentials aktif, `Access-Control-Allow-Origin` TIDAK boleh `*`);
#   * `CSRF_TRUSTED_ORIGINS`   -> Django menerima POST lintas origin yang membawa
#     cookie CSRF (kalau tidak: 403 "Origin checking failed").
# Nilai diisi lewat `.env` (lihat `django_app/.env.example`); default di sini AMAN
# (False/kosong) sehingga deployment satu-domain/produksi tidak berubah perilaku.
CORS_ALLOW_CREDENTIALS = env_bool("CORS_ALLOW_CREDENTIALS", False)
# Default `""` — BUKAN `[]`: `env_list()` menerima default string (lihat definisinya
# di atas), `[]` akan error `AttributeError: 'list' object has no attribute 'split'`.
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")


# Header custom yang dikirim frontend (api-client.ts) — django-cors-headers
# default TIDAK memuat ini, jadi preflight menolak x-device-id dkk.
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (
    *default_headers,
    "x-device-id",
    "x-device-profile",
    "x-base-version",
    "x-conflict-policy",
    "x-force",
    "x-request-id",
    "idempotency-key",
    # Fase 0.5: frontend v2 mengirim header prefiks `x-`; pertahankan
    # `idempotency-key` (lama) supaya tetap kompatibel keduanya.
    "x-idempotency-key",
)

CORS_EXPOSE_HEADERS = (
    "x-request-id",
    "x-idempotent-replay",
    "x-schema-version",
)


# ---------------------------------------------------------------------------
# Django REST Framework — baru sebatas infrastruktur, izin masih AllowAny
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    # Fase G: autentikasi. Sesi (user login) DULU, lalu cookie device binding
    # (perangkat lantai). Keduanya fail-safe: tanpa kredensial request tetap
    # anonim — tidak ada 401/403 selama `permission_classes` masih AllowAny.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "core.auth.authentication.DeviceTokenAuthentication",
    ],
    # Fase 6: rate limiter (memakai cache Redis — lihat CACHES di bawah).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "300/min",
    },
    # Fase 6: response error TIDAK boleh membocorkan stack trace (lihat config/exceptions.py).
    "EXCEPTION_HANDLER": "config.exceptions.custom_exception_handler",
    # Fase 6: skema OpenAPI otomatis (drf-spectacular).
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ---------------------------------------------------------------------------
# Auth hybrid (F6.1) — kuota & umur sesi endpoint `/api/v1/auth/*`
# ---------------------------------------------------------------------------
# Rate limit di endpoint auth TIDAK memakai `DEFAULT_THROTTLE_RATES` di atas
# karena mode test menaikkan kuota DRF ke 100000/min (lihat blok "Mode test"),
# sehingga 429 login tidak bisa dibuktikan lewat throttle bawaan. Limiter
# manual `core.auth.ratelimit` memakai angka di bawah pada SEMUA mode (dev,
# test, produksi) — cache-nya Redis di produksi, LocMem di mode test.
AUTH_RATE_LIMITS = {
    # E1 `POST /auth/login/` — 5 percobaan/menit per IP.
    "login": {
        "limit": env_int("AUTH_LOGIN_RATE_LIMIT", 5),
        "window": env_int("AUTH_LOGIN_RATE_WINDOW", 60),
    },
    # E2 `POST /auth/login-operator/` — 10 percobaan/menit per IP (kode pendek,
    # jadi lebih longgar dari login, tetapi tetap dibatasi dari brute force).
    "login_operator": {
        "limit": env_int("AUTH_OPERATOR_RATE_LIMIT", 10),
        "window": env_int("AUTH_OPERATOR_RATE_WINDOW", 60),
    },
}

# Umur sesi login operator (detik) — E2: HP pribadi di lantai produksi, 8 jam
# per shift. Login admin (E1) memakai `SESSION_COOKIE_AGE` bawaan Django.
AUTH_OPERATOR_SESSION_AGE = env_int("AUTH_OPERATOR_SESSION_AGE", 8 * 60 * 60)

# ---------------------------------------------------------------------------
# Redis & Celery
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "redis://redis:6379/0")

CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)

CELERY_TASK_DEFAULT_QUEUE = "default"
# Task bernama `erp_sync.*` masuk queue terpisah agar worker sinkronisasi bisa
# di-scale sendiri (`celery -A config worker -Q default,erp_sync`).
CELERY_TASK_ROUTES = {
    "erp_sync.*": {"queue": "erp_sync"},
}


CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_WORKER_PREFETCH_MULTIPLIER = env_int("CELERY_WORKER_PREFETCH_MULTIPLIER", 1)
CELERY_TASK_ACKS_LATE = env_bool("CELERY_TASK_ACKS_LATE", True)
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = CELERY_TASK_ALWAYS_EAGER
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_EXPIRES = env_int("CELERY_RESULT_EXPIRES", 3600)

# File schedule celery beat ditulis di /tmp supaya tidak mengganggu
# bind mount source code.
CELERY_BEAT_SCHEDULE_FILENAME = env("CELERY_BEAT_SCHEDULE_FILE", "/tmp/celerybeat-schedule")
# Jadwal master sync harian — jam 02:00 menurut CELERY_TIMEZONE (= Asia/Jakarta)
# — plus poll sales order (I2) tiap 5 menit, sync scrap (I4) per shift,
# sync invoice (I5) tiap 15 menit, recompute readiness (I3.4+I6.3 → I7) harian
# 04:00, dan rekonsiliasi stok MES vs Odoo (I7) mingguan Senin 03:00.
# `task` memakai `name=` yang dideklarasikan di `integrations/erp_sync/
# tasks_master.py` / `tasks_order.py` / `tasks_scrap.py` / `tasks_invoice.py` /
# `tasks_vendor_bill.py` (recompute readiness) / `tasks_reconciliation.py`
# (BUKAN dotted path modul) supaya bisa di-resolve worker mana pun.
CELERY_BEAT_SCHEDULE = {
    "sync-master-products": {
        "task": "erp_sync.sync_master_products",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-boms": {
        "task": "erp_sync.sync_master_boms",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-partners": {
        "task": "erp_sync.sync_master_partners",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-locations": {
        "task": "erp_sync.sync_master_locations",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-taxes": {
        "task": "erp_sync.sync_master_taxes",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-uoms": {
        "task": "erp_sync.sync_master_uoms",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-warehouses": {
        "task": "erp_sync.sync_master_warehouses",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-journals": {
        "task": "erp_sync.sync_master_journals",
        "schedule": crontab(hour=2, minute=0),
    },
    "sync-master-currencies": {
        "task": "erp_sync.sync_master_currencies",
        "schedule": crontab(hour=2, minute=0),
    },
    # Poll sales order (I2) — tiap 5 menit; `name=`-nya di
    # `integrations/erp_sync/tasks_order.py`.
    "sync-sale-orders": {
        "task": "erp_sync.sync_sale_orders",
        "schedule": crontab(minute="*/5"),
    },
    # Sync scrap (I4) — per shift pagi/siang/malam (06:00/14:00/22:00 WIB);
    # `name=`-nya di `integrations/erp_sync/tasks_scrap.py`.
    "sync-scrap-accumulator": {
        "task": "erp_sync.sync_scrap_accumulator",
        "schedule": crontab(hour="6,14,22", minute=0),
    },
    # Sync invoice (I5) — tiap 15 menit (responsif, tapi tidak real-time);
    # `name=`-nya di `integrations/erp_sync/tasks_invoice.py`.
    "sync-invoice": {
        "task": "erp_sync.sync_invoice",
        "schedule": crontab(minute="*/15"),
    },
    # Recompute material readiness (I3.4 + I6.3, dikonsolidasi di I7) — harian
    # 04:00 WIB: PO + vendor bill di-fetch sekali, HANYA OrderLine yang belum
    # READY; `name=`-nya di `tasks_vendor_bill.py`.
    "recompute-readiness": {
        "task": "erp_sync.recompute_readiness",
        "schedule": crontab(hour=4, minute=0),
    },
    # Rekonsiliasi stok MES (WIP+FG) vs Odoo (I7) — mingguan Senin 03:00 WIB
    # (setelah master sync 02:00, sebelum jam kerja); alert WA kalau ada selisih.
    # `name=`-nya di `tasks_reconciliation.py`.
    "reconcile-stock": {
        "task": "erp_sync.reconcile_stock",
        "schedule": crontab(day_of_week=1, hour=3, minute=0),
    },
}

# ---------------------------------------------------------------------------
# Odoo / ERP adapter
# ---------------------------------------------------------------------------
ERP_ADAPTER = env("ERP_ADAPTER", "odoo")  # "odoo" | "null"
ODOO_URL = env("ODOO_URL", "http://odoo:8069")
ODOO_DB = env("ODOO_DB", "")
ODOO_USER = env("ODOO_USER", "")
ODOO_API_KEY = env("ODOO_API_KEY", "")
ODOO_TIMEOUT = env_float("ODOO_TIMEOUT", 30.0)
# Lokasi (stock.location) Odoo untuk two-stage sync — opsional (default None).
# Selama belum diisi, OdooAdapter menolak push dengan pesan jelas (ok=False)
# sehingga tidak ada stok yang terlanjur tercatat di ERP.
#   * ODOO_LOCATION_WIP_ID        : gudang bahan  (sumber WIP issue)
#   * ODOO_LOCATION_PRODUCTION_ID : lokasi produksi/WIP (tujuan WIP issue, sumber FG receipt)
#   * ODOO_LOCATION_FG_ID         : gudang barang jadi (tujuan FG receipt)
ODOO_LOCATION_WIP_ID = env_int_or_none("ODOO_LOCATION_WIP_ID")
ODOO_LOCATION_PRODUCTION_ID = env_int_or_none("ODOO_LOCATION_PRODUCTION_ID")
ODOO_LOCATION_FG_ID = env_int_or_none("ODOO_LOCATION_FG_ID")
#   * ODOO_LOCATION_SCRAP_ID      : lokasi scrap Odoo (tujuan scrap, mis. Virtual Locations/Scrap)
ODOO_LOCATION_SCRAP_ID = env_int_or_none("ODOO_LOCATION_SCRAP_ID")
#   * ODOO_PAYMENT_JOURNAL_ID    : journal pembayaran Odoo (H3.3) untuk
#                                  `account.payment.journal_id`. OPSIONAL: kalau kosong,
#                                  adapter TIDAK mengirim `journal_id` dan Odoo memilih
#                                  sendiri (`_search_default_journal()`); dev: 13 (Bank BNK1).
ODOO_PAYMENT_JOURNAL_ID = env_int_or_none("ODOO_PAYMENT_JOURNAL_ID")
#   * ODOO_UOM_ID                : UoM default untuk push stok. Dipakai TX-SCRAP
#                                  (`stock.scrap.product_uom_id` WAJIB); mis. PCS = 33.
ODOO_UOM_ID = env_int_or_none("ODOO_UOM_ID")
#   * ODOO_PICKING_TYPE_INTERNAL_ID : `stock.picking.type` internal untuk transfer
#                                     antar-lokasi (H2.6). H5.6 — resmi di sini
#                                     (sebelumnya hanya `getattr(settings, …, None)`
#                                     di `adapters/odoo.py`); kosong → adapter mencari
#                                     sendiri `code='internal'` saat dibutuhkan.
ODOO_PICKING_TYPE_INTERNAL_ID = env_int_or_none("ODOO_PICKING_TYPE_INTERNAL_ID")

# Rekonsiliasi stok MES vs Odoo (fase I7) — toleransi selisih per produk.
# Sebuah produk di-flag `is_alert` kalau |diff| > max(UNITS, PCT × mes_qty):
#   * RECONCILIATION_TOLERANCE_UNITS : selisih absolut minimal yang dianggap wajar
#     (menyerap pembulatan ±unit, mis. 5 pcs);
#   * RECONCILIATION_TOLERANCE_PCT   : toleransi relatif untuk volume besar
#     (mis. 0.01 = 1% dari qty MES).
RECONCILIATION_TOLERANCE_UNITS = env_int("RECONCILIATION_TOLERANCE_UNITS", 5)
RECONCILIATION_TOLERANCE_PCT = env_float("RECONCILIATION_TOLERANCE_PCT", 0.01)
# Nomor WA penerima alert rekonsiliasi (dipisah koma, mis. "6281...,6282...").
# Kosong (default) → task `erp_sync.reconcile_stock` tetap jalan & tetap
# menyimpan baris `StockReconciliation`, hanya alert WA-nya dilewati (log info).
# Gateway-nya dari `integrations.wa_bot.services.get_wa_gateway` (lihat WA_BACKEND).
RECONCILIATION_ALERT_WA_TO = env_list("RECONCILIATION_ALERT_WA_TO")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# RotatingFileHandler menulis ke logs/mes.jsonl (satu baris = satu JSON object).
# Folder `logs/` dibuat di sini karena FileHandler/RotatingFileHandler TIDAK
# membuat folder induknya otomatis -> tanpa ini aplikasi gagal saat start.
# (`os` sudah di-import di bagian atas modul ini.)
os.makedirs(BASE_DIR / "logs", exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        # Dipertahankan untuk pemakaian manual (mis. saat debugging lokal).
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
        # Fase 6: satu baris log = satu JSON object (lihat config/logging.py).
        "json": {
            "()": "config.logging.JsonFormatter",
        },
    },
    "filters": {
        # Menempelkan request id request yang sedang berjalan ke tiap record.
        "request_id": {
            "()": "config.middleware.RequestIDFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
        # Trace-Bridge: salinan log ke file berotasi (logs/mes.jsonl) supaya
        # satu request bisa di-tail/di-ingest dari disk, bukan hanya stdout.
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": BASE_DIR / "logs" / "mes.jsonl",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "json",
            "encoding": "utf-8",
            "filters": ["request_id"],
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": env("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "integrations.erp_sync": {
            "handlers": ["console", "file"],
            "level": env("DJANGO_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Printing thermal ESC/POS (Fase 5)
# ---------------------------------------------------------------------------
# Backend cetak: "mock" (dev/test, default) | "usb" (stub) | "network" (TCP raw).
PRINTER_BACKEND = env("PRINTER_BACKEND", "mock")
PRINTER_USB_VENDOR_ID = env_int_or_none("PRINTER_USB_VENDOR_ID")
PRINTER_USB_PRODUCT_ID = env_int_or_none("PRINTER_USB_PRODUCT_ID")
PRINTER_NETWORK_HOST = env("PRINTER_NETWORK_HOST", "") or None
PRINTER_NETWORK_PORT = env_int_or_none("PRINTER_NETWORK_PORT")
# Folder hasil "cetak" backend mock (di /tmp supaya tidak masuk repo).
PRINTER_MOCK_DIR = env("PRINTER_MOCK_DIR", "/tmp/print_mock")

# ---------------------------------------------------------------------------
# WhatsApp gateway (stub) — Fase 5
# ---------------------------------------------------------------------------
# "mock" = tidak mengirim pesan sungguhan (default aman); penyedia lain menyusul.
WA_BACKEND = env("WA_BACKEND", "mock")
WA_API_URL = env("WA_API_URL", "") or None
WA_API_KEY = env("WA_API_KEY", "") or None

# ---------------------------------------------------------------------------
# Cache (Fase 6) — dipakai rate limiter DRF (throttle)
# ---------------------------------------------------------------------------
# Wajib Redis supaya hitungan throttle konsisten antar proses/container
# (gunicorn multi-worker, beberapa replica). Bukan LocMem/memory.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_REDIS_URL", REDIS_URL),
        "KEY_PREFIX": "garmen",
    },
}

# ---------------------------------------------------------------------------
# Channels / WebSocket (Fase E)
# ---------------------------------------------------------------------------
# Group event real-time memakai Redis yang SAMA dengan Celery/cache — tidak ada
# host baru yang di-hardcode (konsisten dengan REDIS_URL di atas). Ini penting
# karena action endpoint bisa jalan di container/worker yang berbeda dari
# container yang memegang koneksi WebSocket klien.
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    },
}

# ---------------------------------------------------------------------------
# Mode test (Fase 6)
# ---------------------------------------------------------------------------
# Semua request test datang dari IP yang sama, sehingga rate limit PRODUKSI
# (60/min anon) akan menabrak ratusan test lama dengan 429 palsu. Di mode test
# hitungan throttle disimpan di memori + rate dinaikkan; PRODUKSI tetap memakai
# Redis + 60/300 per menit (nilai di atas tidak berubah saat tidak test).
#
# Sejak I8.5b deteksinya juga mengenali **pytest**: menjalankan `pytest` tidak
# menaruh argumen `test` di `sys.argv`, jadi tanpa tambahan ini mode test TIDAK
# aktif dan cache throttle produksi (Redis — dibagi lintas proses/wadah) masih
# dipakai → menjalankan beberapa suite beruntun dalam satu menit menghasilkan
# 429 palsu (`anon` cuma 60/menit, sementara satu suite bisa ratusan request).
TESTING = "test" in sys.argv or any("pytest" in arg for arg in sys.argv)
if TESTING:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "garmen-throttle-test",
        }
    }
    REST_FRAMEWORK = {
        **REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {"anon": "100000/min", "user": "100000/min"},
    }
    # WebSocket di mode test pakai layer in-memory: test consumer tidak boleh
    # butuh Redis (dan tidak boleh mencemari group Redis dev).
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# ---------------------------------------------------------------------------
# Keamanan produksi (F3-B.2.2 — menutup audit blocker #4)
# ---------------------------------------------------------------------------
# Aktif HANYA di produksi: `DEBUG=False` DAN bukan mode test.
# Kenapa harus `not TESTING`: `SECURE_SSL_REDIRECT` membuat request HTTP (test
# client Django) dijawab 301 → ratusan test lama akan gagal palsu.
# Blok ini SENGAJA diletakkan setelah `TESTING` di atas agar urutannya benar.
# Semua nilai dapat di-override lewat env (lihat `.env.prod.example`).
if not DEBUG and not TESTING:
    # Percayai `X-Forwarded-Proto` dari Nginx → Django tahu request aslinya HTTPS.
    # Tanpa ini, `SECURE_SSL_REDIRECT` + TLS-terminasi di Nginx = redirect loop.
    if env_bool("DJANGO_SECURE_PROXY_SSL_HEADER", True):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)

    # HSTS 1 tahun (naikkan bertahap bila ingin; default aman untuk HTTPS murni).
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", True)

    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Secret hygiene (F3-B.2.3 — menutup audit blocker #10)
# ---------------------------------------------------------------------------
# FAIL-FAST: di produksi (`DEBUG=False`, bukan test) JANGAN biarkan `SECRET_KEY`
# default/placeholder dipakai. Container gagal start > berjalan dengan kunci bocor.
# Dibandingkan case-insensitive (`SECRET_KEY.strip().lower()`), jadi SEMUA anggota
# di bawah wajib huruf kecil.
INSECURE_SECRET_KEYS = {
    "",
    "change-me",
    "change-me-in-production",
    "django-insecure-dev-only-change-me",
    "__generate_with_openssl_rand_hex_32__",
}
if not DEBUG and not TESTING and SECRET_KEY.strip().lower() in INSECURE_SECRET_KEYS:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY belum diisi (atau masih placeholder). "
        "Generate nilai acak: openssl rand -hex 32"
    )

# ---------------------------------------------------------------------------
# Monitoring — Sentry (F3-B.2.3 — menutup audit blocker #8; OPSIONAL & fail-safe)
# ---------------------------------------------------------------------------
# Aktif HANYA bila `SENTRY_DSN` diisi dan bukan mode test. Import dilakukan di
# dalam blok supaya aplikasi tetap berjalan bila `sentry-sdk` belum terpasang.
SENTRY_DSN = env("SENTRY_DSN", "")
if SENTRY_DSN and not TESTING:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
    except ImportError as exc:  # pragma: no cover - bergantung paket opsional
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "SENTRY_DSN diisi tetapi sentry-sdk tidak terpasang (%s) — monitoring dilewati.", exc
        )
    else:
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment=env("SENTRY_ENVIRONMENT", "production"),
            release=(env("SENTRY_RELEASE", "") or None),
            traces_sample_rate=env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
            send_default_pii=env_bool("SENTRY_SEND_DEFAULT_PII", False),
            integrations=[DjangoIntegration(), CeleryIntegration(), RedisIntegration()],
        )

# ---------------------------------------------------------------------------
# OpenAPI / Swagger (Fase 6)
# ---------------------------------------------------------------------------
SPECTACULAR_SETTINGS = {
    "TITLE": "Garmen Backend API",
    "VERSION": "1.0.0",
    "DESCRIPTION": (
        "Backend produksi garmen: metadata/schema kontrak, action endpoint "
        "idempotent, two-stage sync ERP, printing ESC/POS, dan audit trail. "
        "Frontend tidak menyimpan logika bisnis — semua aturan datang dari "
        "backend (KONTRAK Backend<->Frontend v1.0)."
    ),
    "SERVE_INCLUDE_SCHEMA": False,
}
