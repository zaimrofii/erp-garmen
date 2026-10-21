"""Response synthesizer (G.3) — LLM + context injection, read-only."""

from __future__ import annotations

import json
import re

from ..llm_wrapper.factory import get_llm_provider

SYSTEM_PROMPT = """Kamu adalah asisten Garmen. Jawab pertanyaan
user berdasarkan DATA yang diberikan. JANGAN mengarang data yang
tidak ada. Kalau data tidak cukup, bilang "Data tentang <KONTEKS PERTANYAAN> kosong, tidak cukup untuk
menjawab".

Aturan:
- Bahasa Indonesia, ringkas (maks 300 kata).
- Sebutkan angka spesifik dari data.
- Kalau ada tren naik/turun, sebutkan.
- Kalau user tanya "kenapa", analisa dari data (bandingkan periode,
  WC, line).
- JANGAN menyarankan write action (ubah/tambah/hapus data). Kamu hanya
  baca & analisa.
- JANGAN sebut harga/kredit/pajak kalau user bukan admin/owner/finance.
- JANGAN sebut data produk yang tidak ada di konteks.
- Setiap menyebut entitas, WAJIB pakai field *_name
  (customer_name, product_name, work_center_name, line_name).
  JANGAN sebut ID. Kalau nama kosong, bilang "nama tidak tersedia".
- Kalau data tidak cukup, katakan "Data kosong atau tidak cukup" — JANGAN mengarang.
- Kalau data berisi product_production_count=0 DAN related_orders=[]
  DAN related_bundles=[], jawab: "Produk [nama] belum pernah
  diproduksi (0 order, 0 bundle, 0 produksi)." JANGAN jawab
  "Data tidak cukup" — ini bukan data tidak cukup, ini produk belum
  pernah dipakai.
- Kalau data berisi X dan X kosong, jawab "Tidak ada X" (bukan
  "Data tidak cukup"). Contoh: related_orders kosong →
  "Belum ada order terkait", bukan "Data tidak cukup".
- Kalau user tanya "bagaimana cara..." (how-to), arahkan ke
  halaman/dokumentasi, bukan instruksi eksekusi.
"""

MAX_TOKENS = 500
MAX_ANSWER_CHARS = 5000
WRITE_REJECT_ANSWER = "Maaf, saya tidak bisa menyarankan perubahan data."
EMPTY_ANSWER_FALLBACK = "Maaf, saya tidak bisa menjawab pertanyaan itu."
_WRITE_PATTERN = re.compile(r"\b(UPDATE|DELETE|INSERT|DROP)\s", re.IGNORECASE)
_CONTROL_KEYS = {"message", "context", "intent", "tools"}


def validate_answer(text: str) -> str:
    """Guardrail jawaban LLM: tolak saran write, batasi panjang, fallback kosong."""
    answer = (text or "").strip()
    if not answer:
        return EMPTY_ANSWER_FALLBACK
    if _WRITE_PATTERN.search(answer):
        return WRITE_REJECT_ANSWER
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS] + "..."
    return answer


def _error(error: str, detail: str = "", code: str = "") -> dict:
    payload = {
        "ok": False,
        "error": error,
        "detail": detail,
        "tokens": {"prompt": 0, "completion": 0, "total_cost_usd": 0},
    }
    if code:
        payload["code"] = code
    return payload


def synthesize(message: str, context_data: dict) -> dict:
    """Panggil LLM dengan data konteks → jawaban natural (tidak pernah raise)."""
    question = (message or "").strip()
    if not question:
        return _error("empty_message", "Pertanyaan user kosong.")
    if not isinstance(context_data, dict) or not context_data.get("message"):
        return _error(
            "empty_context",
            "Konteks wajib diisi sebelum memanggil LLM.",
        )

    data_block = {
        key: value for key, value in context_data.items() if key not in _CONTROL_KEYS
    }
    user_prompt = f"""PERTANYAAN USER:
{question}

KONTEKS HALAMAN:
{json.dumps(context_data.get("context", {}), indent=2, default=str)}

DATA DARI SISTEM:
{json.dumps(data_block, indent=2, default=str)}

Jawab pertanyaan user berdasarkan data di atas."""

    try:
        response = get_llm_provider().complete(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=MAX_TOKENS,
        )
    except Exception as exc:
        return _error(
            "llm_failed",
            str(exc),
            code=str(getattr(exc, "code", "llm_error")),
        )

    return {
        "ok": True,
        "answer": validate_answer(response.text),
        "tokens": {
            "prompt": int(response.prompt_tokens or 0),
            "completion": int(response.completion_tokens or 0),
            "total_cost_usd": float(response.total_cost_usd or 0),
        },
        "model": response.model,
        "latency_ms": int(response.latency_ms or 0),
    }


__all__ = (
    "EMPTY_ANSWER_FALLBACK",
    "MAX_ANSWER_CHARS",
    "MAX_TOKENS",
    "SYSTEM_PROMPT",
    "WRITE_REJECT_ANSWER",
    "synthesize",
    "validate_answer",
)
