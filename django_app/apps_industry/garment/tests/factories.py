"""Helper pembuat data uji service garmen (bukan modul test).

Dipakai `tests/test_*.py` supaya fixture data (produk -> order -> order line ->
work order -> bundle, routing/step, line produksi, rule tag router) tidak ditulis
berulang. Nama file tidak diawali `test`, jadi tidak ikut dipungut test runner.
"""

from __future__ import annotations

import itertools

from apps_industry.garment.models import (
    Bundle,
    Order,
    OrderLine,
    ProcessRouting,
    ProductionLine,
    RoutingStep,
    ScrapAccumulator,
    WorkCenter,
    WorkOrder,
)
from core.rule_engine.models import Rule, RuleAction, RuleCondition
from master.models import Product

#: Counter proses untuk kode default yang unik antar test (tanpa perlu state DB).
_seq = itertools.count(1)


def _auto_code(prefix: str) -> str:
    """Kode unik untuk data uji, mis. ``ORD-00003``."""
    return f"{prefix}-{next(_seq):05d}"


def make_product(code: str | None = None, name="Kaos Polos"):
    """Produk master sederhana."""
    return Product.objects.create(code=code or _auto_code("TS"), name=name)


def make_order(code: str | None = None, **kwargs):
    """Order header (customer opsional, tipe default EXPORT)."""
    return Order.objects.create(code=code or _auto_code("ORD"), **kwargs)


def make_order_line(order=None, product=None, tag="FAST_TRACK", qty=10, **kwargs):
    """Order line lengkap dengan order + product otomatis."""
    return OrderLine.objects.create(
        order=order or make_order(),
        product=product or make_product(),
        tag=tag,
        qty=qty,
        **kwargs,
    )


def make_work_order(order_line=None, code: str | None = None, **kwargs):
    """Work order (order line dibuat otomatis kalau tidak diisi)."""
    return WorkOrder.objects.create(
        code=code or _auto_code("WO"),
        order_line=order_line or make_order_line(),
        **kwargs,
    )


def make_work_center(code: str | None = None, **kwargs):
    """Work center dengan nama = code."""
    code = code or _auto_code("WC")
    return WorkCenter.objects.create(code=code, name=code, **kwargs)


def make_bundle(work_order=None, code: str | None = None, qty=5, **kwargs):
    """Bundle (work order dibuat otomatis kalau tidak diisi)."""
    return Bundle.objects.create(
        code=code or _auto_code("BND"),
        work_order=work_order or make_work_order(),
        qty=qty,
        **kwargs,
    )


def make_routing(code: str | None = None, **kwargs):
    """Process routing aktif."""
    code = code or _auto_code("ROUTE")
    return ProcessRouting.objects.create(code=code, name=code, **kwargs)


def make_step(routing, code, order, **kwargs):
    """Routing step (node DAG) pada sebuah routing."""
    return RoutingStep.objects.create(routing=routing, code=code, order=order, **kwargs)


def make_line(code: str | None = None, work_centers=()):
    """Line produksi + work center yang tergabung di dalamnya."""
    code = code or _auto_code("LINE")
    line = ProductionLine.objects.create(code=code, name=code)
    if work_centers:
        line.work_centers.add(*work_centers)
    return line


def make_scrap_accumulator(work_center=None, bundle=None, **kwargs):
    """Catatan QC (scrap/rework/end-loss) — dipakai resource `qc`."""
    return ScrapAccumulator.objects.create(
        work_center=work_center or make_work_center(),
        bundle=bundle,
        **kwargs,
    )


def make_priority_rule(code, value, priority=0, tag="FAST_TRACK", is_active=True):
    """Rule prioritas: kondisi `tag EQ` + aksi SET_PRIORITY (`params["value"]`).

    `code` otomatis diberi prefix ``priority.`` kalau belum ada (prefix inilah
    yang dipakai `PriorityScheduler`).
    """
    if not code.startswith("priority."):
        code = f"priority.{code}"

    rule = Rule.objects.create(
        code=code, name=code, priority=priority, is_active=is_active
    )
    RuleCondition.objects.create(
        rule=rule,
        field="tag",
        operator=RuleCondition.Operator.EQ,
        value=tag,
        order=0,
    )
    RuleAction.objects.create(
        rule=rule, action_type="SET_PRIORITY", params={"value": value}
    )
    return rule


def make_tag_rule(
    code,
    routing_code=None,
    ticket_format=None,
    priority=0,
    tag="FAST_TRACK",
    is_active=True,
):
    """Rule tag router: kondisi `tag EQ` + aksi ROUTING_SELECT / TICKET_ISSUE.

    `code` otomatis diberi prefix ``tag_router.`` kalau belum ada (prefix inilah
    yang dipakai `TagRouter` untuk memilih rule).
    """
    if not code.startswith("tag_router."):
        code = f"tag_router.{code}"

    rule = Rule.objects.create(
        code=code, name=code, priority=priority, is_active=is_active
    )
    RuleCondition.objects.create(
        rule=rule,
        field="tag",
        operator=RuleCondition.Operator.EQ,
        value=tag,
        order=0,
    )
    if routing_code:
        RuleAction.objects.create(
            rule=rule,
            action_type="ROUTING_SELECT",
            params={"routing_code": routing_code},
        )
    if ticket_format:
        RuleAction.objects.create(
            rule=rule,
            action_type="TICKET_ISSUE",
            params={"ticket_format": ticket_format},
        )
    return rule
