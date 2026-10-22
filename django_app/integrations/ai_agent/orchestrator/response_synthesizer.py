"""Response synthesizer (G.3) — LLM + context injection, read-only."""

from __future__ import annotations

import json
import re

from ..clarification import epistemic_classifier, pending_state, templates
from ..llm_wrapper.factory import get_llm_provider
from . import chart_builder

SYSTEM_PROMPT = """Kamu adalah asisten MES Garmen yang ramah dan praktis. Jawab berdasarkan DATA yang diberikan.

ATURAN BAHASA:
- Bahasa Indonesia sederhana, seperti menjelaskan ke teman.
- Angka dibulatkan: "21%" (bukan "21.0%"), "naik 10x lipat" (bukan "dari 1.59% ke 21.0%").
- Fokus: APA masalahnya, KENAPA, APA yang harus dilakukan.
- Maks 5 kalimat per paragraf; gunakan bullet list untuk poin.
- JANGAN tampilkan tabel mentah atau JSON.
- JANGAN bilang "perlu verifikasi data" — kalau tidak yakin, bilang "data belum lengkap".

CONTOH BAIK:
"Scrap naik tajam kemarin — dari 1,6% jadi 21%. Penyebab utama di SEWING-2 (67% scrap). Saran: hentikan sementara, audit proses."

CONTOH BURUK:
"Scrap rate melonjak ke 21.0% pada 2026-10-20 (21 dari 100 unit), naik tajam dari 1.59% pada 2026-10-19..."

ATURAN DATA (WAJIB):
- JANGAN mengarang data yang tidak ada. Kalau data tidak cukup, bilang "Data tentang <KONTEKS PERTANYAAN> kosong, tidak cukup untuk menjawab".
- Sebutkan angka spesifik dari data; kalau ada tren naik/turun, sebutkan.
- Kalau data berisi product_list untuk ranking, hanya tampilkan produk FG (bukan material/kain/benang/aksesoris).
- Kalau data berisi order_bundles, sebutkan daftar bundle (kode + state) untuk order itu.
- Kalau data berisi bundle_operators, sebutkan operator yang mengerjakan bundle tersebut.
- Kalau data berisi customer_detail/customer_spend, sebutkan nama customer, jumlah order, dan total belanja (format Rp).
- Kalau data berisi operator_anomalies, jelaskan temuan phantom, siklus, scrap, dan reliability.
- Kalau user tanya "kenapa", analisa dari data (bandingkan periode, WC, line).
- JANGAN menyarankan write action (ubah/tambah/hapus data). Kamu hanya baca & analisa.
- JANGAN sebut harga/kredit/pajak kalau user bukan admin/owner/finance.
- JANGAN sebut data produk yang tidak ada di konteks.
- Setiap menyebut entitas, WAJIB pakai field *_name (customer_name, product_name, work_center_name, line_name). JANGAN sebut ID. Kalau nama kosong, bilang "nama tidak tersedia".
- Kalau data tidak cukup, katakan "Data kosong atau tidak cukup" — JANGAN mengarang.
- Kalau data berisi product_production_count=0 DAN related_orders=[] DAN related_bundles=[], jawab: "Produk [nama] belum pernah diproduksi (0 order, 0 bundle, 0 produksi)." JANGAN jawab "Data tidak cukup" — ini bukan data tidak cukup, ini produk belum pernah dipakai.
- Kalau data berisi X dan X kosong, jawab "Tidak ada X" (bukan "Data tidak cukup"). Contoh: related_orders kosong → "Belum ada order terkait", bukan "Data tidak cukup".
- Kalau data berisi total_counts, gunakan angka total dan breakdown dari sana. JANGAN menghitung sendiri dari daftar baris.
- Kalau data berisi product_filter_label/product_count, gunakan daftar hasil filter itu; JANGAN mengambil produk acak.
- Kalau data berisi price_aggregate, gunakan nilai agregat itu; JANGAN menghitung ulang.
- Kalau user tanya "bagaimana cara..." (how-to), arahkan ke halaman/dokumentasi, bukan instruksi eksekusi.
"""

SUGGEST_SYSTEM_PROMPT = """Kamu asisten MES Garmen yang ramah. Balas HANYA JSON valid (tanpa markdown, tanpa penjelasan di luar JSON):
{"problem": "...", "proposed_actions": [{"action": "...", "impact": "LOW|MEDIUM|HIGH", "confidence": 0.0-1.0, "reason": "..."}]}

Aturan:
- Bahasa Indonesia sederhana; alasan maks 12 kata; angka dibulatkan.
- Aksi KONKRET (rework bundle X, pindah bundle Y ke Line B, hubungi vendor Z, audit proses Line A).
- JANGAN menyarankan hapus/delete/drop/update semua/reset.
- JANGAN eksekusi aksi. Manusia yang menyetujui (HITL).
"""

MAX_TOKENS = 500
MAX_ANSWER_CHARS = 5000
WRITE_REJECT_ANSWER = "Maaf, saya tidak bisa menyarankan perubahan data."
EMPTY_ANSWER_FALLBACK = "Maaf, saya tidak bisa menjawab pertanyaan itu."
_WRITE_PATTERN = re.compile(r"\b(UPDATE|DELETE|INSERT|DROP)\s", re.IGNORECASE)
_CONTROL_KEYS = {
    "message",
    "context",
    "intent",
    "tools",
    "_candidates",
    "_entity_label",
    "_aggregate_query",
    "_top_query",
    "_count_query",
    "requested_count",
    "_total_query",
    "_followup_empty",
    "_ranking_candidates",
}


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


def _question_entity(question: str) -> str:
    """Entity yang diminta di follow-up, untuk pesan empty-entity."""
    text = str(question or "").lower()
    if "order" in text:
        return "order"
    if "customer" in text or "pelanggan" in text:
        return "customer"
    if "produk" in text or "product" in text:
        return "produk"
    if "bundle" in text:
        return "bundle"
    return "data terkait"


_WRITE_VERBS = ("hapus", "delete", "ubah", "update", "tambah", "create", "drop")
_WRITE_ENTITIES = (
    "order",
    "produk",
    "product",
    "bundle",
    "customer",
    "invoice",
    "stok",
    "purchase order",
)
_SENSITIVE_WORDS = ("password", "api_key", "apikey", "token", "secret", "kredensial")


def _safety_answer(question: str) -> str | None:
    """Guardrail eksplisit untuk write/sensitive/SQL — tanpa LLM."""
    text = str(question or "").lower()
    if any(word in text for word in _SENSITIVE_WORDS):
        return (
            "Tidak ada data kredensial yang bisa ditampilkan. "
            "Hubungi admin untuk reset."
        )
    if re.search(r"\b(sql|query bebas|query sql)\b", text):
        return (
            "Tidak punya akses ke SQL. Silakan gunakan halaman laporan "
            "yang tersedia."
        )
    if any(word in text for word in _WRITE_VERBS) and any(
        word in text for word in _WRITE_ENTITIES
    ):
        verb = next(word for word in _WRITE_VERBS if word in text)
        entity = next(word for word in _WRITE_ENTITIES if word in text)
        action = {
            "hapus": "menghapus",
            "delete": "menghapus",
            "ubah": "mengubah",
            "update": "mengubah",
            "tambah": "menambah",
            "create": "menambah",
            "drop": "menghapus",
        }.get(verb, "mengubah")
        return (
            f"Tidak bisa {action} data. Silakan lakukan lewat halaman "
            f"{entity} di aplikasi."
        )
    return None


def _render_ranking(ranking: list[dict], question: str) -> str:
    """Render ranking produk langsung (bukan klarifikasi)."""
    label = "termurah" if "murah" in str(question or "").lower() else "termahal"
    first = ranking[0]
    attrs = first.get("attrs") or {}
    lines = [f"Produk {label}: {first.get('label')}, {attrs.get('harga', 'harga belum diisi')}."]
    lines.append("Urutan berikutnya:")
    for index, item in enumerate(ranking[1:5], start=2):
        item_attrs = item.get("attrs") or {}
        lines.append(
            f"{index}. {item.get('label')}, {item_attrs.get('harga', 'harga belum diisi')}"
        )
    return "\n".join(lines)


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


def _deterministic(answer: str, model: str) -> dict:
    """Jawaban RULE (0 token) — tidak di-cache agar pending state tidak hilang."""
    return {
        "ok": True,
        "answer": answer,
        "decision_gate_result": "RULE_HIT",
        "tokens": {"prompt": 0, "completion": 0, "total_cost_usd": 0},
        "model": model,
        "latency_ms": 0,
        "cacheable": False,
    }


SUGGEST_ACTION_PROMPT = """Kamu adalah asisten MES Garmen yang membantu supervisor/owner mengambil keputusan. Berdasarkan data yang diberikan:

1. Identifikasi masalah utama (scrap tinggi, bottleneck, dll).
2. Usulkan 2-3 aksi KONKRET (bukan abstrak):
   - "Rework bundle X" (bukan "perbaiki kualitas")
   - "Pindahkan bundle Y ke Line B" (bukan "rebalance line")
   - "Hubungi vendor Z" (bukan "cek vendor")
3. Setiap aksi punya impact_score (LOW/MEDIUM/HIGH) dan confidence (0.0-1.0).
4. Output JSON (HANYA JSON, tanpa teks lain):
   {
     "problem": "scrap SEWING-2 8.4%",
     "proposed_actions": [
       {"action": "rework BND-A-12", "impact": "MEDIUM",
        "confidence": 0.82, "reason": "3.2% scrap"},
       {"action": "pindah BND-A-14 ke SEWING-1", "impact": "MEDIUM",
        "confidence": 0.75, "reason": "2.8% scrap"}
     ]
   }
5. JANGAN eksekusi aksi. Hanya usul. Manusia yang approve.

Data: {data}
"""

#: Aksi berbahaya yang tidak boleh diusulkan (S.2).
_DANGEROUS_ACTIONS = ("hapus", "delete", "drop", "update semua", "reset")
_VALID_IMPACTS = {"LOW", "MEDIUM", "HIGH"}


def _validate_proposed_actions(actions: list[dict]) -> list[dict]:
    """Filter + normalisasi usulan aksi (S.2): aman, spesifik, maks 3."""
    valid: list[dict] = []
    for item in actions or []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        # Harus actionable: minimal verb + object (2 kata).
        if not action or len(action.split()) < 2:
            continue
        lowered = action.lower()
        if any(word in lowered for word in _DANGEROUS_ACTIONS):
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        impact = str(item.get("impact") or "LOW").upper()
        if impact not in _VALID_IMPACTS:
            impact = "LOW"
        valid.append(
            {
                "action": action,
                "impact": impact,
                "confidence": round(min(1.0, max(0.0, confidence)), 2),
                "reason": str(item.get("reason") or ""),
            }
        )

    valid.sort(key=lambda entry: -entry["confidence"])
    return valid[:3]


_FENCE_PATTERN = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    return _FENCE_PATTERN.sub("", text or "").strip()


def _parse_suggest_payload(text: str) -> dict | None:
    """Parse JSON usulan aksi; toleran code-fence, preamble, & trailing comma."""
    raw = _strip_fences(text)
    if not raw:
        return None

    candidates = [raw]
    start, end = raw.find("{"), raw.rfind("}")
    if 0 <= start < end:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        for variant in (candidate, re.sub(r",\s*([}\]])", r"\1", candidate)):
            try:
                data = json.loads(variant)
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict):
                return data
    return None


def _salvage_suggest_payload(text: str) -> dict | None:
    """Ambil problem/aksi dari JSON rusak via regex (hindari JSON mentah ke user)."""
    raw = text or ""
    problem_match = re.search(r'"problem"\s*:\s*"([^"]{0,300})"', raw)
    actions: list[dict] = []

    for block in re.findall(r"\{[^{}]*?\"action\"[^{}]*?\}", raw):
        action_match = re.search(r'"action"\s*:\s*"([^"]{1,200})"', block)
        if action_match is None:
            continue
        impact_match = re.search(
            r'"impact"\s*:\s*"(LOW|MEDIUM|HIGH)"', block, re.IGNORECASE
        )
        conf_match = re.search(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)', block)
        reason_match = re.search(r'"reason"\s*:\s*"([^"]{0,300})"', block)
        actions.append(
            {
                "action": action_match.group(1),
                "impact": impact_match.group(1).upper() if impact_match else "LOW",
                "confidence": float(conf_match.group(1)) if conf_match else 0.5,
                "reason": reason_match.group(1) if reason_match else "",
            }
        )

    if not actions and problem_match is None:
        return None
    return {
        "problem": problem_match.group(1) if problem_match else "",
        "proposed_actions": actions,
    }


def _looks_like_json(text: str) -> bool:
    raw = _strip_fences(text)
    return (raw.startswith("{") and '"' in raw) or '"proposed_actions"' in (text or "")


def _render_suggest_action(problem: str, actions: list[dict]) -> str:
    """Render JSON usulan aksi ke teks natural (bullet, tanpa JSON mentah)."""
    lines: list[str] = []
    if problem:
        lines.append(f"**Masalah:** {problem}\n")

    if actions:
        lines.append("**Usulan aksi:**\n")
        emojis = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
        for index, item in enumerate(actions, start=1):
            impact = str(item.get("impact") or "LOW")
            try:
                confidence = float(item.get("confidence", 0.5))
            except (TypeError, ValueError):
                confidence = 0.5
            lines.append(
                f"{index}. {emojis.get(impact, '⚪')} **{item.get('action', '')}**"
            )
            lines.append(f"   - Prioritas: {impact} (keyakinan {confidence:.0%})")
            if item.get("reason"):
                lines.append(f"   - Alasan: {item['reason']}")
            lines.append("")
    else:
        lines.append("_Belum ada aksi aman yang bisa diusulkan. Data perlu dilengkapi._\n")

    lines.append("_Semua aksi menunggu persetujuan manusia (HITL)._")
    return "\n".join(lines)


def _suggest_result(
    parsed: dict,
    tokens: dict,
    model: str,
    latency_ms: int,
    chart: dict | None = None,
) -> dict:
    actions = _validate_proposed_actions(parsed.get("proposed_actions") or [])
    problem = str(parsed.get("problem") or "").strip()

    payload = {
        "ok": True,
        "answer": _render_suggest_action(problem, actions),
        "problem": problem,
        "hitl_required": bool(actions),
        "cacheable": False,
        "tokens": tokens,
        "model": model,
        "latency_ms": latency_ms,
    }
    if actions:
        payload["proposed_actions"] = actions
    if chart:
        payload["chart_data"] = chart
    return payload


def _natural_fallback(text: str) -> tuple[str, dict | None]:
    """Teks aman untuk user: render JSON rusak, JANGAN pernah kirim JSON mentah."""
    raw = _strip_fences(text)
    if _looks_like_json(raw):
        parsed = _parse_suggest_payload(raw) or _salvage_suggest_payload(raw)
        if parsed is not None:
            actions = _validate_proposed_actions(parsed.get("proposed_actions") or [])
            problem = str(parsed.get("problem") or "").strip()
            if actions or problem:
                return _render_suggest_action(problem, actions), parsed
        return (
            "Data sudah dianalisis, tetapi format jawabannya belum bisa dibaca. "
            "Coba tanyakan lagi dengan menyebut line atau work center.",
            None,
        )
    return validate_answer(raw), None


def synthesize(
    message: str,
    context_data: dict,
    user=None,
    session_id: str | None = None,
    intent: str = "",
) -> dict:
    """Panggil LLM dengan data konteks → jawaban natural (tidak pernah raise).

    `user`/`session_id` hanya dipakai untuk menyimpan pending clarification (R.3);
    bila tidak diberikan, jalur klarifikasi tetap deterministik tanpa state.
    """
    question = (message or "").strip()
    if not question:
        return _error("empty_message", "Pertanyaan user kosong.")
    if not isinstance(context_data, dict) or not context_data.get("message"):
        return _error(
            "empty_context",
            "Konteks wajib diisi sebelum memanggil LLM.",
        )

    safety = _safety_answer(question)
    if safety is not None:
        return _deterministic(safety, "rule:safety")

    ranking = context_data.get("_ranking_candidates")
    if (
        isinstance(ranking, list)
        and ranking
        and not context_data.get("_resolved_candidate")
    ):
        answer = _render_ranking(ranking, question)
        if user is not None:
            pending_state.save(
                user.pk,
                session_id or f"user-{user.pk}",
                {
                    "candidates": ranking,
                    "original_query": question,
                    "question": answer,
                    "turn_count": 0,
                    "entity": "product",
                },
            )
        return _deterministic(answer, "rule:ranking")

    # Fase 3.5C — pronoun ke entity yang tidak ada: jawab deterministik.
    empty_followup = context_data.get("_followup_empty")
    if isinstance(empty_followup, dict):
        entity = str(empty_followup.get("entity") or "data")
        code = str(empty_followup.get("code") or "")
        labels = {
            "bundle": "Bundle",
            "order": "Order",
            "product": "Produk",
            "customer": "Customer",
            "invoice": "Invoice",
            "purchase_order": "Purchase order",
            "work_order": "Work order",
        }
        if user is not None:
            pending_state.clear(user.pk, session_id or f"user-{user.pk}")
        return _deterministic(
            f"{labels.get(entity, entity.title())} {code} tidak ada, "
            f"jadi tidak bisa di-resolve ke {_question_entity(question)}.",
            "rule:empty_followup",
        )

    # R.2/R.3 — klarifikasi deterministik (0 token). Hanya berlaku bila
    # context_builder menandai `_candidates` dan user BELUM memilih kandidat.
    candidates = context_data.get("_candidates")
    if candidates is not None and not context_data.get("_resolved_candidate"):
        epistemic = epistemic_classifier.classify(
            list(candidates),
            question,
            is_aggregate_query=bool(context_data.get("_aggregate_query")),
        )
        entity_label = str(context_data.get("_entity_label") or "data")

        if epistemic.status is epistemic_classifier.EpistemicStatus.EMPTY:
            return _deterministic(
                templates.empty_response(entity_label, question), "rule:empty"
            )

        if epistemic.status in {
            epistemic_classifier.EpistemicStatus.AMBIGUOUS,
            epistemic_classifier.EpistemicStatus.WEAK,
        }:
            chosen = list(epistemic.candidates)
            if (
                epistemic.status
                is epistemic_classifier.EpistemicStatus.AMBIGUOUS
            ):
                answer = templates.ambiguous_question(chosen)
                model = "rule:ambiguous"
            else:
                answer = templates.weak_question(chosen[0])
                model = "rule:weak"

            if user is not None and chosen:
                pending_state.save(
                    user.pk,
                    session_id or f"user-{user.pk}",
                    {
                        "candidates": chosen,
                        "original_query": question,
                        "question": answer,
                        "turn_count": 0,
                        "entity": chosen[0].get("entity"),
                    },
                )
            return _deterministic(answer, model)

    data_block = {
        key: value for key, value in context_data.items() if key not in _CONTROL_KEYS
    }
    chart = chart_builder.build_chart_data(context_data, intent, question)
    suggest_mode = str(intent or "").strip().upper() == "SUGGEST_ACTION"
    if suggest_mode:
        user_prompt = SUGGEST_ACTION_PROMPT.replace(
            "{data}", json.dumps(data_block, indent=2, default=str)
        )
    else:
        user_prompt = f"""PERTANYAAN USER:
{question}

KONTEKS HALAMAN:
{json.dumps(context_data.get("context", {}), indent=2, default=str)}

DATA DARI SISTEM:
{json.dumps(data_block, indent=2, default=str)}

Jawab pertanyaan user berdasarkan data di atas."""

    try:
        response = get_llm_provider().complete(
            system_prompt=SUGGEST_SYSTEM_PROMPT if suggest_mode else SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_tokens=MAX_TOKENS,
        )
    except Exception as exc:
        return _error(
            "llm_failed",
            str(exc),
            code=str(getattr(exc, "code", "llm_error")),
        )

    tokens = {
        "prompt": int(response.prompt_tokens or 0),
        "completion": int(response.completion_tokens or 0),
        "total_cost_usd": float(response.total_cost_usd or 0),
    }
    latency_ms = int(response.latency_ms or 0)

    if suggest_mode:
        parsed = _parse_suggest_payload(response.text) or _salvage_suggest_payload(
            response.text
        )
        if parsed is not None and (
            parsed.get("problem") or parsed.get("proposed_actions")
        ):
            return _suggest_result(parsed, tokens, response.model, latency_ms, chart)

        answer, salvaged = _natural_fallback(response.text)
        if salvaged is not None:
            return _suggest_result(salvaged, tokens, response.model, latency_ms, chart)
        return {
            "ok": True,
            "answer": answer,
            "cacheable": False,
            "tokens": tokens,
            "model": response.model,
            "latency_ms": latency_ms,
        }

    answer, parsed = _natural_fallback(response.text)
    payload = {
        "ok": True,
        "answer": answer,
        "tokens": tokens,
        "model": response.model,
        "latency_ms": latency_ms,
    }
    if chart:
        payload["chart_data"] = chart
    if parsed is not None:
        actions = _validate_proposed_actions(parsed.get("proposed_actions") or [])
        if actions:
            payload["proposed_actions"] = actions
        problem = str(parsed.get("problem") or "").strip()
        if problem:
            payload["problem"] = problem
    return payload


__all__ = (
    "EMPTY_ANSWER_FALLBACK",
    "MAX_ANSWER_CHARS",
    "MAX_TOKENS",
    "SUGGEST_ACTION_PROMPT",
    "SUGGEST_SYSTEM_PROMPT",
    "SYSTEM_PROMPT",
    "WRITE_REJECT_ANSWER",
    "_render_suggest_action",
    "_validate_proposed_actions",
    "synthesize",
    "validate_answer",
)
