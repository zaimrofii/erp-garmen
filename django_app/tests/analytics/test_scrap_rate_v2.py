"""Test formula scrap_rate v2 (kohort DONE). Tanpa LLM."""

from __future__ import annotations

import pytest

from apps_industry.garment.models import (
    Bundle,
    WorkCenter,
    WorkOrder,
    Order,
    OrderLine,
    ScrapAccumulator,
)
from integrations.analytics.plugins.garment.metrics import scrap_rate
from master.models import Partner, Product


def _bundle(code: str, state: str, qty: int, qty_done: int, wc: WorkCenter) -> Bundle:
    partner, _ = Partner.objects.get_or_create(code="S-CUST", defaults={"name": "C"})
    product, _ = Product.objects.get_or_create(
        code="S-PROD", defaults={"name": "P", "sale_price": 1000}
    )
    order = Order.objects.create(code=f"ORD-{code}", customer=partner, state="DONE")
    line = OrderLine.objects.create(order=order, product=product, qty=qty, price_unit=1000)
    work_order = WorkOrder.objects.create(
        code=f"WO-{code}", order_line=line, qty_planned=qty
    )
    return Bundle.objects.create(
        code=code,
        work_order=work_order,
        qty=qty,
        qty_done=qty_done,
        state=state,
        current_work_center=wc,
    )


@pytest.fixture()
def wc(db) -> WorkCenter:
    return WorkCenter.objects.create(code="WC-T", name="Test WC", wc_type="sewing")


@pytest.mark.django_db
def test_done_bundle_scrap_lebih_besar_di_clamp_100(wc):
    bundle = _bundle("B-CLAMP", "DONE", 10, 10, wc)
    ScrapAccumulator.objects.create(work_center=wc, bundle=bundle, qty=20)
    rows = scrap_rate.METRIC.compute({"group_by": "period", "granularity": "day"})
    assert rows and rows[0]["value"] <= 100.0
    assert rows[0]["numerator"] == 20
    assert rows[0]["denominator"] == 10


@pytest.mark.django_db
def test_bundle_belum_done_tidak_dihitung(wc):
    done = _bundle("B-DONE", "DONE", 10, 10, wc)
    pending = _bundle("B-PENDING", "SEWING", 10, 10, wc)
    ScrapAccumulator.objects.create(work_center=wc, bundle=done, qty=5)
    ScrapAccumulator.objects.create(work_center=wc, bundle=pending, qty=50)
    rows = scrap_rate.METRIC.compute({"group_by": "period", "granularity": "day"})
    total = sum(row["numerator"] for row in rows)
    assert total == 5
    assert all(row["value"] <= 100.0 for row in rows)


@pytest.mark.django_db
def test_denominator_nol_mengembalikan_nol(wc):
    bundle = _bundle("B-ZERO", "DONE", 10, 0, wc)
    ScrapAccumulator.objects.create(work_center=wc, bundle=bundle, qty=3)
    rows = scrap_rate.METRIC.compute({"group_by": "period", "granularity": "day"})
    assert rows
    assert rows[0]["denominator"] == 0
    assert rows[0]["value"] == 0
