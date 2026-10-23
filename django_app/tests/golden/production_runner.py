"""Runner pengukuran Fase 1: agent loop produksi (9 tool) di held-out & tuning.

Bukan spike: memakai `integrations.ai_agent.agent.run_agent` + tool produksi +
validator produksi. Skor memakai aturan yang sudah dikunci (`spike_scoring_rules.md`).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone as dt_tz
from pathlib import Path

BASE = Path(__file__).resolve().parent
for parent in (BASE.parent.parent, BASE.parent):
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

import yaml  # noqa: E402
from django.utils import timezone  # noqa: E402

from integrations.ai_agent.agent.loop import run_agent  # noqa: E402
from integrations.ai_agent.api.views import _AGENT_SYSTEM_PROMPT  # noqa: E402
from tests.golden.spike_runner_v3 import check_ground_truth, load_rules  # noqa: E402
from tests.golden.validation_runner import EXPECTED, evaluate_tools  # noqa: E402

BUDGET_USD = float(os.environ.get("SPIKE_BUDGET", "0.035"))
TOTAL_SPENT = 0.0
PREVIOUS_USD = 0.26192426
ROLE = "SUPERVISOR"


def run_question(question: dict, rules: dict) -> tuple[dict, float]:
    messages = [
        {
            "role": "system",
            "content": _AGENT_SYSTEM_PROMPT.format(
                today=timezone.localdate().isoformat(), role=ROLE
            ),
        },
        {"role": "user", "content": question["q"]},
    ]
    if question.get("definition_system"):
        messages[0]["content"] += f"\n\nDEFINISI SISTEM: {question['definition_system']}"

    started = time.perf_counter()
    result = run_agent(messages, ROLE, config={"max_iterations": 5})
    tool_names = [call.get("tool") for call in result.tool_calls]
    arg_list = [call.get("args") or {} for call in result.tool_calls]

    expected = EXPECTED.get(question["id"], {"tool": None})
    tool_ok, param_ok = evaluate_tools(question["id"], tool_names, arg_list, expected, rules)
    gt_ok, gt_reason = check_ground_truth(question, result.answer, rules)
    blocked = bool(result.validator and not result.validator.get("ok", True))

    row = {
        "id": question["id"],
        "category": question["category"],
        "tools": tool_names,
        "arguments": arg_list,
        "answer": result.answer[:500],
        "validator_blocked": blocked,
        "validator_reason": (result.validator or {}).get("reason"),
        "expected_tool": expected["tool"],
        "tool_ok": bool(tool_ok),
        "param_ok": bool(param_ok),
        "gt_ok": bool(gt_ok),
        "gt_reason": gt_reason,
        "e2e": bool(tool_ok and param_ok and gt_ok),
        "iterations": result.iterations,
        "error": result.error,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "cost_usd": round(result.cost_usd, 8),
    }
    return row, float(result.cost_usd)


def summarize(rows: list[dict], cost: float) -> dict:
    total = len(rows)

    def pct(value: int, denominator: int) -> float:
        return round(value / denominator * 100, 1) if denominator else 0.0

    lat = sorted(row["latency_ms"] for row in rows)
    return {
        "mode": "production_agent_loop",
        "total": total,
        "tool_pct": pct(sum(1 for row in rows if row["tool_ok"]), total),
        "param_pct": pct(sum(1 for row in rows if row["param_ok"]), total),
        "e2e_pct": pct(sum(1 for row in rows if row["e2e"]), total),
        "angka_salah_pct": pct(sum(1 for row in rows if row["validator_blocked"]), total),
        "validator_blocked_count": sum(1 for row in rows if row["validator_blocked"]),
        "max_iterations_count": sum(1 for row in rows if row["error"] == "max_iterations"),
        "latensi_p50": lat[len(lat) // 2] if lat else 0,
        "biaya_usd": round(cost, 8),
        "detail": rows,
    }


def main() -> int:
    global TOTAL_SPENT
    rules = load_rules()
    set_name = "held_out"
    if "--set" in sys.argv:
        set_name = sys.argv[sys.argv.index("--set") + 1]
    repeats = 3
    if "--repeats" in sys.argv:
        repeats = max(1, int(sys.argv[sys.argv.index("--repeats") + 1]))

    questions = [
        item
        for item in yaml.safe_load((BASE / "questions.yaml").read_text(encoding="utf-8"))
        if item.get("set") == set_name
    ]

    rows: list[dict] = []
    cost_total = 0.0
    aborted = False
    for question in questions:
        for repeat in range(repeats):
            if TOTAL_SPENT > BUDGET_USD:
                aborted = True
                break
            row, cost = run_question(question, rules)
            TOTAL_SPENT += cost
            cost_total += cost
            row["repeat"] = repeat + 1
            rows.append(row)
            print(
                f"{row['id']}#{repeat + 1} tool={int(row['tool_ok'])} par={int(row['param_ok'])} "
                f"gt={int(row['gt_ok'])} e2e={int(row['e2e'])} blocked={int(row['validator_blocked'])} "
                f"iter={row['iterations']} ${cost:.6f}"
            )
        if aborted:
            break

    summary = summarize(rows, cost_total)
    summary["aborted_budget"] = aborted
    out = {
        "generated_at": datetime.now(dt_tz.utc).isoformat(),
        "set": set_name,
        "mode": "production_agent_loop",
        "role": ROLE,
        "questions_total": len(questions),
        "deepseek": summary,
        "total_cost_usd": round(cost_total, 8),
        "kumulatif_proyek_usd": round(PREVIOUS_USD + cost_total, 8),
    }
    (BASE / f"production_results_{set_name}.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"SUMMARY {set_name}: tool={summary['tool_pct']}% param={summary['param_pct']}% "
        f"e2e={summary['e2e_pct']}% blocked={summary['validator_blocked_count']}/{summary['total']} "
        f"biaya=${cost_total:.8f} kumulatif=${PREVIOUS_USD + cost_total:.8f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
