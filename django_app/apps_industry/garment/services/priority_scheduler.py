"""PriorityScheduler — skor prioritas work order & pemilihan bundle berikutnya (Sprint 2.3).

Skor akhir::

    score = base(rule/tag) + deadline_bonus + order.priority

  * **base** — dari Rule aktif ber-prefix ``priority.`` (aksi `SET_PRIORITY`,
    `params["value"]`). Kalau tidak ada rule yang match, dipakai bobot tag
    (`default_weights`: FAST_TRACK 100 / EXPORT 50 / CUSTOM 10);
  * **deadline_bonus** — ``max(0, 30 - hari_menuju_deadline) * 5``; makin dekat
    (atau sudah lewat) makin besar bonusnya;
  * **order.priority** — angka prioritas manual pada `Order`.

Service **read-only** (tidak menyimpan apa pun) dan deterministik: setiap method
menyebutkan tie-break-nya.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from apps_industry.garment.models import Bundle, WorkCenter, WorkOrder
from apps_industry.garment.services.exceptions import PrioritySchedulerError
from apps_industry.garment.services.wc_queue import WCQueue
from core.rule_engine.models import Rule
from core.rule_engine.services import RuleEngine

logger = logging.getLogger(__name__)


class PriorityScheduler:
    """Penghitung prioritas work order + pemilih bundle berikutnya."""

    RULE_PREFIX = "priority."
    SET_PRIORITY_ACTION = "SET_PRIORITY"
    DEFAULT_WEIGHTS = {"FAST_TRACK": 100, "EXPORT": 50, "CUSTOM": 10}
    DEADLINE_MAX_DAYS = 30
    DEADLINE_WEIGHT = 5

    def __init__(self, rule_engine: RuleEngine | None = None, default_weights: dict | None = None):
        self._engine = rule_engine or RuleEngine()
        self.default_weights = dict(default_weights or self.DEFAULT_WEIGHTS)

    # ------------------------------------------------------------------- score
    def compute_priority(self, work_order: WorkOrder) -> int:
        """Skor prioritas akhir sebuah work order (int, makin besar makin prioritas)."""
        if work_order is None:
            raise PrioritySchedulerError("work_order wajib diisi.")

        order_line = work_order.order_line
        score = self._base_score(order_line)
        score += self.deadline_bonus(order_line.order.deadline)
        score += int(order_line.order.priority or 0)
        return int(score)

    def deadline_bonus(self, deadline) -> int:
        """`max(0, 30 - hari_menuju_deadline) * 5` (0 kalau deadline kosong)."""
        if deadline is None:
            return 0
        days_to_deadline = (deadline - timezone.now()).total_seconds() / 86400
        remaining = max(0.0, self.DEADLINE_MAX_DAYS - days_to_deadline)
        return int(remaining * self.DEADLINE_WEIGHT)

    def _base_score(self, order_line) -> int:
        """Skor dasar: rule `priority.*` kalau ada, kalau tidak bobot tag."""
        rule_score = self._rule_score(order_line)
        if rule_score is not None:
            return rule_score
        return int(self.default_weights.get(order_line.tag, 0))

    def _rule_score(self, order_line) -> int | None:
        """Skor dari Rule aktif `priority.*` (aksi `SET_PRIORITY`)."""
        rules = list(
            Rule.objects.filter(
                is_active=True, code__startswith=self.RULE_PREFIX
            ).order_by("priority", "code")
        )
        if not rules:
            return None

        context = {
            "tag": order_line.tag,
            "qty": order_line.qty,
            "order_type": order_line.order.order_type,
        }
        for result in self._engine.evaluate_all(
            context, rule_codes=[rule.code for rule in rules]
        ):
            if not result.matched:
                continue
            for action in result.actions:
                if action.get("action_type") != self.SET_PRIORITY_ACTION:
                    continue
                value = (action.get("params") or {}).get("value")
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError) as exc:
                    raise PrioritySchedulerError(
                        f"nilai SET_PRIORITY '{value}' bukan angka."
                    ) from exc
        return None

    # -------------------------------------------------------------------- rank
    def rank_work_orders(self, work_orders) -> list[tuple[WorkOrder, int]]:
        """Urutkan work order menurun berdasarkan skor (tie-break: kode WO asc)."""
        if work_orders is None:
            raise PrioritySchedulerError("work_orders wajib diisi.")

        scored = [(work_order, self.compute_priority(work_order)) for work_order in work_orders]
        scored.sort(key=lambda item: (-item[1], item[0].code))
        return scored

    def next_to_process(self, work_center: WorkCenter) -> Bundle | None:
        """Bundle berikutnya di queue WC-nya (tie-break `updated_at` asc)."""
        if work_center is None:
            raise PrioritySchedulerError("work_center wajib diisi.")

        bundles = list(
            WCQueue()
            .get_queue(work_center)
            .select_related(
                "work_order", "work_order__order_line", "work_order__order_line__order"
            )
        )
        if not bundles:
            return None

        bundles.sort(
            key=lambda bundle: (
                -self.compute_priority(bundle.work_order),
                bundle.updated_at,
                bundle.pk,
            )
        )
        return bundles[0]
