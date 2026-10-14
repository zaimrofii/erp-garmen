"""AppConfig app `integrations.wa_bot` (label: ``wa_bot``)."""

from django.apps import AppConfig


class WaBotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations.wa_bot"
    label = "wa_bot"
    verbose_name = "WhatsApp Gateway"
