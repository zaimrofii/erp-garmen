"""Template pertanyaan/jawaban klarifikasi (R.1) — deterministik, tanpa LLM.

Semua string Bahasa Indonesia, tegas, dan stabil agar mudah diuji.
"""

from __future__ import annotations

from typing import Any

#: Batas pilihan yang ditampilkan pada pertanyaan ambigu.
MAX_SHOW = 5


def _attrs_text(attrs: dict[str, Any] | None) -> str:
    if not attrs:
        return ""
    return ", ".join(f"{key}: {value}" for key, value in attrs.items() if value)


def ambiguous_question(
    candidates: list[dict[str, Any]], max_show: int = MAX_SHOW
) -> str:
    """Pertanyaan pilihan untuk status AMBIGUOUS.

    Format::

        Ada 3 yang cocok:
          (1) Kaos Sate Slamet — order: SO-042, tanggal: 15 Okt
          (2) Baju Slametan Anak — order: SO-051, tanggal: 17 Okt
          (3) Pak Slamet — customer: 4 order aktif
        Yang mana?
    """
    if not candidates:
        return "Tidak ada data yang cocok."

    limit = max(1, int(max_show))
    lines = [f"Ada {len(candidates)} yang cocok:"]
    for index, candidate in enumerate(candidates[:limit], start=1):
        label = candidate.get("label", "?")
        attrs = _attrs_text(candidate.get("attrs"))
        lines.append(f"  ({index}) {label}" + (f" — {attrs}" if attrs else ""))

    if len(candidates) > limit:
        lines.append(f"  ... dan {len(candidates) - limit} lainnya")

    lines.append("Yang mana?")
    return "\n".join(lines)


def weak_question(candidate: dict[str, Any]) -> str:
    """Konfirmasi ya/tidak untuk status WEAK (1 kandidat skor rendah)."""
    label = candidate.get("label", "?")
    attrs = _attrs_text(candidate.get("attrs"))
    if attrs:
        return f"Apakah maksud Anda: {label} — {attrs}? (ya/tidak)"
    return f"Apakah maksud Anda: {label}? (ya/tidak)"


def empty_response(entity_label: str, query: str) -> str:
    """Jawaban tegas saat data tidak ada (bukan permintaan maaf)."""
    text = f" untuk '{query}'" if query else ""
    return f"Tidak ada {entity_label}{text} di data saat ini."


def out_of_scope_response() -> str:
    return "Pertanyaan terlalu singkat. Mohon perjelas."


def escalation_response(candidates: list[dict[str, Any]]) -> str:
    """Dipakai setelah `MAX_TURNS` tanpa resolve."""
    lines = ["Saya belum bisa memastikan maksud Anda. Berikut daftar lengkap:"]
    for index, candidate in enumerate(candidates, start=1):
        label = candidate.get("label", "?")
        attrs = _attrs_text(candidate.get("attrs"))
        lines.append(f"  ({index}) {label}" + (f" — {attrs}" if attrs else ""))
    lines.append("Mohon berikan kriteria tambahan (periode, status, dll).")
    return "\n".join(lines)


def all_response(candidates: list[dict[str, Any]]) -> str:
    """Ringkasan deterministik saat user memilih ALL (tanpa LLM)."""
    if not candidates:
        return "Tidak ada data yang cocok."

    lines = [f"Berikut {len(candidates)} data yang cocok:"]
    for index, candidate in enumerate(candidates, start=1):
        label = candidate.get("label", "?")
        attrs = _attrs_text(candidate.get("attrs"))
        lines.append(f"  ({index}) {label}" + (f" — {attrs}" if attrs else ""))
    return "\n".join(lines)


__all__ = (
    "MAX_SHOW",
    "all_response",
    "ambiguous_question",
    "empty_response",
    "escalation_response",
    "out_of_scope_response",
    "weak_question",
)
