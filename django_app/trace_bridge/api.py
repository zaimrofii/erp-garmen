"""FastAPI trace bridge — satu endpoint untuk membaca jejak log satu request/task.

``GET /_ai/trace/{trace_id}`` membaca log JSONL (via :mod:`trace_bridge.reader`)
lalu mengembalikan spans (via :mod:`trace_bridge.normalize`). Untuk pemakaian
lokal: tanpa auth, tanpa CORS. Konfigurasi diambil dari ``config.yaml`` di
folder ini dan bisa di-override lewat env ``TRACE_BRIDGE_<KEY>`` (huruf besar,
mis. ``TRACE_BRIDGE_PORT=9000``).
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException

from trace_bridge.normalize import to_spans
from trace_bridge.reader import read_trace

#: Lokasi ``config.yaml`` — relatif ke file ini.
CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"

#: Prefiks env override (mis. ``TRACE_BRIDGE_PORT``).
ENV_PREFIX = "TRACE_BRIDGE_"

#: Key yang nilainya angka -> dipaksa ``int`` setelah override env (string).
_INT_KEYS = ("max_backups", "max_spans", "max_lines", "port")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Baca ``config.yaml`` lalu override dengan env ``TRACE_BRIDGE_<KEY>``.

    Nilai env (kalau ada) dipakai apa adanya; kalau tidak ada, nilai yaml yang
    dipakai. Key angka di-``int``-kan supaya aman dipakai untuk perhitungan.
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        config: dict = yaml.safe_load(handle) or {}
    for key in list(config):
        env_value = os.environ.get(ENV_PREFIX + key.upper())
        if env_value is not None:
            config[key] = env_value
    for key in _INT_KEYS:
        if key in config:
            config[key] = int(config[key])
    return config


cfg = load_config()

app = FastAPI(title="Trace Bridge", version="0.1.0")


@app.get("/_ai/trace/{trace_id}")
def get_trace(trace_id: str) -> dict:
    """Kembalikan spans satu ``trace_id``; 404 kalau tidak ada baris cocok."""
    rows = read_trace(
        trace_id,
        Path(cfg["log_dir"]),
        basename=cfg["log_basename"],
        max_backups=cfg["max_backups"],
        max_lines=cfg["max_lines"],
    )
    if not rows:
        raise HTTPException(status_code=404, detail="trace not found")
    return to_spans(rows, trace_id, max_spans=cfg["max_spans"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=cfg["host"], port=cfg["port"], log_level="warning")
