"""Normalisasi baris log trace menjadi spans + ringkasan waktu (murni stdlib).

Input: ``list[dict]`` hasil :func:`trace_bridge.reader.read_trace` (baris log
dengan ``timestamp``/``logger``/``funcName``/``level``/``message``). Output:
dict kontrak ``{trace_id, duration_ms, spans, errors}`` yang siap dikirim ke UI
timeline.
"""

from __future__ import annotations

from datetime import datetime

__all__ = ("to_spans",)

#: Level yang dianggap error (nilainya diisi ke ``span["error"]``).
_ERROR_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})


def _parse_ts(iso: str) -> datetime:
    """Parse timestamp ISO-8601 (dengan offset timezone) menjadi ``datetime``."""
    return datetime.fromisoformat(iso)


def _to_ms(iso_a: str, iso_b: str) -> int:
    """Selisih ``iso_b - iso_a`` dalam milidetik (dibulatkan, ``int``)."""
    delta = _parse_ts(iso_b) - _parse_ts(iso_a)
    return int(delta.total_seconds() * 1000)


def to_spans(rows: list[dict], trace_id: str, max_spans: int = 50) -> dict:
    """Ubah ``rows`` menjadi ``{trace_id, duration_ms, spans, errors}``.

    Aturan:

    * ``spans`` diurutkan naik berdasarkan ``timestamp`` (string compare cukup);
    * ``ms`` tiap span = selisih ``timestamp`` dengan baris sebelumnya
      (baris pertama = 0);
    * span diberi key ``error`` (= ``message``) kalau ``level`` termasuk
      WARNING/ERROR/CRITICAL **atau** baris punya key ``error``; kalau tidak,
      key ``error`` tidak ada;
    * ``duration_ms`` = ts terakhir - ts pertama (ms, int) dari **semua** baris;
    * ``errors`` = jumlah span (yang dikembalikan) dengan key ``error``;
    * kalau ``len(rows) > max_spans`` -> dipotong ke ``max_spans`` pertama
      (``duration_ms`` tetap dihitung dari semua baris).
    """
    ordered = sorted(rows, key=lambda row: row.get("timestamp") or "")
    if not ordered:
        return {"trace_id": trace_id, "duration_ms": 0, "spans": [], "errors": 0}

    duration_ms = _to_ms(ordered[0]["timestamp"], ordered[-1]["timestamp"])

    spans: list[dict] = []
    previous_ts: str | None = None
    for row in ordered:
        current_ts = row.get("timestamp")
        ms = 0 if previous_ts is None else _to_ms(previous_ts, current_ts)
        previous_ts = current_ts

        span: dict = {
            "name": f"{row.get('logger', '?')}:{row.get('funcName', '?')}",
            "ms": ms,
        }
        level = str(row.get("level") or "").upper()
        if level in _ERROR_LEVELS or "error" in row:
            span["error"] = row.get("message", "")
        spans.append(span)

    spans = spans[:max_spans]
    errors = sum(1 for span in spans if "error" in span)
    return {
        "trace_id": trace_id,
        "duration_ms": duration_ms,
        "spans": spans,
        "errors": errors,
    }
