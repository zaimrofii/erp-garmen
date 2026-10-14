"""Test ``trace_bridge.reader`` & ``trace_bridge.normalize`` (Django test runner).

Dijalankan lewat ``python manage.py test trace_bridge --verbosity=2`` — karena
itu memakai ``unittest.TestCase`` biasa (bukan pytest fixture) dan tidak butuh
database.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from trace_bridge.normalize import to_spans
from trace_bridge.reader import read_trace


def _write_jsonl(path: Path, entries: list) -> None:
    """Tulis ``entries`` ke ``path`` (dict -> JSON, str ditulis apa adanya)."""
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            if isinstance(entry, str):
                handle.write(entry + "\n")
            else:
                handle.write(json.dumps(entry) + "\n")


class ReadTraceTests(unittest.TestCase):
    """``read_trace`` memfilter per trace id & tahan terhadap baris rusak."""

    def test_read_trace_filters_by_request_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(
                log_dir / "mes.jsonl",
                [
                    {"request_id": "A", "message": "1"},
                    {"request_id": "A", "message": "2"},
                    {"request_id": "A", "message": "3"},
                    {"request_id": "B", "message": "4"},
                    "{ini bukan json }",
                ],
            )

            result = read_trace("A", log_dir)

            self.assertEqual(len(result), 3)
            self.assertTrue(all(row["request_id"] == "A" for row in result))

    def test_read_trace_fallback_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(
                log_dir / "mes.jsonl",
                [
                    {"task_id": "T", "request_id": "-", "message": "1"},
                    {"task_id": "T", "request_id": "-", "message": "2"},
                ],
            )

            result = read_trace("T", log_dir)

            self.assertEqual(len(result), 2)

    def test_read_trace_skips_broken_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            _write_jsonl(
                log_dir / "mes.jsonl",
                [
                    {"request_id": "A"},
                    {"request_id": "A"},
                    "not json at all",
                    {"request_id": "A"},
                ],
            )

            result = read_trace("A", log_dir)

            self.assertEqual(len(result), 3)


class ToSpansTests(unittest.TestCase):
    """``to_spans`` membentuk spans + ringkasan waktu."""

    @staticmethod
    def _rows() -> list[dict]:
        return [
            {
                "timestamp": "2026-01-01T00:00:00.000000+00:00",
                "logger": "alpha",
                "funcName": "start",
                "level": "INFO",
                "message": "start",
            },
            {
                "timestamp": "2026-01-01T00:00:00.100000+00:00",
                "logger": "beta",
                "funcName": "step",
                "level": "INFO",
                "message": "step",
            },
            {
                "timestamp": "2026-01-01T00:00:00.500000+00:00",
                "logger": "gamma",
                "funcName": "boom",
                "level": "ERROR",
                "message": "boom",
            },
        ]

    def test_to_spans_basic(self):
        result = to_spans(self._rows(), "A")

        self.assertEqual(result["trace_id"], "A")
        self.assertEqual(result["duration_ms"], 500)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(len(result["spans"]), 3)
        self.assertEqual(result["spans"][0]["ms"], 0)
        self.assertNotIn("error", result["spans"][0])
        self.assertIn("error", result["spans"][2])
        self.assertEqual(result["spans"][2]["error"], "boom")

    def test_to_spans_empty(self):
        result = to_spans([], "A")

        self.assertEqual(
            result,
            {"trace_id": "A", "duration_ms": 0, "spans": [], "errors": 0},
        )


if __name__ == "__main__":
    unittest.main()
