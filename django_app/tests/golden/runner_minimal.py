"""Runner baseline jalur LAMA untuk 15 pertanyaan golden (Fase G.5).

Biaya LLM = $0. Dua mode:
  * ``deterministic`` (default) — pipeline ai_agent asli berjalan, tetapi provider
    LLM diganti "null provider" yang selalu menolak. Yang diukur adalah akurasi
    jalur non-LLM (rule/ranking/klarifikasi) tanpa biaya.
  * ``stub`` — ``AI_AGENT_ENABLED=False`` (nilai default repo) → endpoint
    mengembalikan ``not_implemented``. Baseline jujur untuk kondisi default.

Jalankan di container:
    docker exec -i garmen_django python tests/golden/runner_minimal.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone as dt_tz
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent
for parent in (BASE.parent.parent, BASE.parent):
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import yaml  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.test import override_settings  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from integrations.ai_agent.llm_wrapper.base import LLMResponse  # noqa: E402

URL = "/api/v1/ai/chat"
P_SYNTH = "integrations.ai_agent.orchestrator.response_synthesizer.get_llm_provider"
P_INTENT = "integrations.ai_agent.orchestrator.intent_classifier.get_llm_provider"
SAFETY_PRODUCT_ID = 54  # "Jaket Bomber" — tidak boleh hilang

_NUM = re.compile(r"\d[\d.,]*")


class NullProvider:
    """LLM palsu deterministik: selalu menolak, 0 token, 0 biaya."""

    model = "null"

    def complete(self, system_prompt, user_prompt, max_tokens=1000):  # noqa: ARG002
        return LLMResponse(
            text="Saya tidak punya data yang cukup untuk menjawab.",
            prompt_tokens=0,
            completion_tokens=0,
            total_cost_usd=0.0,
            model="null",
            latency_ms=0,
            raw={},
        )


def numbers_in(text: str) -> list[float]:
    """Ambil angka dari jawaban; tangani 250.000 dan 77,64."""
    out: list[float] = []
    for token in _NUM.findall(text or ""):
        token = token.rstrip(".,")
        if re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
            value = float(token.replace(".", ""))
        elif re.fullmatch(r"\d+,\d+", token):
            value = float(token.replace(",", "."))
        elif re.fullmatch(r"\d+(\.\d+)?", token):
            value = float(token)
        else:
            value = float(re.sub(r"[.,]", "", token) or 0)
        out.append(value)
    return out


def score(question: dict, answer: str) -> tuple[bool, str]:
    check = question.get("check") or {}
    kind = check.get("type")
    low = (answer or "").lower()
    nums = numbers_in(answer)

    if kind in {"refuse", "no_data"}:
        hit = any(word.lower() in low for word in check.get("words", []))
        return hit, "penanda penolakan/data kosong" if hit else "tidak menolak"

    reasons: list[str] = []
    entities = check.get("entities") or []
    if entities and not any(entity.lower() in low for entity in entities):
        reasons.append("entity tidak muncul")

    for expected in check.get("numbers") or []:
        if expected == 0 and not nums and "tidak ada" in low:
            continue
        if not any(abs(value - expected) <= 0.5 for value in nums):
            reasons.append(f"angka {expected} tidak ada")

    if "approx" in check:
        tolerance = float(check.get("tol", 0.5))
        if not any(abs(value - check["approx"]) <= tolerance for value in nums):
            reasons.append(f"~{check['approx']} tidak ada")

    return (not reasons), (", ".join(reasons) or "cocok")


def extract(resp) -> tuple[str, dict]:
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        head = (resp.content or b"").decode("utf-8", "replace")[:120].replace("\n", " ")
        return f"<non-JSON HTTP {resp.status_code}: {head}>", {"_non_json": True}
    answer = str(data.get("answer") or "").strip()
    if not answer:
        answer = str(data.get("error") or data.get("reason") or "").strip()
    if not answer:
        answer = json.dumps(data, ensure_ascii=False)[:300]
    return answer, data


def run_mode(mode: str, questions: list[dict], user) -> dict:
    detail: list[dict] = []
    cache_key = f"clarification:{user.pk}:user-{user.pk}"

    for question in questions:
        cache.delete(cache_key)  # percakapan baru
        client = APIClient(SERVER_NAME="localhost")  # ALLOWED_HOSTS = localhost/127.0.0.1/django
        client.force_authenticate(user=user)
        payload = {"message": question["q"], "channel": "DESKTOP"}
        started = time.perf_counter()
        if mode == "stub":
            with override_settings(AI_AGENT_ENABLED=False):
                resp = client.post(URL, payload, format="json")
        else:
            with mock.patch(P_SYNTH, return_value=NullProvider()), mock.patch(
                P_INTENT, return_value=NullProvider()
            ):
                resp = client.post(URL, payload, format="json")
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        answer, data = extract(resp)
        ok, reason = score(question, answer)
        if data.get("_non_json"):
            ok, reason = False, "respons bukan JSON"
        detail.append(
            {
                "id": question["id"],
                "q": question["q"],
                "category": question["category"],
                "ground_truth": question["ground_truth"],
                "answer": answer[:400],
                "http_status": resp.status_code,
                "decision_gate_result": data.get("decision_gate_result"),
                "error": data.get("error") or data.get("reason"),
                "correct": ok,
                "reason": reason,
                "latency_ms": latency_ms,
            }
        )
        print(f"{mode:14s} {question['id']} {'PASS' if ok else 'FAIL'} {reason} :: {answer[:90]}")

    total = len(detail)
    benar = sum(1 for row in detail if row["correct"])
    per_category: dict[str, dict] = {}
    for row in detail:
        bucket = per_category.setdefault(row["category"], {"total": 0, "benar": 0})
        bucket["total"] += 1
        bucket["benar"] += int(row["correct"])
    for bucket in per_category.values():
        bucket["pct"] = round(bucket["benar"] / bucket["total"] * 100, 1)

    return {
        "total": total,
        "benar": benar,
        "salah": total - benar,
        "akurasi_pct": round(benar / total * 100, 1) if total else 0.0,
        "per_kategori": per_category,
        "detail_per_pertanyaan": detail,
        "biaya_usd": 0.0,
    }


def main() -> int:
    questions = yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) != 15:
        raise SystemExit(f"questions.yaml harus berisi 15 entri, dapat {len(questions)}")

    user = get_user_model().objects.filter(role__code="OWNER").order_by("pk").first()
    if user is None:
        raise SystemExit("Tidak ada user role OWNER untuk baseline")

    print(f"owner={user.pk}:{user.username} questions={len(questions)}")
    deterministic = run_mode("deterministic", questions, user)
    stub = run_mode("stub", questions, user)

    safety_intact = False
    try:
        from master.models import Product

        safety_intact = Product.objects.filter(pk=SAFETY_PRODUCT_ID).exists()
    except Exception:  # noqa: BLE001
        safety_intact = False

    payload = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "mode_utama": "deterministic",
        **deterministic,
        "modes": {"deterministic": deterministic, "stub": stub},
        "safety_product_intact": safety_intact,
        "catatan": [
            "Mode deterministic = pipeline ai_agent asli + NullProvider (LLM selalu menolak); "
            "mengukur akurasi jalur non-LLM tanpa biaya.",
            "Mode stub = AI_AGENT_ENABLED=False (default repo) -> endpoint membalas not_implemented.",
            "Biaya LLM kedua mode: $0. Tidak ada panggilan jaringan ke provider.",
            "Pending state dibersihkan antar pertanyaan agar tiap pertanyaan = percakapan baru.",
        ],
    }
    out = BASE / os.environ.get("GOLDEN_OUT", "baseline_old_path.json")
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"BASELINE deterministic {deterministic['benar']}/{deterministic['total']} "
        f"({deterministic['akurasi_pct']}%) | stub {stub['benar']}/{stub['total']} "
        f"({stub['akurasi_pct']}%) -> {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

