"""Guard contoh untuk test engine (BUKAN aturan bisnis).

Guard nyata nanti tinggal di app domain (mis.
`apps_industry/garment/services/guards.py`); file ini hanya dummy supaya
`Transition.guard_path` benar-benar di-import lewat `import_string`.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError


def qty_positive(context):
    """Guard contoh bentuk `bool`: `context["qty"]` harus > 0."""
    return int(context.get("qty", 0)) > 0


def reject_with_message(context):
    """Guard contoh bentuk `raise ValidationError` (pesan dipakai sebagai alasan)."""
    raise ValidationError(f"guard contoh menolak: {context!r}")


def allow_with_reason(context):
    """Guard contoh bentuk `(bool, alasan)`."""
    return True, "dizinkan guard contoh"
