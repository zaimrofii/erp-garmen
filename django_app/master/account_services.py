"""Service master **Account** (chart of accounts) — H3.4, **pull-only**.

H3.4 (Journal Entry manual) membutuhkan daftar akun untuk dropdown form; akun
di-*pull* dari Odoo ``account.account`` (`erp_sync.sync_master_accounts`) dan
**tidak pernah** di-push kembali (chart of accounts = wewenang akuntan di Odoo).

Modul ini hanya menyediakan **serialisasi + baca** (read-only): tidak ada
create/update/delete — sama seperti master Tax setelah H3.6 untuk jalur baca.
"""

from __future__ import annotations

from master.models import Account

__all__ = ("account_row", "list_queryset")


def _iso(value) -> str | None:
    """ISO-8601 atau ``None`` (datetime kosong)."""
    return value.isoformat() if value else None


def list_queryset():
    """Query dasar akun (urut kode) — dipakai view list."""
    return Account.objects.all().order_by("code")


def account_row(account: Account) -> dict:
    """Baris akun untuk API (kontrak H3.4 `GET /api/v1/master/accounts/`)."""
    return {
        "id": account.pk,
        "odoo_id": account.odoo_id,
        "code": account.code,
        "name": account.name,
        "account_type": account.account_type,
        "account_type_label": (
            Account.AccountType(account.account_type).label
            if account.account_type in Account.AccountType.values
            else account.account_type
        ),
        "reconcile": account.reconcile,
        "active": account.is_active,
    }
