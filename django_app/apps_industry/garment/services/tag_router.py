"""TagRouter — resolusi tag order menjadi rencana routing + kupon (Sprint 2.2).

Tag pada `OrderLine` (mis. "FAST_TRACK", "EXPORT", "CUSTOM") dipetakan ke
routing & kupon lewat **Rule** di `core.rule_engine` (data, bukan `if` di kode):

  * rule aktif dengan prefix code ``tag_router.`` dipakai lebih dulu;
  * kalau belum ada rule ber-prefix itu, semua rule aktif ikut dievaluasi
    (memudahkan pengujian/onboarding awal);
  * aksi ``ROUTING_SELECT`` (``params.routing_code``) -> pilih `ProcessRouting`;
  * aksi ``TICKET_ISSUE`` (``params.ticket_format``) -> susun kode kupon.

Service ini **murni** (tidak menyimpan apa pun): `order_line.ticket_code` dan
penyimpanan routing dilakukan pemanggil (API Fase 3).

Placeholder kupon dibatasi whitelist dan diganti dengan `str.replace` — tanpa
`eval`/`str.format` (format string bisa menelusuri atribut objek):
``{order_line_id}``, ``{order_code}``, ``{product_code}``, ``{qty}``, ``{tag}``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.rule_engine.models import Rule
from core.rule_engine.services import RuleEngine

from apps_industry.garment.models import OrderLine, ProcessRouting
from apps_industry.garment.services.exceptions import TagRouterError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingPlan:
    """Hasil resolusi tag: routing terpilih + kupon + rule yang match."""

    routing: ProcessRouting | None
    piece_rate_ticket: str | None
    matched_rule: str | None
    reason: str


class TagRouter:
    """Pemetaan tag -> routing/kupon berbasis rule (stateless)."""

    ROUTE_ACTION = "ROUTING_SELECT"
    TICKET_ACTION = "TICKET_ISSUE"
    RULE_PREFIX = "tag_router."
    TICKET_TOKENS = ("order_line_id", "order_code", "product_code", "qty", "tag")

    def __init__(self, engine: RuleEngine | None = None):
        self._engine = engine or RuleEngine()

    def resolve(self, order_line: OrderLine) -> RoutingPlan:
        """Tentukan rencana routing + kupon untuk satu `OrderLine`."""
        if order_line is None:
            raise TagRouterError("order_line wajib diisi.")

        context = {
            "tag": order_line.tag,
            "qty": order_line.qty,
            "order_type": order_line.order.order_type,
        }
        rules = self._tag_rules()
        results = self._engine.evaluate_all(
            context,
            rule_codes=[rule.code for rule in rules] if rules else None,
        )

        for result in results:
            if not result.matched:
                continue
            routing_code, ticket_format = self._extract_actions(result.actions)
            if routing_code is None and ticket_format is None:
                continue  # rule match, tapi bukan rule untuk tag router

            routing = self._resolve_routing(routing_code) if routing_code else None
            ticket = (
                self._render_ticket(ticket_format, order_line) if ticket_format else None
            )
            plan = RoutingPlan(
                routing=routing,
                piece_rate_ticket=ticket,
                matched_rule=result.rule.code if result.rule else None,
                reason=result.reason,
            )
            logger.info("tag router: order line %s -> %s", order_line.pk, plan)
            return plan

        return RoutingPlan(
            routing=None,
            piece_rate_ticket=None,
            matched_rule=None,
            reason="tidak ada rule tag router yang match untuk tag ini.",
        )

    # ----------------------------------------------------------------- helpers
    def _tag_rules(self) -> list[Rule]:
        """Rule aktif untuk tag router, urut `priority` lalu `code`."""
        return list(
            Rule.objects.filter(
                is_active=True, code__startswith=self.RULE_PREFIX
            ).order_by("priority", "code")
        )

    @classmethod
    def _extract_actions(cls, actions: list[dict]) -> tuple[str | None, str | None]:
        """Ambil `routing_code` & `ticket_format` dari daftar aksi rule."""
        routing_code: str | None = None
        ticket_format: str | None = None
        for action in actions:
            params = action.get("params") or {}
            if action.get("action_type") == cls.ROUTE_ACTION:
                routing_code = params.get("routing_code")
            elif action.get("action_type") == cls.TICKET_ACTION:
                ticket_format = params.get("ticket_format")
        return routing_code, ticket_format

    @staticmethod
    def _resolve_routing(routing_code: str) -> ProcessRouting:
        routing = ProcessRouting.objects.filter(
            code=routing_code, is_active=True
        ).first()
        if routing is None:
            raise TagRouterError(
                f"routing '{routing_code}' tidak ditemukan atau tidak aktif."
            )
        return routing

    @classmethod
    def _render_ticket(cls, ticket_format: str, order_line: OrderLine) -> str:
        """Susun kode kupon dari format string (hanya placeholder whitelist)."""
        values = {
            "order_line_id": order_line.pk,
            "order_code": order_line.order.code,
            "product_code": order_line.product.code,
            "qty": order_line.qty,
            "tag": order_line.tag,
        }
        text = str(ticket_format)
        for token in cls.TICKET_TOKENS:
            text = text.replace("{" + token + "}", str(values[token]))

        if "{" in text or "}" in text:
            raise TagRouterError(
                f"ticket_format '{ticket_format}' memakai placeholder tidak dikenal; "
                f"yang tersedia: {', '.join(cls.TICKET_TOKENS)}."
            )
        return text
