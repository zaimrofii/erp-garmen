from django.apps import AppConfig


class CycleHandlerConfig(AppConfig):
    """App `core.cycle_handler` — cycle handler generik (rework loop).

    Definisi siklus (mis. QC -> Sewing -> QC) = data di DB
    (`CycleDefinition`/`CycleStep`), sedangkan eksekusinya di
    `services.CycleHandler`.

    `label` ditulis eksplisit (`cycle_handler`) karena label inilah yang dipakai
    `makemigrations cycle_handler` dan nama tabel (`cycle_handler_cycleinstance`).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.cycle_handler"
    label = "cycle_handler"
    verbose_name = "Core Cycle Handler"
