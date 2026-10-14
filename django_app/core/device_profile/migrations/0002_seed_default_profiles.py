"""Seed profil device bawaan (Sprint 1.2).

Tiga kode ini dipakai kontrak device resolver (§5.2). Seperti role di
`core_auth`, daftar ini hanya **nilai awal** dan tidak menimpa perubahan admin
(pakai `get_or_create`).

Ditulis manual (bukan hasil `makemigrations`) supaya aman kalau `0001_initial`
di-generate ulang.
"""

from django.db import migrations

#: (code, name, config) — konsisten dengan contoh di `core/device_profile/models.py`.
DEFAULT_PROFILES = (
    (
        "OPERATOR_HP",
        "Operator HP",
        {"input_mode": "touch", "scan_button": True, "queue_poll_ms": 5000},
    ),
    (
        "KIOS",
        "Kios Lantai Produksi",
        {"input_mode": "touch", "scan_button": False, "queue_poll_ms": 5000},
    ),
    (
        "SCANNER_USB",
        "Scanner USB + Mini PC",
        {"input_mode": "scanner", "scan_button": False, "queue_poll_ms": 5000},
    ),
)


def create_default_profiles(apps, schema_editor):
    """Buat profil bawaan kalau belum ada (idempotent)."""
    profile_model = apps.get_model("device_profile", "DeviceProfile")
    for code, name, config in DEFAULT_PROFILES:
        profile_model.objects.get_or_create(
            code=code,
            defaults={"name": name, "config": config},
        )


def delete_default_profiles(apps, schema_editor):
    """Kebalikannya: hapus profil bawaan saat migration di-rollback."""
    profile_model = apps.get_model("device_profile", "DeviceProfile")
    profile_model.objects.filter(
        code__in=[code for code, _, _ in DEFAULT_PROFILES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("device_profile", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_profiles, delete_default_profiles),
    ]
