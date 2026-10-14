"""Routing WebSocket event bus (Fase E).

Satu endpoint: ``ws/events/`` (dengan trailing slash, sama seperti kontrak §4).
Didaftarkan di `config/asgi.py` lewat `ProtocolTypeRouter` — jadi path ini TIDAK
muncul di `ROOT_URLCONF`/OpenAPI (memang beda protokol).
"""

from __future__ import annotations

from django.urls import re_path

from .consumers import EventConsumer

__all__ = ("websocket_urlpatterns",)

websocket_urlpatterns = [
    re_path(r"^ws/events/$", EventConsumer.as_asgi()),
]
