"""Interface aggregator (compute-only; TIDAK menyimpan).

Storage dipisah (`core/storage.py`) supaya metrik yang sama bisa dihitung
ulang (real-time) atau dibaca dari snapshot (historis) tanpa duplikasi logika.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseAggregator(ABC):
    """Interface compute-only. TIDAK menyimpan (storage terpisah)."""

    @abstractmethod
    def compute(self, filters: dict[str, Any]) -> list[dict]:
        """Set-based aggregation. Return list dict dengan ``key``/``label``/``value``."""
        raise NotImplementedError


__all__ = ("BaseAggregator",)
