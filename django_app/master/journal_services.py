"""Service master **Journal** baca-saja — H3.4.

``master.Journal`` sudah ada sejak I1 (mirror ``account.journal``, di-pull
`erp_sync.sync_master_journals`). H3.4 menambah **field aditif** ``journal_type``
(hasil pull ``account.journal.type``) dan endpoint **read-only**
``GET /api/v1/master/journals/`` supaya form Journal Entry bisa menampilkan
pilihan journal **general** (keputusan STEP 0 H3.4).

Tidak ada operasi tulis: journal MES = mirror Odoo (pola Account/Tax read-only).
"""

from __future__ import annotations

from master.models import Journal

__all__ = ("journal_row", "list_queryset")


def list_queryset():
    """Query dasar journal (urut kode) — dipakai view list."""
    return Journal.objects.all().order_by("code")


def journal_row(journal: Journal) -> dict:
    """Baris journal untuk API (kontrak H3.4 `GET /api/v1/master/journals/`)."""
    journal_type = journal.journal_type or ""
    return {
        "id": journal.pk,
        "odoo_id": journal.odoo_id,
        "code": journal.code,
        "name": journal.name,
        "journal_type": journal_type,
        "journal_type_label": (
            Journal.JournalType(journal_type).label
            if journal_type in Journal.JournalType.values
            else journal_type
        ),
        "is_general": journal_type == Journal.JournalType.GENERAL.value,
        "active": journal.is_active,
    }
