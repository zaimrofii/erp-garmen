#!/usr/bin/env python
"""Utility CLI Django untuk project `garmen`."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Jalankan perintah administratif Django."""
    # Root project (berisi `config/`, `apps_industry/`, `integrations/`,
    # `master/`) dipastikan ada di sys.path supaya perintah seperti
    # `python manage.py check` jalan dari cwd manapun.
    base_dir = Path(__file__).resolve().parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover - guard untuk venv salah
        raise ImportError(
            "Tidak bisa import Django. Pastikan dependency sudah diinstall "
            "(pip install -r requirements.txt) dan virtualenv aktif."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
        