"""Intent classifier (G.2) — LLM classify → intent terbatas."""

from __future__ import annotations

from ..llm_wrapper.factory import get_llm_provider
from .text_normalizer import normalize

VALID_INTENTS = {
    "ANALYTICS_QUERY",
    "DATA_LOOKUP",
    "DIAGNOSTIC",
    "SUGGEST_ACTION",
    "GENERAL_CHAT",
    "UNKNOWN",
}

SYSTEM_PROMPT = "Kamu adalah classifier intent. Jawab singkat."

INTENT_PROMPT = """Klasifikasikan pertanyaan user ke salah satu intent:
- ANALYTICS_QUERY: pertanyaan tentang metrik produksi (scrap, rework,
  lead time, OEE, dll)
- DATA_LOOKUP: pertanyaan tentang data spesifik (produk, order,
  bundle, invoice)
- DIAGNOSTIC: pertanyaan "kenapa X terjadi?" (analisis penyebab)
- SUGGEST_ACTION: pertanyaan "apa yang harus saya lakukan?",
  "bagaimana cara memperbaiki?", "usulkan aksi", "rekomendasi"
- GENERAL_CHAT: sapaan, pertanyaan umum
- UNKNOWN: tidak bisa diklasifikasi

Jawab HANYA dengan nama intent (satu kata). Jangan tambahkan
penjelasan.

Pertanyaan: {message}
Intent:"""


def classify(message: str) -> dict:
    """Return `{"intent", "confidence", "tokens"}`; tidak pernah raise."""
    normalized = normalize(message)["normalized"] or (message or "").strip()
    prompt = INTENT_PROMPT.format(message=normalized)
    try:
        response = get_llm_provider().complete(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=prompt,
            max_tokens=10,
        )
    except Exception:
        return {"intent": "UNKNOWN", "confidence": 0.0, "tokens": 0}

    token = (response.text or "").strip().split()
    intent = token[0].strip(".,:;!?\"'`").upper() if token else ""
    if intent not in VALID_INTENTS:
        intent = "UNKNOWN"

    return {
        "intent": intent,
        "confidence": 0.8 if intent != "UNKNOWN" else 0.0,
        "tokens": int(response.prompt_tokens or 0) + int(response.completion_tokens or 0),
        "cost_usd": float(getattr(response, "total_cost_usd", 0) or 0),
    }


def is_suggest_action(intent: str) -> bool:
    """True bila intent meminta usulan aksi (HITL)."""
    return str(intent or "").strip().upper() == "SUGGEST_ACTION"


__all__ = ("VALID_INTENTS", "classify", "is_suggest_action")
