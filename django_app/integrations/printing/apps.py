"""AppConfig app `integrations.printing` (label: ``printing``)."""

from django.apps import AppConfig


class PrintingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.printing"
    #: Label eksplisit supaya tabel/migrasi bernama `printing_*` (bukan
    #: `erp_sync_*`/`integrations_printing_*`) dan tidak bentrok antar-integrasi.
    label = "printing"
    verbose_name = "Printing (ESC/POS)"
