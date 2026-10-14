from django.apps import AppConfig


class DeviceProfileConfig(AppConfig):
    """App `core.device_profile` — device profile manager (multi-device adaptive).

    Profil perangkat (HP operator / kios / scanner USB) + binding perangkat ke
    work center = data di DB; resolusi profil ada di
    `services.DeviceProfileResolver`, endpoint core-nya di `api.DeviceMeView`.

    `label` ditulis eksplisit (`device_profile`) karena label inilah yang dipakai
    `makemigrations device_profile` dan nama tabel
    (`device_profile_deviceprofile`).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.device_profile"
    label = "device_profile"
    verbose_name = "Core Device Profile"
