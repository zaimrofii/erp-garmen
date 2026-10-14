"""Endpoint **monitoring read-only** (FASE 4.4) — invoice & SyncRecord.

Dua endpoint baca-saja untuk frontend monitoring (TIDAK ada mutasi):

* ``GET /api/v1/finance/invoices/``  → :class:`InvoiceListView`
  Daftar antrean invoice = ``SyncRecord(resource="order", stage="INVOICE")``
  (satu ``Order`` = satu invoice, lihat `services/invoice_sync.py`) di-join ke
  ``Order`` lewat ``resource_id``.
* ``GET /api/v1/sync/records/``      → :class:`SyncRecordListView`
  Daftar ``SyncRecord`` apa pun (filter opsional ``stage`` / ``status``).

Catatan desain:

* **Auth** ``IsAuthenticated`` (konsisten endpoint sync/monitoring lain, FASE 4.1).
* **Paging** offset-based (``limit`` + ``cursor``) seperti `ResourceListView`
  kontrak §3 — ``cursor`` = offset baris berikutnya (``next_cursor``).
* ``SyncRecord.resource_id`` bertipe **string** sedangkan ``Order.pk`` integer →
  di-cast; ``resource_id`` yang bukan angka dianggap **orphan** (``order_no=None``).
* Param ``state`` pada endpoint invoice di brief menyebut ``draft|posted`` (state
  invoice **Odoo**), tetapi repo **tidak menyimpan** state itu: payload record
  hanya ``{"order_id", "ref"}`` (lihat `InvoiceSyncService.enqueue`). Jadi
  ``state`` di sini diartikan sebagai filter **status sync** (``PENDING``/
  ``SENT``/``FAILED``/``DUPLICATE``, case-insensitive) — lihat laporan.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, DecimalField, F, Max, Min, Q, Sum
from django.db.models.functions import TruncMonth, TruncQuarter
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    CustomerInvoiceLine,
    JournalEntryLine,
    Order,
    OrderLine,
    Payment,
    ProcessRouting,
    ProductionLine,
    PurchaseOrder,
    PurchaseOrderLine,
    ScrapAccumulator,
    VendorBill,
    VendorBillLine,
    WorkCenter,
    WorkOrder,
)
from apps_industry.garment.services import (
    BottleneckDetector,
    ReworkLoopError,
    ReworkLoopHandler,
    TagRouter,
    TagRouterError,
    TwoStageAggregator,
    WCQueue,
)
from core.cycle_handler.models import CycleInstance
from master.models import Account, Location, Partner, Product

from .models import SyncRecord, SyncResource, SyncStage
from .transport import get_transport

logger = logging.getLogger(__name__)

__all__ = (
    "BufferQueueView",
    "DashboardSummaryView",
    "ExecutiveDashboardView",
    "InventoryOperationsView",
    "InventoryProductsView",
    "InventoryReportingView",
    "InvoiceListView",
    "PurchaseOrdersView",
    "PurchaseReportingView",
    "PurchaseVendorsView",
    "QualityAqlView",
    "QualityDefectsView",
    "QualityReworkView",
    "ReportsCogsView",
    "ReportsLeadTimeBundlesView",
    "ReportsLeadTimeView",
    "ReportsLineEfficiencyByWcView",
    "ReportsLineEfficiencyView",
    "ReportsOnTimeDeliveryOrdersView",
    "ReportsOnTimeDeliveryView",
    "ReportsPnlView",
    "ReportsProductionView",
    "ReportsPurchasesView",
    "ReportsSalesView",
    "ReportsStockView",
    "ReportsWipByWcView",
    "ReportsWipView",
    "RoutingGraphView",
    "SyncRecordListView",
)

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
DEFAULT_OFFSET = 0
MAX_OFFSET = 100000

#: Resource SyncRecord milik invoice (satu order = satu invoice).
INVOICE_RESOURCE = SyncResource.ORDER.value

#: State bundle yang dihitung pada blok ``bundles`` (kunci response, lowercase).
BUNDLE_STATE_KEYS = ("draft", "cutting", "sewing", "qc", "done")

#: State Order yang dianggap **terminal** -> tidak lagi "open" & tidak dihitung
#: overdue. Catatan: repo TIDAK men-seed state machine ``garment.order`` (baru
#: ``garment.bundle`` & ``garment.work_order`` di migration 0002), jadi daftar ini
#: = konvensi yang konsisten dengan state terminal ``garment.work_order``.
ORDER_TERMINAL_STATES = ("DONE", "CANCELLED")

#: Ambang queue WC untuk memunculkan alert (selaras default `BottleneckDetector`).
BOTTLENECK_QUEUE_THRESHOLD = 10

#: Ranking severity untuk pengurutan alert (kecil = lebih parah).
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _int_param(request, name: str, default: int, minimum: int, maximum: int):
    """PURE — baca query param angka → ``(value, error_message)``."""
    raw = request.query_params.get(name)
    if raw in (None, ""):
        return default, None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None, f"Parameter '{name}' harus berupa angka."
    if value < minimum or value > maximum:
        return None, f"Parameter '{name}' harus antara {minimum} dan {maximum}."
    return value, None


def _iso(value) -> str | None:
    """ISO-8601 dari datetime; ``None`` kalau kosong."""
    return value.isoformat() if value else None


def _page(queryset, offset: int, limit: int):
    """``(rows, total, has_next)`` — paging offset-based."""
    total = queryset.count()
    rows = list(queryset[offset : offset + limit])
    return rows, total, offset + len(rows) < total


def _envelope(rows: list, total: int, has_next: bool, offset: int) -> dict:
    """Amplop list: ``{rows, total_count, has_next, next_cursor}``."""
    return {
        "rows": rows,
        "total_count": total,
        "has_next": has_next,
        "next_cursor": (offset + len(rows)) if has_next else None,
    }


class SyncRecordListView(APIView):
    """``GET /api/v1/sync/records/`` — daftar ``SyncRecord`` (filter opsional)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Balas ``{rows, total_count, has_next, next_cursor}`` (urut terbaru dulu)."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = SyncRecord.objects.all()

        stage = str(request.query_params.get("stage") or "").strip()
        if stage:
            queryset = queryset.filter(stage__iexact=stage)

        record_status = str(request.query_params.get("status") or "").strip()
        if record_status:
            queryset = queryset.filter(status__iexact=record_status)

        rows, total, has_next = _page(
            queryset.order_by("-created_at", "-id"), offset, limit
        )
        return Response(_envelope([self._row(r) for r in rows], total, has_next, offset))

    @staticmethod
    def _row(record: SyncRecord) -> dict:
        """Satu baris `SyncRecord` (bentuk kontrak monitoring)."""
        return {
            "id": record.pk,
            "resource": record.resource,
            "resource_id": record.resource_id,
            "stage": record.stage,
            "status": record.status,
            "attempts": record.attempts,
            "last_error": record.last_error,
            "erp_id": record.erp_id,
            "sent_at": _iso(record.sent_at),
            "created_at": _iso(record.created_at),
        }


class InvoiceListView(APIView):
    """``GET /api/v1/finance/invoices/`` — antrean invoice (SyncRecord + Order)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Balas ``{rows, total_count, has_next, next_cursor}``.

        Baris: ``{order_id, order_no, invoice_status, erp_id, attempts,
        last_error, sent_at, created_at}``. Order yang tidak ada (orphan) →
        ``order_no = None``.
        """
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        queryset = SyncRecord.objects.filter(
            stage=SyncStage.INVOICE.value, resource=INVOICE_RESOURCE
        )

        # `state` = filter status sync (PENDING/SENT/FAILED/DUPLICATE) — repo tidak
        # menyimpan state invoice Odoo (draft/posted); lihat docstring modul.
        state = str(request.query_params.get("state") or "").strip()
        if state:
            queryset = queryset.filter(status__iexact=state)

        rows, total, has_next = _page(
            queryset.order_by("-created_at", "-id"), offset, limit
        )
        orders = self._orders_for(rows)

        payload_rows = []
        for record in rows:
            order_id = self._cast_order_id(record.resource_id)
            order = orders.get(order_id)
            payload_rows.append(
                {
                    "order_id": order_id,
                    "order_no": order.code if order is not None else None,
                    "invoice_status": record.status,
                    "erp_id": record.erp_id,
                    "attempts": record.attempts,
                    "last_error": record.last_error,
                    "sent_at": _iso(record.sent_at),
                    "created_at": _iso(record.created_at),
                }
            )

        return Response(_envelope(payload_rows, total, has_next, offset))

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _cast_order_id(resource_id) -> int | None:
        """``SyncRecord.resource_id`` (string) → ``Order.pk`` (int); ``None`` bila bukan angka."""
        try:
            return int(str(resource_id))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _orders_for(cls, records: list) -> dict:
        """``{order_pk: Order}`` untuk semua ``resource_id`` (hindari N+1)."""
        order_ids = [
            order_id
            for order_id in (cls._cast_order_id(record.resource_id) for record in records)
            if order_id is not None
        ]
        if not order_ids:
            return {}
        return {order.pk: order for order in Order.objects.filter(pk__in=order_ids)}


# ---------------------------------------------------------------------------
# Dashboard summary (F1 / B1) — helper agregat murni DB (tanpa Odoo)
# ---------------------------------------------------------------------------
def _today_start():
    """Awal hari (00:00) menurut timezone aktif (WIB) -> datetime aware."""
    now = timezone.localtime(timezone.now())
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _bundle_counts() -> dict:
    """Jumlah bundle per state (satu query agregat) untuk 5 state dikenal.

    State di luar `BUNDLE_STATE_KEYS` diabaikan (tidak menambah kunci response),
    sehingga bentuk response selalu punya kunci yang sama.
    """
    counts = {key: 0 for key in BUNDLE_STATE_KEYS}
    for row in Bundle.objects.values("state").annotate(total=Count("id")):
        key = str(row["state"] or "").strip().lower()
        if key in counts:
            counts[key] = row["total"]
    return counts


def _terminal_work_center_ids() -> set[int]:
    """Set id work center yang dipakai step terminal routing aktif (1-2 query).

    Pengganti BATCH untuk `TwoStageAggregator.is_terminal_work_center()` yang
    sebelumnya dipanggil per bundle (N+1). Hasilnya identik dengan
    ``routing.steps.filter(work_center=wc, is_terminal=True).exists()``.
    """
    routing = ProcessRouting.objects.filter(is_active=True).order_by("id").first()
    if routing is None:
        return set()
    return set(
        routing.steps.filter(is_terminal=True).values_list("work_center_id", flat=True)
    )


def _floor_bundles():
    """QuerySet bundle di lantai + relasi staging (`select_related`, tanpa N+1).

    Scope = bundle dengan ``current_work_center`` terisi dan produk pada order
    line-nya (agregator butuh ``order_line.product``) — sama seperti sebelumnya.
    """
    return (
        Bundle.objects.filter(
            current_work_center__isnull=False,
            work_order__order_line__product__isnull=False,
        )
        .select_related("current_work_center", "work_order__order_line__product")
        .order_by("code")
    )


def _wip_fg_qty() -> tuple[int, int]:
    """Total qty WIP & FG — **1 query agregat** (bukan loop Python per bundle).

    Stage mengikuti `TwoStageAggregator`: bundle di WC step terminal → **FG**
    (qty ``qty_done``), selain itu **WIP** (qty ``qty``). Sebelum F5.2 fungsi ini
    memanggil ``build_payload()`` per bundle → 2 query per bundle (N+1).
    """
    terminal_ids = _terminal_work_center_ids()
    totals = _floor_bundles().aggregate(
        wip_qty=Sum("qty", filter=~Q(current_work_center_id__in=terminal_ids)),
        fg_qty=Sum("qty_done", filter=Q(current_work_center_id__in=terminal_ids)),
    )
    return totals["wip_qty"] or 0, totals["fg_qty"] or 0


def _order_counts() -> dict:
    """``{open, overdue}`` — overdue = deadline lewat & state masih non-terminal."""
    open_orders = Order.objects.exclude(state__in=ORDER_TERMINAL_STATES)
    return {
        "open": open_orders.count(),
        "overdue": open_orders.filter(
            deadline__isnull=False, deadline__lt=timezone.now()
        ).count(),
    }


def _scrap_qty_today() -> int:
    """Total ``ScrapAccumulator.qty`` yang dibuat sejak 00:00 WIB hari ini."""
    total = ScrapAccumulator.objects.filter(
        created_at__gte=_today_start()
    ).aggregate(total=Sum("qty"))["total"]
    return total or 0


def _alerts() -> list[dict]:
    """Alert bottleneck: satu per WC dengan queue > ambang (**1 query agregat**).

    ``depth`` = jumlah bundle belum ``DONE``/``CANCELLED`` pada WC tsb — semantik
    identik ``BottleneckDetector.detect().queue_depth``, yang sebelum F5.2
    dihitung **satu query per work center** (N+1). Ambang tetap diambil dari
    :class:`BottleneckDetector` supaya tidak ada dua sumber kebenaran.
    ``severity`` = ``high`` bila queue >= 2x ambang, selain itu ``medium``.
    """
    detector = BottleneckDetector(queue_depth_threshold=BOTTLENECK_QUEUE_THRESHOLD)
    threshold = detector.queue_depth_threshold

    depths = (
        Bundle.objects.exclude(state__in=WCQueue.EXCLUDED_STATES)
        .filter(current_work_center__isnull=False)
        .values("current_work_center__code")
        .annotate(depth=Count("id"))
    )

    alerts: list[dict] = []
    for row in depths:
        depth = row["depth"]
        if depth <= threshold:
            continue
        code = str(row["current_work_center__code"] or "")
        alerts.append(
            {
                "code": f"BOTTLENECK_{code}",
                "message": (
                    f"Work center {code} punya antrean {depth} "
                    f"bundle (ambang {threshold})."
                ),
                "severity": "high" if depth >= threshold * 2 else "medium",
            }
        )
    alerts.sort(
        key=lambda alert: (_SEVERITY_RANK.get(alert["severity"], 3), alert["code"])
    )
    return alerts


#: Jumlah hari pada series `trend` dashboard (G1).
TREND_DAYS = 7


def _efficiency_pct_for(from_dt, to_dt, days: int) -> float:
    """Rata-rata ``efficiency_pct`` per WC yang punya bundle selesai (reuse B13).

    Memakai `_line_efficiency_durations` + `_target_per_day` (logika yang SAMA
    dengan `ReportsLineEfficiencyView`) supaya angka konsisten. ``0.0`` bila tak
    ada WC dengan bundle selesai pada rentang.
    """
    buckets = _line_efficiency_durations(from_dt, to_dt)
    if not buckets:
        return 0.0

    work_centers = {wc.pk: wc for wc in WorkCenter.objects.filter(pk__in=buckets.keys())}
    values: list[float] = []
    for wc_id, (done, _total_minutes) in buckets.items():
        work_center = work_centers.get(wc_id)
        if work_center is None or done <= 0:
            continue
        capacity = _target_per_day(work_center) * days
        if capacity:
            values.append(done / capacity * 100)

    return round(sum(values) / len(values), 1) if values else 0.0


def _line_efficiency_summary() -> dict:
    """``{pct, delta}`` — efisiensi hari ini + selisih vs 7 hari sebelumnya.

    ``delta`` dalam **persen poin** (``pct`` hari ini − ``pct`` rata-rata 7 hari
    terakhir sebelumnya).
    """
    today = _today_start()
    pct_today = _efficiency_pct_for(today, timezone.now(), 1)
    pct_prev = _efficiency_pct_for(today - timedelta(days=TREND_DAYS), today, TREND_DAYS)
    return {"pct": pct_today, "delta": round(pct_today - pct_prev, 1)}


def _daily_trend() -> list[dict]:
    """Series ``TREND_DAYS`` hari terakhir (ascending): ``[{date, wip, fg}]``.

    Snapshot akhir hari memakai ``BundleEvent.ts``: bundle dianggap **FG** bila
    ``BUNDLE_FINISH`` sudah terjadi ``<=`` akhir hari; selain itu **WIP** bila
    ``BUNDLE_START`` sudah terjadi. Hari tanpa data → ``{"wip": 0, "fg": 0}``.
    """
    events = list(
        BundleEvent.objects.filter(
            event_type__in=(BUNDLE_START_EVENT, BUNDLE_FINISH_EVENT)
        ).values_list("bundle_id", "event_type", "ts")
    )

    starts: dict = {}
    finishes: dict = {}
    for bundle_id, event_type, ts in events:
        if event_type == BUNDLE_START_EVENT:
            if bundle_id not in starts or ts < starts[bundle_id]:
                starts[bundle_id] = ts
        elif bundle_id not in finishes or ts < finishes[bundle_id]:
            finishes[bundle_id] = ts

    qtys = {
        row["id"]: row
        for row in Bundle.objects.filter(pk__in=set(starts) | set(finishes)).values(
            "id", "qty", "qty_done"
        )
    }

    today = timezone.localtime(timezone.now()).date()
    trend: list[dict] = []
    for offset in range(TREND_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        day_end = timezone.make_aware(datetime.combine(day, time.max))
        wip = 0
        fg = 0
        for bundle_id, qty_row in qtys.items():
            finish_ts = finishes.get(bundle_id)
            start_ts = starts.get(bundle_id)
            if finish_ts is not None and finish_ts <= day_end:
                fg += qty_row["qty_done"] or 0
            elif start_ts is not None and start_ts <= day_end:
                wip += qty_row["qty"] or 0
        trend.append({"date": day.isoformat(), "wip": wip, "fg": fg})
    return trend


class DashboardSummaryView(APIView):
    """``GET /api/v1/dashboard/summary/`` — ringkasan agregat lantai produksi.

    **Read-only**, murni DB Django (tidak memanggil Odoo, tanpa model baru).
    Bentuk response (kunci persis)::

        {
          "bundles": {"draft": N, "cutting": N, "sewing": N, "qc": N, "done": N},
          "wip_qty": N,
          "fg_qty": N,
          "orders": {"open": N, "overdue": N},
          "scrap_qty_today": N,
          "alerts": [{"code": "...", "message": "...", "severity": "high|medium|low"}],
          "line_efficiency": {"pct": float, "delta": float},
          "trend": [{"date": "YYYY-MM-DD", "wip": N, "fg": N}],
          "generated_at": "ISO-8601"
        }

    * ``wip_qty``/``fg_qty`` dihitung lewat :class:`TwoStageAggregator` supaya
      definisi WIP/FG konsisten dengan sync stok ERP (bukan query ad-hoc);
    * ``orders.overdue`` = ``Order.deadline`` lewat **dan** ``Order.state``
      non-terminal (``ORDER_TERMINAL_STATES``);
    * ``scrap_qty_today`` = akumulasi ``ScrapAccumulator.qty`` sejak 00:00 WIB;
    * ``alerts`` = alert bottleneck per work center (queue > ambang; default 10).
      Sejak F5.2 depth dihitung **1 query agregat** (semantik sama dengan
      :class:`BottleneckDetector`, yang dipakai sebagai sumber ambang);
    * ``line_efficiency`` (G1, **aditif**) = ``{pct, delta}`` — rata-rata
      ``efficiency_pct`` WC yang punya bundle selesai (reuse logika B13) + selisih
      vs rata-rata 7 hari sebelumnya (persen poin);
    * ``trend`` (G1, **aditif**) = series 7 hari terakhir ``[{date, wip, fg}]``
      (snapshot akhir hari lewat ``BundleEvent.ts``).

    Permission ``IsAuthenticated`` (konsisten endpoint monitoring/sync lain) →
    anonim **403**; method selain ``GET`` → **405** otomatis.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Susun ringkasan; lihat docstring kelas."""
        wip_qty, fg_qty = _wip_fg_qty()
        payload = {
            "bundles": _bundle_counts(),
            "wip_qty": wip_qty,
            "fg_qty": fg_qty,
            "orders": _order_counts(),
            "scrap_qty_today": _scrap_qty_today(),
            "alerts": _alerts(),
            "line_efficiency": _line_efficiency_summary(),
            "trend": _daily_trend(),
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
        }
        logger.info(
            "dashboard summary: wip=%s fg=%s open=%s overdue=%s alerts=%s",
            wip_qty,
            fg_qty,
            payload["orders"]["open"],
            payload["orders"]["overdue"],
            len(payload["alerts"]),
        )
        return Response(payload)


# ---------------------------------------------------------------------------
# Buffer queue (F1 / B2) — GET /api/v1/production/buffer-queue/
# ---------------------------------------------------------------------------
#: Maksimum bundle yang ditampilkan per work center (urut waited_min DESC).
BUFFER_QUEUE_MAX_BUNDLES = 10


def _minutes_since(moment) -> float:
    """Selisih ``(now - moment)`` dalam menit (float, belum dibulatkan)."""
    return (timezone.now() - moment).total_seconds() / 60


def _routing_wc_neighbors(routing) -> dict[int, tuple[str | None, str | None]]:
    """`{wc_id: (prev_code, next_code)}` dari **satu** fetch step routing.

    Pengganti pemanggilan `_prev_wc_code`/`_next_wc_code` per bundle (yang
    masing-masing 2-3 query → N+1 di buffer-queue). Semantik **sama**:

      * ``next`` = ``allowed_next_steps`` pertama (urut ``order``, ``id``) bila ada,
        kalau tidak step dengan ``order`` berikutnya; ``None`` di step terminal;
      * ``prev`` = WC ``rework_target_step`` bila diisi (bucket rework), kalau tidak
        step dengan ``order`` sebelumnya; ``None`` di step pertama.
    """
    if routing is None:
        return {}

    steps = list(
        routing.steps.select_related("work_center", "rework_target_step__work_center")
        .prefetch_related("allowed_next_steps__work_center")
        .order_by("order", "id")
    )

    neighbors: dict[int, tuple[str | None, str | None]] = {}
    for step in steps:
        if step.work_center_id is None:
            continue

        next_step = None
        if not step.is_terminal:
            allowed = sorted(
                step.allowed_next_steps.all(), key=lambda item: (item.order, item.id)
            )
            if allowed:
                next_step = allowed[0]
            else:
                next_step = next(
                    (
                        candidate
                        for candidate in steps
                        if candidate.order > step.order
                    ),
                    None,
                )

        prev_step = None
        if step.rework_target_step_id is not None:
            target = step.rework_target_step
            if target is not None and target.work_center_id is not None:
                prev_step = target
        if prev_step is None:
            prev_step = next(
                (
                    candidate
                    for candidate in reversed(steps)
                    if candidate.order < step.order
                ),
                None,
            )

        neighbors[step.work_center_id] = (
            (
                prev_step.work_center.code
                if prev_step is not None and prev_step.work_center_id is not None
                else None
            ),
            (
                next_step.work_center.code
                if next_step is not None and next_step.work_center_id is not None
                else None
            ),
        )

    return neighbors


def _buffer_queue_rows() -> list[dict]:
    """Antrean aktif per work center — **batch** (1 query bundle + 1 query WC).

    Scope = bundle yang punya ``current_work_center`` dan belum
    ``DONE``/``CANCELLED`` (lihat ``WCQueue.EXCLUDED_STATES``). Work center tanpa
    bundle aktif **dilewati** (tidak ditampilkan dengan ``queue_depth`` 0).

    Sebelum F5.2 queue diambil **per work center** dan ``from_wc``/``to_wc``
    dihitung per bundle (ratusan query); sekarang 1 pass ordered
    ``(updated_at, id)`` lalu group di Python — urutan & nilai tetap sama.
    """
    routing = TwoStageAggregator().routing
    neighbors = _routing_wc_neighbors(routing)

    active = (
        Bundle.objects.exclude(state__in=WCQueue.EXCLUDED_STATES)
        .filter(current_work_center__isnull=False)
        .select_related("current_work_center")
        .order_by("updated_at", "id")
    )
    grouped: dict[int, list[Bundle]] = {}
    for bundle in active:
        grouped.setdefault(bundle.current_work_center_id, []).append(bundle)

    work_centers = {wc.pk: wc for wc in WorkCenter.objects.filter(pk__in=list(grouped))}

    rows: list[dict] = []
    for wc_id, bundles in grouped.items():
        work_center = work_centers.get(wc_id)
        if work_center is None:
            continue
        waits = {bundle.pk: _minutes_since(bundle.updated_at) for bundle in bundles}
        top = sorted(bundles, key=lambda bundle: waits[bundle.pk], reverse=True)[
            :BUFFER_QUEUE_MAX_BUNDLES
        ]
        # G2 (aditif): `from_wc`/`to_wc` dari ROUTING (bukan event — `BundleEvent`
        # tak menyimpan WC); `from_wc` = step sebelumnya (atau rework_target).
        prev_code, next_code = neighbors.get(work_center.pk, (None, None))
        rows.append(
            {
                "wc_code": work_center.code,
                "wc_name": work_center.name,
                "queue_depth": len(bundles),
                "avg_wait_min": round(sum(waits.values()) / len(bundles), 1),
                "bundles": [
                    {
                        "code": bundle.code,
                        "qty": bundle.qty,
                        "waited_min": round(waits[bundle.pk], 1),
                        "state": bundle.state,
                        "from_wc": prev_code,
                        "to_wc": next_code,
                        "status": bundle.state,
                    }
                    for bundle in top
                ],
            }
        )
    rows.sort(key=lambda row: row["wc_code"])
    return rows


class BufferQueueView(APIView):
    """``GET /api/v1/production/buffer-queue/`` — antrean bundle per work center.

    Read-only, agregat DB murni (tanpa Odoo). Bentuk::

        {"rows": [{"wc_code", "wc_name", "queue_depth", "avg_wait_min",
                   "bundles": [{"code", "qty", "waited_min", "state",
                                "from_wc", "to_wc", "status"}]}],
         "generated_at": "ISO-8601"}

    * ``waited_min`` = ``(now - Bundle.updated_at)`` menit, 1 desimal;
    * ``avg_wait_min`` = rata-rata ``waited_min`` semua bundle aktif di WC itu;
    * ``bundles`` = maksimum 10 teratas, urut ``waited_min`` DESC;
    * queue diambil lewat :class:`WCQueue` (bundle belum ``DONE``/``CANCELLED``);
    * work center tanpa bundle aktif **tidak** muncul;
    * G2 (**aditif**) pada ``bundles[]``: ``status`` = ``Bundle.state``;
      ``to_wc`` = WC step berikutnya dari routing (``null`` di WC terminal);
      ``from_wc`` = WC step SEBELUMNYA dari routing (``null`` di step pertama);
      bucket rework memakai ``RoutingStep.rework_target_step``.
    * Routing diambil dari konvensi routing aktif pertama
      (``TwoStageAggregator.routing``) — `WorkOrder` **tidak** punya FK routing,
      jadi ``Bundle.work_order.routing_id`` tidak tersedia.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Susun antrean; lihat docstring kelas."""
        return Response(
            {
                "rows": _buffer_queue_rows(),
                "generated_at": timezone.localtime(timezone.now()).isoformat(),
            }
        )


# ---------------------------------------------------------------------------
# Routing graph (F1 / B3) — GET /api/v1/routing/graph/
# ---------------------------------------------------------------------------
#: `ProcessRouting` TIDAK punya field versi (versioning = bikin header baru,
#: lihat docstring model) → konstanta ini mengisi kontrak response.
ROUTING_GRAPH_VERSION = 1


def _routing_for_product(product_id) -> ProcessRouting | None:
    """Resolusi routing untuk `product_id` lewat `TagRouter` (rule tag → routing).

    Model **tidak** menghubungkan `Product` ke `ProcessRouting` secara langsung;
    pemetaan resmi ada di `TagRouter` (tag `OrderLine` → rule ``ROUTING_SELECT``).
    Ambil order line pertama produk tsb lalu `TagRouter.resolve`; `None` kalau
    tidak ada order line / tidak ada rule yang match.
    """
    try:
        product_pk = int(product_id)
    except (TypeError, ValueError):
        return None

    order_line = (
        OrderLine.objects.filter(product_id=product_pk)
        .select_related("order", "product")
        .order_by("id")
        .first()
    )
    if order_line is None:
        return None
    try:
        return TagRouter().resolve(order_line).routing
    except TagRouterError:
        return None


def _routing_nodes_edges(routing: ProcessRouting) -> tuple[list[dict], list[dict]]:
    """`(nodes, edges)` dari `RoutingStep`.

    * ``step_no`` = ``RoutingStep.order``;
    * ``label`` = ``RoutingStep.label`` (fallback ``code``) — model tidak punya
      ``name``/``wc_type``;
    * edges dari ``allowed_next_steps`` (``is_rework=false``) **plus**
      ``rework_target_step`` (``is_rework=true``);
    * ``overlap_pct`` = 0 (belum ada field overlap di model).
    """
    steps = list(
        routing.steps.select_related("rework_target_step")
        .prefetch_related("allowed_next_steps")
        .order_by("order", "id")
    )
    node_ids = {step.pk for step in steps}
    nodes = [
        {"id": step.pk, "label": step.label or step.code, "step_no": step.order}
        for step in steps
    ]

    edges: list[dict] = []
    for step in steps:
        for nxt in step.allowed_next_steps.all():
            if nxt.pk in node_ids:
                edges.append(
                    {
                        "from": step.pk,
                        "to": nxt.pk,
                        "overlap_pct": 0,
                        "is_rework": False,
                    }
                )
        if step.rework_target_step_id and step.rework_target_step_id in node_ids:
            edges.append(
                {
                    "from": step.pk,
                    "to": step.rework_target_step_id,
                    "overlap_pct": 0,
                    "is_rework": True,
                }
            )
    return nodes, edges


class RoutingGraphView(APIView):
    """``GET /api/v1/routing/graph/`` — graf DAG routing (nodes + edges).

    Query ``?product_id=<id>`` opsional: tanpa param → routing aktif pertama
    (``is_active=True``, by id); dengan param → routing hasil `TagRouter` untuk
    produk itu.

    Bentuk::

        {"routing_id", "routing_name", "version",
         "nodes": [{"id", "label", "step_no"}],
         "edges": [{"from", "to", "overlap_pct", "is_rework"}]}

    ``product_id`` ada tapi routing tidak ketemu → **404**
    ``{"detail": "routing not found"}``; tidak ada routing aktif sama sekali →
    **404** ``{"detail": "no active routing"}``.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun graf routing; lihat docstring kelas."""
        product_id = request.query_params.get("product_id")
        routing = None
        if product_id not in (None, ""):
            routing = _routing_for_product(product_id)
            if routing is None:
                return Response(
                    {"detail": "routing not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
        if routing is None:
            routing = (
                ProcessRouting.objects.filter(is_active=True).order_by("id").first()
            )
        if routing is None:
            return Response(
                {"detail": "no active routing"}, status=status.HTTP_404_NOT_FOUND
            )

        nodes, edges = _routing_nodes_edges(routing)
        return Response(
            {
                "routing_id": routing.pk,
                "routing_name": routing.name,
                "version": ROUTING_GRAPH_VERSION,
                "nodes": nodes,
                "edges": edges,
            }
        )


# ---------------------------------------------------------------------------
# Quality defects (F1 / B4) — GET /api/v1/quality/defects/
# ---------------------------------------------------------------------------
#: event_type aksi scrap di repo = ``BUNDLE_SCRAP`` (lihat
#: `api/actions/executor.py` → `_record_event` → `action_events.record_bundle_action`
#: yang menulis ``event_type=str(action_id)``). Token lama ``SCRAP`` tetap
#: diterima supaya klien/spec lama tidak pecah.
DEFECT_EVENT_TYPES = ("SCRAP", "BUNDLE_SCRAP")

#: F3A.3 (B7b) — event jejak untuk defect yang berujung **rework** (bukan scrap).
#: Ditulis oleh `QualityDefectsView.post`; `_defects_queryset` otomatis ikut
#: menangkapnya karena payload-nya memuat key ``defect_type``.
BUNDLE_QC_REWORK_EVENT = "BUNDLE_QC_REWORK"


class _ActionRequestShim:
    """Shim ``request`` minimal agar endpoint lain bisa memakai `ActionExecutor`.

    Hanya atribut yang benar-benar dibaca executor/builder yang disediakan:
    ``data`` (body aksi bentuk ``{"fields": {...}}``), ``user`` (untuk aktor
    `BundleEvent`), dan ``headers`` kosong (tanpa `Idempotency-Key`/`X-*`).
    Dengan ini logika scrap **tidak** diduplikasi di endpoint defect.
    """

    def __init__(self, request, fields: dict):
        self.user = getattr(request, "user", None)
        self.data = {"fields": dict(fields)}
        self.headers: dict = {}

    def __repr__(self) -> str:  # pragma: no cover - bantu debugging
        return f"<ActionRequestShim fields={sorted(self.data['fields'])}>"


def _defects_queryset(request):
    """QuerySet `BundleEvent` defect (filter opsional ``wc``), urut ``ts`` DESC.

    Sumber = event scrap (``event_type`` ``BUNDLE_SCRAP``/``SCRAP``) **atau**
    event apa pun yang ``payload``-nya punya key ``defect_type``.
    ``BundleEvent`` **tidak** punya ``wc_id`` → filter WC lewat bundle.
    """
    events = BundleEvent.objects.select_related(
        "bundle", "bundle__current_work_center"
    ).filter(
        Q(event_type__in=DEFECT_EVENT_TYPES) | Q(payload__has_key="defect_type")
    )

    wc = str(request.query_params.get("wc") or "").strip()
    if wc:
        events = events.filter(bundle__current_work_center__code=wc)
    return events.order_by("-ts")


def _defect_entries(payload: dict) -> list[dict]:
    """Detail per-cacat (G3, aditif).

    Kalau ``payload.defect_entries`` berupa list (non-kosong) → map langsung;
    kalau tidak → **fallback** 1 entry dari field flat (``defect_type``/``scrap_qty``/
    ``location``/``reason``).
    """
    raw = payload.get("defect_entries")
    if isinstance(raw, list):
        entries = [
            {
                "type": item.get("type", payload.get("defect_type", "unknown")),
                "qty": item.get("qty", 0),
                "location": item.get("location"),
                "note": item.get("note", payload.get("reason", "")),
            }
            for item in raw
            if isinstance(item, dict)
        ]
        if entries:
            return entries

    return [
        {
            "type": payload.get("defect_type", "unknown"),
            "qty": payload.get("scrap_qty", 0),
            "location": payload.get("location"),
            "note": payload.get("reason", ""),
        }
    ]


def _defect_action(event) -> str | None:
    """``"rework"``/``"scrap"``/``None`` (G3, aditif).

    ``payload.action`` dipakai lebih dulu bila valid; kalau tidak, diturunkan dari
    ``event_type`` (``BUNDLE_SCRAP`` → ``scrap``; event mengandung ``REWORK`` →
    ``rework``); selain itu ``None``.
    """
    payload = event.payload or {}
    action = payload.get("action")
    if action in ("rework", "scrap"):
        return action

    event_type = str(event.event_type or "").upper()
    if event_type == "BUNDLE_SCRAP":
        return "scrap"
    if "REWORK" in event_type:
        return "rework"
    return None


def _defect_row(event) -> dict:
    """Satu baris defect (``wc_code`` dari ``bundle.current_work_center``)."""
    payload = event.payload or {}
    bundle = event.bundle
    work_center = bundle.current_work_center if bundle else None
    return {
        "bundle_code": bundle.code if bundle else None,
        "wc_code": work_center.code if work_center else None,
        "defect_type": payload.get("defect_type", "unknown"),
        "qty": payload.get("scrap_qty", 0),
        "reason": payload.get("reason", ""),
        "recorded_at": _iso(event.ts),
        # G3 (aditif):
        "location": payload.get("location"),
        "action": _defect_action(event),
        "defect_entries": _defect_entries(payload),
    }


class QualityDefectsView(APIView):
    """``GET /api/v1/quality/defects/`` — daftar defect dari `BundleEvent`.

    **Tanpa model baru**: sumber = `BundleEvent` aksi scrap (``event_type``
    ``BUNDLE_SCRAP``). Query: ``?limit`` (1..200, default 50), ``?cursor``
    (offset), ``?wc`` (kode WorkCenter, exact). Bentuk ListPage::

        {"rows": [{"bundle_code", "wc_code", "defect_type", "qty", "reason",
                   "recorded_at", "location", "action", "defect_entries"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    * ``defect_type`` = ``payload.defect_type`` (fallback ``"unknown"``);
    * ``qty`` = ``payload.scrap_qty`` (fallback 0 — diisi FASE 4.3);
    * ``reason`` = ``payload.reason`` (fallback "");
    * ``recorded_at`` = ``BundleEvent.ts`` (model **tidak** punya ``timestamp``);
    * ``wc_code`` = ``bundle.current_work_center.code`` (bisa ``null``);
    * G3 (**aditif**): ``defect_entries`` = list detail per-cacat (fallback 1 entry
      dari field flat), ``action`` = ``rework``/``scrap``/``null``,
      ``location`` = ``payload.location``/``null``. Field lama TETAP.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage defect; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        events = _defects_queryset(request)
        rows, total, has_more = _page(events, offset, limit)
        return Response(
            {
                "rows": [_defect_row(event) for event in rows],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(rows)) if has_more else None,
            }
        )

    def post(self, request):
        """**POST** defect dari form QC (F3A.3 / B7b).

        Body::

            {"bundle_id": 12, "defect_type": "jahitan", "qty": 3,
             "reason": "meleset", "action": "rework"|"scrap"}

        * ``action="scrap"`` → **delegasi** ke action endpoint yang sudah ada
          (``POST /api/v1/garmen/bundles/<id>/BUNDLE_SCRAP/``) lewat
          :class:`ActionExecutor` — logika scrap TIDAK diduplikasi;
        * ``action="rework"`` → tulis ``BundleEvent(BUNDLE_QC_REWORK)`` lalu
          jalankan :class:`ReworkLoopHandler` (siklus ``QC_REWORK`` yang sudah ada,
          **tidak** membuat definisi baru): ``start_qc_rework`` + ``record_rework``
          (1 iterasi), dibungkus satu transaksi;
        * sukses → **200** ``{"ok": true, "bundle_event_id": "...",
          "cycle_instance_id": ...?}`` (``cycle_instance_id`` hanya untuk rework).

        Validasi → **400**: ``bundle_id`` bukan integer; ``defect_type`` kosong;
        ``qty`` bukan integer > 0; ``action`` bukan ``rework``/``scrap``; siklus
        rework EXHAUSTED. Bundle tak ada → **404**. Transisi scrap tidak sah
        (mis. bundle sudah ``DONE``) → status dari action endpoint (400).
        """
        data = request.data or {}

        bundle_id = data.get("bundle_id")
        if isinstance(bundle_id, bool) or not isinstance(bundle_id, int):
            return Response(
                {"detail": "Field 'bundle_id' harus integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        bundle = Bundle.objects.filter(pk=bundle_id).first()
        if bundle is None:
            return Response(
                {"detail": f"Bundle {bundle_id} tidak ditemukan."},
                status=status.HTTP_404_NOT_FOUND,
            )

        defect_type = str(data.get("defect_type") or "").strip()
        if not defect_type:
            return Response(
                {"detail": "Field 'defect_type' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qty = data.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            return Response(
                {"detail": "Field 'qty' harus integer > 0."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = str(data.get("action") or "").strip().lower()
        if action not in ("rework", "scrap"):
            return Response(
                {"detail": "Field 'action' harus 'rework' atau 'scrap'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reason = str(data.get("reason") or "")
        if action == "scrap":
            return self._submit_scrap(request, bundle, defect_type, qty, reason)
        return self._submit_rework(request, bundle, defect_type, qty, reason)

    @staticmethod
    def _submit_scrap(request, bundle, defect_type, qty, reason):
        """Delegasi ke action endpoint ``BUNDLE_SCRAP`` (reuse `ActionExecutor`)."""
        # Import lokal: layer `api.actions` ada DI ATAS modul monitoring; import di
        # level modul berisiko siklus (api -> integrations).
        from apps_industry.garment.api.actions.executor import ActionExecutor

        shim = _ActionRequestShim(
            request,
            {
                "scrap_qty": qty,
                "reason": reason,
                "defect_type": defect_type,
                "action": "scrap",
            },
        )
        result = ActionExecutor().execute(
            resource_name="bundles",
            instance_id=bundle.pk,
            action_id="BUNDLE_SCRAP",
            request=shim,
        )
        if result["status"] != status.HTTP_200_OK:
            # Fail-closed: status + detail dari action endpoint diteruskan apa adanya.
            return Response(result["payload"], status=result["status"])

        event = (
            BundleEvent.objects.filter(bundle=bundle, event_type__in=DEFECT_EVENT_TYPES)
            .order_by("-ts")
            .first()
        )
        logger.info("quality.defects: scrap %s lewat BUNDLE_SCRAP.", bundle.code)
        return Response({"ok": True, "bundle_event_id": str(event.pk) if event else None})

    @staticmethod
    def _submit_rework(request, bundle, defect_type, qty, reason):
        """``BundleEvent(BUNDLE_QC_REWORK)`` + 1 iterasi siklus ``QC_REWORK``."""
        actor = (
            request.user if getattr(request.user, "is_authenticated", False) else None
        )
        try:
            with transaction.atomic():
                handler = ReworkLoopHandler()
                handler.start_qc_rework(bundle)
                instance = handler.record_rework(bundle)
                event = BundleEvent.objects.create(
                    bundle=bundle,
                    actor=actor,
                    event_type=BUNDLE_QC_REWORK_EVENT,
                    text=f"QC rework: {defect_type} x{qty}",
                    payload={
                        "defect_type": defect_type,
                        "scrap_qty": qty,
                        "reason": reason,
                        "action": "rework",
                    },
                )
        except ReworkLoopError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("quality.defects: rework %s (event=%s).", bundle.code, event.pk)
        return Response(
            {
                "ok": True,
                "bundle_event_id": str(event.pk),
                "cycle_instance_id": instance.pk,
            }
        )


# ---------------------------------------------------------------------------
# Quality AQL (F3A.3 / B5) — GET /api/v1/quality/aql/
# ---------------------------------------------------------------------------
#: Ambang severity AQL (persen): <=1.5 pass, <=4.0 warn, >4.0 fail.
AQL_WARN_THRESHOLD = 1.5
AQL_FAIL_THRESHOLD = 4.0


def _aql_severity(aql_pct: float) -> str:
    """PURE — severity dari ``aql_pct`` (aturan brief B5)."""
    if aql_pct <= AQL_WARN_THRESHOLD:
        return "pass"
    if aql_pct <= AQL_FAIL_THRESHOLD:
        return "warn"
    return "fail"


def _aql_scrap_qty(payload: dict) -> int:
    """Qty defect dari payload event scrap (``scrap_qty`` → fallback ``qty``)."""
    for key in ("scrap_qty", "qty"):
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def _aql_rows(from_dt, to_dt) -> list[dict]:
    """Agregat AQL per work center: sampel (``BUNDLE_FINISH``) vs defect (scrap).

    * ``sample_qty`` = jumlah event ``BUNDLE_FINISH`` pada periode & WC itu;
    * ``defect_qty`` = Σ ``payload.scrap_qty`` event scrap pada periode & WC itu;
    * ``aql_pct`` = ``defect_qty / sample_qty * 100`` (``0.0`` bila tanpa sampel);
    * WC tanpa sampel **dan** tanpa defect dilewati (baris tak bermakna).
    """
    samples: dict = {}
    for event in BundleEvent.objects.filter(
        event_type=BUNDLE_FINISH_EVENT, ts__gte=from_dt, ts__lte=to_dt
    ).select_related("bundle__current_work_center"):
        work_center = event.bundle.current_work_center if event.bundle else None
        if work_center is None:
            continue
        samples[work_center.pk] = samples.get(work_center.pk, 0) + 1

    defects: dict = {}
    for event in BundleEvent.objects.filter(
        event_type__in=DEFECT_EVENT_TYPES, ts__gte=from_dt, ts__lte=to_dt
    ).select_related("bundle__current_work_center"):
        work_center = event.bundle.current_work_center if event.bundle else None
        if work_center is None:
            continue
        defects[work_center.pk] = defects.get(work_center.pk, 0) + _aql_scrap_qty(
            event.payload or {}
        )

    work_centers = {
        work_center.pk: work_center
        for work_center in WorkCenter.objects.filter(pk__in=set(samples) | set(defects))
    }
    rows = []
    for pk, work_center in work_centers.items():
        sample_qty = samples.get(pk, 0)
        defect_qty = defects.get(pk, 0)
        aql_pct = round(defect_qty / sample_qty * 100, 1) if sample_qty else 0.0
        rows.append(
            {
                "wc_code": work_center.code,
                "wc_name": work_center.name,
                "sample_qty": sample_qty,
                "defect_qty": defect_qty,
                "aql_pct": aql_pct,
                "severity": _aql_severity(aql_pct),
            }
        )
    rows.sort(key=lambda row: row["wc_code"])
    return rows


class QualityAqlView(APIView):
    """``GET /api/v1/quality/aql/`` — AQL (Acceptable Quality Level) per work center.

    Bentuk::

        {"rows": [{"wc_code", "wc_name", "sample_qty", "defect_qty", "aql_pct",
                   "severity"}],
         "generated_at": "ISO-8601", "period": {"from", "to"}}

    * Sumber = `BundleEvent`: ``BUNDLE_FINISH`` (sampel) + event scrap
      (``BUNDLE_SCRAP``/``SCRAP`` → ``payload.scrap_qty``) — **tanpa model baru**;
    * ``severity``: ``aql_pct <= 1.5`` → ``pass``; ``<= 4.0`` → ``warn``;
      ``> 4.0`` → ``fail``;
    * ``?from``/``?to`` ISO-8601 (default 7 hari); invalid / ``from > to`` → **400**;
    * WC tanpa sampel & tanpa defect tidak muncul (``rows`` bisa kosong).

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan AQL; lihat docstring kelas."""
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "rows": _aql_rows(from_dt, to_dt),
                "generated_at": timezone.localtime(timezone.now()).isoformat(),
                "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            }
        )


# ---------------------------------------------------------------------------
# Quality rework (F1 / B6) — GET /api/v1/quality/rework/
# ---------------------------------------------------------------------------
#: Definisi siklus rework QC (lihat `services/rework_loop.py`).
REWORK_CYCLE_CODE = "QC_REWORK"
#: `CycleInstance.ref_type` yang dipakai jembatan garmen (`ReworkLoopHandler`).
REWORK_REF_TYPE = "bundle"


def _rework_queryset(request):
    """QuerySet `CycleInstance` siklus QC_REWORK (filter opsional ``open``).

    ``CycleInstance`` **tidak** punya field ``closed_at``/``metadata`` → status
    dipakai untuk menentukan buka/tutup.
    """
    instances = CycleInstance.objects.filter(
        definition__code=REWORK_CYCLE_CODE
    ).select_related("current_step")

    open_param = request.query_params.get("open")
    if open_param not in (None, ""):
        ingin_buka = str(open_param).strip().lower() in {"1", "true", "yes"}
        if ingin_buka:
            instances = instances.filter(status=CycleInstance.Status.ACTIVE)
        else:
            instances = instances.exclude(status=CycleInstance.Status.ACTIVE)
    return instances.order_by("-started_at")


def _bundle_codes(instances) -> dict[int, str]:
    """`{bundle_pk: code}` untuk semua instance ref_type='bundle' (hindari N+1)."""
    ids: list[int] = []
    for instance in instances:
        if instance.ref_type != REWORK_REF_TYPE:
            continue
        try:
            ids.append(int(instance.ref_id))
        except (TypeError, ValueError):
            continue
    return {bundle.pk: bundle.code for bundle in Bundle.objects.filter(pk__in=ids)}


def _rework_row(instance, bundle_codes: dict[int, str]) -> dict:
    """Satu baris rework.

    ``from_step``/``to_step`` selalu ``None`` (model tidak punya ``metadata``);
    ``iteration`` memakai field RIIL ``iteration_count``; ``closed_at`` selalu
    ``None`` (model tidak menyimpan waktu tutup) → ``is_open`` dari ``status``.
    """
    bundle_code = None
    if instance.ref_type == REWORK_REF_TYPE:
        try:
            bundle_code = bundle_codes.get(int(instance.ref_id))
        except (TypeError, ValueError):
            bundle_code = None
    return {
        "bundle_code": bundle_code,
        "from_step": None,
        "to_step": None,
        "iteration": instance.iteration_count,
        "started_at": _iso(instance.started_at),
        "closed_at": None,
        "is_open": instance.status == CycleInstance.Status.ACTIVE,
    }


class QualityReworkView(APIView):
    """``GET /api/v1/quality/rework/`` — instance siklus rework QC.

    Sumber = `CycleInstance` dengan ``definition.code == "QC_REWORK"`` (definisi
    dibuat oleh `ReworkLoopHandler`, bukan migration). **Tanpa model baru.**

    Query: ``?limit`` (1..200, default 50), ``?cursor`` (offset),
    ``?open=true|false`` (filter ``is_open``). Bentuk ListPage::

        {"rows": [{"bundle_code", "from_step", "to_step", "iteration",
                   "started_at", "closed_at", "is_open"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Penyimpangan model (dilaporkan, tanpa migration):

    * ``from_step``/``to_step`` → **null** (model tidak punya ``metadata``);
    * ``iteration`` ← field RIIL ``CycleInstance.iteration_count``;
    * ``closed_at`` → **null** (tidak ada field waktu tutup); ``is_open`` =
      ``status == ACTIVE``.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage rework; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        instances = list(_rework_queryset(request))
        total = len(instances)
        page = instances[offset : offset + limit]
        has_more = offset + len(page) < total
        bundle_codes = _bundle_codes(page)
        return Response(
            {
                "rows": [_rework_row(instance, bundle_codes) for instance in page],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
            }
        )


# ---------------------------------------------------------------------------
# Inventory products (F1 / B7) — GET /api/v1/inventory/products/
# ---------------------------------------------------------------------------
def _stock_by_product() -> dict[int, int]:
    """`{product_pk: stock_qty}` = WIP+FG per produk — **1 query agregat**.

    Stage dari set WC step terminal (`_terminal_work_center_ids`): FG →
    ``qty_done``, WIP → ``qty``. Sebelum F5.2 tiap bundle memanggil
    ``build_payload()`` → 2 query per bundle (N+1); setelah itu loop Python per
    bundle (masih menarik 10 rb baris) → sekarang SUM dikerjakan DB
    (``values().annotate()``, grup per produk).
    """
    terminal_ids = _terminal_work_center_ids()
    rows = (
        _floor_bundles()
        .order_by()  # penting: bersihkan ordering agar GROUP BY hanya per produk
        .values("work_order__order_line__product_id")
        .annotate(
            wip_qty=Sum("qty", filter=~Q(current_work_center_id__in=terminal_ids)),
            fg_qty=Sum("qty_done", filter=Q(current_work_center_id__in=terminal_ids)),
        )
    )

    stock: dict[int, int] = {}
    for row in rows:
        product_id = row["work_order__order_line__product_id"]
        if product_id is None:
            continue
        stock[product_id] = (row["wip_qty"] or 0) + (row["fg_qty"] or 0)
    return stock


class InventoryProductsView(APIView):
    """``GET /api/v1/inventory/products/`` — master produk + stok (WIP+FG).

    Sumber = `master.Product` (DB, **bukan** Odoo live). Bentuk ListPage::

        {"rows": [{"id", "code", "name", "odoo_id", "stock_qty"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?q`` (``code``/``name`` icontains), ``?limit``, ``?cursor``.

    * ``code`` = ``Product.code`` (bukan ``default_code``);
    * ``stock_qty`` = agregat WIP+FG per produk via `TwoStageAggregator`
      (batch 1 pass); produk tanpa bundle → **0**.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage produk; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        products = Product.objects.all().order_by("code")
        query = str(request.query_params.get("q") or "").strip()
        if query:
            products = products.filter(
                Q(code__icontains=query) | Q(name__icontains=query)
            )

        rows, total, has_more = _page(products, offset, limit)
        stock = _stock_by_product()
        return Response(
            {
                "rows": [
                    {
                        "id": product.pk,
                        "code": product.code,
                        "name": product.name,
                        "odoo_id": product.odoo_id,
                        "stock_qty": stock.get(product.pk, 0),
                    }
                    for product in rows
                ],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(rows)) if has_more else None,
            }
        )


# ---------------------------------------------------------------------------
# Inventory operations (F1 / B8) — GET /api/v1/inventory/operations/
# ---------------------------------------------------------------------------
#: Mapping `SyncRecord.stage` → label operasi (read-only monitor).
OPERATION_TYPE_BY_STAGE = {
    SyncStage.WIP.value: "WIP_ISSUE",
    SyncStage.FG.value: "FG_RECEIPT",
    SyncStage.SCRAP.value: "SCRAP",
    SyncStage.INVOICE.value: "INVOICE",
}


def _resolve_product_code(record) -> str | None:
    """`product_code` dari resource (`bundle`) kalau bisa di-resolve; else `None`."""
    if record.resource != SyncResource.BUNDLE.value:
        return None
    try:
        bundle_id = int(record.resource_id)
    except (TypeError, ValueError):
        return None
    bundle = (
        Bundle.objects.filter(pk=bundle_id)
        .select_related("work_order__order_line__product")
        .first()
    )
    if bundle is None:
        return None
    product = bundle.work_order.order_line.product
    return product.code if product else None


def _operation_row(record) -> dict:
    """Satu baris operasi sync.

    ``qty``/``product_code`` diambil dari ``payload`` — `SyncRecord` **tidak**
    punya field ``metadata`` (payload = JSON hasil `TwoStageAggregator`).
    """
    payload = record.payload or {}
    product_code = payload.get("product_ref") or _resolve_product_code(record)
    return {
        "type": OPERATION_TYPE_BY_STAGE.get(record.stage, record.stage),
        "ref": record.resource_id,
        "product_code": product_code,
        "qty": payload.get("qty"),
        "status": record.status,
        "at": _iso(record.updated_at),
    }


class InventoryOperationsView(APIView):
    """``GET /api/v1/inventory/operations/`` — monitor operasi sync (read-only).

    Sumber = `SyncRecord` — **read-only monitor**, TIDAK memicu sync/Celery/Odoo.
    Bentuk ListPage::

        {"rows": [{"type", "ref", "product_code", "qty", "status", "at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    * ``type`` = label ``stage`` (WIP→WIP_ISSUE, FG→FG_RECEIPT, SCRAP, INVOICE);
    * ``ref`` = ``resource_id`` apa adanya;
    * ``product_code`` = ``payload.product_ref`` (fallback resolve dari bundle) / null;
    * ``qty`` = ``payload.qty`` (tidak ada ``metadata``) / null;
    * ``at`` = ``updated_at``; urut ``updated_at`` DESC.

    Query: ``?limit``, ``?cursor``, ``?stage=WIP|FG|SCRAP``.
    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage operasi; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        records = SyncRecord.objects.all()
        stage = str(request.query_params.get("stage") or "").strip().upper()
        if stage:
            records = records.filter(stage=stage)
        records = records.order_by("-updated_at")

        rows, total, has_more = _page(records, offset, limit)
        return Response(
            {
                "rows": [_operation_row(record) for record in rows],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(rows)) if has_more else None,
            }
        )


# ---------------------------------------------------------------------------
# Purchase vendors (F1 / B12) — GET /api/v1/purchase/vendors/
# ---------------------------------------------------------------------------
def _partner_row(partner) -> dict:
    """Satu baris partner.

    H1.6 menutup penyimpangan lama: `master.Partner` **kini** punya
    ``email``/``phone``/``city`` + penanda peran (``is_customer``/``is_vendor``),
    jadi nilainya dikembalikan apa adanya (sebelumnya selalu ``null``). Path & nama
    key lama **tidak** diubah supaya konsumen frontend (VendorsPage) tetap kompatibel;
    key baru bersifat aditif.
    """
    return {
        "id": partner.pk,
        "name": partner.name,
        "odoo_id": partner.odoo_id,
        "email": partner.email or None,
        "phone": partner.phone or None,
        "city": partner.city or None,
        "is_customer": bool(partner.is_customer),
        "is_vendor": bool(partner.is_vendor),
    }


class PurchaseVendorsView(APIView):
    """``GET /api/v1/purchase/vendors/`` — daftar partner (cache, bukan Odoo live).

    Sumber = `master.Partner`. Bentuk ListPage::

        {"rows": [{"id", "name", "odoo_id", "email", "phone", "city",
                   "is_customer", "is_vendor"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    H1.6: ``email``/``phone``/``city`` kini berisi nilai nyata (sebelumnya ``null``
    karena model belum punya field-nya) dan ditambah penanda peran
    ``is_customer``/``is_vendor`` — key lama tidak berubah.

    Query: ``?q`` (``name`` icontains), ``?limit``, ``?cursor``. Urut ``name`` ASC.
    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage vendor; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        partners = Partner.objects.all().order_by("name")
        query = str(request.query_params.get("q") or "").strip()
        if query:
            partners = partners.filter(name__icontains=query)

        rows, total, has_more = _page(partners, offset, limit)
        return Response(
            {
                "rows": [_partner_row(partner) for partner in rows],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(rows)) if has_more else None,
            }
        )


# ---------------------------------------------------------------------------
# Reports line efficiency (F1 / B13) — GET /api/v1/reports/line-efficiency/
# ---------------------------------------------------------------------------
#: event_type aksi mulai/selesai bundle (nilai RIIL = `action_id`, seeder 0002).
BUNDLE_START_EVENT = "BUNDLE_START"
BUNDLE_FINISH_EVENT = "BUNDLE_FINISH"

#: Rentang default laporan (hari ke belakang).
LINE_EFFICIENCY_DEFAULT_DAYS = 7
#: `target_per_day` fallback kalau `WorkCenter.config` tidak mengisinya.
LINE_EFFICIENCY_DEFAULT_TARGET = 100


def _parse_report_range(request):
    """`(from_dt, to_dt, error)` dari `?from`/`?to` (default 7 hari s/d now)."""
    now = timezone.now()

    to_dt = now
    to_raw = request.query_params.get("to")
    if to_raw not in (None, ""):
        to_dt = parse_datetime(str(to_raw))
        if to_dt is None:
            return None, None, f"Parameter 'to'={to_raw!r} bukan ISO-8601 valid."
        if timezone.is_naive(to_dt):
            to_dt = timezone.make_aware(to_dt)

    from_dt = to_dt - timedelta(days=LINE_EFFICIENCY_DEFAULT_DAYS)
    from_raw = request.query_params.get("from")
    if from_raw not in (None, ""):
        from_dt = parse_datetime(str(from_raw))
        if from_dt is None:
            return None, None, f"Parameter 'from'={from_raw!r} bukan ISO-8601 valid."
        if timezone.is_naive(from_dt):
            from_dt = timezone.make_aware(from_dt)

    if from_dt > to_dt:
        return None, None, "Parameter 'from' tidak boleh lebih besar dari 'to'."
    return from_dt, to_dt, None


def _line_efficiency_durations(from_dt, to_dt) -> dict:
    """`{wc_pk: (bundles_done, total_minutes)}` dari pasangan START+FINISH.

    Untuk tiap bundle dengan event ``BUNDLE_FINISH`` dalam rentang, diambil
    ``BUNDLE_START`` terawal-nya → durasi = FINISH.ts - START.ts. Atribusi WC
    memakai ``Bundle.current_work_center`` karena `BundleEvent` **tidak** punya
    ``wc_id``.
    """
    finishes = list(
        BundleEvent.objects.filter(
            event_type=BUNDLE_FINISH_EVENT, ts__gte=from_dt, ts__lte=to_dt
        ).select_related("bundle", "bundle__current_work_center")
    )
    bundle_ids = {event.bundle_id for event in finishes}
    starts: dict = {}
    for event in BundleEvent.objects.filter(
        event_type=BUNDLE_START_EVENT, bundle_id__in=bundle_ids
    ).order_by("ts"):
        starts.setdefault(event.bundle_id, event.ts)

    buckets: dict = {}
    for event in finishes:
        start_ts = starts.get(event.bundle_id)
        work_center = event.bundle.current_work_center
        if start_ts is None or work_center is None:
            continue
        minutes = (event.ts - start_ts).total_seconds() / 60
        done, total = buckets.get(work_center.pk, (0, 0.0))
        buckets[work_center.pk] = (done + 1, total + minutes)
    return buckets


def _target_per_day(work_center) -> int:
    """`WorkCenter.config['target_per_day']` (fallback 100)."""
    config = work_center.config if isinstance(work_center.config, dict) else {}
    try:
        return int(config.get("target_per_day", LINE_EFFICIENCY_DEFAULT_TARGET))
    except (TypeError, ValueError):
        return LINE_EFFICIENCY_DEFAULT_TARGET


def _efficiency_trends_by_wc(work_centers, days: int = TREND_DAYS) -> dict[int, list[dict]]:
    """`{wc_pk: [{date, value}]}` efisiensi `days` hari terakhir — **2 query total**.

    Sebelum F5.2 dihitung **per WC** dan tiap hari memanggil
    `_line_efficiency_durations` (2 query/hari/WC) → N+1. Sekarang satu pass event
    FINISH + START untuk seluruh window, lalu di-bucket per (WC, hari). Nilai
    ``value`` **identik** cara lama: ``done / target_per_day * 100`` (1 desimal).
    """
    today = timezone.localtime(timezone.now()).date()
    day_list = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    window_start = timezone.make_aware(datetime.combine(day_list[0], time.min))
    window_end = timezone.make_aware(datetime.combine(day_list[-1], time.max))

    finishes = list(
        BundleEvent.objects.filter(
            event_type=BUNDLE_FINISH_EVENT, ts__gte=window_start, ts__lte=window_end
        ).select_related("bundle")
    )
    bundle_ids = {event.bundle_id for event in finishes}
    starts: dict = {}
    for event in BundleEvent.objects.filter(
        event_type=BUNDLE_START_EVENT, bundle_id__in=bundle_ids
    ).order_by("ts"):
        starts.setdefault(event.bundle_id, event.ts)

    done_by_day: dict[tuple, int] = {}
    for event in finishes:
        work_center_id = event.bundle.current_work_center_id
        if work_center_id is None or starts.get(event.bundle_id) is None:
            continue
        day = timezone.localtime(event.ts).date()
        key = (work_center_id, day)
        done_by_day[key] = done_by_day.get(key, 0) + 1

    trends: dict[int, list[dict]] = {}
    for work_center in work_centers:
        capacity = _target_per_day(work_center)
        series: list[dict] = []
        for day in day_list:
            done = done_by_day.get((work_center.pk, day), 0)
            series.append(
                {
                    "date": day.isoformat(),
                    "value": round(done / capacity * 100, 1) if capacity else 0.0,
                }
            )
        trends[work_center.pk] = series
    return trends


class ReportsLineEfficiencyView(APIView):
    """``GET /api/v1/reports/line-efficiency/`` — efisiensi per work center.

    Read-only dari `BundleEvent` (``BUNDLE_START``+``BUNDLE_FINISH``) + atribusi
    WC via ``Bundle.current_work_center``. Bentuk::

        {"rows": [{"wc_code", "wc_name", "bundles_done", "avg_min_per_bundle",
                   "efficiency_pct", "label", "unit", "trend", "series"}],
         "generated_at": "ISO-8601",
         "period": {"from": "ISO", "to": "ISO"}}

    * ``avg_min_per_bundle`` = rata-rata durasi (FINISH−START) menit, 1 desimal;
    * ``efficiency_pct`` = ``bundles_done / (target_per_day * jumlah_hari) * 100``,
      1 desimal; ``target_per_day`` dari ``WorkCenter.config`` (fallback 100);
    * semua WC **aktif** ditampilkan (yang tanpa bundle selesai → nilai 0);
    * ``?from``/``?to`` ISO-8601 (default 7 hari s/d now); invalid → **400**,
      ``from > to`` → **400**;
    * G4b (**aditif**): ``label`` = ``wc_name``, ``unit`` = ``"%"``,
      ``trend`` = ``[{date, value}]`` efisiensi per hari (7 hari terakhir),
      ``series`` = alias ``[{x, y}]`` untuk chart. Field lama TETAP.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan efisiensi; lihat docstring kelas."""
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        days = max((to_dt - from_dt).days, 1)
        buckets = _line_efficiency_durations(from_dt, to_dt)

        active_work_centers = list(WorkCenter.objects.filter(is_active=True).order_by("code"))
        # G4b (aditif) — trend 7 hari per WC, dihitung BATCH (2 query untuk semua
        # WC) supaya tidak ada N+1 lewat `_line_efficiency_durations` per hari/WC.
        trends = _efficiency_trends_by_wc(active_work_centers)

        rows = []
        for work_center in active_work_centers:
            done, total_minutes = buckets.get(work_center.pk, (0, 0.0))
            capacity = _target_per_day(work_center) * days
            eff_trend = trends.get(work_center.pk, [])
            rows.append(
                {
                    "wc_code": work_center.code,
                    "wc_name": work_center.name,
                    "bundles_done": done,
                    "avg_min_per_bundle": round(total_minutes / done, 1) if done else 0.0,
                    "efficiency_pct": (
                        round(done / capacity * 100, 1) if capacity else 0.0
                    ),
                    # G4b (aditif)
                    "label": work_center.name,
                    "unit": "%",
                    "trend": eff_trend,
                    "series": [
                        {"x": point["date"], "y": point["value"]} for point in eff_trend
                    ],
                }
            )
        return Response(
            {
                "rows": rows,
                "generated_at": timezone.localtime(timezone.now()).isoformat(),
                "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            }
        )


# ---------------------------------------------------------------------------
# Reports WIP (F1 / B16) — GET /api/v1/reports/wip/
# ---------------------------------------------------------------------------
#: Nilai `group_by` yang dikenal.
WIP_GROUP_BY_VALUES = ("wc", "none")


def _wip_trends_by_wc(work_centers, days: int = TREND_DAYS) -> dict[int, list[dict]]:
    """`{wc_pk: [{date, value}]}` WIP kumulatif `days` hari terakhir — **1 query**.

    Proxy historis **sama** seperti cara lama: bundle di WC itu (state bukan
    ``DONE``/``CANCELLED``) dengan ``updated_at <= akhir hari``. Bedanya semua hari
    × semua WC dihitung dari SATU query (sebelumnya 7 query agregat **per WC**).
    """
    today = timezone.localtime(timezone.now()).date()
    day_list = [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]
    day_ends = [timezone.make_aware(datetime.combine(day, time.max)) for day in day_list]
    wc_ids = [work_center.pk for work_center in work_centers]

    rows = (
        Bundle.objects.filter(current_work_center_id__in=wc_ids)
        .exclude(state__in=WCQueue.EXCLUDED_STATES)
        .values_list("current_work_center_id", "qty", "updated_at")
    )
    by_wc: dict[int, list[tuple]] = {}
    for wc_id, qty, updated_at in rows:
        by_wc.setdefault(wc_id, []).append((updated_at, qty or 0))

    trends: dict[int, list[dict]] = {}
    for wc_id in wc_ids:
        items = sorted(by_wc.get(wc_id, []))
        series: list[dict] = []
        index = 0
        running = 0
        for day, day_end in zip(day_list, day_ends):
            while index < len(items) and items[index][0] <= day_end:
                running += items[index][1]
                index += 1
            series.append({"date": day.isoformat(), "value": running})
        trends[wc_id] = series
    return trends


def _wip_rows() -> list[dict]:
    """WIP per work center: bundle belum selesai (state != DONE/CANCELLED).

    Reuse semantik `WCQueue.EXCLUDED_STATES` (bundle dianggap bukan WIP kalau
    sudah selesai). Satu query agregat (bukan per WC). WC tanpa bundle WIP →
    dilewati.
    """
    aggregate = (
        Bundle.objects.filter(current_work_center__isnull=False)
        .exclude(state__in=WCQueue.EXCLUDED_STATES)
        .values("current_work_center_id")
        .annotate(wip_qty=Sum("qty"), queue_depth=Count("id"))
    )
    work_centers = {
        wc.pk: wc
        for wc in WorkCenter.objects.filter(
            pk__in=[row["current_work_center_id"] for row in aggregate]
        )
    }
    # G4 (aditif) — trend 7 hari per WC dihitung BATCH (1 query untuk semua WC);
    # sebelumnya `_wip_trend_for()` menembak 7 query agregat per WC (N+1).
    trends = _wip_trends_by_wc(list(work_centers.values()))
    rows = []
    for row in aggregate:
        work_center = work_centers.get(row["current_work_center_id"])
        if work_center is None:
            continue
        wip_trend = trends.get(work_center.pk, [])
        rows.append(
            {
                "wc_code": work_center.code,
                "wc_name": work_center.name,
                "wip_qty": row["wip_qty"] or 0,
                "queue_depth": row["queue_depth"],
                # G4 (aditif)
                "label": work_center.name,
                "unit": "pcs",
                "trend": wip_trend,
                "series": [
                    {"x": point["date"], "y": point["value"]} for point in wip_trend
                ],
            }
        )
    rows.sort(key=lambda row: row["wc_code"])
    return rows


class ReportsWipView(APIView):
    """``GET /api/v1/reports/wip/`` — WIP per work center (atau total saja).

    Read-only dari `Bundle` (state != ``DONE``). Bentuk ``group_by=wc``::

        {"rows": [{"wc_code", "wc_name", "wip_qty", "queue_depth",
                   "label", "unit", "trend", "series"}],
         "total_wip": N, "group_by": "wc", "generated_at": "ISO-8601"}

    ``group_by=none`` → **tanpa** ``rows`` (hanya ``total_wip``/``group_by``/
    ``generated_at``). Query ``?group_by=wc|none`` (default ``wc``); nilai lain →
    **400**. WC tanpa bundle WIP **tidak** muncul.

    * G4 (**aditif**) per row: ``label`` = ``wc_name``, ``unit`` = ``"pcs"``,
      ``trend`` = ``[{date, value}]`` WIP per hari (7 hari terakhir),
      ``series`` = alias ``[{x, y}]`` untuk chart. Field lama TETAP.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan WIP; lihat docstring kelas."""
        group_by = str(request.query_params.get("group_by") or "wc").strip().lower()
        if group_by not in WIP_GROUP_BY_VALUES:
            return Response(
                {"detail": f"group_by={group_by!r} tidak dikenal (wc|none)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        rows = _wip_rows()
        total_wip = sum(row["wip_qty"] for row in rows)

        payload: dict = {"total_wip": total_wip, "group_by": group_by}
        if group_by == "wc":
            payload["rows"] = rows
        payload["generated_at"] = timezone.localtime(timezone.now()).isoformat()
        return Response(payload)


# ---------------------------------------------------------------------------
# Reports sub-route DB-only (F3A.1 / B18–B21)
#   * GET /api/v1/reports/line-efficiency/by-wc/   -> ReportsLineEfficiencyByWcView
#   * GET /api/v1/reports/lead-time/               -> ReportsLeadTimeView
#   * GET /api/v1/reports/lead-time/bundles/       -> ReportsLeadTimeBundlesView
#   * GET /api/v1/reports/on-time-delivery/        -> ReportsOnTimeDeliveryView
#   * GET /api/v1/reports/on-time-delivery/orders/ -> ReportsOnTimeDeliveryOrdersView
#   * GET /api/v1/reports/wip/by-wc/               -> ReportsWipByWcView
#
# TANPA model/migration baru — semua diturunkan dari kolom yang SUDAH ada.
# Dua derivasi WAJIB dicatat (tidak ada kolom khusus):
#   * `Bundle` dan `WorkOrder` TIDAK punya `finished_at`; waktu selesai diambil
#     dari `BundleEvent(event_type="BUNDLE_FINISH").ts` (pola yang sama dengan
#     B13), fallback `WorkOrder.updated_at` bila bundle belum punya event FINISH.
#   * `BundleEvent` TIDAK punya `wc_id`; atribusi WC memakai
#     `Bundle.current_work_center` (keterbatasan identik dengan B13).
# ---------------------------------------------------------------------------


def _hours_between(start, end) -> float:
    """Selisih jam (2 desimal); ``0.0`` bila salah satu ``None``."""
    if start is None or end is None:
        return 0.0
    return round((end - start).total_seconds() / 3600, 2)


def _pair_stages(events) -> list[dict]:
    """Pasangan ``BUNDLE_START`` → ``BUNDLE_FINISH`` menjadi ``[{wc_code, minutes}]``.

    ``events`` HARUS terurut kronologis untuk satu bundle. ``wc_code`` diambil dari
    ``Bundle.current_work_center`` (BundleEvent tak punya ``wc_id``) sehingga satu
    siklus START→FINISH (termasuk rework) menjadi satu "stage".
    """
    stages: list[dict] = []
    pending_start = None
    for event in events:
        if event.event_type == BUNDLE_START_EVENT:
            pending_start = event.ts
        elif event.event_type == BUNDLE_FINISH_EVENT and pending_start is not None:
            minutes = (event.ts - pending_start).total_seconds() / 60
            work_center = getattr(event.bundle, "current_work_center", None)
            stages.append(
                {
                    "wc_code": work_center.code if work_center is not None else None,
                    "minutes": round(minutes, 1),
                }
            )
            pending_start = None
    return stages


def _bundle_stages_map(bundle_ids) -> dict:
    """``{bundle_id: [stage, ...]}`` — satu query untuk semua bundle (bukan N+1)."""
    ids = {bundle_id for bundle_id in bundle_ids if bundle_id is not None}
    if not ids:
        return {}

    grouped: dict = {}
    events = (
        BundleEvent.objects.filter(
            bundle_id__in=ids,
            event_type__in=(BUNDLE_START_EVENT, BUNDLE_FINISH_EVENT),
        )
        .select_related("bundle", "bundle__current_work_center")
        .order_by("bundle_id", "ts")
    )
    for event in events:
        grouped.setdefault(event.bundle_id, []).append(event)

    return {bundle_id: _pair_stages(items) for bundle_id, items in grouped.items()}


def _bundle_finish_map(bundle_ids) -> dict:
    """``{bundle_id: ts_finish_terakhir}`` dari event ``BUNDLE_FINISH``."""
    ids = {bundle_id for bundle_id in bundle_ids if bundle_id is not None}
    if not ids:
        return {}

    finishes: dict = {}
    for event in BundleEvent.objects.filter(
        event_type=BUNDLE_FINISH_EVENT, bundle_id__in=ids
    ).order_by("ts"):
        finishes[event.bundle_id] = event.ts
    return finishes


def _lead_time_rows(from_dt, to_dt) -> list[dict]:
    """Baris lead-time per bundle yang **selesai** (FINISH) dalam rentang.

    ``hours_total`` = ``created_at`` bundle → FINISH terakhir (jam, 2 desimal).
    Terurut ``finished_at`` DESC (terbaru dulu).
    """
    finishes: dict = {}
    for event in BundleEvent.objects.filter(
        event_type=BUNDLE_FINISH_EVENT, ts__gte=from_dt, ts__lte=to_dt
    ).select_related("bundle"):
        current = finishes.get(event.bundle_id)
        if current is None or event.ts > current:
            finishes[event.bundle_id] = event.ts
    if not finishes:
        return []

    bundles = {bundle.pk: bundle for bundle in Bundle.objects.filter(pk__in=finishes)}
    stages_map = _bundle_stages_map(finishes)

    rows: list[dict] = []
    for bundle_id, finished_at in finishes.items():
        bundle = bundles.get(bundle_id)
        if bundle is None:
            continue
        rows.append(
            {
                "bundle_code": bundle.code,
                "created_at": _iso(bundle.created_at),
                "finished_at": _iso(finished_at),
                "hours_total": _hours_between(bundle.created_at, finished_at),
                "stages": stages_map.get(bundle_id, []),
            }
        )
    rows.sort(key=lambda row: row["finished_at"] or "", reverse=True)
    return rows


class ReportsLineEfficiencyByWcView(APIView):
    """``GET /api/v1/reports/line-efficiency/by-wc/`` — detail per work center.

    Bentuk::

        {"rows": [{"wc_code", "wc_name", "bundles_done", "avg_min_per_bundle",
                   "efficiency_pct", "pct_delta_vs_prev"}],
         "generated_at": "ISO-8601", "period": {"from", "to"}}

    * Sumber & rumus identik B13 (`BundleEvent` FINISH/START + ``current_work_center``);
    * ``pct_delta_vs_prev`` = ``efficiency_pct`` periode ini − periode **sebelumnya
      yang sama panjangnya** (bisa negatif), 1 desimal;
    * SEMUA WC aktif tampil (tanpa bundle selesai → 0.0);
    * ``?from``/``?to`` ISO-8601 (default 7 hari); invalid / ``from > to`` → **400**.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan efisiensi per WC + delta; lihat docstring kelas."""
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        days = max((to_dt - from_dt).days, 1)
        span = to_dt - from_dt
        buckets = _line_efficiency_durations(from_dt, to_dt)
        previous_buckets = _line_efficiency_durations(from_dt - span, from_dt)

        rows = []
        for work_center in WorkCenter.objects.filter(is_active=True).order_by("code"):
            done, total_minutes = buckets.get(work_center.pk, (0, 0.0))
            capacity = _target_per_day(work_center) * days
            efficiency_pct = round(done / capacity * 100, 1) if capacity else 0.0
            prev_done = previous_buckets.get(work_center.pk, (0, 0.0))[0]
            prev_pct = round(prev_done / capacity * 100, 1) if capacity else 0.0
            rows.append(
                {
                    "wc_code": work_center.code,
                    "wc_name": work_center.name,
                    "bundles_done": done,
                    "avg_min_per_bundle": round(total_minutes / done, 1) if done else 0.0,
                    "efficiency_pct": efficiency_pct,
                    "pct_delta_vs_prev": round(efficiency_pct - prev_pct, 1),
                }
            )

        return Response(
            {
                "rows": rows,
                "generated_at": timezone.localtime(timezone.now()).isoformat(),
                "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            }
        )


class ReportsLeadTimeView(APIView):
    """``GET /api/v1/reports/lead-time/`` — lead time per bundle (+ rincian stage).

    Bentuk (ListPage + agregat)::

        {"rows": [{"bundle_code", "created_at", "finished_at", "hours_total",
                   "stages": [{"wc_code", "minutes"}]}],
         "total_count": N, "has_more": bool, "next_cursor": int|null,
         "avg_hours": float}

    * Hanya bundle dengan event ``BUNDLE_FINISH`` **dalam rentang** yang muncul;
    * ``?limit`` (default 50, maks 200), ``?cursor`` (offset),
      ``?from``/``?to`` ISO-8601 (default 7 hari, filter pada ``finished_at``);
      invalid / ``from > to`` → **400**;
    * ``finished_at`` = ``ts`` event FINISH terakhir (bukan kolom model);
      ``hours_total`` = ``Bundle.created_at`` → ``finished_at``;
    * ``stages`` = pasangan START→FINISH berurutan; ``wc_code`` dari
      ``Bundle.current_work_center`` (BundleEvent tak punya ``wc_id``) → bisa ``null``;
    * ``avg_hours`` = rata-rata ``hours_total`` **seluruh** baris (bukan hanya halaman).

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan lead-time; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        rows = _lead_time_rows(from_dt, to_dt)
        total = len(rows)
        page = rows[offset : offset + limit]
        has_more = offset + len(page) < total

        return Response(
            {
                "rows": page,
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
                "avg_hours": (
                    round(sum(row["hours_total"] for row in rows) / total, 2)
                    if total
                    else 0.0
                ),
            }
        )


class ReportsLeadTimeBundlesView(APIView):
    """``GET /api/v1/reports/lead-time/bundles/`` — lead time FLAT (tanpa stages).

    Bentuk ListPage::

        {"rows": [{"bundle_code", "hours_total", "wc_count", "done_at"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    * ``wc_count`` = jumlah **stage** (pasangan START→FINISH) pada bundle — dipakai
      sebagai proksi jumlah WC karena ``BundleEvent`` tak menyimpan ``wc_id``;
    * ``done_at`` = ``ts`` event FINISH terakhir;
    * Urut ``hours_total`` **DESC** (paling lama dulu);
    * Query: ``?limit``, ``?cursor``, ``?from``/``?to`` (default 7 hari).

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun daftar lead-time flat; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        rows = [
            {
                "bundle_code": row["bundle_code"],
                "hours_total": row["hours_total"],
                "wc_count": len(row["stages"]),
                "done_at": row["finished_at"],
            }
            for row in _lead_time_rows(from_dt, to_dt)
        ]
        rows.sort(key=lambda row: row["hours_total"], reverse=True)

        total = len(rows)
        page = rows[offset : offset + limit]
        has_more = offset + len(page) < total
        return Response(
            {
                "rows": page,
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
            }
        )


def _wo_finish_map(work_orders) -> dict:
    """``{work_order_pk: ts_finish}`` = event FINISH terakhir bundle milik WO itu.

    ``WorkOrder`` tidak punya kolom ``finished_at`` → diturunkan dari BUNDLE_FINISH
    milik bundle-nya (satu query untuk semua WO).
    """
    wo_ids = [wo.pk for wo in work_orders]
    if not wo_ids:
        return {}

    bundle_to_wo = {
        bundle_pk: wo_id
        for bundle_pk, wo_id in Bundle.objects.filter(work_order_id__in=wo_ids).values_list(
            "pk", "work_order_id"
        )
    }
    finishes: dict = {}
    for bundle_id, ts in _bundle_finish_map(bundle_to_wo).items():
        wo_id = bundle_to_wo[bundle_id]
        current = finishes.get(wo_id)
        if current is None or ts > current:
            finishes[wo_id] = ts
    return finishes


def _otd_metrics(deadline, finished_at):
    """``(on_time, delay_hours)``; ``(None, 0.0)`` bila salah satu belum ada."""
    if deadline is None or finished_at is None:
        return None, 0.0
    if finished_at > deadline:
        return False, round((finished_at - deadline).total_seconds() / 3600, 2)
    return True, 0.0


def _otd_pct(rows) -> float:
    """Persentase on-time di antara baris yang ``on_time``-nya **bukan** ``None``."""
    decided = [row for row in rows if row["on_time"] is not None]
    if not decided:
        return 0.0
    return round(sum(1 for row in decided if row["on_time"]) / len(decided) * 100, 1)


def _on_time_filter(request):
    """``(value, error)`` dari ``?on_time=true|false`` (kosong → ``None``)."""
    raw = request.query_params.get("on_time")
    if raw in (None, ""):
        return None, None
    value = str(raw).strip().lower()
    if value in ("true", "1", "yes"):
        return True, None
    if value in ("false", "0", "no"):
        return False, None
    return None, f"Parameter 'on_time'={raw!r} harus true|false."


class ReportsOnTimeDeliveryView(APIView):
    """``GET /api/v1/reports/on-time-delivery/`` — OTD per **work order** selesai.

    Bentuk (ListPage + agregat)::

        {"rows": [{"order_code", "deadline", "finished_at", "on_time", "delay_hours"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null,
         "otd_pct": float}

    * Baris = `WorkOrder` ber-state ``DONE`` (satu baris per WO; ``order_code``
      bisa berulang untuk order yang sama — agregat per Order ada di
      ``/reports/on-time-delivery/orders/``);
    * ``finished_at`` = event FINISH terakhir bundle WO tsb, **fallback**
      ``WorkOrder.updated_at`` (WorkOrder tak punya kolom ``finished_at``);
    * ``on_time`` = ``finished_at <= Order.deadline``; ``None`` bila deadline/waktu
      selesai tidak diketahui; ``delay_hours`` = kelebihan jam (``0.0`` bila tepat/awal);
    * ``otd_pct`` = persen on-time di antara baris yang ``on_time``-nya bukan ``None``;
    * Query: ``?limit``, ``?cursor``, ``?from``/``?to`` (filter ``finished_at``),
      ``?on_time=true|false``; invalid → **400**.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan OTD; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        on_time_filter, error = _on_time_filter(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        work_orders = list(
            WorkOrder.objects.filter(state="DONE")
            .select_related("order_line__order")
            .order_by("code")
        )
        finish_map = _wo_finish_map(work_orders)

        rows = []
        for work_order in work_orders:
            order = work_order.order_line.order
            finished_at = finish_map.get(work_order.pk) or work_order.updated_at
            if finished_at is None or finished_at < from_dt or finished_at > to_dt:
                continue
            on_time, delay_hours = _otd_metrics(order.deadline, finished_at)
            if on_time_filter is not None and on_time is not on_time_filter:
                continue
            rows.append(
                {
                    "order_code": order.code,
                    "deadline": _iso(order.deadline),
                    "finished_at": _iso(finished_at),
                    "on_time": on_time,
                    "delay_hours": delay_hours,
                }
            )

        rows.sort(key=lambda row: row["finished_at"] or "", reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        has_more = offset + len(page) < total
        return Response(
            {
                "rows": page,
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
                "otd_pct": _otd_pct(rows),
            }
        )


class ReportsOnTimeDeliveryOrdersView(APIView):
    """``GET /api/v1/reports/on-time-delivery/orders/`` — OTD agregat per Order.

    Bentuk ListPage::

        {"rows": [{"order_code", "deadline", "last_wo_finished", "on_time", "wo_count"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    * Hanya Order yang punya minimal satu `WorkOrder` ``DONE``;
    * ``last_wo_finished`` = ``finished_at`` terakhir di antara WO order tsb;
    * ``on_time`` = ``last_wo_finished <= deadline`` (``None`` bila salah satu kosong);
    * ``wo_count`` = jumlah WorkOrder ``DONE`` order tsb (yang dihitung);
    * Query: ``?limit``, ``?cursor``, ``?from``/``?to``, ``?on_time=true|false``.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun OTD agregat per order; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        from_dt, to_dt, error = _parse_report_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        on_time_filter, error = _on_time_filter(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        work_orders = list(
            WorkOrder.objects.filter(state="DONE")
            .select_related("order_line__order")
            .order_by("code")
        )
        finish_map = _wo_finish_map(work_orders)

        grouped: dict = {}
        for work_order in work_orders:
            order = work_order.order_line.order
            finished_at = finish_map.get(work_order.pk) or work_order.updated_at
            entry = grouped.setdefault(
                order.pk, {"order": order, "finished": [], "wo_count": 0}
            )
            entry["wo_count"] += 1
            if finished_at is not None:
                entry["finished"].append(finished_at)

        rows = []
        for entry in grouped.values():
            order = entry["order"]
            last_finished = max(entry["finished"]) if entry["finished"] else None
            if last_finished is None or last_finished < from_dt or last_finished > to_dt:
                continue
            on_time, _delay = _otd_metrics(order.deadline, last_finished)
            if on_time_filter is not None and on_time is not on_time_filter:
                continue
            rows.append(
                {
                    "order_code": order.code,
                    "deadline": _iso(order.deadline),
                    "last_wo_finished": _iso(last_finished),
                    "on_time": on_time,
                    "wo_count": entry["wo_count"],
                }
            )

        rows.sort(key=lambda row: row["last_wo_finished"] or "", reverse=True)
        total = len(rows)
        page = rows[offset : offset + limit]
        has_more = offset + len(page) < total
        return Response(
            {
                "rows": page,
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
            }
        )


class ReportsWipByWcView(APIView):
    """``GET /api/v1/reports/wip/by-wc/`` — WIP per WC, **flat** (tanpa trend/series).

    Bentuk::

        {"rows": [{"wc_code", "wc_name", "wip_qty", "queue_depth",
                   "oldest_bundle_age_hours"}],
         "total_wip": N, "generated_at": "ISO-8601"}

    * Semantik WIP sama dengan B16 (`WCQueue.EXCLUDED_STATES` = bundle selesai
      tidak dihitung); WC tanpa bundle WIP **tidak** muncul;
    * ``oldest_bundle_age_hours`` = umur bundle WIP **tertua** di WC itu
      (``Bundle.created_at`` → sekarang, jam 1 desimal);
    * Ringkas untuk tabel: tanpa ``label``/``unit``/``trend``/``series``.

    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun tabel ringkas WIP per WC; lihat docstring kelas."""
        now = timezone.now()
        aggregate = (
            Bundle.objects.filter(current_work_center__isnull=False)
            .exclude(state__in=WCQueue.EXCLUDED_STATES)
            .values("current_work_center_id")
            .annotate(
                wip_qty=Sum("qty"),
                queue_depth=Count("id"),
                oldest_created_at=Min("created_at"),
            )
        )
        work_centers = {
            work_center.pk: work_center
            for work_center in WorkCenter.objects.filter(
                pk__in=[row["current_work_center_id"] for row in aggregate]
            )
        }

        rows = []
        for row in aggregate:
            work_center = work_centers.get(row["current_work_center_id"])
            if work_center is None:
                continue
            oldest = row["oldest_created_at"]
            rows.append(
                {
                    "wc_code": work_center.code,
                    "wc_name": work_center.name,
                    "wip_qty": row["wip_qty"] or 0,
                    "queue_depth": row["queue_depth"],
                    "oldest_bundle_age_hours": (
                        round((now - oldest).total_seconds() / 3600, 1)
                        if oldest is not None
                        else 0.0
                    ),
                }
            )
        rows.sort(key=lambda row: row["wc_code"])

        return Response(
            {
                "rows": rows,
                "total_wip": sum(row["wip_qty"] for row in rows),
                "generated_at": timezone.localtime(now).isoformat(),
            }
        )


# ---------------------------------------------------------------------------
# Reports sales (H4.1) — GET /api/v1/reports/sales/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``period``).
SALES_GROUP_BY_VALUES = ("period", "customer", "product")

#: Tipe order yang dikenal (turunan `Order.OrderType`: EXPORT/CUSTOM/BRAND).
SALES_ORDER_TYPES = tuple(Order.OrderType.values)

#: State `Payment` INBOUND yang dihitung pada ``summary.paid_amount`` (H4.1).
SALES_PAID_STATES = ("SENT", "DONE")

#: State yang TIDAK dihitung: order CANCELLED bukan penjualan, invoice CANCELLED
#: bukan piutang.
SALES_EXCLUDED_STATES = ("CANCELLED",)

#: TTL cache laporan penjualan (detik) — laporan "berat" (5 menit).
SALES_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
SALES_CACHE_PREFIX = "reports:sales:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
SALES_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Batas atas `customer_id`/`product_id` (PositiveBigInteger).
SALES_MAX_ID = 2**31 - 1


def _sales_month_range(month: str):
    """``(from_dt, to_dt, error)`` dari ``YYYY-MM`` (awal..akhir bulan, tz-aware)."""
    try:
        year_raw, month_raw = month.split("-", 1)
        first = datetime(int(year_raw), int(month_raw), 1)
    except (TypeError, ValueError):
        return None, None, f"Parameter 'period'={month!r} bukan format YYYY-MM."

    if first.month == 12:
        last = datetime(first.year + 1, 1, 1) - timedelta(microseconds=1)
    else:
        last = datetime(first.year, first.month + 1, 1) - timedelta(microseconds=1)
    return timezone.make_aware(first), timezone.make_aware(last), None


def _sales_boundary(raw: str, *, end: bool):
    """``(datetime, error)`` dari ISO-8601 (``date`` **atau** ``datetime``).

    Tanggal tanpa jam → ``00:00:00`` (``end=False``) atau ``23:59:59.999999``
    (``end=True``) supaya batas rentang selalu **inklusif**. ``parse_date``
    diperiksa **lebih dulu**: Python 3.11 ``datetime.fromisoformat`` menerima
    ``YYYY-MM-DD`` dan mengembalikan tengah malam, jadi batas atas bisa "hilang"
    kalau urutannya dibalik.
    """
    day = parse_date(raw)
    if day is not None:
        value = datetime.combine(day, time.max if end else time.min)
    else:
        value = parse_datetime(raw)
        if value is None:
            return None, f"Parameter tanggal {raw!r} bukan ISO-8601 valid."
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value, None


def _sales_range(request):
    """``(from_dt, to_dt, echo, error)`` — prioritas param rentang laporan sales.

    Prioritas (keputusan H4.1): ``?period=YYYY-MM`` > ``?date_from``/``?date_to``
    > ``?from``/``?to``. Default = **bulan berjalan**. Bila hanya batas atas
    diisi, batas bawah = awal bulan dari batas atas itu; bila hanya batas bawah,
    batas atas = ``now``. ``from > to`` → error (view membalas **400**).
    """
    period_raw = str(request.query_params.get("period") or "").strip()
    date_from_raw = str(request.query_params.get("date_from") or "").strip()
    date_to_raw = str(request.query_params.get("date_to") or "").strip()
    from_raw = str(request.query_params.get("from") or "").strip()
    to_raw = str(request.query_params.get("to") or "").strip()
    echo = {
        "period": period_raw or None,
        "date_from": date_from_raw or None,
        "date_to": date_to_raw or None,
        "from": from_raw or None,
        "to": to_raw or None,
    }

    now = timezone.now()
    error = None
    if period_raw:
        from_dt, to_dt, error = _sales_month_range(period_raw)
    else:
        raw_from = date_from_raw or from_raw
        raw_to = date_to_raw or to_raw
        if not raw_from and not raw_to:
            from_dt, to_dt, error = _sales_month_range(
                timezone.localtime(now).strftime("%Y-%m")
            )
        else:
            to_dt = now
            if raw_to:
                to_dt, error = _sales_boundary(raw_to, end=True)
            if error is None:
                month_key = timezone.localtime(to_dt).strftime("%Y-%m")
                from_dt, _month_end, error = _sales_month_range(month_key)
            if error is None and raw_from:
                from_dt, error = _sales_boundary(raw_from, end=False)

    if error:
        return None, None, echo, error
    if from_dt > to_dt:
        return None, None, echo, "Parameter 'from' tidak boleh lebih besar dari 'to'."
    return from_dt, to_dt, echo, None


def _sales_options(request):
    """``(options, error)`` — parse grup & filter laporan sales (PURE).

    ``group_by`` default ``period``; ``order_type`` case-insensitive
    (``EXPORT``/``CUSTOM``/``BRAND``); ``customer_id``/``product_id`` angka ≥ 1;
    ``_nocache`` truthy → ``{"1", "true", "yes", "on"}`` (case-insensitive).
    """
    group_by = str(request.query_params.get("group_by") or "period").strip().lower()
    if group_by not in SALES_GROUP_BY_VALUES:
        return None, (
            f"Parameter 'group_by'={group_by!r} tidak dikenal "
            f"({'|'.join(SALES_GROUP_BY_VALUES)})."
        )

    order_type_raw = str(request.query_params.get("order_type") or "").strip()
    order_type = order_type_raw.upper()
    if order_type and order_type not in SALES_ORDER_TYPES:
        return None, (
            f"Parameter 'order_type'={order_type_raw!r} tidak dikenal "
            f"({'|'.join(SALES_ORDER_TYPES)})."
        )

    customer_id, error = _int_param(request, "customer_id", None, 1, SALES_MAX_ID)
    if error:
        return None, error
    product_id, error = _int_param(request, "product_id", None, 1, SALES_MAX_ID)
    if error:
        return None, error

    nocache_raw = str(request.query_params.get("_nocache") or "").strip().lower()
    return (
        {
            "group_by": group_by,
            "order_type": order_type or None,
            "customer_id": customer_id,
            "product_id": product_id,
            "nocache": nocache_raw in SALES_NOCACHE_TRUTHY,
        },
        None,
    )


def _sales_amount_expr():
    """PURE — ekspresi ``qty × price_unit``; `OrderLine` **tidak** punya `line_total`.

    Field baru **tidak** ditambahkan ke model demi laporan (keputusan H4.1):
    nilai uang penjualan dihitung dari kolom yang sudah ada.
    """
    return Sum(
        F("qty") * F("price_unit"),
        output_field=DecimalField(max_digits=22, decimal_places=2),
    )


def _money(value) -> float:
    """Decimal/None → float 2 desimal (rincian uang laporan)."""
    return round(float(value or 0), 2)


def _sales_lines(from_dt, to_dt, customer_id=None, product_id=None, order_type=None):
    """QuerySet `OrderLine` dalam rentang — basis periode ``Order.created_at``.

    Accrual basis (keputusan H4.1): sales diakui saat order **dibuat**. Order
    ``CANCELLED`` dibuang (bukan penjualan).
    """
    lines = OrderLine.objects.filter(
        order__created_at__gte=from_dt,
        order__created_at__lte=to_dt,
    ).exclude(order__state__in=SALES_EXCLUDED_STATES)
    if customer_id is not None:
        lines = lines.filter(order__customer_id=customer_id)
    if product_id is not None:
        lines = lines.filter(product_id=product_id)
    if order_type:
        lines = lines.filter(order__order_type=order_type)
    return lines


def _sales_row(key: str, label: str, row: dict, extra: dict | None = None) -> dict:
    """PURE — satu baris laporan (`key`/`label`/`unit`/`value` + angka + `extra`)."""
    total_amount = _money(row["total_amount"])
    payload = {
        "key": key,
        "label": label,
        "unit": "IDR",
        "value": total_amount,
        "total_qty": int(row["total_qty"] or 0),
        "total_amount": total_amount,
        "order_count": int(row["order_count"] or 0),
        "line_count": int(row["line_count"] or 0),
    }
    if extra:
        payload.update(extra)
    return payload


def _sales_rows(lines, group_by: str) -> list[dict]:
    """Agregat per ``group_by`` — ``period`` (urut naik) | ``customer``/``product``.

    ``customer``/``product`` diurutkan ``-total_amount`` lalu nama (tie-break).
    Baris tanpa master (FK ``NULL``) tetap muncul dengan label ``(tanpa ...)``.
    ``key`` = ``YYYY-MM`` (period) atau **kode master** (customer/product).
    """
    common = {
        "total_qty": Sum("qty"),
        "total_amount": _sales_amount_expr(),
        "order_count": Count("order_id", distinct=True),
        "line_count": Count("id"),
    }

    if group_by == "period":
        aggregate = (
            lines.annotate(period=TruncMonth("order__created_at"))
            .values("period")
            .annotate(**common)
            .order_by("period")
        )
        rows = []
        for row in aggregate:
            key = row["period"].strftime("%Y-%m") if row["period"] else ""
            rows.append(_sales_row(key, key, row, extra={"period": key}))
        return rows

    if group_by == "customer":
        aggregate = (
            lines.values(
                "order__customer_id",
                "order__customer__code",
                "order__customer__name",
            )
            .annotate(**common)
            .order_by("-total_amount", "order__customer__name")
        )
        rows = []
        for row in aggregate:
            customer_id = row["order__customer_id"]
            code = row["order__customer__code"] or ""
            name = row["order__customer__name"] or ""
            rows.append(
                _sales_row(
                    code or str(customer_id or ""),
                    name or code or "(tanpa customer)",
                    row,
                    extra={
                        "customer_id": customer_id,
                        "customer_code": code,
                        "customer_name": name,
                    },
                )
            )
        return rows

    aggregate = (
        lines.values("product_id", "product__code", "product__name")
        .annotate(**common)
        .order_by("-total_amount", "product__name")
    )
    rows = []
    for row in aggregate:
        product_id = row["product_id"]
        code = row["product__code"] or ""
        name = row["product__name"] or ""
        rows.append(
            _sales_row(
                code or str(product_id or ""),
                name or code or "(tanpa produk)",
                row,
                extra={
                    "product_id": product_id,
                    "product_code": code,
                    "product_name": name,
                },
            )
        )
    return rows


def _sales_summary(
    lines, from_dt, to_dt, customer_id=None, product_id=None, order_type=None
) -> dict:
    """Ringkasan periode — order-side (accrual), ``invoiced_amount``, ``paid_amount``.

    * ``total_*``/``count_*`` = agregat `OrderLine` (mengikuti `group_by` apa pun);
    * ``invoiced_amount`` = Σ `CustomerInvoiceLine.line_total` (SEBELUM pajak, H3.1)
      untuk ``invoice_date`` dalam rentang; invoice ``CANCELLED`` dibuang — ini
      **piutang**, bukan kas;
    * ``paid_amount`` = Σ `Payment.amount` dengan ``payment_type=INBOUND``,
      ``state`` ∈ `SALES_PAID_STATES` (SENT/DONE), ``payment_date`` dalam rentang —
      **BUKAN** dari `CustomerInvoice.amount_total` (keputusan H4.1). Filter
      ``product_id`` diterapkan lewat invoice sumber (subquery, tanpa duplikasi).
    """
    totals = lines.aggregate(
        total_qty=Sum("qty"),
        total_amount=_sales_amount_expr(),
        count_orders=Count("order_id", distinct=True),
        count_lines=Count("id"),
    )

    date_from = timezone.localtime(from_dt).date()
    date_to = timezone.localtime(to_dt).date()

    invoice_lines = CustomerInvoiceLine.objects.filter(
        invoice__invoice_date__gte=date_from,
        invoice__invoice_date__lte=date_to,
    ).exclude(invoice__state__in=SALES_EXCLUDED_STATES)
    if customer_id is not None:
        invoice_lines = invoice_lines.filter(invoice__customer_id=customer_id)
    if product_id is not None:
        invoice_lines = invoice_lines.filter(product_id=product_id)
    if order_type:
        invoice_lines = invoice_lines.filter(invoice__order__order_type=order_type)
    invoiced = invoice_lines.aggregate(
        total=Sum("line_total"), count=Count("invoice_id", distinct=True)
    )

    payments = Payment.objects.filter(
        payment_type=Payment.PaymentType.INBOUND,
        state__in=SALES_PAID_STATES,
        payment_date__gte=date_from,
        payment_date__lte=date_to,
    )
    if customer_id is not None:
        payments = payments.filter(partner_id=customer_id)
    if product_id is not None:
        payments = payments.filter(
            customer_invoice_id__in=CustomerInvoiceLine.objects.filter(
                product_id=product_id
            ).values("invoice_id")
        )
    if order_type:
        payments = payments.filter(customer_invoice__order__order_type=order_type)
    paid = payments.aggregate(total=Sum("amount"), count=Count("id"))

    return {
        "total_qty": int(totals["total_qty"] or 0),
        "total_amount": _money(totals["total_amount"]),
        "count_orders": int(totals["count_orders"] or 0),
        "count_lines": int(totals["count_lines"] or 0),
        "invoiced_amount": _money(invoiced["total"]),
        "invoice_count": int(invoiced["count"] or 0),
        "paid_amount": _money(paid["total"]),
        "payment_count": int(paid["count"] or 0),
        "currency": "IDR",
    }


def _sales_cache_key(
    from_dt, to_dt, group_by: str, customer_id, product_id, order_type
) -> str:
    """Key cache ``reports:sales:<sha1(filter efektif)>`` (TTL `SALES_CACHE_TTL`)."""
    raw = "|".join(
        (
            from_dt.isoformat(),
            to_dt.isoformat(),
            group_by,
            "" if customer_id is None else str(customer_id),
            "" if product_id is None else str(product_id),
            order_type or "",
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{SALES_CACHE_PREFIX}{digest}"


def _sales_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif di respons (`None` = klien tidak mengirim param itu)."""
    return {
        **echo,
        "group_by": options["group_by"],
        "customer_id": options["customer_id"],
        "product_id": options["product_id"],
        "order_type": options["order_type"],
        "nocache": options["nocache"],
        "resolved_from": from_dt.isoformat(),
        "resolved_to": to_dt.isoformat(),
    }


class ReportsSalesView(APIView):
    """``GET /api/v1/reports/sales/`` — laporan penjualan agregat (H4.1, read-only).

    Bentuk::

        {"rows": [{"key", "label", "unit", "value", "total_qty", "total_amount",
                   "order_count", "line_count", ...}],
         "summary": {"total_qty", "total_amount", "count_orders", "count_lines",
                     "invoiced_amount", "invoice_count", "paid_amount",
                     "payment_count", "currency"},
         "group_by": "period", "filters": {...echo...},
         "period": {"from": "ISO-8601", "to": "ISO-8601"},
         "generated_at": "ISO-8601", "cached": false}

    * **Basis periode = ``Order.created_at``** (accrual basis, keputusan H4.1):
      sales diakui saat order **dibuat**. Order ``CANCELLED`` tidak dihitung;
      ``customer_id``/``product_id``/``order_type`` menyaring baris order;
    * nilai uang baris = ``Σ(qty × price_unit)`` — `OrderLine` **tidak** punya
      ``line_total``, jadi dihitung di query (tanpa field/migration baru);
    * ``summary.invoiced_amount`` = piutang dari `CustomerInvoiceLine.line_total`
      (SEBELUM pajak) per ``invoice_date``; ``summary.paid_amount`` = Σ
      `Payment.amount` INBOUND state SENT/DONE per ``payment_date`` — **bukan**
      dari ``CustomerInvoice.amount_total``;
    * `group_by`: ``period`` (bulan, urut naik) | ``customer`` | ``product``
      (``-total_amount`` lalu nama); ``rows`` per grup berisi ``key``/``label``/
      ``unit``/``value`` (alias jumlah uang, pola G4) + ``total_qty``/
      ``total_amount``/``order_count``/``line_count`` dan identitas grup;
    * param rentang: ``?period=YYYY-MM`` > ``?date_from``/``?date_to`` >
      ``?from``/``?to`` (ISO-8601 inklusif; default **bulan berjalan**);
      lainnya: ``?customer_id=``, ``?product_id=``, ``?order_type=``,
      ``?group_by=``, ``?_nocache=1``. Nilai tak dikenal → **400**
      (``{"detail": ...}``), ``from > to`` → **400**;
    * cache 300 detik dengan key ``reports:sales:<sha1(filter)>``; ``cached``
      menandai respons dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak
      menulis cache (escape hatch debug/force refresh).

    Read-only **DB murni** (tanpa Odoo/Celery/task, tanpa migration baru) dan
    tidak mengubah endpoint B13/B16/B18–B21. Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan penjualan; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _sales_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _sales_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        group_by = options["group_by"]
        customer_id = options["customer_id"]
        product_id = options["product_id"]
        order_type = options["order_type"]
        cache_key = _sales_cache_key(
            from_dt, to_dt, group_by, customer_id, product_id, order_type
        )

        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        lines = _sales_lines(from_dt, to_dt, customer_id, product_id, order_type)
        payload = {
            "rows": _sales_rows(lines, group_by),
            "summary": _sales_summary(
                lines, from_dt, to_dt, customer_id, product_id, order_type
            ),
            "group_by": group_by,
            "filters": _sales_filters_echo(echo, options, from_dt, to_dt),
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, SALES_CACHE_TTL)

        logger.info(
            "reports sales: group_by=%s rows=%s order_type=%s customer_id=%s "
            "product_id=%s nocache=%s",
            group_by,
            len(payload["rows"]),
            order_type,
            customer_id,
            product_id,
            options["nocache"],
        )
        return Response(payload)


# ---------------------------------------------------------------------------
# Reports purchases (H4.2) — GET /api/v1/reports/purchases/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``period``).
PURCHASES_GROUP_BY_VALUES = ("period", "vendor", "product")

#: State `PurchaseOrder` yang dikenal (turunan `purchase_order_services.PO_STATES`).
PURCHASES_STATUS_VALUES = ("DRAFT", "CONFIRMED", "DONE", "CANCELLED")

#: State `Payment` OUTBOUND yang dihitung pada ``summary.paid_amount`` (H4.2).
PURCHASES_PAID_STATES = ("SENT", "DONE")

#: State yang TIDAK dihitung: PO CANCELLED bukan pembelian, bill CANCELLED bukan utang.
PURCHASES_EXCLUDED_STATES = ("CANCELLED",)

#: TTL cache laporan pembelian (detik) — laporan "berat" (5 menit).
PURCHASES_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
PURCHASES_CACHE_PREFIX = "reports:purchases:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
PURCHASES_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Batas atas `vendor_id`/`product_id` (PositiveBigInteger).
PURCHASES_MAX_ID = 2**31 - 1


def _purchases_month_range(month: str):
    """``(from_dt, to_dt, error)`` dari ``YYYY-MM`` (delegasi `_sales_month_range`)."""
    return _sales_month_range(month)


def _purchases_boundary(raw: str, *, end: bool):
    """``(datetime, error)`` dari ISO-8601 (delegasi `_sales_boundary`)."""
    return _sales_boundary(raw, end=end)


def _purchases_range(request):
    """``(from_dt, to_dt, echo, error)`` — prioritas param rentang laporan purchases.

    Aturan rentang **identik** H4.1 (delegasi `_sales_range`): ``?period=YYYY-MM``
    > ``?date_from``/``?date_to`` > ``?from``/``?to``; default **bulan berjalan**;
    ``from > to`` → error (view membalas **400**).
    """
    return _sales_range(request)


def _purchases_options(request):
    """``(options, error)`` — parse grup, status, & filter laporan purchases (PURE).

    ``group_by`` default ``period``; ``status`` case-insensitive (``DRAFT``/
    ``CONFIRMED``/``DONE``/``CANCELLED`` — state `PurchaseOrder` MES H2.2);
    ``vendor_id``/``product_id`` angka >= 1; ``_nocache`` truthy.
    """
    group_by = str(request.query_params.get("group_by") or "period").strip().lower()
    if group_by not in PURCHASES_GROUP_BY_VALUES:
        return None, (
            f"Parameter 'group_by'={group_by!r} tidak dikenal "
            f"({'|'.join(PURCHASES_GROUP_BY_VALUES)})."
        )

    status_raw = str(request.query_params.get("status") or "").strip()
    status = status_raw.upper()
    if status and status not in PURCHASES_STATUS_VALUES:
        return None, (
            f"Parameter 'status'={status_raw!r} tidak dikenal "
            f"({'|'.join(PURCHASES_STATUS_VALUES)})."
        )

    vendor_id, error = _int_param(request, "vendor_id", None, 1, PURCHASES_MAX_ID)
    if error:
        return None, error
    product_id, error = _int_param(request, "product_id", None, 1, PURCHASES_MAX_ID)
    if error:
        return None, error

    nocache_raw = str(request.query_params.get("_nocache") or "").strip().lower()
    return (
        {
            "group_by": group_by,
            "status": status or None,
            "vendor_id": vendor_id,
            "product_id": product_id,
            "nocache": nocache_raw in PURCHASES_NOCACHE_TRUTHY,
        },
        None,
    )


def _purchases_amount_expr():
    """PURE — ekspresi ``qty × price_unit``; `PurchaseOrderLine` **tidak** punya `line_total`.

    Field baru **tidak** ditambahkan ke model demi laporan (keputusan H4.2, pola
    H4.1): nilai uang pembelian dihitung dari kolom yang sudah ada.
    """
    return _sales_amount_expr()


def _qty(value) -> float:
    """Decimal/None → float 2 desimal (qty pembelian boleh pecahan, mis. benang 0.3)."""
    return round(float(value or 0), 2)


def _purchases_lines(from_dt, to_dt, vendor_id=None, product_id=None, status=None):
    """QuerySet `PurchaseOrderLine` dalam rentang — basis periode ``PurchaseOrder.created_at``.

    Accrual basis (keputusan H4.2, konsisten H4.1): pembelian diakui saat PO
    **dibuat**. PO ``CANCELLED`` dibuang (bukan pembelian).
    """
    lines = PurchaseOrderLine.objects.filter(
        po__created_at__gte=from_dt,
        po__created_at__lte=to_dt,
    ).exclude(po__state__in=PURCHASES_EXCLUDED_STATES)
    if vendor_id is not None:
        lines = lines.filter(po__vendor_id=vendor_id)
    if product_id is not None:
        lines = lines.filter(product_id=product_id)
    if status:
        lines = lines.filter(po__state=status)
    return lines


def _purchases_row(key: str, label: str, row: dict, extra: dict | None = None) -> dict:
    """PURE — satu baris laporan (`key`/`label`/`unit`/`value` + angka + `extra`)."""
    total_amount = _money(row["total_amount"])
    payload = {
        "key": key,
        "label": label,
        "unit": "IDR",
        "value": total_amount,
        "total_qty": _qty(row["total_qty"]),
        "total_amount": total_amount,
        "purchase_count": int(row["purchase_count"] or 0),
        "line_count": int(row["line_count"] or 0),
    }
    if extra:
        payload.update(extra)
    return payload

def _purchases_rows(lines, group_by: str) -> list[dict]:
    """Agregat per ``group_by`` — ``period`` (urut naik) | ``vendor``/``product``.

    ``vendor``/``product`` diurutkan ``-total_amount`` lalu nama (tie-break).
    ``key`` = ``YYYY-MM`` (period) atau **kode master** (vendor/product).
    """
    common = {
        "total_qty": Sum("qty"),
        "total_amount": _purchases_amount_expr(),
        "purchase_count": Count("po_id", distinct=True),
        "line_count": Count("id"),
    }

    if group_by == "period":
        aggregate = (
            lines.annotate(period=TruncMonth("po__created_at"))
            .values("period")
            .annotate(**common)
            .order_by("period")
        )
        rows = []
        for row in aggregate:
            key = row["period"].strftime("%Y-%m") if row["period"] else ""
            rows.append(_purchases_row(key, key, row, extra={"period": key}))
        return rows

    if group_by == "vendor":
        aggregate = (
            lines.values(
                "po__vendor_id",
                "po__vendor__code",
                "po__vendor__name",
            )
            .annotate(**common)
            .order_by("-total_amount", "po__vendor__name")
        )
        rows = []
        for row in aggregate:
            vendor_id = row["po__vendor_id"]
            code = row["po__vendor__code"] or ""
            name = row["po__vendor__name"] or ""
            rows.append(
                _purchases_row(
                    code or str(vendor_id or ""),
                    name or code or "(tanpa vendor)",
                    row,
                    extra={
                        "vendor_id": vendor_id,
                        "vendor_code": code,
                        "vendor_name": name,
                    },
                )
            )
        return rows

    aggregate = (
        lines.values("product_id", "product__code", "product__name")
        .annotate(**common)
        .order_by("-total_amount", "product__name")
    )
    rows = []
    for row in aggregate:
        product_id = row["product_id"]
        code = row["product__code"] or ""
        name = row["product__name"] or ""
        rows.append(
            _purchases_row(
                code or str(product_id or ""),
                name or code or "(tanpa produk)",
                row,
                extra={
                    "product_id": product_id,
                    "product_code": code,
                    "product_name": name,
                },
            )
        )
    return rows

def _purchases_summary(
    lines, from_dt, to_dt, vendor_id=None, product_id=None, status=None
) -> dict:
    """Ringkasan periode — PO-side (accrual), ``billed_amount``, ``paid_amount``.

    * ``total_*``/``count_*`` = agregat `PurchaseOrderLine` (mengikuti `group_by` apa pun);
    * ``billed_amount`` = Sum `VendorBillLine.line_total` (SEBELUM pajak, H3.2) untuk
      ``invoice_date`` dalam rentang; bill ``CANCELLED`` dibuang — ini **utang**, bukan kas;
    * ``paid_amount`` = Sum `Payment.amount` dengan ``payment_type=OUTBOUND``,
      ``state`` in `PURCHASES_PAID_STATES` (SENT/DONE), ``payment_date`` dalam rentang —
      **BUKAN** dari `VendorBill.amount_total` (keputusan H4.2).
    """
    totals = lines.aggregate(
        total_qty=Sum("qty"),
        total_amount=_purchases_amount_expr(),
        count_purchases=Count("po_id", distinct=True),
        count_lines=Count("id"),
    )

    date_from = timezone.localtime(from_dt).date()
    date_to = timezone.localtime(to_dt).date()

    bill_lines = VendorBillLine.objects.filter(
        bill__invoice_date__gte=date_from,
        bill__invoice_date__lte=date_to,
    ).exclude(bill__state__in=PURCHASES_EXCLUDED_STATES)
    if vendor_id is not None:
        bill_lines = bill_lines.filter(bill__vendor_id=vendor_id)
    if product_id is not None:
        bill_lines = bill_lines.filter(product_id=product_id)
    if status:
        bill_lines = bill_lines.filter(bill__purchase_order__state=status)
    billed = bill_lines.aggregate(
        total=Sum("line_total"), count=Count("bill_id", distinct=True)
    )

    payments = Payment.objects.filter(
        payment_type=Payment.PaymentType.OUTBOUND,
        state__in=PURCHASES_PAID_STATES,
        payment_date__gte=date_from,
        payment_date__lte=date_to,
    )
    if vendor_id is not None:
        payments = payments.filter(partner_id=vendor_id)
    if product_id is not None:
        payments = payments.filter(
            vendor_bill_id__in=VendorBillLine.objects.filter(
                product_id=product_id
            ).values("bill_id")
        )
    if status:
        payments = payments.filter(vendor_bill__purchase_order__state=status)
    paid = payments.aggregate(total=Sum("amount"), count=Count("id"))

    return {
        "total_qty": _qty(totals["total_qty"]),
        "total_amount": _money(totals["total_amount"]),
        "count_purchases": int(totals["count_purchases"] or 0),
        "count_lines": int(totals["count_lines"] or 0),
        "billed_amount": _money(billed["total"]),
        "bill_count": int(billed["count"] or 0),
        "paid_amount": _money(paid["total"]),
        "payment_count": int(paid["count"] or 0),
        "currency": "IDR",
    }

def _purchases_cache_key(
    from_dt, to_dt, group_by: str, vendor_id, product_id, status
) -> str:
    """Key cache ``reports:purchases:<sha1(filter efektif)>`` (TTL `PURCHASES_CACHE_TTL`)."""
    raw = "|".join(
        (
            from_dt.isoformat(),
            to_dt.isoformat(),
            group_by,
            "" if vendor_id is None else str(vendor_id),
            "" if product_id is None else str(product_id),
            status or "",
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{PURCHASES_CACHE_PREFIX}{digest}"


def _purchases_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif di respons (`None` = klien tidak mengirim param itu)."""
    return {
        **echo,
        "group_by": options["group_by"],
        "vendor_id": options["vendor_id"],
        "product_id": options["product_id"],
        "status": options["status"],
        "nocache": options["nocache"],
        "resolved_from": from_dt.isoformat(),
        "resolved_to": to_dt.isoformat(),
    }


class ReportsPurchasesView(APIView):
    """``GET /api/v1/reports/purchases/`` — laporan pembelian agregat (H4.2, read-only).

    Bentuk::

        {"rows": [{"key", "label", "unit", "value", "total_qty", "total_amount",
                   "purchase_count", "line_count", ...}],
         "summary": {"total_qty", "total_amount", "count_purchases", "count_lines",
                     "billed_amount", "bill_count", "paid_amount", "payment_count",
                     "currency"},
         "group_by": "period", "filters": {...echo...},
         "period": {"from": "ISO-8601", "to": "ISO-8601"},
         "generated_at": "ISO-8601", "cached": false}

    * **Basis periode = ``PurchaseOrder.created_at``** (accrual basis, keputusan
      H4.2 — konsisten H4.1): pembelian diakui saat PO **dibuat**. PO ``CANCELLED``
      tidak dihitung; ``vendor_id``/``product_id``/``status`` menyaring baris PO;
    * nilai uang baris = ``Sum(qty × price_unit)`` — `PurchaseOrderLine` **tidak**
      punya ``line_total``, jadi dihitung di query (tanpa field/migration baru);
    * ``summary.billed_amount`` = utang dari `VendorBillLine.line_total` (SEBELUM
      pajak) per ``invoice_date``; ``summary.paid_amount`` = Sum `Payment.amount`
      OUTBOUND state SENT/DONE per ``payment_date`` — **bukan** dari
      ``VendorBill.amount_total``;
    * `group_by`: ``period`` (bulan, urut naik) | ``vendor`` | ``product``
      (``-total_amount`` lalu nama); ``rows`` per grup berisi ``key``/``label``/
      ``unit``/``value`` (alias jumlah uang, pola G4) + ``total_qty`` (float; qty
      pembelian boleh pecahan)/``total_amount``/``purchase_count``/``line_count``;
    * param rentang: ``?period=YYYY-MM`` > ``?date_from``/``?date_to`` >
      ``?from``/``?to`` (ISO-8601 inklusif; default **bulan berjalan**);
      lainnya: ``?vendor_id=``, ``?product_id=``, ``?status=`` (state PO:
      ``DRAFT|CONFIRMED|DONE|CANCELLED``, case-insensitive), ``?group_by=``,
      ``?_nocache=1``. Nilai tak dikenal → **400** (``{"detail": ...}``);
    * cache 300 detik dengan key ``reports:purchases:<sha1(filter)>``; ``cached``
      menandai respons dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak
      menulis cache (escape hatch debug/force refresh).

    Read-only **DB murni** (tanpa Odoo/Celery/task, tanpa migration baru) dan
    tidak mengubah endpoint B10/B11/H4.1. Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan pembelian; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _purchases_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _purchases_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        group_by = options["group_by"]
        vendor_id = options["vendor_id"]
        product_id = options["product_id"]
        po_status = options["status"]
        cache_key = _purchases_cache_key(
            from_dt, to_dt, group_by, vendor_id, product_id, po_status
        )

        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        lines = _purchases_lines(from_dt, to_dt, vendor_id, product_id, po_status)
        payload = {
            "rows": _purchases_rows(lines, group_by),
            "summary": _purchases_summary(
                lines, from_dt, to_dt, vendor_id, product_id, po_status
            ),
            "group_by": group_by,
            "filters": _purchases_filters_echo(echo, options, from_dt, to_dt),
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, PURCHASES_CACHE_TTL)

        logger.info(
            "reports purchases: group_by=%s rows=%s status=%s vendor_id=%s "
            "product_id=%s nocache=%s",
            group_by,
            len(payload["rows"]),
            po_status,
            vendor_id,
            product_id,
            options["nocache"],
        )
        return Response(payload)


# ---------------------------------------------------------------------------
# Reports stock (H4.3) — GET /api/v1/reports/stock/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``product``).
STOCK_GROUP_BY_VALUES = ("product", "location")

#: TTL cache laporan stok (detik) — snapshot Odoo; jangan flood (5 menit).
STOCK_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
STOCK_CACHE_PREFIX = "reports:stock:"

#: Nilai `?only_nonzero` / `?_nocache` yang dianggap **true** (case-insensitive).
STOCK_TRUTHY = ("1", "true", "yes", "on")

#: Batas atas `location_id`/`product_id` (PositiveBigInteger).
STOCK_MAX_ID = 2**31 - 1

#: Satuan baris — H4.3 = **quantity fisik saja** (nilai Rp / COGS = H4.4).
STOCK_UNIT = "unit"


def _stock_truthy(value) -> bool:
    """PURE — param boolean gaya laporan (``1|true|yes|on``, case-insensitive)."""
    return str(value or "").strip().lower() in STOCK_TRUTHY


def _stock_options(request):
    """``(options, error)`` — parse filter laporan stok (PURE).

    ``group_by`` default ``product`` (``product``|``location``); ``location_id``/
    ``product_id`` = **pk `master.Location`/`master.Product`** (dropdown MES, bukan
    ``odoo_id`` — konsisten ``/inventory/stock-qty/``); ``search`` = cari
    `Product.code`/``name`` (case-insensitive); ``only_nonzero``/``_nocache`` truthy.

    **TANPA** param rentang: stok = **snapshot**, bukan time-series (keputusan H4.3).
    """
    group_by = str(request.query_params.get("group_by") or "product").strip().lower()
    if group_by not in STOCK_GROUP_BY_VALUES:
        return None, (
            f"Parameter 'group_by'={group_by!r} tidak dikenal "
            f"({'|'.join(STOCK_GROUP_BY_VALUES)})."
        )

    location_id, error = _int_param(request, "location_id", None, 1, STOCK_MAX_ID)
    if error:
        return None, error
    product_id, error = _int_param(request, "product_id", None, 1, STOCK_MAX_ID)
    if error:
        return None, error

    search = str(request.query_params.get("search") or "").strip()
    return (
        {
            "group_by": group_by,
            "location_id": location_id,
            "product_id": product_id,
            "search": search or None,
            "only_nonzero": _stock_truthy(request.query_params.get("only_nonzero")),
            "nocache": _stock_truthy(request.query_params.get("_nocache")),
        },
        None,
    )


def _stock_location_filter(location_id):
    """``(location, odoo_id, error)`` — validasi `?location_id=` (pk MES).

    Lokasi **wajib** ada, ``usage='internal'``, dan sudah tersinkron (``odoo_id``
    terisi) — kalau tidak → pesan error (view membalas **400**).
    """
    location = Location.objects.filter(pk=location_id).first()
    if location is None:
        return None, None, f"Location {location_id} tidak ditemukan."
    if location.usage != Location.Usage.INTERNAL:
        return (
            None,
            None,
            f"Location usage='{location.usage}'; laporan stok hanya untuk lokasi "
            f"usage='{Location.Usage.INTERNAL}'.",
        )
    if not location.odoo_id:
        return (
            None,
            None,
            f"Location {location.code} belum punya odoo_id (belum tersinkron dari Odoo).",
        )
    return location, int(location.odoo_id), None


def _stock_fetch(location_odoo_id=None):
    """Baca stok dari Odoo lewat jalur **I7** (read-only) → ``(locations, quants, error)``.

    **Dua RPC konstan** (pola `services/reconciliation.py:141-155`):
    ``fetch_internal_locations()`` lalu ``fetch_stock_quants(ids, child_of=True)`` —
    sekali untuk semua lokasi internal, **bukan** per produk. ``child_of=True`` ⇒
    lokasi anak ikut terhitung. ``location_odoo_id`` diisi → hanya lokasi itu
    (+ anaknya) yang dibaca.

    Fail-safe (pola I7/B11): tanpa client (``ERP_ADAPTER`` belum siap) → ``[]``;
    transport melempar (Odoo down/timeout) → ``([], [], pesan)`` + **warning log**
    — **bukan** 500 dan angka tidak dikarang.
    """

    def _read(transport):
        locations = transport.fetch_internal_locations() or []
        if location_odoo_id is not None:
            ids = [location_odoo_id]
        else:
            ids = [
                row["id"]
                for row in locations
                if isinstance(row, dict) and row.get("id") is not None
            ]
        if not ids:
            return locations, []
        return locations, transport.fetch_stock_quants(ids, child_of=True) or []

    try:
        locations, quants = _fetch_transport_data(_read)
    except Exception as exc:  # noqa: BLE001 - laporan read-only; jangan jadikan 500
        logger.warning(
            "reports stock: gagal membaca stock.quant dari Odoo: %s", exc, exc_info=True
        )
        return [], [], "gagal membaca stok dari Odoo"
    return locations or [], quants or [], None

def _stock_product_map():
    """``{odoo_id: Product}`` — HANYA produk master (pola I7); ``uom`` di-prefetch."""
    return {
        int(product.odoo_id): product
        for product in Product.objects.filter(odoo_id__isnull=False).select_related("uom")
    }


def _stock_location_map():
    """``{odoo_id: Location}`` — lokasi master (enrich kode/nama dari MES)."""
    return {
        int(location.odoo_id): location
        for location in Location.objects.filter(odoo_id__isnull=False)
    }


def _stock_location_meta(quants, locations, location_map) -> dict:
    """``{odoo_id lokasi: {location_id, location_code, location_name, location_odoo_id}}``.

    Kode/nama di-*enrich* dari `master.Location` (via ``odoo_id``); fallback ke
    ``complete_name`` Odoo kalau lokasi belum tersinkron ke MES.
    """
    complete = {
        int(row["id"]): (row.get("complete_name") or "")
        for row in (locations or [])
        if isinstance(row, dict) and row.get("id") is not None
    }
    odoo_ids = set(complete)
    for row in quants or []:
        if isinstance(row, dict):
            location_odoo_id = _many2one_id(row.get("location_id"))
            if location_odoo_id is not None:
                odoo_ids.add(int(location_odoo_id))

    meta: dict = {}
    for odoo_id in odoo_ids:
        master = location_map.get(int(odoo_id))
        meta[int(odoo_id)] = {
            "location_id": master.pk if master is not None else None,
            "location_code": (master.code if master is not None else "") or "",
            "location_name": (master.name if master is not None else "")
            or complete.get(int(odoo_id), ""),
            "location_odoo_id": int(odoo_id),
        }
    return meta


def _stock_aggregate(quants, products, options):
    """Agregat **in-memory** per produk & per lokasi → ``(by_product, by_location, stats)``.

    Hanya baris yang produknya **ter-map ke master** yang diagregasi (pola I7
    ``_master_products_by_odoo_id``); produk Odoo non-master tetap dihitung
    transparan di ``stats`` (``unmapped_product_count``/``unmapped_qty``) supaya
    total bisa direkonsiliasi user. Tidak menyentuh DB stok apa pun (CHANGES-DETAIL §4).
    """
    by_product: dict = {}
    by_location: dict = {}
    quant_count = 0
    unmapped_ids: set = set()
    unmapped_qty = 0.0

    search = (options["search"] or "").lower()
    wanted_odoo_id = options.get("product_odoo_id")

    for row in quants or []:
        if not isinstance(row, dict):
            continue
        product_odoo_id = _many2one_id(row.get("product_id"))
        if product_odoo_id is None:
            continue
        product = products.get(int(product_odoo_id))
        if product is None:
            unmapped_ids.add(int(product_odoo_id))
            unmapped_qty += _to_float(row.get("quantity"))
            continue
        if wanted_odoo_id is not None and int(product_odoo_id) != int(wanted_odoo_id):
            continue
        if search and search not in (product.code or "").lower() and search not in (product.name or "").lower():
            continue

        qty = _to_float(row.get("quantity"))
        reserved = _to_float(row.get("reserved_quantity"))
        quant_count += 1

        bucket = by_product.setdefault(
            int(product_odoo_id), {"qty": 0.0, "reserved": 0.0, "locations": set()}
        )
        bucket["qty"] += qty
        bucket["reserved"] += reserved

        location_odoo_id = _many2one_id(row.get("location_id"))
        if location_odoo_id is not None:
            bucket["locations"].add(int(location_odoo_id))
            location_bucket = by_location.setdefault(
                int(location_odoo_id), {"qty": 0.0, "reserved": 0.0, "products": set()}
            )
            location_bucket["qty"] += qty
            location_bucket["reserved"] += reserved
            location_bucket["products"].add(int(product_odoo_id))

    stats = {
        "quant_count": quant_count,
        "unmapped_product_count": len(unmapped_ids),
        "unmapped_qty": _qty(unmapped_qty),
    }
    return by_product, by_location, stats


def _stock_rows(by_product, by_location, products, location_meta, group_by: str) -> list:
    """Baris laporan per ``group_by`` — urut ``-total_qty`` lalu nama (tie-break)."""
    if group_by == "location":
        rows = []
        for location_odoo_id, bucket in by_location.items():
            meta = location_meta.get(int(location_odoo_id), {})
            total_qty = _qty(bucket["qty"])
            reserved_qty = _qty(bucket["reserved"])
            code = meta.get("location_code") or ""
            name = meta.get("location_name") or ""
            rows.append(
                {
                    "key": code or str(location_odoo_id),
                    "label": name or code or f"Location {location_odoo_id}",
                    "unit": STOCK_UNIT,
                    "location_id": meta.get("location_id"),
                    "location_code": code,
                    "location_name": name,
                    "location_odoo_id": int(location_odoo_id),
                    "total_qty": total_qty,
                    "reserved_qty": reserved_qty,
                    "available_qty": _qty(total_qty - reserved_qty),
                    "products_count": len(bucket["products"]),
                }
            )
        rows.sort(key=lambda item: (-item["total_qty"], item["label"]))
        return rows

    rows = []
    for product_odoo_id, bucket in by_product.items():
        product = products[int(product_odoo_id)]
        total_qty = _qty(bucket["qty"])
        reserved_qty = _qty(bucket["reserved"])
        rows.append(
            {
                "key": product.code,
                "label": product.name,
                "unit": STOCK_UNIT,
                "product_id": product.pk,
                "product_code": product.code,
                "product_name": product.name,
                "uom_code": (product.uom.code if product.uom is not None else ""),
                "total_qty": total_qty,
                "reserved_qty": reserved_qty,
                "available_qty": _qty(total_qty - reserved_qty),
                "locations_count": len(bucket["locations"]),
            }
        )
    rows.sort(key=lambda item: (-item["total_qty"], item["label"]))
    return rows


def _stock_summary(by_product, by_location, stats) -> dict:
    """Ringkasan snapshot: qty fisik + reserved/available + hitungan.

    **TANPA** ``currency`` — H4.3 murni quantity (nilai Rp / COGS = H4.4).
    """
    total_qty = _qty(sum(bucket["qty"] for bucket in by_product.values()))
    reserved_qty = _qty(sum(bucket["reserved"] for bucket in by_product.values()))
    return {
        "total_qty": total_qty,
        "reserved_qty": reserved_qty,
        "available_qty": _qty(total_qty - reserved_qty),
        "product_count": len(by_product),
        "location_count": len(by_location),
        "quant_count": int(stats["quant_count"]),
        "unmapped_product_count": int(stats["unmapped_product_count"]),
        "unmapped_qty": stats["unmapped_qty"],
    }


def _stock_cache_key(group_by, location_id, product_id, search, only_nonzero) -> str:
    """Key cache ``reports:stock:<sha1(filter efektif)>`` (TTL `STOCK_CACHE_TTL`)."""
    raw = "|".join(
        (
            group_by,
            "" if location_id is None else str(location_id),
            "" if product_id is None else str(product_id),
            search or "",
            "1" if only_nonzero else "",
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{STOCK_CACHE_PREFIX}{digest}"


def _stock_filters_echo(options: dict) -> dict:
    """Echo filter efektif + penanda sumber (``source='odoo'``)."""
    return {
        "group_by": options["group_by"],
        "location_id": options["location_id"],
        "product_id": options["product_id"],
        "search": options["search"],
        "only_nonzero": options["only_nonzero"],
        "nocache": options["nocache"],
        "source": "odoo",
    }

class ReportsStockView(APIView):
    """``GET /api/v1/reports/stock/`` — laporan stok snapshot (H4.3, read-only).

    Bentuk::

        {"rows": [{"key", "label", "unit", "product_id", "product_code",
                   "product_name", "uom_code", "total_qty", "reserved_qty",
                   "available_qty", "locations_count"}],
         "summary": {"total_qty", "reserved_qty", "available_qty", "product_count",
                     "location_count", "quant_count", "unmapped_product_count",
                     "unmapped_qty"},
         "group_by": "product", "filters": {...echo + source},
         "generated_at": "ISO-8601", "cached": false, "source": "odoo"}

    * **Sumber = Odoo ``stock.quant`` LIVE** (``quantity``/``reserved_quantity``)
      dibaca on-demand lewat jalur **I7** — ``fetch_internal_locations()`` +
      ``fetch_stock_quants(ids, child_of=True)`` = **2 RPC per request** (bukan per
      produk), lihat ``services/reconciliation.py``. MES **TIDAK** menyimpan tabel
      stok (CHANGES-DETAIL §4) — tidak ada model/migrasi baru;
    * ``available_qty = quantity − reserved_quantity`` dihitung di MES (field
      ``available_quantity`` tidak diambil I7 ⇒ hemat RPC);
    * **snapshot, bukan time-series** ⇒ **TANPA** ``?period``/``?date_from``/
      ``?date_to``;
    * ``?group_by=product`` (default) | ``location``; ``?location_id=``/
      ``?product_id=`` = **pk MES** (dropdown master) di-map ke ``odoo_id``
      (lokasi non-``internal``/belum sinkron → **400**); ``?search=`` cari
      `Product.code`/``name``; ``?only_nonzero=1``; ``?_nocache=1``. Nilai tak
      dikenal → **400**;
    * hanya baris yang produknya **ter-map ke master MES** yang diagregasi (pola I7);
      produk Odoo non-master tetap dihitung **transparan** di
      ``summary.unmapped_product_count``/``unmapped_qty`` supaya total bisa
      direkonsiliasi (angka tidak "hilang");
    * cache 300 detik key ``reports:stock:<sha1(filter)>`` (**jangan flood Odoo**);
      ``cached`` menandai respons dari cache; ``?_nocache=1`` = tidak membaca **dan**
      tidak menulis cache;
    * **fail-safe**: ``ERP_ADAPTER`` belum siap / Odoo down / tanpa lokasi internal →
      HTTP **200** dengan ``rows=[]`` + summary nol + **warning** di log (pola
      I7/B11) — bukan 500, angka tidak dikarang.

    Read-only (tanpa Odoo write, tanpa task/Celery, tanpa migration) dan **tidak**
    mengubah I7 (``/reconciliation/report/``), B30 (``/inventory/reporting/``),
    ``/inventory/stock-qty/``, H4.1, H4.2. Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan stok; lihat docstring kelas."""
        options, error = _stock_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        location_odoo_id = None
        if options["location_id"] is not None:
            _location, location_odoo_id, error = _stock_location_filter(options["location_id"])
            if error:
                return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        product_odoo_id = None
        if options["product_id"] is not None:
            product = Product.objects.filter(pk=options["product_id"]).first()
            if product is None:
                return Response(
                    {"detail": f"Product {options['product_id']} tidak ditemukan."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not product.odoo_id:
                return Response(
                    {
                        "detail": (
                            f"Product {product.code} belum punya odoo_id "
                            "(belum tersinkron dari Odoo)."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            product_odoo_id = int(product.odoo_id)
        options = {**options, "product_odoo_id": product_odoo_id}

        cache_key = _stock_cache_key(
            options["group_by"],
            options["location_id"],
            options["product_id"],
            options["search"],
            options["only_nonzero"],
        )
        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        locations, quants, fetch_error = _stock_fetch(location_odoo_id)
        if fetch_error is not None:
            by_product: dict = {}
            by_location: dict = {}
            location_meta: dict = {}
            products: dict = {}
            stats = {"quant_count": 0, "unmapped_product_count": 0, "unmapped_qty": 0.0}
        else:
            products = _stock_product_map()
            location_meta = _stock_location_meta(quants, locations, _stock_location_map())
            by_product, by_location, stats = _stock_aggregate(quants, products, options)
            if options["only_nonzero"]:
                by_product = {
                    key: value
                    for key, value in by_product.items()
                    if _qty(value["qty"]) != 0
                }
                by_location = {
                    key: value
                    for key, value in by_location.items()
                    if _qty(value["qty"]) != 0
                }

        payload = {
            "rows": _stock_rows(
                by_product, by_location, products, location_meta, options["group_by"]
            ),
            "summary": _stock_summary(by_product, by_location, stats),
            "group_by": options["group_by"],
            "filters": _stock_filters_echo(options),
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
            "source": "odoo",
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, STOCK_CACHE_TTL)

        logger.info(
            "reports stock: group_by=%s rows=%s location_id=%s product_id=%s "
            "search=%s only_nonzero=%s nocache=%s quant=%s",
            options["group_by"],
            len(payload["rows"]),
            options["location_id"],
            options["product_id"],
            options["search"],
            options["only_nonzero"],
            options["nocache"],
            stats["quant_count"],
        )
        return Response(payload)

# ---------------------------------------------------------------------------
# Reports COGS / HPP (H4.4) — GET /api/v1/reports/cogs/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``period``).
COGS_GROUP_BY_VALUES = ("period", "customer", "product")

#: Tipe order yang dikenal (turunan `Order.OrderType`: EXPORT/CUSTOM/BRAND).
COGS_ORDER_TYPES = SALES_ORDER_TYPES

#: State Order yang TIDAK dihitung: CANCELLED bukan penjualan (konsisten H4.1).
COGS_EXCLUDED_STATES = ("CANCELLED",)

#: TTL cache laporan HPP (detik) — laporan "berat" (5 menit).
COGS_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
COGS_CACHE_PREFIX = "reports:cogs:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
COGS_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Batas atas `customer_id`/`product_id` (PositiveBigInteger).
COGS_MAX_ID = 2**31 - 1

#: Mata uang laporan uang (konsisten H4.1/H4.2; H4.3 quantity sengaja tanpa ini).
COGS_CURRENCY = "IDR"

#: Alasan baris kehilangan COGS: produk belum tersinkron (``product`` NULL).
COGS_MISSING_NO_PRODUCT = "no_product"
#: Alasan baris kehilangan COGS: produk ada tapi ``cost_price`` masih 0.
COGS_MISSING_NO_COST = "no_cost"


def _cogs_options(request):
    """``(options, error)`` — parse grup & filter laporan HPP (PURE).

    Semantik **identik** H4.1 (delegasi `_sales_options`): ``group_by`` default
    ``period`` (``period``|``customer``|``product``); ``order_type``
    case-insensitive (``EXPORT``/``CUSTOM``/``BRAND``); ``customer_id``/
    ``product_id`` angka >= 1; ``_nocache`` truthy.
    """
    return _sales_options(request)


def _cogs_lines(from_dt, to_dt, customer_id=None, product_id=None, order_type=None):
    """QuerySet `OrderLine` dalam rentang — basis ``Order.created_at`` (accrual).

    Sumber **sama** H4.1 (delegasi `_sales_lines`): order ``CANCELLED`` dibuang
    (bukan penjualan ⇒ tidak ada HPP yang diakui).
    """
    return _sales_lines(from_dt, to_dt, customer_id, product_id, order_type)


def _cogs_sales_expr():
    """PURE — ekspresi omzet ``qty × price_unit`` (delegasi `_sales_amount_expr`)."""
    return _sales_amount_expr()


def _cogs_cost_expr():
    """PURE — ekspresi HPP ``qty × product.cost_price``.

    ``product`` NULL (baris belum tersinkron) → ``product__cost_price`` NULL →
    kontribusi **0** (Sum mengabaikan NULL) — COGS **tidak difabrikasi**; baris
    seperti itu ditandai lewat ``has_missing_cost``/``missing_cost_reason``.
    """
    return Sum(
        F("qty") * F("product__cost_price"),
        output_field=DecimalField(max_digits=22, decimal_places=2),
    )


def _cogs_missing_exprs() -> dict:
    """PURE — ekspresi hitung baris tanpa COGS (2 alasan, 1 query)."""
    return {
        "missing_product": Count("id", filter=Q(product__isnull=True)),
        "missing_cost": Count(
            "id", filter=Q(product__isnull=False, product__cost_price=0)
        ),
    }


def _money_pct(numerator, denominator) -> float:
    """PURE — persentase 2 desimal; ``denominator = 0`` → ``0.0`` (tanpa div/0)."""
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator) * 100, 2)

def _cogs_row(key: str, label: str, row: dict, extra: dict | None = None) -> dict:
    """PURE — satu baris laporan HPP (omzet, HPP, laba kotor, margin %, flag)."""
    sales_amount = _money(row["sales"])
    cogs_amount = _money(row["cogs"])
    gross_profit = _money(sales_amount - cogs_amount)
    missing_product = int(row["missing_product"] or 0)
    missing_cost = int(row["missing_cost"] or 0)

    if missing_product:
        reason = COGS_MISSING_NO_PRODUCT
    elif missing_cost:
        reason = COGS_MISSING_NO_COST
    else:
        reason = None

    payload = {
        "key": key,
        "label": label,
        "sales_amount": sales_amount,
        "cogs_amount": cogs_amount,
        "gross_profit": gross_profit,
        "gross_margin_pct": _money_pct(gross_profit, sales_amount),
        "order_count": int(row["orders"] or 0),
        "line_count": int(row["lines"] or 0),
        "qty_total": int(row["qty"] or 0),
        # Transparansi: baris agregat ini memuat baris order yang COGS-nya hilang.
        "has_missing_cost": (missing_product + missing_cost) > 0,
        "missing_cost_reason": reason,
    }
    if extra:
        payload.update(extra)
    return payload


def _cogs_rows(lines, group_by: str) -> list:
    """Agregat per ``group_by`` — ``period`` (urut naik) | ``customer``/``product``.

    ``customer``/``product`` diurutkan ``-sales_amount`` lalu nama (tie-break) —
    konsisten pola H4.1/H4.2 (urut nilai uang terbesar).
    """
    common = {
        "sales": _cogs_sales_expr(),
        "cogs": _cogs_cost_expr(),
        "qty": Sum("qty"),
        "lines": Count("id"),
        "orders": Count("order_id", distinct=True),
        **_cogs_missing_exprs(),
    }

    if group_by == "period":
        aggregate = (
            lines.annotate(period=TruncMonth("order__created_at"))
            .values("period")
            .annotate(**common)
            .order_by("period")
        )
        rows = []
        for row in aggregate:
            key = row["period"].strftime("%Y-%m") if row["period"] else ""
            rows.append(_cogs_row(key, key, row, extra={"period": key}))
        return rows

    if group_by == "customer":
        aggregate = (
            lines.values(
                "order__customer_id",
                "order__customer__code",
                "order__customer__name",
            )
            .annotate(**common)
            .order_by("-sales", "order__customer__name")
        )
        rows = []
        for row in aggregate:
            customer_id = row["order__customer_id"]
            code = row["order__customer__code"] or ""
            name = row["order__customer__name"] or ""
            rows.append(
                _cogs_row(
                    code or str(customer_id or ""),
                    name or code or "(tanpa customer)",
                    row,
                    extra={
                        "customer_id": customer_id,
                        "customer_code": code,
                        "customer_name": name,
                    },
                )
            )
        return rows

    aggregate = (
        lines.values("product_id", "product__code", "product__name")
        .annotate(**common)
        .order_by("-sales", "product__name")
    )
    rows = []
    for row in aggregate:
        product_id = row["product_id"]
        code = row["product__code"] or ""
        name = row["product__name"] or ""
        rows.append(
            _cogs_row(
                code or str(product_id or ""),
                name or code or "(tanpa produk)",
                row,
                extra={
                    "product_id": product_id,
                    "product_code": code,
                    "product_name": name,
                    "qty": int(row["qty"] or 0),
                },
            )
        )
    return rows


def _cogs_summary(lines) -> dict:
    """Ringkasan periode — omzet, HPP simplified, laba kotor, margin %, penanda data hilang.

    ``rows_with_missing_cost`` = jumlah **baris OrderLine** yang COGS-nya tidak bisa
    dihitung (``product`` NULL **atau** ``product.cost_price = 0``) — angka penjualan
    tetap dihitung apa adanya; COGS **tidak difabrikasi**.
    """
    totals = lines.aggregate(
        sales=_cogs_sales_expr(),
        cogs=_cogs_cost_expr(),
        qty=Sum("qty"),
        count_orders=Count("order_id", distinct=True),
        count_lines=Count("id"),
        **_cogs_missing_exprs(),
    )

    sales = _money(totals["sales"])
    cogs = _money(totals["cogs"])
    gross_profit = _money(sales - cogs)

    return {
        "total_sales": sales,
        "total_cogs": cogs,
        "total_gross_profit": gross_profit,
        "gross_margin_pct": _money_pct(gross_profit, sales),
        "order_count": int(totals["count_orders"] or 0),
        "line_count": int(totals["count_lines"] or 0),
        "qty_total": int(totals["qty"] or 0),
        "rows_with_missing_cost": int(
            (totals["missing_product"] or 0) + (totals["missing_cost"] or 0)
        ),
        "currency": COGS_CURRENCY,
    }


def _cogs_cache_key(
    from_dt, to_dt, group_by: str, customer_id, product_id, order_type
) -> str:
    """Key cache ``reports:cogs:<sha1(filter efektif)>`` (TTL `COGS_CACHE_TTL`)."""
    raw = "|".join(
        (
            from_dt.isoformat(),
            to_dt.isoformat(),
            group_by,
            "" if customer_id is None else str(customer_id),
            "" if product_id is None else str(product_id),
            order_type or "",
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{COGS_CACHE_PREFIX}{digest}"


def _cogs_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif di respons (pola H4.1 — `None` = klien tidak kirim)."""
    return _sales_filters_echo(echo, options, from_dt, to_dt)

class ReportsCogsView(APIView):
    """``GET /api/v1/reports/cogs/`` — laporan HPP/laba kotor (H4.4, read-only).

    Bentuk::

        {"rows": [{"key", "label", "sales_amount", "cogs_amount",
                   "gross_profit", "gross_margin_pct", "order_count",
                   "line_count", "qty_total", "has_missing_cost",
                   "missing_cost_reason", ...}],
         "summary": {"total_sales", "total_cogs", "total_gross_profit",
                     "gross_margin_pct", "order_count", "line_count", "qty_total",
                     "rows_with_missing_cost", "currency"},
         "group_by": "period", "filters": {...echo...},
         "period": {"from": "ISO-8601", "to": "ISO-8601"},
         "generated_at": "ISO-8601", "cached": false}

    * **HPP simplified (keputusan H4.4)**: ``cogs = Σ(qty × Product.cost_price)``;
      omzet ``sales = Σ(qty × OrderLine.price_unit)``; ``gross_profit = sales − cogs``;
      ``gross_margin_pct = gross_profit / sales × 100`` (``sales = 0`` → **0**, tanpa
      divide-by-zero). **Biaya tenaga kerja + overhead = sprint terpisah** (H4.4 hanya
      bahan/harga pokok produk);
    * **basis periode = ``Order.created_at``** (accrual, konsisten H4.1); order
      ``CANCELLED`` dibuang (bukan penjualan ⇒ tidak ada HPP);
    * **``cost_price = 0`` ATAU ``product`` NULL → COGS 0, JANGAN difabrikasi**: baris
      tetap dihitung (omzet apa adanya) dan ditandai ``has_missing_cost: true`` +
      ``missing_cost_reason`` (``no_product`` > ``no_cost``); totalnya di
      ``summary.rows_with_missing_cost`` (jumlah **baris OrderLine**) supaya angka bisa
      direkonsiliasi user;
    * ``?group_by=period`` (default) | ``customer`` | ``product``; rumus agregat dihitung
      di DB (1 query per response, tanpa N+1); urut ``period`` naik, ``customer``/
      ``product`` = ``-sales_amount`` lalu nama;
    * param: ``?period=YYYY-MM`` > ``?date_from``/``?date_to`` > ``?from``/``?to``
      (ISO-8601 inklusif; default **bulan berjalan**) — delegasi `_sales_range`,
      konsisten H4.1; lainnya ``?customer_id=``, ``?product_id=``, ``?order_type=``,
      ``?group_by=``, ``?_nocache=1``. Nilai tak dikenal → **400**;
    * cache 300 detik key ``reports:cogs:<sha1(filter)>``; ``cached`` menandai respons
      dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak menulis cache
      (cache hit = **0 query** — laporan uang ini "berat").

    Read-only **DB murni** (tanpa Odoo/Celery/task, tanpa migration baru) — **tidak**
    mengubah H4.1/H4.2/H4.3, endpoint harga H3.5 (``Product.cost_price`` +
    ``price_updated_at``), maupun auto-fill H2.2 (`PurchaseOrderLine.price_unit`).
    Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan HPP; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _sales_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _cogs_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        group_by = options["group_by"]
        customer_id = options["customer_id"]
        product_id = options["product_id"]
        order_type = options["order_type"]
        cache_key = _cogs_cache_key(
            from_dt, to_dt, group_by, customer_id, product_id, order_type
        )

        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        lines = _cogs_lines(from_dt, to_dt, customer_id, product_id, order_type)
        payload = {
            "rows": _cogs_rows(lines, group_by),
            "summary": _cogs_summary(lines),
            "group_by": group_by,
            "filters": _cogs_filters_echo(echo, options, from_dt, to_dt),
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, COGS_CACHE_TTL)

        logger.info(
            "reports cogs: group_by=%s rows=%s order_type=%s customer_id=%s "
            "product_id=%s nocache=%s missing=%s",
            group_by,
            len(payload["rows"]),
            order_type,
            customer_id,
            product_id,
            options["nocache"],
            payload["summary"]["rows_with_missing_cost"],
        )
        return Response(payload)

# ---------------------------------------------------------------------------
# Reports PnL / Laba-Rugi (H4.5) — GET /api/v1/reports/pnl/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``period``).
PNL_GROUP_BY_VALUES = ("period", "quarter")

#: State Order yang TIDAK dihitung (konsisten H4.1/H4.4).
PNL_EXCLUDED_STATES = ("CANCELLED",)

#: TTL cache laporan laba-rugi (detik) — laporan "berat" (5 menit).
PNL_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
PNL_CACHE_PREFIX = "reports:pnl:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
PNL_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Mata uang laporan uang (konsisten H4.1/H4.2/H4.4).
PNL_CURRENCY = "IDR"

#: `account.account_type` yang dihitung sebagai **biaya operasional** (opex).
#: CATATAN: ``expense_direct_cost`` = "Cost of Revenue" (COGS-like) — tetap
#: dimasukkan sesuai keputusan H4.5 (HPP H4.4 dihitung dari `Product.cost_price`,
#: jadi tidak ada nominal yang dihitung dua kali); nilainya diekspos di summary
#: (``opex_account_types``) supaya bisa diaudit user.
PNL_OPEX_ACCOUNT_TYPES = ("expense", "expense_depreciation", "expense_direct_cost")

#: State `JournalEntry` yang dihitung sebagai opex (keputusan H4.5).
#: ``CONFIRMED`` = niat final akuntan (hanya lag push); ``SENT``/``DONE`` = final.
PNL_OPEX_STATES = ("CONFIRMED", "SENT", "DONE")

#: Penanda sumber opex di summary.
PNL_OPEX_SOURCE_JOURNAL = "journal_entry"
PNL_OPEX_SOURCE_UNAVAILABLE = "unavailable"

#: Bucket kosong (bulan/kuartal tanpa OrderLine) — supaya baris opex-only tetap bisa.
PNL_ZERO_BUCKET = {
    "revenue": 0,
    "cogs": 0,
    "orders": 0,
    "lines": 0,
    "missing_product": 0,
    "missing_cost": 0,
}


def _pnl_options(request):
    """``(options, error)`` — parse grup laporan laba-rugi (PURE).

    ``group_by`` default ``period`` (``period``|``quarter``); ``_nocache`` truthy.
    **TANPA** ``?customer_id``/``?product_id`` — PnL = agregat bisnis (keputusan H4.5).
    """
    group_by = str(request.query_params.get("group_by") or "period").strip().lower()
    if group_by not in PNL_GROUP_BY_VALUES:
        return None, (
            f"Parameter 'group_by'={group_by!r} tidak dikenal "
            f"({'|'.join(PNL_GROUP_BY_VALUES)})."
        )

    nocache_raw = str(request.query_params.get("_nocache") or "").strip().lower()
    return (
        {
            "group_by": group_by,
            "nocache": nocache_raw in PNL_NOCACHE_TRUTHY,
        },
        None,
    )


def _pnl_revenue_expr():
    """PURE — ekspresi omzet ``qty × price_unit`` (reuse H4.4)."""
    return _cogs_sales_expr()


def _pnl_cost_expr():
    """PURE — ekspresi HPP ``qty × product.cost_price`` (reuse H4.4)."""
    return _cogs_cost_expr()


def _pnl_bucket_label(value, group_by: str) -> str:
    """PURE — label bucket: ``YYYY-MM`` (period) atau ``YYYY-Qn`` (quarter)."""
    if group_by == "quarter":
        return f"{value.year}-Q{(value.month - 1) // 3 + 1}"
    return value.strftime("%Y-%m")


def _pnl_opex_available() -> bool:
    """``True`` bila chart of accounts sudah punya >= 1 akun expense-family.

    Kalau **belum ada** (pull Odoo belum jalan) → opex **tidak tersedia**: jangan
    menampilkan ``0`` yang menyesatkan (keputusan H4.5).
    """
    return Account.objects.filter(account_type__in=PNL_OPEX_ACCOUNT_TYPES).exists()


def _pnl_opex_by_bucket(date_from, date_to, group_by: str) -> dict:
    """``{bucket: opex}`` — Σ(debit − credit) jurnal expense per bulan/kuartal (1 query).

    Sumber: `JournalEntryLine` (H3.4) → `entry.state ∈ PNL_OPEX_STATES`,
    `entry.entry_date` dalam rentang, ``account.account_type ∈ PNL_OPEX_ACCOUNT_TYPES``.
    """
    trunc = TruncMonth if group_by == "period" else TruncQuarter
    aggregate = (
        JournalEntryLine.objects.filter(
            entry__state__in=PNL_OPEX_STATES,
            entry__entry_date__gte=date_from,
            entry__entry_date__lte=date_to,
            account__account_type__in=PNL_OPEX_ACCOUNT_TYPES,
        )
        .annotate(bucket=trunc("entry__entry_date"))
        .values("bucket")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )

    totals: dict = {}
    for row in aggregate:
        bucket = row["bucket"]
        if bucket is None:
            continue
        key = _pnl_bucket_label(bucket, group_by)
        totals[key] = _money(_to_float(row["debit"]) - _to_float(row["credit"]))
    return totals

def _pnl_row(key: str, label: str, row: dict, opex, extra: dict | None = None) -> dict:
    """PURE — satu baris PnL (omzet, HPP, laba kotor, opex, laba bersih, margin %)."""
    revenue = _money(row["revenue"])
    cogs = _money(row["cogs"])
    gross_profit = _money(revenue - cogs)
    net_profit = gross_profit if opex is None else _money(gross_profit - opex)

    missing_product = int(row["missing_product"] or 0)
    missing_cost = int(row["missing_cost"] or 0)
    if missing_product:
        reason = COGS_MISSING_NO_PRODUCT
    elif missing_cost:
        reason = COGS_MISSING_NO_COST
    else:
        reason = None

    payload = {
        "key": key,
        "label": label,
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": _money_pct(gross_profit, revenue),
        "opex": opex,
        "net_profit": net_profit,
        "net_margin_pct": _money_pct(net_profit, revenue),
        "order_count": int(row["orders"] or 0),
        "line_count": int(row["lines"] or 0),
        "has_missing_cost": (missing_product + missing_cost) > 0,
        "missing_cost_reason": reason,
    }
    if extra:
        payload.update(extra)
    return payload


def _pnl_rows(lines, group_by: str, opex_by_bucket: dict, opex_available: bool) -> list:
    """Baris per bulan/kuartal — gabungan bucket **penjualan ∪ beban** (urut naik).

    Bucket dari jurnal yang tidak punya penjualan tetap muncul (beban periode itu
    nyata) ⇒ Σ baris == summary. Urut naik (period/quarter).
    """
    trunc = TruncMonth if group_by == "period" else TruncQuarter
    common = {
        "revenue": _pnl_revenue_expr(),
        "cogs": _pnl_cost_expr(),
        "orders": Count("order_id", distinct=True),
        "lines": Count("id"),
        **_cogs_missing_exprs(),
    }
    aggregate = (
        lines.annotate(bucket=trunc("order__created_at"))
        .values("bucket")
        .annotate(**common)
    )

    sales_by_bucket: dict = {}
    for row in aggregate:
        if row["bucket"] is None:
            continue
        sales_by_bucket[_pnl_bucket_label(row["bucket"], group_by)] = row

    field = "quarter" if group_by == "quarter" else "period"
    rows = []
    for key in sorted(set(sales_by_bucket) | set(opex_by_bucket)):
        row = sales_by_bucket.get(key) or PNL_ZERO_BUCKET
        opex = opex_by_bucket.get(key, 0.0) if opex_available else None
        rows.append(_pnl_row(key, key, row, opex, extra={field: key}))
    return rows


def _pnl_summary(lines, opex, opex_source: str) -> dict:
    """Ringkasan PnL — omzet, HPP, laba kotor, opex, laba bersih, margin, sumber opex.

    ``opex = None`` (sumber tidak tersedia) → ``net_profit = gross_profit`` dan
    ``net_margin_pct = gross_margin_pct`` — angka **tidak dikarang** (keputusan H4.5).
    """
    totals = lines.aggregate(
        revenue=_pnl_revenue_expr(),
        cogs=_pnl_cost_expr(),
        count_orders=Count("order_id", distinct=True),
        lines=Count("id"),
        **_cogs_missing_exprs(),
    )

    revenue = _money(totals["revenue"])
    cogs = _money(totals["cogs"])
    gross_profit = _money(revenue - cogs)
    net_profit = gross_profit if opex is None else _money(gross_profit - opex)

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_margin_pct": _money_pct(gross_profit, revenue),
        "opex": opex,
        "net_profit": net_profit,
        "net_margin_pct": _money_pct(net_profit, revenue),
        "opex_source": opex_source,
        "opex_account_types": list(PNL_OPEX_ACCOUNT_TYPES),
        "opex_states": list(PNL_OPEX_STATES),
        "order_count": int(totals["count_orders"] or 0),
        "line_count": int(totals["lines"] or 0),
        "rows_with_missing_cost": int(
            (totals["missing_product"] or 0) + (totals["missing_cost"] or 0)
        ),
        "currency": PNL_CURRENCY,
    }


def _pnl_cache_key(from_dt, to_dt, group_by: str) -> str:
    """Key cache ``reports:pnl:<sha1(filter efektif)>`` (TTL `PNL_CACHE_TTL`)."""
    raw = "|".join((from_dt.isoformat(), to_dt.isoformat(), group_by))
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{PNL_CACHE_PREFIX}{digest}"


def _pnl_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif di respons (pola H4.1; TANPA customer/product/order_type)."""
    return {
        **echo,
        "group_by": options["group_by"],
        "nocache": options["nocache"],
        "resolved_from": from_dt.isoformat(),
        "resolved_to": to_dt.isoformat(),
    }

class ReportsPnlView(APIView):
    """``GET /api/v1/reports/pnl/`` — laporan laba-rugi (H4.5, read-only).

    Bentuk::

        {"rows": [{"key", "label", "revenue", "cogs", "gross_profit",
                   "gross_margin_pct", "opex", "net_profit", "net_margin_pct",
                   "order_count", "line_count", "has_missing_cost",
                   "missing_cost_reason", "period"|"quarter"}],
         "summary": {"revenue", "cogs", "gross_profit", "gross_margin_pct",
                     "opex", "net_profit", "net_margin_pct", "opex_source",
                     "opex_account_types", "opex_states", "order_count",
                     "line_count", "rows_with_missing_cost", "currency"},
         "group_by": "period", "filters": {...echo...},
         "period": {"from": "ISO-8601", "to": "ISO-8601"},
         "generated_at": "ISO-8601", "cached": false}

    * **Rantai PnL (keputusan H4.5)**: ``revenue = Σ(qty × price_unit)`` (reuse
      H4.1/H4.4) → ``cogs = Σ(qty × Product.cost_price)`` (HPP simplified H4.4) →
      ``gross_profit = revenue − cogs`` → ``opex`` (biaya operasional) →
      ``net_profit = gross_profit − opex``; ``*_margin_pct = laba / revenue × 100``
      (``revenue = 0`` → **0**, tanpa divide-by-zero);
    * **basis periode = ``Order.created_at``** (accrual, konsisten H4.1); order
      ``CANCELLED`` dibuang (tidak ada omzet/HPP yang diakui);
    * **opex = Σ(debit − credit) `JournalEntryLine`** (H3.4) dengan
      ``account.account_type`` ∈ `PNL_OPEX_ACCOUNT_TYPES` (``expense``,
      ``expense_depreciation``, ``expense_direct_cost``) dan ``entry.state`` ∈
      `PNL_OPEX_STATES` (``CONFIRMED``/``SENT``/``DONE``), ``entry.entry_date``
      dalam rentang. ``expense_direct_cost`` = *Cost of Revenue* (COGS-like) tetap
      dihitung di sini sesuai keputusan H4.5 — **bukan** double-count nominal
      karena HPP H4.4 berasal dari `Product.cost_price` (posting berbeda); daftar
      tipe akun diekspos di ``summary.opex_account_types`` agar bisa diaudit;
    * **``opex_source``**: ``journal_entry`` bila chart of accounts sudah punya akun
      expense-family; ``unavailable`` bila **belum ada** → ``opex = null`` dan
      ``net_profit = gross_profit`` (**angka tidak dikarang**) + **warning** di log;
    * ``?group_by=period`` (default, bucket ``YYYY-MM``) | ``quarter`` (bucket
      ``YYYY-Qn``, `TruncQuarter`); baris = **gabungan bucket penjualan ∪ bucket
      beban** ⇒ bulan/kuartal tanpa penjualan tapi ada beban tetap muncul dan
      **Σ baris == summary**; urut naik;
    * param rentang: ``?period=YYYY-MM`` > ``?date_from``/``?date_to`` >
      ``?from``/``?to`` (ISO-8601 inklusif; default **bulan berjalan**) — delegasi
      `_sales_range`, konsisten H4.1; plus ``?group_by=``, ``?_nocache=1``.
      **TANPA** ``?customer_id``/``?product_id`` (PnL = agregat bisnis); nilai tak
      dikenal → **400**;
    * cache 300 detik key ``reports:pnl:<sha1(filter)>``; ``cached`` menandai respons
      dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak menulis cache
      (cache hit = **0 query DB**).

    Read-only (tanpa Odoo/task/migration) dan **tidak** mengubah H4.1–H4.4 maupun
    H3.4 (`/finance/journal-entries/`). Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan laba-rugi; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _sales_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _pnl_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        group_by = options["group_by"]
        cache_key = _pnl_cache_key(from_dt, to_dt, group_by)
        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        date_from = timezone.localtime(from_dt).date()
        date_to = timezone.localtime(to_dt).date()
        lines = _cogs_lines(from_dt, to_dt)

        if _pnl_opex_available():
            opex_source = PNL_OPEX_SOURCE_JOURNAL
            opex_by_bucket = _pnl_opex_by_bucket(date_from, date_to, group_by)
            opex_total = _money(sum(opex_by_bucket.values()))
        else:
            logger.warning(
                "reports pnl: chart of accounts expense belum tersedia -> opex "
                "'unavailable' (net_profit = gross_profit, bukan 0 yang menyesatkan)."
            )
            opex_source = PNL_OPEX_SOURCE_UNAVAILABLE
            opex_by_bucket = {}
            opex_total = None

        opex_available = opex_source == PNL_OPEX_SOURCE_JOURNAL
        payload = {
            "rows": _pnl_rows(lines, group_by, opex_by_bucket, opex_available),
            "summary": _pnl_summary(lines, opex_total, opex_source),
            "group_by": group_by,
            "filters": _pnl_filters_echo(echo, options, from_dt, to_dt),
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, PNL_CACHE_TTL)

        logger.info(
            "reports pnl: group_by=%s rows=%s opex_source=%s opex=%s nocache=%s",
            group_by,
            len(payload["rows"]),
            opex_source,
            opex_total,
            options["nocache"],
        )
        return Response(payload)

# ---------------------------------------------------------------------------
# Reports production (H4.6) — GET /api/v1/reports/production/
# ---------------------------------------------------------------------------
#: Nilai `?group_by` yang dikenal (default ``period``).
PRODUCTION_GROUP_BY_VALUES = ("period", "work_center", "line")

#: State Bundle yang TIDAK dihitung sebagai output (dibatalkan).
PRODUCTION_EXCLUDED_BUNDLE_STATES = ("CANCELLED",)

#: TTL cache laporan produksi (detik) — laporan "berat" (5 menit).
PRODUCTION_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari filter efektif.
PRODUCTION_CACHE_PREFIX = "reports:production:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
PRODUCTION_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Batas atas `work_center_id`/`line_id` (PositiveBigInteger).
PRODUCTION_MAX_ID = 2**31 - 1

#: Basis waktu per metrik (keputusan H4.6) — **dua** sumber karena scrap tidak punya
#: event: output/efisiensi/OTD dari realisasi `BundleEvent.ts`; scrap dari
#: `ScrapAccumulator.created_at` (satu-satunya kolom waktunya).
PRODUCTION_BASIS = {
    "output": "bundle_event.ts",
    "efficiency": "bundle_event.ts",
    "otd": "bundle_event.ts",
    "scrap": "scrap_accumulator.created_at",
}



def _production_options(request):
    """``(options, error)`` — parse grup & filter laporan produksi (PURE).

    ``group_by`` default ``period`` (``period``|``work_center``|``line``);
    ``work_center_id``/``line_id`` = **pk MES** (`garment.WorkCenter`/
    `garment.ProductionLine`); ``_nocache`` truthy.
    """
    group_by = str(request.query_params.get("group_by") or "period").strip().lower()
    if group_by not in PRODUCTION_GROUP_BY_VALUES:
        return None, (
            f"Parameter 'group_by'={group_by!r} tidak dikenal "
            f"({'|'.join(PRODUCTION_GROUP_BY_VALUES)})."
        )

    work_center_id, error = _int_param(request, "work_center_id", None, 1, PRODUCTION_MAX_ID)
    if error:
        return None, error
    line_id, error = _int_param(request, "line_id", None, 1, PRODUCTION_MAX_ID)
    if error:
        return None, error

    nocache_raw = str(request.query_params.get("_nocache") or "").strip().lower()
    return (
        {
            "group_by": group_by,
            "work_center_id": work_center_id,
            "line_id": line_id,
            "nocache": nocache_raw in PRODUCTION_NOCACHE_TRUTHY,
        },
        None,
    )


def _production_bucket_range(key: str, group_by: str):
    """``(from_dt, to_dt)`` tz-aware untuk bucket ``YYYY-MM``/``YYYY-Qn`` (inklusif).

    Dipakai menghitung efisiensi per bucket dengan rumus **identik B13**
    (`_efficiency_pct_for`) yang butuh rentang + jumlah hari.
    """
    try:
        if group_by == "quarter":
            year_raw, quarter_raw = key.split("-Q", 1)
            year, month, span = int(year_raw), (int(quarter_raw) - 1) * 3 + 1, 3
        else:
            year_raw, month_raw = key.split("-", 1)
            year, month, span = int(year_raw), int(month_raw), 1
    except (TypeError, ValueError):
        return None, None

    first = datetime(year, month, 1)
    shifted = month + span
    next_year = year + (shifted - 1) // 12
    next_month = (shifted - 1) % 12 + 1
    last = datetime(next_year, next_month, 1) - timedelta(microseconds=1)
    return timezone.make_aware(first), timezone.make_aware(last)


def _production_output(first_finish):
    """``{bucket: {output_pcs, bundles, wos}}`` — output per bucket (realisasi FINISH).

    Satu bundle dihitung **sekali** (FINISH pertama dalam rentang; rework-loop tidak
    menggandakan) dan hanya bundle non-``CANCELLED``.
    """
    buckets: dict = {}
    for event in first_finish:
        bundle = event.bundle
        bucket = buckets.setdefault(
            event.bucket_key, {"output_pcs": 0, "bundles": set(), "wos": set()}
        )
        bucket["output_pcs"] += int(bundle.qty_done or 0)
        bucket["bundles"].add(bundle.pk)
        bucket["wos"].add(bundle.work_order_id)
    return buckets


def _production_finish_buckets(from_dt, to_dt, group_by, work_center_id=None, line_id=None):
    """Daftar event FINISH pertama per bundle (beserta ``bucket_key``) dalam rentang.

    Atribusi bucket: ``period`` → bulan lokal event (``YYYY-MM``); ``work_center`` →
    ``Bundle.current_work_center_id`` (pola B13); ``line`` → ``Bundle.production_line_id``.
    Filter ``work_center_id``/``line_id`` (pk MES) dipakai apa adanya (tanpa validasi
    entitas — konsisten H4.1/H4.2).
    """
    events = (
        BundleEvent.objects.filter(
            event_type=BUNDLE_FINISH_EVENT, ts__gte=from_dt, ts__lte=to_dt
        )
        .exclude(bundle__state__in=PRODUCTION_EXCLUDED_BUNDLE_STATES)
        .select_related("bundle", "bundle__current_work_center", "bundle__production_line")
        .order_by("ts")
    )
    if work_center_id is not None:
        events = events.filter(bundle__current_work_center_id=work_center_id)
    if line_id is not None:
        events = events.filter(bundle__production_line_id=line_id)

    seen: dict = {}
    for event in events:
        if event.bundle_id in seen:
            continue
        if group_by == "period":
            event.bucket_key = _pnl_bucket_label(timezone.localtime(event.ts), "period")
        elif group_by == "work_center":
            event.bucket_key = event.bundle.current_work_center_id
        else:
            event.bucket_key = event.bundle.production_line_id
        seen[event.bundle_id] = event
    return list(seen.values())


def _production_scrap_buckets(date_from, date_to, group_by, work_center_id=None, line_id=None):
    """``{bucket: {scrap_pcs, rework_pcs, end_loss_pcs}}`` — scrap per bucket (1 query).

    Basis = ``ScrapAccumulator.created_at`` (tidak ada event scrap). ``rework_qty`` &
    ``end_loss_qty`` dikumpulkan **terpisah** dari ``qty`` scrap (3 konsep berbeda).
    """
    scrap = ScrapAccumulator.objects.filter(
        created_at__gte=date_from, created_at__lte=date_to
    )
    if work_center_id is not None:
        scrap = scrap.filter(work_center_id=work_center_id)
    if line_id is not None:
        scrap = scrap.filter(bundle__production_line_id=line_id)

    sums = {
        "scrap_pcs": Sum("qty"),
        "rework_pcs": Sum("rework_qty"),
        "end_loss_pcs": Sum("end_loss_qty"),
    }

    if group_by == "period":
        aggregate = scrap.annotate(bucket=TruncMonth("created_at")).values("bucket").annotate(**sums)
        key_of = lambda row: (  # noqa: E731 - konversi bucket -> label bulan
            _pnl_bucket_label(row["bucket"], "period") if row["bucket"] is not None else None
        )
    elif group_by == "work_center":
        aggregate = scrap.values("work_center_id").annotate(**sums)
        key_of = lambda row: row["work_center_id"]  # noqa: E731
    else:
        aggregate = scrap.values("bundle__production_line_id").annotate(**sums)
        key_of = lambda row: row["bundle__production_line_id"]  # noqa: E731

    buckets: dict = {}
    for row in aggregate:
        key = key_of(row)
        if key is None:
            continue
        buckets[key] = {
            "scrap_pcs": int(row["scrap_pcs"] or 0),
            "rework_pcs": int(row["rework_pcs"] or 0),
            "end_loss_pcs": int(row["end_loss_pcs"] or 0),
        }
    return buckets

def _production_avg_efficiency(from_dt, to_dt, work_center_id=None, line_id=None) -> float:
    """Rata-rata efisiensi rentang — **rumus identik B13**.

    Tanpa filter → delegasi `_efficiency_pct_for` (rata-rata lintas WC). Dengan
    ``work_center_id``/``line_id`` → dihitung hanya untuk entitas itu supaya angka
    ringkasan tidak "bocor" dari WC lain.
    """
    days = max((to_dt - from_dt).days, 1)
    if work_center_id is None and line_id is None:
        return _efficiency_pct_for(from_dt, to_dt, days)

    durations = _line_efficiency_durations(from_dt, to_dt)

    if work_center_id is not None:
        work_center = WorkCenter.objects.filter(pk=work_center_id).first()
        done = durations.get(work_center_id, (0, 0.0))[0]
        capacity = _target_per_day(work_center) * days if work_center is not None else 0
        return round(done / capacity * 100, 1) if capacity else 0.0

    line = (
        ProductionLine.objects.filter(pk=line_id).prefetch_related("work_centers").first()
    )
    if line is None:
        return 0.0
    values: list = []
    for work_center in line.work_centers.all():
        done = durations.get(work_center.pk, (0, 0.0))[0]
        capacity = _target_per_day(work_center) * days
        if capacity:
            values.append(done / capacity * 100)
    return round(sum(values) / len(values), 1) if values else 0.0


def _production_efficiency_map(keys, group_by: str, from_dt, to_dt) -> dict:
    """``{bucket: efficiency_pct}`` — ``period`` per bulan; ``work_center``/``line`` per entitas."""
    days = max((to_dt - from_dt).days, 1)

    if group_by == "period":
        result: dict = {}
        for key in keys:
            bucket_from, bucket_to = _production_bucket_range(str(key), "period")
            if bucket_from is None:
                result[key] = 0.0
                continue
            # Clamp ke rentang laporan supaya efisiensi baris memakai window yang SAMA
            # dengan output baris itu (bukan seluruh bulan saat filter sebagian bulan).
            bucket_from = max(bucket_from, from_dt)
            bucket_to = min(bucket_to, to_dt)
            result[key] = _efficiency_pct_for(
                bucket_from, bucket_to, max((bucket_to - bucket_from).days, 1)
            )
        return result

    durations = _line_efficiency_durations(from_dt, to_dt)
    ids = [key for key in keys if key is not None]

    if group_by == "work_center":
        work_centers = {wc.pk: wc for wc in WorkCenter.objects.filter(pk__in=ids)}
        result = {}
        for key in keys:
            work_center = work_centers.get(key)
            done = durations.get(key, (0, 0.0))[0]
            capacity = _target_per_day(work_center) * days if work_center is not None else 0
            result[key] = round(done / capacity * 100, 1) if capacity else 0.0
        return result

    lines = {
        line.pk: line
        for line in ProductionLine.objects.filter(pk__in=ids).prefetch_related("work_centers")
    }
    result = {}
    for key in keys:
        line = lines.get(key)
        if line is None:
            result[key] = 0.0
            continue
        done = 0
        capacity = 0
        for work_center in line.work_centers.all():
            done += durations.get(work_center.pk, (0, 0.0))[0]
            capacity += _target_per_day(work_center) * days
        result[key] = round(done / capacity * 100, 1) if capacity else 0.0
    return result


def _production_otd_rows(from_dt, to_dt) -> list:
    """Baris OTD **order-level** (pola B20) untuk WO ``DONE`` yang FINISH-nya dalam rentang.

    ``finished_at`` = event FINISH terakhir bundle WO tsb, fallback
    ``WorkOrder.updated_at``; ``on_time = finished_at <= Order.deadline``.
    """
    work_orders = list(WorkOrder.objects.filter(state="DONE").select_related("order_line__order"))
    finish_map = _wo_finish_map(work_orders)

    rows = []
    for work_order in work_orders:
        order = work_order.order_line.order
        finished_at = finish_map.get(work_order.pk) or work_order.updated_at
        if finished_at is None or finished_at < from_dt or finished_at > to_dt:
            continue
        on_time, delay_hours = _otd_metrics(order.deadline, finished_at)
        rows.append(
            {"on_time": on_time, "delay_hours": delay_hours, "finished_at": finished_at}
        )
    return rows


def _production_otd_pct_for(otd_rows, from_dt, to_dt) -> float:
    """PURE — OTD% baris yang ``finished_at``-nya dalam sub-rentang (pola `_otd_pct`)."""
    window = [row for row in otd_rows if from_dt <= row["finished_at"] <= to_dt]
    return _otd_pct(window)


def _production_scrap_pct(output_pcs: int, scrap_pcs: int) -> float:
    """PURE — persentase scrap; denominator 0 -> ``0.0`` (tanpa divide-by-zero)."""
    total_flow = output_pcs + scrap_pcs
    return round(scrap_pcs / total_flow * 100, 2) if total_flow else 0.0


def _production_metrics(
    output_pcs: int,
    scrap_pcs: int,
    efficiency_pct,
    otd_pct,
    rework_pcs=None,
    end_loss_pcs=None,
) -> dict:
    """PURE — blok metrik baris; ``scrap_pct`` aman saat denominator 0 (→ ``0.0``)."""
    metrics = {
        "output_pcs": output_pcs,
        "scrap_pcs": scrap_pcs,
        "scrap_pct": _production_scrap_pct(output_pcs, scrap_pcs),
        "efficiency_pct": efficiency_pct,
        "otd_pct": otd_pct,
    }
    if rework_pcs is not None:
        metrics["rework_pcs"] = rework_pcs
    if end_loss_pcs is not None:
        metrics["end_loss_pcs"] = end_loss_pcs
    return metrics


def _production_row(
    key, label: str, output: dict, scrap: dict, efficiency_pct, otd_pct, extra=None, breakdown=False
) -> dict:
    """PURE — satu baris laporan produksi (``key``/``label`` + metrik + identitas grup)."""
    payload = {
        "key": "" if key is None else str(key),
        "label": label,
        **_production_metrics(
            int(output.get("output_pcs") or 0),
            int(scrap.get("scrap_pcs") or 0),
            efficiency_pct,
            otd_pct,
            rework_pcs=int(scrap.get("rework_pcs") or 0) if breakdown else None,
            end_loss_pcs=int(scrap.get("end_loss_pcs") or 0) if breakdown else None,
        ),
    }
    if extra:
        payload.update(extra)
    return payload


def _production_summary(output_buckets, scrap_buckets, otd_rows, from_dt, to_dt, options) -> dict:
    """Ringkasan rentang — output/scrap/rework/end-loss + efisiensi + OTD (order-level).

    **TANPA** ``currency`` — H4.6 murni kuantitas (pcs) + persentase (pola H4.3).
    """
    total_output = sum(int(value["output_pcs"] or 0) for value in output_buckets.values())
    total_scrap = sum(int(value["scrap_pcs"] or 0) for value in scrap_buckets.values())
    total_rework = sum(int(value["rework_pcs"] or 0) for value in scrap_buckets.values())
    total_end_loss = sum(int(value["end_loss_pcs"] or 0) for value in scrap_buckets.values())

    bundles: set = set()
    work_orders: set = set()
    for value in output_buckets.values():
        bundles |= value["bundles"]
        work_orders |= value["wos"]

    return {
        "total_output_pcs": total_output,
        "total_scrap_pcs": total_scrap,
        "total_rework_pcs": total_rework,
        "total_end_loss_pcs": total_end_loss,
        "scrap_pct": _production_scrap_pct(total_output, total_scrap),
        "avg_efficiency_pct": _production_avg_efficiency(
            from_dt, to_dt, options["work_center_id"], options["line_id"]
        ),
        "otd_pct": _otd_pct(otd_rows),
        "total_bundles": len(bundles),
        "total_work_orders": len(work_orders),
    }

def _production_cache_key(from_dt, to_dt, group_by: str, work_center_id, line_id) -> str:
    """Key cache ``reports:production:<sha1(filter efektif)>`` (TTL `PRODUCTION_CACHE_TTL`)."""
    raw = "|".join(
        (
            from_dt.isoformat(),
            to_dt.isoformat(),
            group_by,
            "" if work_center_id is None else str(work_center_id),
            "" if line_id is None else str(line_id),
        )
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{PRODUCTION_CACHE_PREFIX}{digest}"


def _production_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif + penanda basis waktu per metrik (transparansi H4.6)."""
    return {
        **echo,
        "group_by": options["group_by"],
        "work_center_id": options["work_center_id"],
        "line_id": options["line_id"],
        "nocache": options["nocache"],
        "basis": dict(PRODUCTION_BASIS),
        "resolved_from": from_dt.isoformat(),
        "resolved_to": to_dt.isoformat(),
    }


def _production_rows(
    keys, output_buckets, scrap_buckets, otd_rows, efficiency_map, group_by
) -> list:
    """PURE — baris laporan produksi per ``group_by`` (ekstraksi H4.8).

    Dipindahkan **verbatim** dari `ReportsProductionView.get()` supaya laporan
    H4.6 dan export Excel/PDF H4.8 memakai KOMPOSISI baris yang sama (kalau
    tidak, keduanya bisa drift). Perilaku identik — dijaga 20 test H4.6
    (``tests/integration/test_reports_production.py``).
    """
    rows: list = []
    if group_by == "period":
        for key in keys:
            output = output_buckets.get(key, {})
            scrap = scrap_buckets.get(key, {})
            bucket_from, bucket_to = _production_bucket_range(str(key), "period")
            otd_pct = (
                _production_otd_pct_for(otd_rows, bucket_from, bucket_to)
                if bucket_from is not None
                else 0.0
            )
            rows.append(
                _production_row(
                    key,
                    str(key),
                    output,
                    scrap,
                    efficiency_map.get(key, 0.0),
                    otd_pct,
                    extra={
                        "period": str(key),
                        "bundle_count": len(output.get("bundles") or ()),
                        "wo_count": len(output.get("wos") or ()),
                    },
                    breakdown=True,
                )
            )
    elif group_by == "work_center":
        work_centers = {
            wc.pk: wc
            for wc in WorkCenter.objects.filter(pk__in=[key for key in keys if key is not None])
        }
        for key in keys:
            work_center = work_centers.get(key)
            output = output_buckets.get(key, {})
            code = work_center.code if work_center is not None else ""
            name = work_center.name if work_center is not None else ""
            rows.append(
                _production_row(
                    code or "" if key is None else (code or str(key)),
                    name or code or "(tanpa work center)",
                    output,
                    scrap_buckets.get(key, {}),
                    efficiency_map.get(key, 0.0),
                    None,
                    extra={
                        "wc_id": key,
                        "wc_code": code,
                        "wc_name": name,
                        "bundle_count": len(output.get("bundles") or ()),
                    },
                )
            )
    else:
        lines = {
            line.pk: line
            for line in ProductionLine.objects.filter(
                pk__in=[key for key in keys if key is not None]
            )
        }
        for key in keys:
            line = lines.get(key)
            output = output_buckets.get(key, {})
            code = line.code if line is not None else ""
            name = line.name if line is not None else ""
            rows.append(
                _production_row(
                    code or "" if key is None else (code or str(key)),
                    name or code or "(tanpa line)",
                    output,
                    scrap_buckets.get(key, {}),
                    efficiency_map.get(key, 0.0),
                    None,
                    extra={
                        "line_id": key,
                        "line_code": code,
                        "line_name": name,
                        "bundle_count": len(output.get("bundles") or ()),
                    },
                )
            )
    return rows


class ReportsProductionView(APIView):
    """``GET /api/v1/reports/production/`` — laporan produksi per periode/WC/line (H4.6).

    Bentuk::

        {"rows": [{"key", "label", "output_pcs", "scrap_pcs", "scrap_pct",
                   "efficiency_pct", "otd_pct", ...}],
         "summary": {"total_output_pcs", "total_scrap_pcs", "total_rework_pcs",
                     "total_end_loss_pcs", "scrap_pct", "avg_efficiency_pct",
                     "otd_pct", "total_bundles", "total_work_orders"},
         "group_by": "period", "filters": {...echo + basis},
         "period": {"from": "ISO-8601", "to": "ISO-8601"},
         "generated_at": "ISO-8601", "cached": false}

    * **SUPERSET** B13/B16/B18–B21 (read-only, DB murni): menambah **dimensi
      periode** ke metrik produksi yang sudah ada; endpoint existing **tidak**
      diubah;
    * **basis waktu per metrik (keputusan H4.6 — dua sumber)**:
      ``output``/``efficiency``/``otd`` = realisasi ``BundleEvent.ts``;
      ``scrap`` = ``ScrapAccumulator.created_at`` (tidak ada event scrap).
      ``Bundle.created_at`` (planning) **tidak** dipakai. Basis diekspos di
      ``filters.basis``;
    * ``output_pcs`` = Σ ``Bundle.qty_done`` untuk bundle dengan event
      ``BUNDLE_FINISH`` ∈ rentang dan ``state != CANCELLED`` (satu bundle dihitung
      **sekali** — FINISH pertama; rework-loop tidak menggandakan);
    * ``scrap_pcs`` = Σ ``ScrapAccumulator.qty``; ``rework_qty`` & ``end_loss_qty``
      **dipisah** (`summary.total_rework_pcs`/`total_end_loss_pcs`, dan baris
      ``group_by=period`` memuat ``rework_pcs``/``end_loss_pcs`` sebagai
      drill-down) — tiga konsep berbeda, tidak dicampur;
    * ``scrap_pct = scrap_pcs / (output_pcs + scrap_pcs) × 100`` (denominator 0 →
      **0**);
    * ``efficiency_pct`` memakai **rumus identik B13**: ``period`` → delegasi
      `_efficiency_pct_for` per bucket; ``work_center`` →
      ``done / (target_per_day × hari) × 100``; ``line`` →
      ``Σdone_wc / (Σtarget_wc × hari) × 100`` (ekstensi terdokumentasi — line
      tidak punya target sendiri);
    * ``otd_pct`` = metrik **order-level** (pola B20: WO ``DONE`` + FINISH ∈
      rentang vs ``Order.deadline``); hanya ada di ``group_by=period`` + summary —
      baris ``work_center``/``line`` bernilai **``null``** (mempartisi OTD per WC/line
      akan menyesatkan);
    * ``group_by=period`` (default) | ``work_center`` | ``line``; baris =
      **gabungan bucket output ∪ bucket scrap** ⇒ bulan dengan scrap tanpa output
      tetap muncul; urut ``period`` naik, ``work_center``/``line`` menurut kode;
    * param rentang: ``?period=YYYY-MM`` > ``?date_from``/``?date_to`` >
      ``?from``/``?to`` (delegasi `_sales_range`, konsisten H4.1–H4.5; default
      **bulan berjalan**); plus ``?work_center_id=``/``?line_id=`` (**pk MES**),
      ``?group_by=``, ``?_nocache=1``. Nilai tak dikenal → **400**;
    * cache 300 detik key ``reports:production:<sha1(filter)>``; ``cached``
      menandai respons dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak
      menulis cache (cache hit = **0 query DB**);
    * **TANPA** ``currency`` — H4.6 murni kuantitas (pcs) + persentase (pola H4.3).

    Read-only (tanpa Odoo/task/migration) dan tidak mengubah B2/B13/B16/B18–B21
    maupun H2.3/H2.4 + H4.1–H4.5. Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan produksi; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _sales_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _production_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        group_by = options["group_by"]
        work_center_id = options["work_center_id"]
        line_id = options["line_id"]
        cache_key = _production_cache_key(from_dt, to_dt, group_by, work_center_id, line_id)
        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        finish_events = _production_finish_buckets(
            from_dt, to_dt, group_by, work_center_id, line_id
        )
        output_buckets = _production_output(finish_events)
        scrap_buckets = _production_scrap_buckets(
            from_dt, to_dt, group_by, work_center_id, line_id
        )
        otd_rows = _production_otd_rows(from_dt, to_dt)

        keys = sorted(
            set(output_buckets) | set(scrap_buckets),
            key=lambda value: (value is None, "" if value is None else value),
        )
        efficiency_map = _production_efficiency_map(keys, group_by, from_dt, to_dt)

        rows = _production_rows(
            keys, output_buckets, scrap_buckets, otd_rows, efficiency_map, group_by
        )

        payload = {
            "rows": rows,
            "summary": _production_summary(
                output_buckets, scrap_buckets, otd_rows, from_dt, to_dt, options
            ),
            "group_by": group_by,
            "filters": _production_filters_echo(echo, options, from_dt, to_dt),
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, PRODUCTION_CACHE_TTL)

        logger.info(
            "reports production: group_by=%s rows=%s wc=%s line=%s nocache=%s "
            "output=%s scrap=%s",
            group_by,
            len(rows),
            work_center_id,
            line_id,
            options["nocache"],
            payload["summary"]["total_output_pcs"],
            payload["summary"]["total_scrap_pcs"],
        )
        return Response(payload)

# ---------------------------------------------------------------------------
# Dashboard executive (H4.7) — GET /api/v1/dashboard/executive/
# ---------------------------------------------------------------------------
#: TTL cache dashboard eksekutif (detik) — orkestrasi 6 laporan (5 menit).
EXEC_CACHE_TTL = 300

#: Prefix key cache; sisanya = sha1 dari rentang efektif.
EXEC_CACHE_PREFIX = "reports:executive:"

#: Nilai `?_nocache` yang dianggap **true** (escape hatch force refresh).
EXEC_NOCACHE_TRUTHY = ("1", "true", "yes", "on")

#: Alert statis (teks persis keputusan H4.7) — bagian dinamis memakai f-string.
EXEC_ALERT_OPEX_UNAVAILABLE = "Opex unavailable: chart of accounts belum di-pull"
EXEC_ALERT_STOCK_UNREADABLE = "Stok tidak terbaca dari Odoo"


def _exec_options(request):
    """``(options, error)`` — parse opsi dashboard eksekutif (PURE).

    Rentang **tidak** di-parse di sini: H4.7 mendelegasikan ke `_sales_range`
    (``?period`` > ``?date_from``/``?date_to`` > ``?from``/``?to``, default bulan
    berjalan) supaya konsisten H4.1–H4.6. Hanya ``_nocache`` yang di-parse.
    """
    nocache_raw = str(request.query_params.get("_nocache") or "").strip().lower()
    return {"nocache": nocache_raw in EXEC_NOCACHE_TRUTHY}, None


def _exec_orderline_base(from_dt, to_dt) -> dict:
    """Agregat gabungan `OrderLine` (sales + cogs + basis PnL) — **1 query agregat**.

    OPTIMASI H4.7: `_sales_lines` **identik** `_cogs_lines` pada rentang yang sama
    (order ``CANCELLED`` dibuang) sehingga sales/cogs/revenue/``rows_with_missing_cost``
    bisa dihitung dari **satu** `aggregate()` — bukan 3 query terpisah. Rumus tetap
    milik helper H4.1/H4.4 (`_sales_amount_expr`/`_cogs_cost_expr`/`_cogs_missing_exprs`).
    """
    return _sales_lines(from_dt, to_dt).aggregate(
        total_amount=_sales_amount_expr(),
        total_cogs=_cogs_cost_expr(),
        count_orders=Count("order_id", distinct=True),
        count_lines=Count("id"),
        **_cogs_missing_exprs(),
    )


def _exec_missing_cost_count(base: dict) -> int:
    """PURE — jumlah baris OrderLine tanpa HPP (``product`` NULL atau ``cost_price`` 0)."""
    return int((base["missing_product"] or 0) + (base["missing_cost"] or 0))


def _exec_purchases_section(from_dt, to_dt) -> dict:
    """Section pembelian (reuse H4.2) — **1 query agregat**.

    Formula milik H4.2 tetap dipakai (`_purchases_lines` + `_purchases_amount_expr`);
    H4.7 hanya BUTUH total (bukan baris per grup), sehingga 2 query tambahan
    (bill/payment) milik `_purchases_summary` tidak dijalankan.
    """
    totals = _purchases_lines(from_dt, to_dt).aggregate(
        total_amount=_purchases_amount_expr(),
        count_purchases=Count("po_id", distinct=True),
        count_lines=Count("id"),
    )
    return {
        "total_amount": _money(totals["total_amount"]),
        "count_purchases": int(totals["count_purchases"] or 0),
        "count_lines": int(totals["count_lines"] or 0),
    }


def _exec_stock_section():
    """Section stok (reuse H4.3) → ``(section | None, alerts)`` — fail-safe **partial**.

    ``None`` + alert bila Odoo tak terbaca (transport error **atau** enumerasi lokasi
    internal kosong) — angka stok tidak dikarang; section lain tetap terisi.
    """
    locations, quants, fetch_error = _stock_fetch()
    if fetch_error is not None or not locations:
        logger.warning(
            "dashboard executive: stock tidak terbaca dari Odoo (%s).",
            fetch_error or "tanpa lokasi internal",
        )
        return None, [EXEC_ALERT_STOCK_UNREADABLE]

    products = _stock_product_map()
    by_product, by_location, stats = _stock_aggregate(
        quants, products, {"search": None, "product_odoo_id": None}
    )
    summary = _stock_summary(by_product, by_location, stats)
    return (
        {
            "total_qty": summary["total_qty"],
            "product_count": summary["product_count"],
            "location_count": summary["location_count"],
            "unmapped_product_count": summary["unmapped_product_count"],
        },
        [],
    )


def _exec_pnl_section(from_dt, to_dt):
    """Section PnL (reuse H4.5) → ``(section, opex_source)``.

    Opex diambil lewat `_pnl_opex_available` + `_pnl_opex_by_bucket` (H4.5); seluruh
    angka laba/margin dari `_pnl_summary` supaya **identik H4.5**.
    """
    date_from = timezone.localtime(from_dt).date()
    date_to = timezone.localtime(to_dt).date()
    lines = _cogs_lines(from_dt, to_dt)

    if _pnl_opex_available():
        opex_source = PNL_OPEX_SOURCE_JOURNAL
        opex_total = _money(sum(_pnl_opex_by_bucket(date_from, date_to, "period").values()))
    else:
        logger.warning(
            "dashboard executive: opex 'unavailable' (chart of accounts expense belum ada)."
        )
        opex_source = PNL_OPEX_SOURCE_UNAVAILABLE
        opex_total = None

    summary = _pnl_summary(lines, opex_total, opex_source)
    return (
        {
            "revenue": summary["revenue"],
            "cogs": summary["cogs"],
            "gross_profit": summary["gross_profit"],
            "gross_margin_pct": summary["gross_margin_pct"],
            "opex": summary["opex"],
            "net_profit": summary["net_profit"],
            "net_margin_pct": summary["net_margin_pct"],
            "opex_source": summary["opex_source"],
            "opex_account_types": summary["opex_account_types"],
            "opex_states": summary["opex_states"],
        },
        opex_source,
    )


def _exec_production_section(from_dt, to_dt) -> dict:
    """Section produksi (reuse H4.6) — grain ``period`` tanpa filter WC/line."""
    finish_events = _production_finish_buckets(from_dt, to_dt, "period")
    output_buckets = _production_output(finish_events)
    scrap_buckets = _production_scrap_buckets(from_dt, to_dt, "period")
    otd_rows = _production_otd_rows(from_dt, to_dt)
    summary = _production_summary(
        output_buckets,
        scrap_buckets,
        otd_rows,
        from_dt,
        to_dt,
        {"work_center_id": None, "line_id": None},
    )
    return {
        "output_pcs": summary["total_output_pcs"],
        "scrap_pcs": summary["total_scrap_pcs"],
        "scrap_pct": summary["scrap_pct"],
        "rework_pcs": summary["total_rework_pcs"],
        "end_loss_pcs": summary["total_end_loss_pcs"],
        "avg_efficiency_pct": summary["avg_efficiency_pct"],
        "otd_pct": summary["otd_pct"],
        "total_bundles": summary["total_bundles"],
        "total_work_orders": summary["total_work_orders"],
    }

def _exec_alerts(stock_alerts, stock_section, opex_source, missing_cost) -> list:
    """PURE — alert dashboard eksekutif (ekstraksi H4.8, urutan deterministik).

    Dipakai `ExecutiveDashboardView` (H4.7) DAN export dashboard (H4.8) supaya
    daftar peringatan tidak pernah berbeda antar jalur.
    """
    alerts: list = list(stock_alerts)
    if opex_source == PNL_OPEX_SOURCE_UNAVAILABLE:
        alerts.append(EXEC_ALERT_OPEX_UNAVAILABLE)
    if stock_section is not None and stock_section["unmapped_product_count"] > 0:
        alerts.append(f"{stock_section['unmapped_product_count']} produk tanpa odoo_id")
    if missing_cost > 0:
        alerts.append(f"{missing_cost} baris OrderLine tanpa cost_price")
    return alerts


def _exec_cache_key(from_dt, to_dt) -> str:
    """Key cache ``reports:executive:<sha1(rentang efektif)>`` (TTL `EXEC_CACHE_TTL`)."""
    raw = "|".join((from_dt.isoformat(), to_dt.isoformat()))
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{EXEC_CACHE_PREFIX}{digest}"


def _exec_filters_echo(echo: dict, options: dict, from_dt, to_dt) -> dict:
    """Echo filter efektif (ADDITIF di H4.7 — konsisten H4.1–H4.6)."""
    return {
        **echo,
        "nocache": options["nocache"],
        "resolved_from": from_dt.isoformat(),
        "resolved_to": to_dt.isoformat(),
    }


class ExecutiveDashboardView(APIView):
    """``GET /api/v1/dashboard/executive/`` — dashboard eksekutif (H4.7, read-only).

    **ORKESTRASI**, bukan duplikasi: seluruh angka berasal dari helper internal
    H4.1–H4.6 (tidak memanggil view HTTP, tidak menyalin rumus). Bentuk::

        {"period": {"from": "ISO-8601", "to": "ISO-8601"},
         "filters": {...echo...},
         "sales": {"total_amount", "count_orders", "count_lines"},
         "purchases": {"total_amount", "count_purchases", "count_lines"},
         "stock": {"total_qty", "product_count", "location_count",
                   "unmapped_product_count"} | null,
         "cogs": {"total_cogs", "gross_profit", "gross_margin_pct",
                  "rows_with_missing_cost"},
         "pnl": {"revenue", "cogs", "gross_profit", "gross_margin_pct", "opex",
                 "net_profit", "net_margin_pct", "opex_source",
                 "opex_account_types", "opex_states"},
         "production": {"output_pcs", "scrap_pcs", "scrap_pct", "rework_pcs",
                        "end_loss_pcs", "avg_efficiency_pct", "otd_pct",
                        "total_bundles", "total_work_orders"},
         "alerts": ["..."], "generated_at": "ISO-8601", "cached": false}

    * **reuse helper internal** H4.1–H4.6: `_sales_lines`/`_sales_amount_expr`,
      `_purchases_lines`/`_purchases_amount_expr` (H4.2), `_stock_fetch`/
      `_stock_product_map`/`_stock_aggregate`/`_stock_summary` (H4.3),
      `_cogs_cost_expr`/`_cogs_missing_exprs` (H4.4), `_pnl_opex_available`/
      `_pnl_opex_by_bucket`/`_pnl_summary` (H4.5), `_production_*` (H4.6). **Tidak**
      ada rumus yang disalin ulang;
    * **optimasi query**: `_sales_lines` identik `_cogs_lines` pada rentang yang sama
      ⇒ sales + cogs + basis PnL dihitung dari **satu** `aggregate()`
      (`_exec_orderline_base`). Budget **≤ 15 query DB** (+ 2 RPC Odoo utk stok),
      diuji eksplisit dengan `CaptureQueriesContext`;
    * **`?period`** > `?date_from`/`?date_to` > `?from`/`?to` (delegasi `_sales_range`,
      konsisten H4.1–H4.6; default bulan berjalan) + `?_nocache=1`; rentang tak valid
      → **400**;
    * **fail-safe PARTIAL per-section** (keputusan H4.7): kegagalan satu sumber
      **tidak** menggagalkan seluruh dashboard — Odoo stok tak terbaca → ``stock = null``
      + alert, sedangkan sales/purchases/cogs/pnl/production tetap terisi;
    * ``alerts`` = **``list[str]``** (informatif; **beda** dari B2 yang memakai objek
      ``{code, message, severity}`` karena konteksnya operasional). Sumber alert:
      stok tak terbaca, opex ``unavailable``, produk Odoo tanpa master,
      baris OrderLine tanpa ``cost_price``;
    * metrik **top-N** (``top_customer``/``top_vendor``) sengaja **tidak** ada di sini
      (drill-down ke H4.1/H4.2) demi budget query;
    * cache 300 detik key ``reports:executive:<sha1(rentang)>``; ``cached`` menandai
      respons dari cache; ``?_nocache=1`` = tidak membaca **dan** tidak menulis cache
      (cache hit = **0 query DB**).

    Read-only (tanpa Odoo write/task/migration) dan **tidak** mengubah B2
    (``/dashboard/summary/``) maupun H4.1–H4.6. Anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun dashboard eksekutif; lihat docstring kelas."""
        from_dt, to_dt, echo, error = _sales_range(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        options, error = _exec_options(request)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        cache_key = _exec_cache_key(from_dt, to_dt)
        if not options["nocache"]:
            hit = cache.get(cache_key)
            if hit is not None:
                return Response({**hit, "cached": True})

        # 1 query agregat gabungan (sales + cogs + basis PnL).
        base = _exec_orderline_base(from_dt, to_dt)
        sales_amount = _money(base["total_amount"])
        cogs_amount = _money(base["total_cogs"])
        gross_profit = _money(sales_amount - cogs_amount)
        missing_cost = _exec_missing_cost_count(base)

        pnl_section, opex_source = _exec_pnl_section(from_dt, to_dt)
        stock_section, stock_alerts = _exec_stock_section()
        production_section = _exec_production_section(from_dt, to_dt)
        purchases_section = _exec_purchases_section(from_dt, to_dt)

        alerts = _exec_alerts(stock_alerts, stock_section, opex_source, missing_cost)

        payload = {
            "period": {"from": from_dt.isoformat(), "to": to_dt.isoformat()},
            "filters": _exec_filters_echo(echo, options, from_dt, to_dt),
            "sales": {
                "total_amount": sales_amount,
                "count_orders": int(base["count_orders"] or 0),
                "count_lines": int(base["count_lines"] or 0),
            },
            "purchases": purchases_section,
            "stock": stock_section,
            "cogs": {
                "total_cogs": cogs_amount,
                "gross_profit": gross_profit,
                "gross_margin_pct": _money_pct(gross_profit, sales_amount),
                "rows_with_missing_cost": missing_cost,
            },
            "pnl": pnl_section,
            "production": production_section,
            "alerts": alerts,
            "generated_at": timezone.localtime(timezone.now()).isoformat(),
            "cached": False,
        }
        if not options["nocache"]:
            cache.set(cache_key, payload, EXEC_CACHE_TTL)

        logger.info(
            "dashboard executive: sales=%s cogs=%s net=%s output=%s alerts=%s nocache=%s",
            sales_amount,
            cogs_amount,
            pnl_section["net_profit"],
            production_section["output_pcs"],
            len(alerts),
            options["nocache"],
        )
        return Response(payload)

# ---------------------------------------------------------------------------
# Purchase orders & reporting (F2 / B10+B11) — Odoo transport (read-only)
# ---------------------------------------------------------------------------
#: Status `purchase.order` yang dipakai laporan (draft + confirmed + locked).
PURCHASE_ORDER_STATES = ("draft", "purchase", "done")

#: Maksimum vendor pada `top_vendors` (B11).
PURCHASE_REPORTING_TOP_VENDORS = 5


def _to_float(value) -> float:
    """Nilai Odoo → float (tahan ``None``/string)."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _many2one_name(value) -> str | None:
    """Nama dari field many2one Odoo (``[id, name]`` → ``name``)."""
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return value[1]
    return None


def _many2one_id(value) -> int | None:
    """Id dari field many2one Odoo (``[id, name]`` → ``id``; ``int`` apa adanya)."""
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        return first if isinstance(first, int) else None
    if isinstance(value, int):
        return value
    return None


def _fetch_transport_data(fetch):
    """Panggil ``fetch(transport)`` lalu tutup transport.

    Transport diambil lewat :func:`get_transport` (menghormati ``ERP_ADAPTER``)
    — read-only, **tidak** memicu sync/Celery. ``ERP_ADAPTER=null`` → transport
    tanpa client → ``fetch_*`` mengembalikan ``[]`` (fail-safe, tanpa error).
    """
    transport = get_transport()
    try:
        return fetch(transport)
    finally:
        closer = getattr(transport, "close", None)
        if callable(closer):
            closer()


def _product_codes(odoo_ids) -> dict:
    """``{Product.odoo_id: code}`` untuk id produk yang ada di `master.Product`."""
    ids = {oid for oid in odoo_ids if oid is not None}
    if not ids:
        return {}
    return {
        product.odoo_id: product.code
        for product in Product.objects.filter(odoo_id__in=ids)
    }


def _vendor_codes(po_rows) -> dict:
    """``{partner_odoo_id: vendor_code}`` dari `master.Partner` (code, fallback id)."""
    ids = {
        pid
        for pid in (_many2one_id(order.get("partner_id")) for order in po_rows)
        if pid is not None
    }
    if not ids:
        return {}
    return {
        partner.odoo_id: (partner.code or str(partner.odoo_id))
        for partner in Partner.objects.filter(odoo_id__in=ids)
    }


def _purchase_line_row(line, product_codes: dict) -> dict:
    """Satu baris PO line (G5, aditif).

    ``product_code`` = ``master.Product.code`` (via ``product_id`` many2one → odoo_id)
    dengan fallback nama many2one; ``description`` = nama many2one produk.
    """
    qty = _to_float(line.get("product_qty"))
    price = _to_float(line.get("price_unit"))
    product_id = _many2one_id(line.get("product_id"))
    product_name = _many2one_name(line.get("product_id"))
    return {
        "product_code": product_codes.get(product_id) or product_name,
        "description": product_name,
        "qty": line.get("product_qty", 0),
        "price_unit": line.get("price_unit", 0.0),
        "subtotal": qty * price,
    }


def _purchase_lines_by_order(order_ids) -> dict:
    """``{po_id: [line]}`` untuk `order_ids`.

    Fail-safe: transport error / bentuk tak terduga → ``{}`` (bukan 500). Satu
    panggilan `fetch_purchase_order_lines` untuk semua id (bukan N+1).
    """
    ids = [oid for oid in order_ids if isinstance(oid, int)]
    if not ids:
        return {}

    try:
        lines = _fetch_transport_data(
            lambda transport: transport.fetch_purchase_order_lines(ids)
        )
    except Exception:  # noqa: BLE001 - fail-safe: jangan 500 kalau transport error
        logger.warning("purchase orders: fetch lines gagal -> lines=[]", exc_info=True)
        return {}

    if not isinstance(lines, list):
        return {}

    product_codes = _product_codes(
        _many2one_id(line.get("product_id"))
        for line in lines
        if isinstance(line, dict)
    )
    grouped: dict = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        order_id = _many2one_id(line.get("order_id"))
        if order_id is None:
            continue
        grouped.setdefault(order_id, []).append(_purchase_line_row(line, product_codes))
    return grouped


def _purchase_order_row(order, vendor_codes=None, lines_by_order=None) -> dict:
    """Satu baris PO (field minimal dari ``fetch_purchase_orders``) + G5 aditif."""
    vendor_codes = vendor_codes or {}
    lines_by_order = lines_by_order or {}
    partner_id = _many2one_id(order.get("partner_id"))
    return {
        "id": order.get("id"),
        "name": order.get("name"),
        "partner_name": _many2one_name(order.get("partner_id")),
        "state": order.get("state"),
        "date_order": order.get("date_order"),
        "date_planned": order.get("date_planned"),
        "amount_total": order.get("amount_total"),
        # G5 (aditif):
        "vendor_code": vendor_codes.get(partner_id),
        "lines": lines_by_order.get(order.get("id"), []),
    }


def _paginate(rows, offset: int, limit: int):
    """``(page, total, has_more)`` untuk sumber **list** (bukan queryset)."""
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, total, offset + len(page) < total


class PurchaseOrdersView(APIView):
    """``GET /api/v1/purchase/orders/`` — daftar PO Odoo (read-only).

    Sumber = ``transport.fetch_purchase_orders`` (I3) — **tanpa** trigger sync.
    Bentuk ListPage::

        {"rows": [{"id", "name", "partner_name", "state", "date_order",
                   "date_planned", "amount_total", "vendor_code", "lines"}],
         "total_count": N, "has_more": bool, "next_cursor": int|null}

    Query: ``?limit`` (1..200, default 50), ``?cursor`` (offset),
    ``?state=draft|purchase|done`` (tanpa param → ketiga state).

    * G5 (**aditif**): ``vendor_code`` = ``master.Partner.code`` (di-resolve via
      ``partner_id`` → ``Partner.odoo_id``; ``null`` bila tak ada di master);
      ``lines`` = ``fetch_purchase_order_lines`` per PO (fail-safe → ``[]``).
      Field lama TETAP.

    Fail-safe: ``ERP_ADAPTER=null`` / kredensial kosong → transport tanpa client
    → ``fetch_*`` mengembalikan ``[]`` → respons **200** ``rows=[]`` (bukan
    error). Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun ListPage PO; lihat docstring kelas."""
        limit, error = _int_param(request, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
        offset, error = _int_param(request, "cursor", DEFAULT_OFFSET, 0, MAX_OFFSET)
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

        state = str(request.query_params.get("state") or "").strip().lower()
        if state and state not in PURCHASE_ORDER_STATES:
            return Response(
                {"detail": f"state={state!r} tidak dikenal (draft|purchase|done)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        states = (state,) if state else PURCHASE_ORDER_STATES

        orders = _fetch_transport_data(
            lambda transport: transport.fetch_purchase_orders(states=states)
        )
        page, total, has_more = _paginate(orders, offset, limit)
        vendor_codes = _vendor_codes(page)
        lines_by_order = _purchase_lines_by_order([order.get("id") for order in page])
        return Response(
            {
                "rows": [
                    _purchase_order_row(order, vendor_codes, lines_by_order)
                    for order in page
                ],
                "total_count": total,
                "has_more": has_more,
                "next_cursor": (offset + len(page)) if has_more else None,
            }
        )


#: Jumlah bulan pada `monthly_series` purchase reporting (G5b).
PURCHASE_TREND_MONTHS = 6


def _month_label(value) -> str | None:
    """``"YYYY-MM"`` dari string tanggal Odoo (``"YYYY-MM-DD ..."``), atau ``None``."""
    raw = str(value or "")
    return raw[:7] if len(raw) >= 7 else None


def _monthly_series(orders, bills, months: int = PURCHASE_TREND_MONTHS) -> list[dict]:
    """Agregat bulanan ``months`` bulan terakhir (termasuk bulan ini) — G5b.

    ``po_count``/``amount_total`` dari PO (``date_order``); ``vendor_bill_count``
    dari vendor bill (``invoice_date`` fallback ``date``). Bulan tanpa data → 0
    (semua bulan tetap muncul, urut **ascending**).
    """
    today = timezone.localtime(timezone.now()).date()
    labels: list[str] = []
    year, month = today.year, today.month
    for _ in range(months):
        labels.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    labels.reverse()

    buckets = {
        label: {
            "month": label,
            "po_count": 0,
            "amount_total": 0.0,
            "vendor_bill_count": 0,
        }
        for label in labels
    }

    for order in orders:
        bucket = buckets.get(_month_label(order.get("date_order")))
        if bucket is not None:
            bucket["po_count"] += 1
            bucket["amount_total"] += _to_float(order.get("amount_total"))

    for bill in bills:
        bucket = buckets.get(_month_label(bill.get("invoice_date") or bill.get("date")))
        if bucket is not None:
            bucket["vendor_bill_count"] += 1

    return [
        {**buckets[label], "amount_total": round(buckets[label]["amount_total"], 2)}
        for label in labels
    ]


def _purchase_reporting(orders, bills) -> dict:
    """Agregat PO + vendor bill (murni, tanpa I/O)."""
    by_state = {state: 0 for state in PURCHASE_ORDER_STATES}
    vendors: dict = {}
    total_amount = 0.0
    vendor_codes = _vendor_codes(orders)

    for order in orders:
        amount = _to_float(order.get("amount_total"))
        total_amount += amount

        state = str(order.get("state") or "").lower()
        if state in by_state:
            by_state[state] += 1

        partner_id = _many2one_id(order.get("partner_id"))
        name = _many2one_name(order.get("partner_id"))
        entry = vendors.setdefault(
            partner_id,
            {
                "partner_name": name,
                "total_amount": 0.0,
                "po_count": 0,
                # G5b (aditif):
                "vendor_name": name,
                "vendor_code": vendor_codes.get(partner_id),
                "amount_total": 0.0,
            },
        )
        entry["total_amount"] += amount
        entry["amount_total"] += amount
        entry["po_count"] += 1

    top_vendors = sorted(
        vendors.values(),
        key=lambda vendor: (-vendor["total_amount"], str(vendor["partner_name"] or "")),
    )[:PURCHASE_REPORTING_TOP_VENDORS]
    for vendor in top_vendors:
        vendor["total_amount"] = round(vendor["total_amount"], 2)
        vendor["amount_total"] = round(vendor["amount_total"], 2)

    bills_by_state: dict = {}
    bills_amount = 0.0
    for bill in bills:
        bills_amount += _to_float(bill.get("amount_total"))
        state = str(bill.get("state") or "").lower()
        bills_by_state[state] = bills_by_state.get(state, 0) + 1

    return {
        "total_po": len(orders),
        "total_amount": round(total_amount, 2),
        "by_state": by_state,
        "top_vendors": top_vendors,
        "monthly_series": _monthly_series(orders, bills),
        "vendor_bills": {
            "total": len(bills),
            "total_amount": round(bills_amount, 2),
            "by_state": bills_by_state,
        },
    }


class PurchaseReportingView(APIView):
    """``GET /api/v1/purchase/reporting/`` — agregat pembelian (read-only).

    Sumber = ``fetch_purchase_orders`` (I3) + ``fetch_vendor_bills`` (I6).
    Bentuk::

        {"total_po": N, "total_amount": X, "by_state": {"draft","purchase","done"},
         "top_vendors": [{"partner_name", "total_amount", "po_count",
                          "vendor_name", "vendor_code", "amount_total"}],
         "monthly_series": [{"month", "po_count", "amount_total", "vendor_bill_count"}],
         "vendor_bills": {"total", "total_amount", "by_state"}}

    ``top_vendors`` = 5 vendor dengan ``total_amount`` terbesar (tie-break nama).
    G5b (**aditif**): ``monthly_series`` = 6 bulan terakhir (ascending) + alias
    ``vendor_name``/``vendor_code``/``amount_total`` di tiap ``top_vendors``.
    Field lama TETAP.
    Fail-safe: ``ERP_ADAPTER=null`` → semua nilai 0 / list kosong (bukan error).
    Permission ``IsAuthenticated`` → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):  # noqa: ARG002 - request tak dipakai
        """Susun laporan pembelian; lihat docstring kelas."""
        orders = _fetch_transport_data(
            lambda transport: transport.fetch_purchase_orders(
                states=PURCHASE_ORDER_STATES
            )
        )
        bills = _fetch_transport_data(lambda transport: transport.fetch_vendor_bills())
        return Response(_purchase_reporting(orders, bills))


# ---------------------------------------------------------------------------
# Inventory reporting (F5.4.2 / B30) — agregat stok per lokasi (read-only)
# ---------------------------------------------------------------------------

#: ``(kode lokasi, label, nama setting env id Odoo)`` — urutan baris laporan.
INVENTORY_LOCATION_SPECS = (
    ("WH/WIP", "Gudang Bahan (WIP)", "ODOO_LOCATION_WIP_ID"),
    ("Virtual/Production", "Lokasi Produksi (WIP Issue)", "ODOO_LOCATION_PRODUCTION_ID"),
    ("WH/FG", "Gudang Barang Jadi (FG)", "ODOO_LOCATION_FG_ID"),
    ("Virtual/Scrap", "Lokasi Scrap", "ODOO_LOCATION_SCRAP_ID"),
)


def _location_env_id(setting_name: str) -> str:
    """Id lokasi Odoo dari settings (``''`` kalau belum dikonfigurasi)."""
    return str(getattr(settings, setting_name, "") or "").strip()


def _bundle_location_stats(queryset, qty_field: str):
    """``(total_qty, product_count, last_updated)`` untuk sekumpulan bundle.

    ``product_count`` = jumlah produk distinct (hanya bundle yang produk order
    line-nya termapping) — 1 query agregat + 1 query distinct.
    """
    aggregate = queryset.aggregate(total=Sum(qty_field), last=Max("updated_at"))
    products = (
        queryset.exclude(work_order__order_line__product__isnull=True)
        .order_by()
        .values("work_order__order_line__product_id")
        .distinct()
        .count()
    )
    return aggregate["total"] or 0, products, _iso(aggregate["last"])


def _inventory_reporting_rows() -> list[dict]:
    """Agregat stok **per lokasi** (4 baris; ``?location_code=`` memfilter).

    Sumber = data MES (tanpa memanggil Odoo) — proksi per lokasi:

      * ``WH/WIP``             → bundle ``DRAFT`` (belum di-issue ke lantai);
      * ``Virtual/Production`` → bundle di lantai (WC terisi, state bukan
        ``DONE``/``CANCELLED``) — barang yang sudah keluar dari gudang bahan;
      * ``WH/FG``              → bundle ``DONE`` (memakai ``qty_done``);
      * ``Virtual/Scrap``      → akumulasi ``ScrapAccumulator.qty``.

    **Fail-safe**: kalau env id lokasi (``ODOO_LOCATION_*``) kosong → baris tetap
    muncul dengan ``total_qty=0``/``product_count=0``/``last_updated=null`` dan
    **tanpa query** (konsisten kontrak: tidak error, tidak mengarang angka).
    """
    rows: list[dict] = []

    for code, label, setting_name in INVENTORY_LOCATION_SPECS:
        if not _location_env_id(setting_name):
            rows.append(
                {
                    "location_code": code,
                    "location_name": label,
                    "product_count": 0,
                    "total_qty": 0,
                    "last_updated": None,
                }
            )
            continue

        if code == "WH/WIP":
            total, products, last_updated = _bundle_location_stats(
                Bundle.objects.filter(
                    state="DRAFT", current_work_center__isnull=True
                ),
                "qty",
            )
        elif code == "Virtual/Production":
            total, products, last_updated = _bundle_location_stats(
                Bundle.objects.exclude(state__in=WCQueue.EXCLUDED_STATES).filter(
                    current_work_center__isnull=False
                ),
                "qty",
            )
        elif code == "WH/FG":
            total, products, last_updated = _bundle_location_stats(
                Bundle.objects.filter(state="DONE"), "qty_done"
            )
        else:  # Virtual/Scrap
            scrap = ScrapAccumulator.objects.all()
            aggregate = scrap.aggregate(total=Sum("qty"), last=Max("updated_at"))
            products = (
                scrap.exclude(bundle__work_order__order_line__product__isnull=True)
                .order_by()
                .values("bundle__work_order__order_line__product_id")
                .distinct()
                .count()
            )
            total, last_updated = aggregate["total"] or 0, _iso(aggregate["last"])

        rows.append(
            {
                "location_code": code,
                "location_name": label,
                "product_count": products,
                "total_qty": total,
                "last_updated": last_updated,
            }
        )

    return rows


class InventoryReportingView(APIView):
    """``GET /api/v1/inventory/reporting/`` — agregat stok per lokasi (F5.4.2 / B30).

    Bentuk::

        {"rows": [{"location_code", "location_name", "product_count",
                   "total_qty", "last_updated"}],
         "total_locations": 4, "generated_at": "ISO-8601"}

    Lokasi = 4 konfigurasi env (``ODOO_LOCATION_WIP_ID``,
    ``ODOO_LOCATION_PRODUCTION_ID``, ``ODOO_LOCATION_FG_ID``,
    ``ODOO_LOCATION_SCRAP_ID``) dengan label manual (``WH/WIP``,
    ``Virtual/Production``, ``WH/FG``, ``Virtual/Scrap``). Query opsional
    ``?location_code=WH/WIP`` (case-insensitive).

    Read-only, murni DB MES (tanpa panggilan Odoo) → fail-safe: env kosong atau
    belum ada data = nilai **0** (tidak error). Permission ``IsAuthenticated``
    (konsisten endpoint inventory lain) → anonim **403**.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Susun laporan stok per lokasi; lihat docstring kelas."""
        rows = _inventory_reporting_rows()

        location_code = str(request.query_params.get("location_code") or "").strip()
        if location_code:
            rows = [
                row
                for row in rows
                if row["location_code"].lower() == location_code.lower()
            ]

        return Response(
            {
                "rows": rows,
                "total_locations": len(rows),
                "generated_at": timezone.localtime(timezone.now()).isoformat(),
            }
        )
