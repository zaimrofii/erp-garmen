"""Celery app project `garmen`.

Konfigurasi (broker, result backend, timezone, serializer) diambil dari Django
settings dengan prefix `CELERY_` (lihat `config/settings.py`), sehingga hanya
ada satu sumber kebenaran.
"""

import os
import sys
from pathlib import Path

from celery import Celery

# Root project = folder yang berisi `config/`, `apps_industry/`,
# `integrations/`, `master/`; dipastikan ada di sys.path supaya semuanya
# bisa di-import dari manapun proses celery dijalankan.
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("garmen")

# Baca semua setting `CELERY_*` dari Django settings.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Temukan task di semua app INSTALLED_APPS (mis. integrations/erp_sync/tasks.py,
# master/tasks.py) lewat dotted path-nya.
app.autodiscover_tasks()

# Task routing: task bernama `erp_sync.*` selalu masuk queue `erp_sync`
# (worker: `celery -A config worker -Q default,erp_sync`).
app.conf.task_routes = {
    **(app.conf.task_routes or {}),
    "erp_sync.*": {"queue": "erp_sync"},
}
app.conf.task_default_queue = "default"


@app.task(bind=True, name="config.debug_task")
def debug_task(self):
    """Task diagnosa: pastikan worker + broker jalan (`debug_task.delay()`)."""
    return {"status": "ok", "task_id": self.request.id, "queue": "default"}
