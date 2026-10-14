"""ASGI entrypoint project `garmen` — HTTP + WebSocket (Channels, Fase E).

    * ``http``      -> aplikasi Django biasa (DRF, admin, docs).
    * ``websocket`` -> ``AuthMiddlewareStack`` + ``core.event_bus.routing``
      (path ``ws://<host>/ws/events/``).

Catatan urutan (WAJIB): `get_asgi_application()` dipanggil **sebelum** modul yang
menyentuh ORM (`core.event_bus.routing`) diimpor — sesuai panduan Channels,
kalau dibalik import app code terjadi sebelum app registry siap.

Jalur HTTP tetap dijaga: kalau `daphne`/`channels` tidak terpasang, ASGI app
jatuh ke Django murni (log warning) sehingga HTTP tidak ikut mati hanya karena
fitur real-time belum tersedia. Menjalankan server: `manage.py runserver`
(Daphne mengambil alih karena ia ada paling depan di INSTALLED_APPS) atau
`daphne config.asgi:application`.
"""

import logging
import os
import sys
from pathlib import Path

from django.core.asgi import get_asgi_application

logger = logging.getLogger(__name__)

# Root project (berisi `config/`, `apps_industry/`, `integrations/`,
# `master/`) dipastikan ada di sys.path supaya `config.settings` dan
# app di folder baru bisa di-import dari cwd manapun.
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# HTTP dulu (sekaligus django.setup() + mengisi app registry).
django_asgi_app = get_asgi_application()

try:
    from channels.auth import AuthMiddlewareStack
    from channels.routing import ProtocolTypeRouter, URLRouter

    from core.event_bus.routing import websocket_urlpatterns
except ModuleNotFoundError:  # pragma: no cover - environment tanpa channels
    logger.warning(
        "channels/daphne tidak terpasang -> WebSocket dinonaktifkan, "
        "hanya HTTP yang dilayani (lihat requirements.txt)."
    )
    application = django_asgi_app
else:
    application = ProtocolTypeRouter(
        {
            "http": django_asgi_app,
            "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
        }
    )


# Root project (berisi `config/`, `apps_industry/`, `integrations/`,
# `master/`) dipastikan ada di sys.path supaya `config.settings` dan
# app di folder baru bisa di-import dari cwd manapun.
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

