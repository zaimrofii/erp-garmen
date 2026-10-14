"""Seed sequence **ADJ** (Inventory Adjustment, H2.5) untuk tahun berjalan.

Aditif: hanya menambah satu baris ``master.NumberSequence`` (prefix ``ADJ``) supaya
nomor MES adjustment mengikuti konvensi Sprint C ``<PREFIX>-<YEAR>-<SEQ:04d>``
(mis. ``ADJ-2026-0001``). Idempotent (`get_or_create`) & aman dijalankan berulang;
sequence lain (SO/PO/WO/INV/VB/PAY/JE) TIDAK disentuh.
"""

from django.db import migrations
from django.utils import timezone

#: (code, name, prefix)
SEQUENCE = ("ADJ", "Inventory Adjustment", "ADJ")
DEFAULT_PADDING = 4


def seed_adj_sequence(apps, schema_editor):
    """Buat sequence ADJ tahun berjalan kalau belum ada."""
    number_sequence = apps.get_model("master", "NumberSequence")
    code, name, prefix = SEQUENCE
    year = timezone.now().year

    number_sequence.objects.get_or_create(
        code=code,
        year=year,
        defaults={
            "name": name,
            "prefix": prefix,
            "padding": DEFAULT_PADDING,
            "last_seq": 0,
        },
    )


def unseed_adj_sequence(apps, schema_editor):
    """Hapus sequence ADJ (kebalikannya)."""
    number_sequence = apps.get_model("master", "NumberSequence")
    code, _name, _prefix = SEQUENCE
    number_sequence.objects.filter(code=code).delete()


class Migration(migrations.Migration):
    """Data migration: seed sequence ADJ."""

    dependencies = [
        ("master", "0014_seed_sequences"),
    ]

    operations = [
        migrations.RunPython(seed_adj_sequence, unseed_adj_sequence),
    ]
