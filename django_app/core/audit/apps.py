"""AppConfig app `core.audit` (label: ``audit``)."""

from django.apps import AppConfig


class AuditConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.audit"
    #: Label eksplisit -> tabel `audit_auditlog` (rapi, tidak bentrok).
    label = "audit"
    verbose_name = "Audit Log"
