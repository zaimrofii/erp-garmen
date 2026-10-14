"""Seed role ``PURCHASING`` (H1.1).

H1.1 membuka CRUD master Product dari MES dengan izin **admin/owner/purchasing**
(brief H1.1 + ``docs/CHANGES-DETAIL-H1H5.md`` bagian 7: "Role Baru: purchasing").
Role = data di DB (bukan enum), jadi staf purchasing harus ada sebagai baris
``core_auth.Role`` — kalau tidak, satu-satunya cara membuatnya adalah lewat admin
manual dan endpoint master akan menolak semua user purchasing.

Migration ini **data-only** dan idempotent (``get_or_create``), pola sama seperti
``0002_seed_default_roles``: role lain yang sudah ada tidak disentuh, dan
rollback hanya menghapus role bawaan yang dibuat di sini.

File ditulis manual (bukan hasil ``makemigrations``) supaya aman walau schema
migration ``0001_initial`` di-generate ulang.
"""

from django.db import migrations

#: (code, name, description) — konsisten dengan `Role.Code.PURCHASING` di `core/auth/models.py`.
PURCHASING_ROLE = (
    "PURCHASING",
    "Purchasing",
    "Staf pembelian: input & ubah master produk, supplier, dan dokumen pembelian.",
)


def create_purchasing_role(apps, schema_editor):
    """Buat role PURCHASING kalau belum ada (idempotent)."""
    role_model = apps.get_model("core_auth", "Role")
    code, name, description = PURCHASING_ROLE
    role_model.objects.get_or_create(
        code=code,
        defaults={"name": name, "description": description},
    )


def delete_purchasing_role(apps, schema_editor):
    """Hapus role PURCHASING saat migration di-rollback."""
    role_model = apps.get_model("core_auth", "Role")
    role_model.objects.filter(code=PURCHASING_ROLE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core_auth", "0003_user_operator_code"),
    ]

    operations = [
        migrations.RunPython(create_purchasing_role, delete_purchasing_role),
    ]
