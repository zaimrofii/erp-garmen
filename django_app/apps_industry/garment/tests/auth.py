"""Helper auth untuk test (FASE 4.1 hardening — endpoint aksi kini `IsAuthenticated`).

`POST /api/v1/<industry>/<resource>/<id>/<action>/` berubah dari `AllowAny` →
`IsAuthenticated`; test yang memanggilnya perlu klien terautentikasi. Nama file
tidak diawali `test`, jadi tidak dipungut test runner.

`force_authenticate` dipakai (bukan `force_login`) supaya konsisten dengan test
endpoint `IsAuthenticated` yang sudah ada (mis. `test_e2e_bundle_flow`) dan tidak
memerlukan CSRF cookie.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

__all__ = ("authenticate", "make_user")

#: Username default user test (dibuat ulang per test — transaksi TestCase rollback).
DEFAULT_USERNAME = "sim-auth"


def make_user(username: str | None = None, **kwargs):
    """User Django untuk test (idempotent per transaksi)."""
    return get_user_model().objects.get_or_create(
        username=username or DEFAULT_USERNAME, defaults=kwargs
    )[0]


def authenticate(client, username: str | None = None):
    """Autentikasi `client` (APIClient) lewat `force_authenticate`; return user."""
    user = make_user(username)
    client.force_authenticate(user)
    return user
