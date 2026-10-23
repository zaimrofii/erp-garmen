"""Probe tambahan (non-produksi, ambigu, majemuk) via endpoint /ai/chat."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
for parent in (BASE.parent.parent, BASE.parent):
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from rest_framework.test import APIClient  # noqa: E402

from core.auth.models import Role, User  # noqa: E402
from integrations.ai_agent.models import AIDecisionLog  # noqa: E402

URL = "/api/v1/ai/chat"
CAP_USD = float(os.environ.get("PROBE_CAP", "0.0285"))

QUESTIONS = [
    ("B1", "apa itu sapi"),
    ("B2", "siapa presiden Indonesia sekarang"),
    ("B3", "bagaimana cuaca hari ini"),
    ("B4", "berapa 2+2"),
    ("B5", "ceritakan lelucon singkat"),
    ("D1", "produk itu berapa harganya?"),
    ("D2", "order tadi gimana?"),
    ("D3", "yang kedua?"),
    ("E2", "produk termahal dan stoknya?"),
    ("E3", "scrap minggu ini dan work center terbesar?"),
]


def _supervisor() -> User:
    user, created = User.objects.get_or_create(
        username="demo-supervisor",
        defaults={"role": Role.objects.get(code=Role.Code.SUPERVISOR)},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def main() -> int:
    client = APIClient(SERVER_NAME="localhost")
    client.force_authenticate(_supervisor())
    spent = 0.0
    rows = []
    for index, (tag, question) in enumerate(QUESTIONS, start=1):
        if spent > CAP_USD:
            print(f"ABORT cap ${CAP_USD} tercapai")
            break
        started = time.monotonic()
        response = client.post(
            URL,
            {"message": question, "channel": "DESKTOP"},
            format="json",
            HTTP_X_CONVERSATION_ID=f"probe-{tag}-{index}",
        )
        latency = int((time.monotonic() - started) * 1000)
        data = response.json() if response["Content-Type"].startswith("application/json") else {}
        log = AIDecisionLog.objects.filter(query_text=question).order_by("-id").first()
        cost = float(log.total_cost_usd) if log else 0.0
        spent += cost
        tools = [item.get("tool") for item in data.get("tool_calls") or []]
        row = {
            "tag": tag,
            "question": question,
            "status": response.status_code,
            "tools": tools,
            "blocked_reason": data.get("blocked_reason"),
            "validator_ok": getattr(log, "validator_ok", None),
            "validator_reason": getattr(log, "validator_reason", None),
            "answer": (data.get("answer") or "")[:300],
            "cost_usd": round(cost, 8),
            "latency_ms": latency,
        }
        rows.append(row)
        print(
            f"{tag} status={row['status']} tools={','.join(t for t in tools if t) or '-'} "
            f"blocked={row['blocked_reason'] or '-'} v_ok={row['validator_ok']} "
            f"v_reason={row['validator_reason']!r} ${cost:.6f} | {row['answer'][:120]!r}"
        )
    (BASE / "probe_extra_results.json").write_text(
        json.dumps({"spent_usd": round(spent, 8), "rows": rows}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"TOTAL probe: {len(rows)} soal, ${spent:.8f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
