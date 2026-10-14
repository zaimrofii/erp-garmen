"""Service auth tingkat core (F6.1) — helper yang dipakai endpoint `/api/v1/auth/*`.

Isi sengaja kecil dan **tanpa I/O**: hanya aturan "siapa yang dianggap admin".
Diletakkan di `core.auth` (bukan di `apps_industry.garment`) supaya bisa dipakai
endpoint core mana pun tanpa membuat core bergantung pada app industri.

Catatan: logika yang sama masih ada di
`apps_industry/garment/api/settings/views.py` (`_is_admin`/`_require_admin`,
F5.4.1). Duplikasi ini disengaja untuk sekarang — memindahkan helper di sana
berarti menyentuh endpoint B26/B27/B28 yang sudah stabil; penyatuannya bisa
dilakukan di fase refactor, dan mulai sekarang kode baru memakai modul ini.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

__all__ = ("ADMIN_ROLE_CODES", "is_admin_user", "require_admin")

#: Kode role yang dianggap "admin" (UPPERCASE — hasil migrasi `core_auth.0002`).
ADMIN_ROLE_CODES = ("ADMIN", "OWNER")


def is_admin_user(user) -> bool:
    """True untuk superuser **atau** user ber-role ``ADMIN``/``OWNER``.

    ``is_superuser`` dihitung admin supaya akun hasil ``createsuperuser`` (yang
    biasanya belum punya ``role``) tetap bisa mengelola user lain.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    role = getattr(user, "role", None)
    return role is not None and str(role.code).strip().upper() in ADMIN_ROLE_CODES


def require_admin(request) -> None:
    """Raise ``PermissionDenied`` (403) kalau pemanggil bukan admin/owner."""
    if not is_admin_user(request.user):
        raise PermissionDenied(
            "Hanya user dengan role ADMIN/OWNER yang boleh mengakses resource ini."
        )
