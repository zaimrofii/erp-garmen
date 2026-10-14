"""RuleEngine — evaluasi rule generik TANPA `eval`/`exec`.

Semua operator dipetakan lewat dict (`_OPERATOR_MAP`); nilai yang tersimpan di
DB tidak pernah dieksekusi sebagai kode. Setiap kegagalan — key tidak ada di
context, tipe tidak cocok, regex invalid, operator tak dikenal — berarti
**tidak match** (fail-closed), bukan exception.

Contoh::

    hasil = RuleEngine().evaluate("PRIORITY_FAST_TRACK", {"order": {"tag": "FAST_TRACK"}})
    if hasil.matched:
        for action in hasil.actions:  # {"action_type": ..., "params": {...}}
            ...  # eksekusi = tanggung jawab app domain, bukan engine
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .models import Rule, RuleCondition

logger = logging.getLogger(__name__)

#: Penanda "field tidak ada di context" — beda dari nilai `None` yang sah.
_MISSING = object()


def _lookup(context: Mapping[str, Any], path: str) -> Any:
    """Ambil nilai `path` (boleh dotted, mis. 'bundle.qty'); `_MISSING` kalau absen."""
    current: Any = context
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return _MISSING
    return current


def _as_number(value: Any) -> float:
    """Konversi nilai ke float untuk pembanding numerik (`bool` ditolak)."""
    if isinstance(value, bool):
        raise TypeError("bool bukan angka")
    return float(value)


def _comparable(operator: Callable[[Any, Any], bool]) -> Callable[[Any, Any], bool]:
    """Bungkus pembanding: coba apa adanya, lalu numerik, terakhir fail-closed."""

    def _compare(actual: Any, expected: Any) -> bool:
        try:
            return bool(operator(actual, expected))
        except TypeError:
            try:
                return bool(operator(_as_number(actual), _as_number(expected)))
            except (TypeError, ValueError):
                return False

    return _compare


def _contains(actual: Any, expected: Any) -> bool:
    """CONTAINS: substring untuk string, item untuk list/tuple/set."""
    if isinstance(actual, str):
        return str(expected) in actual
    if isinstance(actual, (list, tuple, set, frozenset)):
        return expected in actual
    return False


def _in(actual: Any, expected: Any) -> bool:
    """IN: `value` WAJIB list/tuple/set; kalau bukan -> tidak match."""
    if isinstance(expected, (list, tuple, set, frozenset)):
        return actual in expected
    return False


def _regex(actual: Any, expected: Any) -> bool:
    """REGEX: `re.search` (case-insensitive); pola invalid -> tidak match."""
    if actual is None or not isinstance(expected, str):
        return False
    try:
        return re.search(expected, str(actual), flags=re.IGNORECASE) is not None
    except re.error:
        logger.warning("regex tidak valid pada RuleCondition: %r", expected)
        return False


#: Mapping operator -> callable. Tidak ada eval/exec di mana pun.
_OPERATOR_MAP: dict[str, Callable[[Any, Any], bool]] = {
    RuleCondition.Operator.EQ: _comparable(lambda a, b: a == b),
    RuleCondition.Operator.NE: _comparable(lambda a, b: a != b),
    RuleCondition.Operator.GT: _comparable(lambda a, b: a > b),
    RuleCondition.Operator.GTE: _comparable(lambda a, b: a >= b),
    RuleCondition.Operator.LT: _comparable(lambda a, b: a < b),
    RuleCondition.Operator.LTE: _comparable(lambda a, b: a <= b),
    RuleCondition.Operator.IN: _in,
    RuleCondition.Operator.CONTAINS: _contains,
    RuleCondition.Operator.REGEX: _regex,
}


@dataclass(frozen=True)
class RuleResult:
    """Hasil evaluasi satu rule."""

    matched: bool
    rule: Rule | None = None
    actions: list[dict] = field(default_factory=list)
    reason: str = ""


class RuleEngine:
    """Evaluasi rule dari DB (stateless)."""

    def evaluate(
        self, rule_code: str, context: Mapping[str, Any] | None = None
    ) -> RuleResult:
        """Evaluasi satu rule by `code` (fail-closed kalau tidak ada/nonaktif)."""
        rule = self._get_rule(rule_code)
        if rule is None:
            return RuleResult(
                matched=False,
                rule=None,
                actions=[],
                reason=f"rule '{rule_code}' tidak ditemukan atau tidak aktif.",
            )
        return self._evaluate_rule(rule, dict(context or {}))

    def evaluate_all(
        self,
        context: Mapping[str, Any] | None = None,
        rule_codes: list[str] | None = None,
    ) -> list[RuleResult]:
        """Evaluasi banyak rule sekaligus (urut `priority`, lalu `code`).

        Semua rule yang dievaluasi dikembalikan — termasuk yang **tidak** match —
        supaya alasan penolakannya bisa diaudit; pemanggil tinggal memfilter
        `result.matched`.
        """
        payload = dict(context or {})
        queryset = Rule.objects.filter(is_active=True).prefetch_related(
            "conditions", "actions"
        )
        if rule_codes:
            queryset = queryset.filter(code__in=[str(code) for code in rule_codes])
        return [
            self._evaluate_rule(rule, payload)
            for rule in queryset.order_by("priority", "code")
        ]

    # ----------------------------------------------------------------- internal
    @staticmethod
    def _get_rule(rule_code: str) -> Rule | None:
        return Rule.objects.filter(code=rule_code, is_active=True).first()

    def _evaluate_rule(self, rule: Rule, context: Mapping[str, Any]) -> RuleResult:
        """Semua kondisi harus match (AND); berhenti di kondisi pertama yang gagal."""
        conditions = list(rule.conditions.all())
        for condition in conditions:
            matched, reason = self._check_condition(condition, context)
            if not matched:
                return RuleResult(matched=False, rule=rule, actions=[], reason=reason)

        actions = [
            {"action_type": action.action_type, "params": dict(action.params or {})}
            for action in rule.actions.all()
        ]
        reason = (
            "semua kondisi terpenuhi"
            if conditions
            else "rule tanpa kondisi (selalu match)"
        )
        return RuleResult(matched=True, rule=rule, actions=actions, reason=reason)

    def _check_condition(
        self, condition: RuleCondition, context: Mapping[str, Any]
    ) -> tuple[bool, str]:
        """Evaluasi satu kondisi -> `(match, alasan)`. Semua error = tidak match."""
        actual = _lookup(context, condition.field)
        if actual is _MISSING:
            return False, f"context tidak punya field '{condition.field}' (fail-closed)."

        operator = _OPERATOR_MAP.get(condition.operator)
        if operator is None:
            return False, f"operator '{condition.operator}' tidak dikenal (fail-closed)."

        if operator(actual, condition.value):
            return True, ""
        return False, f"kondisi '{condition.field} {condition.operator}' tidak terpenuhi."
