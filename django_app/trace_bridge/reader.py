"""Reader log JSONL untuk Trace Bridge (murni stdlib).

Membaca file log rotasi (``mes.jsonl`` + ``mes.jsonl.1 .. .N``) dari yang
**terbaru** lebih dulu, lalu memfilter baris milik satu trace (``request_id``
atau ``task_id``). Dipakai untuk merangkai jejak satu request HTTP -> task
Celery tanpa perlu mesin log eksternal.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = ("read_trace",)

logger = logging.getLogger(__name__)


def _iter_lines(paths: Iterable[Path], max_lines: int) -> Iterator[str]:
    """Hasilkan baris mentah dari ``paths`` (urut terbaru dulu), maks ``max_lines``.

    Berhenti lebih awal begitu ``max_lines`` baris sudah dihasilkan supaya file
    log besar tidak dibaca penuh. File yang tidak ada / tidak bisa dibaca
    dilewati (dicatat WARNING), bukan melempar exception.
    """
    produced = 0
    for path in paths:
        if produced >= max_lines:
            return
        # File rotasi yang belum ada (mis. `mes.jsonl.1` sebelum rotasi pertama)
        # wajar untuk dilewati TANPA noise; hanya error baca nyata yang di-WARNING.
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if produced >= max_lines:
                        return
                    produced += 1
                    yield line
        except OSError as exc:
            logger.warning("trace_bridge: gagal membaca %s: %s", path, exc)


def _matches(row: dict, trace_id: str) -> bool:
    """True kalau ``row`` milik ``trace_id`` (``request_id`` atau ``task_id``)."""
    return row.get("request_id") == trace_id or row.get("task_id") == trace_id


def read_trace(
    trace_id: str,
    log_dir: Path,
    basename: str = "mes.jsonl",
    max_backups: int = 5,
    max_lines: int = 5000,
) -> list[dict]:
    """Kumpulkan baris log milik ``trace_id`` dari ``log_dir``.

    Urutan file: ``basename`` (terbaru) lalu ``basename.1`` .. ``basename.N``
    (``N = max_backups``). Baris rusak (bukan JSON) dilewati. Hasil dikembalikan
    sesuai urutan baca (paling baru dulu).
    """
    directory = Path(log_dir)
    paths = [directory / basename]
    paths.extend(
        directory / f"{basename}.{index}" for index in range(1, max_backups + 1)
    )

    matched: list[dict] = []
    for raw in _iter_lines(paths, max_lines):
        text = raw.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            logger.warning("trace_bridge: baris rusak dilewati di %s.", directory)
            continue
        if isinstance(row, dict) and _matches(row, trace_id):
            matched.append(row)
    return matched
