"""WSGI entrypoint project `garmen` (dipakai gunicorn di production)."""

import os
import sys
from pathlib import Path

from django.core.wsgi import get_wsgi_application

# Root project (berisi `config/`, `apps_industry/`, `integrations/`,
# `master/`) dipastikan ada di sys.path supaya `config.settings` dan
# app di folder baru bisa di-import dari cwd manapun.
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()

