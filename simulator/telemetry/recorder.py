"""Perekam telemetry run → file JSONL append-only — fase M2.

Setiap keputusan agent (scripted maupun LLM) dicatat satu baris JSON agar bisa
di-replay / dijadikan regression test (prinsip "output jujur" di
``konsep-dasar.md``). Perekam **tidak menyimpan state** selain handle file yang
dibuka saat run — tidak ada DB, tidak ada buffer di memori.

Format baris: satu objek JSON, ``ensure_ascii=False`` (teks Indonesia tetap
terbaca), tanpa indent, dengan ``timestamp`` (UTC ISO-8601) sebagai **kolom
pertama**.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

__all__ = ("DecisionSource", "Recorder")

#: Sumber keputusan yang sah — scripted (deterministik) atau llm (agen).
DecisionSource = Literal["scripted", "llm"]
_VALID_SOURCES: tuple[str, ...] = ("scripted", "llm")


class Recorder:
    """Tulis jejak telemetry ke file ``.jsonl`` (append-only, context manager)."""

    def __init__(
        self,
        scenario_name: str,
        output_pattern: str = "runs/{scenario}_{timestamp}.jsonl",
    ) -> None:
        self.scenario_name = scenario_name
        self.output_pattern = output_pattern
        self.started_at = datetime.now(timezone.utc)
        stamp = self.started_at.strftime("%Y%m%dT%H%M%S%fZ")
        #: Path file run (dir induk dibuat otomatis bila belum ada).
        self.path = Path(output_pattern.format(scenario=scenario_name, timestamp=stamp))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")

    # ------------------------------------------------------------------ tulis
    @staticmethod
    def _now() -> str:
        """Timestamp UTC ISO-8601 untuk sebuah baris."""

        return datetime.now(timezone.utc).isoformat()

    def _write(self, obj: dict) -> None:
        self._fh.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def record(
        self,
        agent_id: str,
        endpoint: str,
        method: str,
        payload: Optional[dict],
        status_code: Optional[int],
        latency_ms: float,
        trace_id: Optional[str],
        decision_source: DecisionSource,
    ) -> None:
        """Catat satu pemanggilan API.

        ``decision_source`` wajib ``"scripted"`` atau ``"llm"`` — selain itu
        ``ValueError`` (fail-closed, supaya typo tidak lolos diam-diam).
        """

        if decision_source not in _VALID_SOURCES:
            raise ValueError(
                "decision_source harus 'scripted' atau 'llm', "
                f"dapat: {decision_source!r}"
            )
        self._write(
            {
                "timestamp": self._now(),  # kolom pertama
                "agent_id": agent_id,
                "endpoint": endpoint,
                "method": method,
                "payload": payload,
                "status_code": status_code,
                "latency_ms": latency_ms,
                "trace_id": trace_id,
                "decision_source": decision_source,
            }
        )

    def record_error(
        self,
        agent_id: str,
        endpoint: str,
        error: str,
        trace_id: Optional[str],
    ) -> None:
        """Catat kegagalan (exception) saat memanggil API."""

        self._write(
            {
                "timestamp": self._now(),  # kolom pertama
                "agent_id": agent_id,
                "endpoint": endpoint,
                "error": error,
                "trace_id": trace_id,
            }
        )

    # ------------------------------------------------------------- daur hidup
    def flush(self) -> None:
        """Paksa tulis buffer ke disk."""

        self._fh.flush()

    def close(self) -> None:
        """Flush lalu tutup file (aman dipanggil berkali-kali)."""

        if not self._fh.closed:
            self._fh.flush()
            self._fh.close()

    def __enter__(self) -> "Recorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
