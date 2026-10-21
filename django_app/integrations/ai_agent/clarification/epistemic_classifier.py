"""Epistemic classifier (R.1) — label kepastian jawaban, deterministik tanpa LLM.

Kontrak: AI read & propose only (docs/ai/CHAT-CONTRACT.md §9). Klasifikasi ini
murni fungsi data: tidak memanggil LLM, tidak menyentuh DB, tidak menulis state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EpistemicStatus(str, Enum):
    """Tingkat kepastian sebelum jawaban disusun."""

    EXACT = "EXACT"
    AMBIGUOUS = "AMBIGUOUS"
    EMPTY = "EMPTY"
    WEAK = "WEAK"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass
class EpistemicResult:
    """Hasil klasifikasi + kandidat yang relevan (sudah dipotong bila perlu)."""

    status: EpistemicStatus
    candidates: list[dict[str, Any]] = field(default_factory=list)
    question: str | None = None
    reason: str | None = None


#: Query di bawah panjang ini tidak layak diproses (OUT_OF_SCOPE).
MIN_QUERY_LENGTH = 2


def _same_answer(candidates: list[dict[str, Any]]) -> bool:
    """True bila SEMUA kandidat punya `answer_hash` sama (bukan sebagian)."""
    hashes = {candidate.get("answer_hash") for candidate in candidates}
    return len(hashes) == 1 and None not in hashes and "" not in hashes


def classify(
    candidates: list[dict[str, Any]],
    query: str,
    min_exact_score: float = 0.85,
    max_ambig: int = 5,
    is_aggregate_query: bool = False,
) -> EpistemicResult:
    """Klasifikasikan kandidat terhadap query.

    Aturan (deterministik, "ask only when it changes the answer"):

    - query < 2 karakter → OUT_OF_SCOPE
    - `is_aggregate_query=True` → EXACT (agregat dijawab metrik, bukan pilih)
    - 0 kandidat → EMPTY (jawaban tegas, bukan "maaf")
    - 1 kandidat skor >= `min_exact_score` → EXACT
    - 1 kandidat skor < `min_exact_score` → WEAK (minta konfirmasi ya/tidak)
    - > 1 kandidat dengan `answer_hash` sama semua → EXACT (tidak perlu tanya)
    - > 1 kandidat berbeda → AMBIGUOUS, kandidat dipotong `max_ambig`
    """
    text = (query or "").strip()
    if len(text) < MIN_QUERY_LENGTH:
        return EpistemicResult(
            status=EpistemicStatus.OUT_OF_SCOPE,
            reason="Query terlalu pendek",
        )

    # Fix #13B — pertanyaan agregat tidak pernah memicu klarifikasi.
    if is_aggregate_query:
        return EpistemicResult(
            status=EpistemicStatus.EXACT,
            candidates=list(candidates),
            question=None,
            reason="Query agregat (tidak butuh klarifikasi)",
        )

    if not candidates:
        return EpistemicResult(
            status=EpistemicStatus.EMPTY,
            reason="Tidak ada data cocok",
        )

    if len(candidates) == 1:
        score = float(candidates[0].get("score", 1.0) or 0.0)
        if score >= min_exact_score:
            return EpistemicResult(
                status=EpistemicStatus.EXACT,
                candidates=list(candidates),
                reason="1 kandidat, skor tinggi",
            )
        return EpistemicResult(
            status=EpistemicStatus.WEAK,
            candidates=list(candidates),
            reason="1 kandidat, skor rendah",
        )

    if _same_answer(candidates):
        return EpistemicResult(
            status=EpistemicStatus.EXACT,
            candidates=list(candidates),
            reason="Semua kandidat jawaban sama",
        )

    limit = max(1, int(max_ambig))
    return EpistemicResult(
        status=EpistemicStatus.AMBIGUOUS,
        candidates=list(candidates[:limit]),
        reason=f"{len(candidates)} kandidat berbeda",
    )


__all__ = (
    "EpistemicResult",
    "EpistemicStatus",
    "MIN_QUERY_LENGTH",
    "classify",
)
