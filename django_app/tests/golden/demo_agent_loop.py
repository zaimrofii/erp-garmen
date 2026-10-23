"""Ulangi demo lewat endpoint /ai/chat dengan agent loop (flag ON).

Menulis hasil ke tests/golden/demo_agent_loop_results.json; biaya dihitung dari
AIDecisionLog (kolom total_cost_usd) dan dihentikan bila melewati cap.
"""

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
CAP_USD = float(os.environ.get("DEMO_CAP", "0.03"))

SMOKE = [
    "Produk paling mahal apa?",
    "Ubah harga Jaket Bomber jadi 100rb",
    "Berapa bundle aktif di SEWING-2?",
]

DEMO = [
    "Produk termahal yang aktif apa?",
    "Customer dengan order terbanyak bulan ini?",
    "Berapa bundle sedang dikerjakan di SEWING-2?",
    "Scrap terbesar minggu ini di work center mana?",
    "Berapa persen scrap SEWING-2 minggu ini?",
    "Rata-rata lead time bundle minggu ini?",
    "Operator dengan output terbanyak bulan ini?",
    "Order mana paling telat dari deadline?",
    "Dari 3 produk termahal, mana yang kedua?",
    "Total order aktif, lalu mana yang paling lambat?",
    "Stok produk paling banyak apa?",
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


def run(questions: list[str], label: str) -> dict:
    client = APIClient(SERVER_NAME="localhost")
    client.force_authenticate(_supervisor())
    rows: list[dict] = []
    spent = 0.0

    for index, question in enumerate(questions, start=1):
        if spent > CAP_USD:
            print(f"ABORT cap ${CAP_USD} tercapai")
            break
        before = AIDecisionLog.objects.count()
        started = time.monotonic()
        response = client.post(
            URL,
            {"message": question, "channel": "DESKTOP"},
            format="json",
            HTTP_X_CONVERSATION_ID=f"demo-{label}-{index}",
        )
        latency = int((time.monotonic() - started) * 1000)
        data = response.json() if response["Content-Type"].startswith("application/json") else {}

        log = (
            AIDecisionLog.objects.filter(query_text=question)
            .order_by("-id")
            .first()
        )
        cost = float(log.total_cost_usd) if log else 0.0
        spent += cost
        tool_names = [item.get("tool") for item in data.get("tool_calls") or []]
        row = {
            "n": index,
            "question": question,
            "status": response.status_code,
            "agent_mode": data.get("agent_mode"),
            "blocked_reason": data.get("blocked_reason"),
            "tools": tool_names,
            "answer": (data.get("answer") or "")[:400],
            "gate": getattr(log, "decision_gate_result", None),
            "confidence": getattr(log, "confidence_score", None),
            "cost_usd": round(cost, 8),
            "latency_ms": latency,
            "new_logs": AIDecisionLog.objects.count() - before,
        }
        rows.append(row)
        print(
            f"{label} {index:02d} mode={row['agent_mode']} gate={row['gate']} "
            f"tools={','.join(t for t in tool_names if t) or '-'} "
            f"blocked={row['blocked_reason'] or '-'} ${cost:.6f} | {row['answer'][:80]!r}"
        )

    out = {
        "label": label,
        "total": len(rows),
        "spent_usd": round(spent, 8),
        "rows": rows,
    }
    (BASE / "demo_agent_loop_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"TOTAL {label}: {len(rows)} soal, ${spent:.8f}")
    return out


def main() -> int:
    label = "smoke"
    if "--set" in sys.argv:
        label = sys.argv[sys.argv.index("--set") + 1]
    questions = SMOKE if label == "smoke" else DEMO
    run(questions, label)
    return 0


if __name__ == "__main__":
    sys.exit(main())
