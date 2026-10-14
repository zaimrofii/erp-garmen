"""Seed profil device sesuai kontrak UI (Fase G).

Kontrak frontend (`frontend_app/src/core/useDeviceProfile.ts`) mengenal **4** profil:
``OPERATOR_HP | KIOSK_TABLET | SCANNER_USB | DESKTOP``. Sprint 1.2 hanya menyemai
tiga (memakai kode ``KIOS`` untuk tablet lantai), sehingga
``POST /api/v1/devices/bind`` akan **400** untuk ``KIOSK_TABLET``/``DESKTOP``
walau UI-nya sah (nilainya datang dari `metadata.device_hint`).

Migration ini menambahkan dua kode yang kurang:
  * ``KIOSK_TABLET`` — tablet kios lantai (kode yang dipakai metadata/frontend);
  * ``DESKTOP``       — workstation manajemen/supervisor.

Data-only + idempotent (`get_or_create`); ``KIOS`` **tidak** dihapus supaya
binding lama (mis. kios yang sudah terpasang) tetap valid. Tanpa perubahan skema.
"""

from django.db import migrations

#: (code, name, config) — hanya kode yang BELUM ada di `0002_seed_default_profiles`.
ADDED_PROFILES = (
    (
        "KIOSK_TABLET",
        "Kios Tablet Lantai Produksi",
        {"input_mode": "touch", "scan_button": False, "queue_poll_ms": 5000},
    ),
    (
        "DESKTOP",
        "Desktop Manajemen",
        {"input_mode": "keyboard", "scan_button": False, "queue_poll_ms": 15000},
    ),
)


def create_added_profiles(apps, schema_editor):
    """Buat profil tambahan kalau belum ada (idempotent)."""
    profile_model = apps.get_model("device_profile", "DeviceProfile")
    for code, name, config in ADDED_PROFILES:
        profile_model.objects.get_or_create(code=code, defaults={"name": name, "config": config})


def delete_added_profiles(apps, schema_editor):
    """Kebalikannya: hapus HANYA kode yang ditambahkan migration ini."""
    profile_model = apps.get_model("device_profile", "DeviceProfile")
    profile_model.objects.filter(code__in=[code for code, _, _ in ADDED_PROFILES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("device_profile", "0002_seed_default_profiles"),
    ]

    operations = [
        migrations.RunPython(create_added_profiles, delete_added_profiles),
    ]
