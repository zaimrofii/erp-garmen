"""Project Django `garmen` (integrasi Django <-> Odoo 17).

Celery app di-import di sini supaya:
  * `celery -A config worker` menemukan app-nya,
  * `@shared_task` selalu terikat ke app yang sama saat Django startup.
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
