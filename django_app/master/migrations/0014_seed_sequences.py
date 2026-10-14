"""Seed 7 Number Sequence default (Sprint C) — **data-only**.

Kode & nama mengikuti keputusan pemilik proyek: SO/PO/WO/INV/VB/PAY/JE
(`BB`/bundle **tidak** ditambahkan — kode bundle existing formatnya beda, dibahas H2.4).

``year`` diambil dari ``timezone.now().year`` **saat migrasi dijalankan** ⇒ migrasi ini
non-deterministik by design (dicatat di ``decisions[]`` JSON). Baris tahun berikutnya
dibuat otomatis oleh `master/sequence_services.py::next_number` (reset per tahun:
copy ``prefix``/``padding``, ``last_seq=0``).

Idempoten: ``get_or_create`` per ``(code, year)`` sehingga aman dijalankan berulang.
"""

from __future__ import annotations

from django.db import migrations
from django.utils import timezone

#: (code, name, prefix) — prefix default = code.
SEQUENCES: tuple[tuple[str, str, str], ...] = (
    ("SO", "Sales Order", "SO"),
    ("PO", "Purchase Order", "PO"),
    ("WO", "Work Order", "WO"),
    ("INV", "Customer Invoice", "INV"),
    ("VB", "Vendor Bill", "VB"),
    ("PAY", "Payment", "PAY"),
    ("JE", "Journal Entry", "JE"),
)

DEFAULT_LAST_SEQ = 0
DEFAULT_PADDING = 4


def seed_sequences(apps, schema_editor):
    """Buat 7 baris sequence untuk tahun berjalan (skip yang sudah ada)."""
    number_sequence = apps.get_model("master", "NumberSequence")
    year = timezone.now().year

    for code, name, prefix in SEQUENCES:
        number_sequence.objects.get_or_create(
            code=code,
            year=year,
            defaults={
                "name": name,
                "prefix": prefix,
                "last_seq": DEFAULT_LAST_SEQ,
                "padding": DEFAULT_PADDING,
                "is_active": True,
            },
        )


def unseed_sequences(apps, schema_editor):
    """Hapus baris seed tahun berjalan (baris tahun lain tidak disentuh)."""
    number_sequence = apps.get_model("master", "NumberSequence")
    year = timezone.now().year

    number_sequence.objects.filter(
        code__in=[code for code, _, _ in SEQUENCES],
        year=year,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("master", "0013_number_sequence"),
    ]

    operations = [
        migrations.RunPython(seed_sequences, unseed_sequences),
    ]
