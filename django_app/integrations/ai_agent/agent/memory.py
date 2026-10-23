"""Memori L3 — ringkas history panjang sebelum dikirim ke LLM."""

from __future__ import annotations

SUMMARY_PREFIX = "Ringkasan percakapan sebelumnya: "


def summarize_history(
    history: list[dict] | None,
    max_turns: int = 10,
    provider=None,
) -> list[dict]:
    """Kembalikan <= max_turns turn terakhir, dengan ringkasan bila lebih.

    Provider bersifat opsional; tanpa provider (atau gagal) history hanya dipotong
    agar loop tetap jalan tanpa biaya tambahan.
    """
    items = [item for item in (history or []) if isinstance(item, dict) and item.get("content")]
    if len(items) <= max_turns:
        return items

    older, recent = items[:-max_turns], items[-max_turns:]
    summary = ""
    if provider is not None:
        transcript = "\n".join(f"{item.get('role')}: {str(item.get('content'))[:300]}" for item in older)
        try:
            response = provider.complete(
                "Ringkas percakapan berikut menjadi 1-2 kalimat padat berbahasa Indonesia.",
                transcript,
                max_tokens=120,
            )
            summary = str(getattr(response, "text", "") or "").strip()
        except Exception:  # noqa: BLE001 - ringkasan gagal tidak boleh menggagalkan chat
            summary = ""
    if not summary:
        summary = f"{len(older)} pesan sebelumnya tidak ditampilkan (ringkasan tidak tersedia)."
    return [{"role": "system", "content": f"{SUMMARY_PREFIX}{summary}"}] + recent


__all__ = ("SUMMARY_PREFIX", "summarize_history")
