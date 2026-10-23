"""Memori L3 — ringkas history panjang sebelum dikirim ke LLM (dengan cache)."""

from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

SUMMARY_PREFIX = "Ringkasan percakapan sebelumnya: "
CACHE_TTL_SECONDS = 600


def _summary_cache_key(conversation_id: str, older: list[dict]) -> str:
    blob = json.dumps(older, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return f"summary:{conversation_id or 'anon'}:{digest}"


def summarize_history(
    history: list[dict] | None,
    max_turns: int = 10,
    provider=None,
    conversation_id: str = "",
) -> list[dict]:
    """Kembalikan <= max_turns turn terakhir, dengan ringkasan (cached) bila lebih.

    Ringkasan di-cache 10 menit per conversation + hash turn lama, sehingga turn
    baru tidak memicu panggilan LLM ulang selama bagian lama tidak berubah.
    """
    items = [item for item in (history or []) if isinstance(item, dict) and item.get("content")]
    if len(items) <= max_turns:
        return items

    older, recent = items[:-max_turns], items[-max_turns:]
    cache_key = _summary_cache_key(conversation_id, older)
    summary = cache.get(cache_key) or ""

    if not summary and provider is not None:
        transcript = "\n".join(
            f"{item.get('role')}: {str(item.get('content'))[:300]}" for item in older
        )
        try:
            response = provider.complete(
                "Ringkas percakapan berikut menjadi 1-2 kalimat padat berbahasa Indonesia.",
                transcript,
                max_tokens=120,
            )
            summary = str(getattr(response, "text", "") or "").strip()
            if summary:
                cache.set(cache_key, summary, CACHE_TTL_SECONDS)
        except Exception:  # noqa: BLE001 - ringkasan gagal tidak boleh menggagalkan chat
            summary = ""

    if not summary:
        summary = f"{len(older)} pesan sebelumnya tidak ditampilkan (ringkasan tidak tersedia)."
    return [{"role": "system", "content": f"{SUMMARY_PREFIX}{summary}"}] + recent


__all__ = ("CACHE_TTL_SECONDS", "SUMMARY_PREFIX", "summarize_history")

