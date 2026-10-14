"""Model app `core.event_bus` — belum ada model (placeholder Fase 0).

App ini baru **didaftarkan** sebagai Django app mandiri (`core.event_bus`)
supaya folder core engine bisa diisi model pada fase berikutnya tanpa
mengubah `INSTALLED_APPS` lagi.

Rencana model (Fase 1 — jangan ditulis sekarang):
  * ``EventLog`` — jejak audit event yang dipublikasikan lewat event bus
    (nama event, payload JSON, sumber/aggregate, timestamp).

Belum ada model bisnis. Setup infrastruktur dulu (lihat instruksi project).
"""

# from django.db import models

# TODO: definisikan EventLog saat event bus (Django signals + Celery)
#       mulai diimplementasikan, lalu buat migration pertamanya.
