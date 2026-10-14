"""Seed role bawaan (Fase 1.1).

Role = data di DB (`core_auth.Role`), jadi daftar ini hanya **nilai awal** supaya
sistem langsung bisa dipakai. Role tambahan dibuat lewat admin dan tidak akan
ditimpa (pakai `get_or_create`).

File ini ditulis manual (bukan hasil `makemigrations`), sehingga tetap aman
walau migration `0001_initial` di-generate ulang.
"""

from django.db import migrations

#: (code, name, description) — konsisten dengan `Role.Code` di `core/auth/models.py`.
DEFAULT_ROLES = (
    ("OPERATOR", "Operator", "Operator lantai produksi (mulai/selesai/scrap bundle)."),
    ("QC", "QC", "Inspeksi kualitas per bundle (cacat, rework vs scrap)."),
    ("SUPERVISOR", "Supervisor", "Pemantau buffer queue work center & approver."),
    ("ADMIN", "Administrator", "Konfigurasi routing, bundling, line, dan device."),
    ("OWNER", "Owner", "Pemilik / approver tingkat tertinggi."),
)


def create_default_roles(apps, schema_editor):
    """Buat role bawaan kalau belum ada (idempotent)."""
    role_model = apps.get_model("core_auth", "Role")
    for code, name, description in DEFAULT_ROLES:
        role_model.objects.get_or_create(
            code=code,
            defaults={"name": name, "description": description},
        )


def delete_default_roles(apps, schema_editor):
    """Kebalikannya: hapus role bawaan saat migration di-rollback."""
    role_model = apps.get_model("core_auth", "Role")
    role_model.objects.filter(code__in=[code for code, _, _ in DEFAULT_ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core_auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_default_roles, delete_default_roles),
    ]
