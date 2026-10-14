from django.apps import AppConfig


class EventBusConfig(AppConfig):
    """App `core.event_bus` — event bus generik (Django signals + Celery).

    Fase 0: hanya registrasi app. Tidak ada logika bisnis di sini.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.event_bus"
    verbose_name = "Core Event Bus"
