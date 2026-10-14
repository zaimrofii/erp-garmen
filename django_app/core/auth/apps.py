from django.apps import AppConfig


class CoreAuthConfig(AppConfig):
    """App `core.auth` — auth & role (operator, QC, supervisor, admin, owner).

    PENTING — kenapa `label` di-set eksplisit:

    Folder ini bernama `auth`, jadi app_label default-nya juga "auth" dan itu
    **bentrok** dengan `django.contrib.auth` yang sudah dipakai project ini.
    Django menolak saat startup (lihat `django/apps/registry.py`):

        ImproperlyConfigured: Application labels aren't unique, duplicates: auth

    Selain label, nama tabel default `auth_user` juga akan bentrok. Karena itu
    label dipakai "core_auth" sehingga model user menjadi
    `AUTH_USER_MODEL = "core_auth.User"` (lihat `config/settings.py`).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.auth"
    label = "core_auth"
    verbose_name = "Core Auth & Role"
