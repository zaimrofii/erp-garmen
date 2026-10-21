"""Template pertanyaan/jawaban klarifikasi (R.1) — deterministik, tanpa LLM.

Semua string Bahasa Indonesia, tegas, dan stabil agar mudah diuji.
"""

from __future__ import annotations

from typing import Any

#: Batas pilihan yang ditampilkan pada pertanyaan ambigu.
MAX_SHOW = 5


#: Nilai attrs yang dianggap tidak informatif (Fix #15).
PLACEHOLDER_VALUES = frozenset(
    {"harga belum diisi", "tanpa kategori", "-", ""}
)


def _has_evidence(candidate: dict[str, Any]) -> bool:
    """True bila kandidat punya minimal 1 attrs pembeda yang bermakna."""
    attrs = candidate.get("attrs") or {}
    hidden = {"kode", "code", "id"}
    return any(
        str(value).strip()
        and str(value).strip().lower() not in PLACEHOLDER_VALUES
        for key, value in attrs.items()
        if str(key).strip().lower() not in hidden
    )


def _attrs_text(attrs: dict[str, Any] | None) -> str:
    """Gabungkan attrs menjadi teks bukti; SKIP kode/id (Fix #14/#15).

    Harga ditampilkan apa adanya (``Rp50.000``), atribut lain diberi label
    (``kategori Kaos``, ``status SEWING``) agar mudah dibaca owner/operator.
    Placeholder (``Rp0``/kategori kosong) tidak ditampilkan.
    """
    if not attrs:
        return ""

    hidden = {"kode", "code", "id"}
    value_only = {"harga", "price"}
    parts = []
    for key, value in attrs.items():
        if not value:
            continue
        label = str(key).strip().lower()
        if label in hidden:
            continue
        if str(value).strip().lower() in PLACEHOLDER_VALUES:
            continue
        parts.append(str(value) if label in value_only else f"{label} {value}")
    return ", ".join(parts)


def ambiguous_question(
    candidates: list[dict[str, Any]], max_show: int = MAX_SHOW
) -> str:
    """Pertanyaan pilihan untuk status AMBIGUOUS (berbasis bukti).

    Format (label sama)::

        Ada 2 Kaos Polos:
          (1) Rp50.000, kategori Kaos
          (2) Rp75.000, kategori Kaos
        Yang mana?

    Format (label berbeda)::

        Ada 2 yang cocok:
          (1) Kaos Polos Cotton — Rp50.000, kategori Kaos
          (2) Kaos Polos Premium — Rp75.000, kategori Kaos
        Yang mana?
    """
    if not candidates:
        return "Tidak ada data yang cocok."

    limit = max(1, int(max_show))

    # Fix #15C — semua attrs kosong/placeholder: fallback jujur + catatan.
    if not any(_has_evidence(candidate) for candidate in candidates):
        lines = [f"Ada {len(candidates)} yang cocok:"]
        for index, candidate in enumerate(candidates[:limit], start=1):
            lines.append(f"  ({index}) {candidate.get('label', '?')}")
        lines.append("")
        lines.append(
            "Catatan: data pembeda (harga, kategori) belum lengkap. "
            "Mohon periksa halaman produk."
        )
        lines.append("Yang mana?")
        return "\n".join(lines)

    labels = [str(candidate.get("label", "?")) for candidate in candidates]
    same_label = len(set(labels)) == 1

    if same_label:
        header = f"Ada {len(candidates)} {labels[0]}:"
    else:
        header = f"Ada {len(candidates)} yang cocok:"

    lines = [header]
    for index, candidate in enumerate(candidates[:limit], start=1):
        label = str(candidate.get("label", "?"))
        attrs = _attrs_text(candidate.get("attrs"))
        if same_label and attrs:
            lines.append(f"  ({index}) {attrs}")
        elif attrs:
            lines.append(f"  ({index}) {label} — {attrs}")
        else:
            lines.append(f"  ({index}) {label}")

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
