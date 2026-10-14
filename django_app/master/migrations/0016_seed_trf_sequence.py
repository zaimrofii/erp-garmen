"""Seed sequence **TRF** (Stock Transfer, H2.6) untuk tahun berjalan.

Aditif: hanya menambah satu baris ``master.NumberSequence`` (prefix ``TRF``) supaya
nomor MES transfer mengikuti konvensi Sprint C ``<PREFIX>-<YEAR>-<SEQ:04d>``
(mis. ``TRF-2026-0001``) dan bisa dipakai sebagai ``origin`` picking Odoo.
Idempotent (``get_or_create``); sequence lain (SO/PO/WO/INV/VB/PAY/JE/ADJ) TIDAK disentuh.
"""

from django.db import migrations
from django.utils import timezone

#: (code, name, prefix)
SEQUENCE = ("TRF", "Stock Transfer", "TRF")
DEFAULT_PADDING = 4


def seed_trf_sequence(apps, schema_editor):
    """Buat sequence TRF tahun berjalan kalau belum ada."""
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


def unseed_trf_sequence(apps, schema_editor):
    """Hapus sequence TRF (kebalikannya)."""
    number_sequence = apps.get_model("master", "NumberSequence")
    code, _name, _prefix = SEQUENCE
    number_sequence.objects.filter(code=code).delete()


class Migration(migrations.Migration):
    """Data migration: seed sequence TRF."""

    dependencies = [
        ("master", "0015_seed_adj_sequence"),
    ]

    operations = [
        migrations.RunPython(seed_trf_sequence, unseed_trf_sequence),
    ]
