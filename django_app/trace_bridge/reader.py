"""Reader log JSONL untuk Trace Bridge (murni stdlib).

Membaca file log rotasi (``mes.jsonl`` + ``mes.jsonl.1 .. .N``) dari yang
**terbaru** lebih dulu — dan dari **baris TERAKHIR** tiap file (tail), karena
baris terbaru selalu ada di ujung file. Lalu memfilter baris milik satu trace
(``request_id`` atau ``task_id``). Dipakai untuk merangkai jejak satu request
HTTP -> task Celery tanpa perlu mesin log eksternal.

Catatan PRA-0A.2: versi lama membaca 5000 baris PERTAMA file terbaru. Setelah
``mes.jsonl`` tumbuh > 5000 baris, baris trace terbaru tidak pernah terbaca
(test e2e jadi "flake" yang sebenarnya bug deterministik). Sekarang dibaca
dari ekor file.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Iterator
from pathlib import Path

__all__ = ("read_trace",)

logger = logging.getLogger(__name__)

#: Ukuran blok baca mundur untuk tail (64 KiB) — cukup besar agar file 10 MB
#: hanya butuh beberapa seek.
_TAIL_BLOCK = 64 * 1024


def _tail_lines(path: Path, max_lines: int) -> Iterator[str]:
    """Hasilkan maks ``max_lines`` baris **TERAKHIR** ``path`` (paling baru dulu).

    Membaca mundur per blok (``seek`` dari EOF) supaya file besar tidak dibaca
    penuh. Baris dikembalikan urut TERBARU -> terlama, sesuai docstring
    :func:`read_trace`.
    """
    if max_lines <= 0:
        return

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            data = b""
            while position > 0 and data.count(b"\n") <= max_lines:
                read_size = min(_TAIL_BLOCK, position)
                position -= read_size
                handle.seek(position)
                data = handle.read(read_size) + data
    except OSError as exc:
        logger.warning("trace_bridge: gagal membaca %s: %s", path, exc)
        return

    for raw in reversed(data.splitlines()[-max_lines:]):
        yield raw.decode("utf-8", "replace") + "\n"


def _iter_lines(paths: Iterable[Path], max_lines: int) -> Iterator[str]:
    """Hasilkan baris dari ``paths`` (urut terbaru dulu), maks ``max_lines``.

    Tiap file dibaca dari EKOR (lihat :func:`_tail_lines`) lalu berhenti lebih
    awal begitu ``max_lines`` baris sudah dihasilkan. File yang tidak ada /
    tidak bisa dibaca dilewati (dicatat WARNING), bukan melempar exception.
    """
    produced = 0
    for path in paths:
        if produced >= max_lines:
            return
        # File rotasi yang belum ada (mis. `mes.jsonl.1` sebelum rotasi pertama)
        # wajar untuk dilewati TANPA noise; hanya error baca nyata yang di-WARNING.
        if not path.is_file():
            continue
        for line in _tail_lines(path, max_lines - produced):
            produced += 1
            yield line


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
