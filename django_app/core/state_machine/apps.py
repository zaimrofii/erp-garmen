from django.apps import AppConfig


class StateMachineConfig(AppConfig):
    """App `core.state_machine` — state machine engine generik.

    Fase 0: hanya registrasi app. Tidak ada logika bisnis di sini.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.state_machine"
    verbose_name = "Core State Machine"
