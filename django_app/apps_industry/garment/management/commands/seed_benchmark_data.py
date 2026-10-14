"""Seed data sintetis untuk benchmark performa (F5.2) — **TOOL SEMENTARA**.

Membuat data skala besar (WorkOrder + Bundle + BundleEvent) dengan `bulk_create`
supaya benchmark endpoint agregat bisa dijalankan di dev DB **tanpa** Odoo dan
tanpa menyentuh fixture produksi.

    docker compose exec django python manage.py seed_benchmark_data --bundles 1000
    docker compose exec django python manage.py seed_benchmark_data --bundles 10000 --reset

Aturan:
  * **idempoten** — kalau data benchmark (prefix ``BENCH-``) sudah ada, command
    berhenti tanpa menulis apa pun; pakai ``--reset`` untuk hapus lalu seed ulang;
  * **BUKAN fixture produksi** — semua baris ber-prefix ``BENCH-`` dan hanya
    dipakai `tests/integration/test_perf_queries.py` + dokumen
    ``docs/perf-benchmark.md``;
  * tanpa migration & tanpa perubahan model.
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps_industry.garment.models import (
    Bundle,
    BundleEvent,
    Order,
    OrderLine,
    ProcessRouting,
    RoutingStep,
    WorkCenter,
    WorkOrder,
)
from master.models import Product

#: Prefix semua baris benchmark (juga penanda idempotensi).
PREFIX = "BENCH"

#: State bundle yang dipakai (semua bukan DONE supaya masuk queue/WIP).
BENCH_STATES = ("DRAFT", "CUTTING", "SEWING", "QC", "SEWING", "SEWING")

#: Nama event (konstanta sama dengan `monitoring.py`).
EVENT_START = "BUNDLE_START"
EVENT_FINISH = "BUNDLE_FINISH"
EVENT_TRANSFER = "BUNDLE_TRANSFER"

BUNDLES_PER_WORK_ORDER = 25
CHUNK = 1000
TREND_DAYS = 7


class Command(BaseCommand):
    """Buat/hapus data benchmark sintetis (lihat docstring modul)."""

    help = "Seed data sintetis untuk benchmark performa (prefix BENCH-, tool sementara)."

    def add_arguments(self, parser):
        """Argumen CLI (brief F5.2)."""
        parser.add_argument("--bundles", type=int, default=1000)
        parser.add_argument("--events-per-bundle", type=int, default=5)
        parser.add_argument("--work-centers", type=int, default=6)
        parser.add_argument("--reset", action="store_true")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Hapus & seed ulang walau data BENCH- sudah ada (alias --reset).",
        )

    def handle(self, *args, **options):
        """Jalankan seed; lihat docstring modul."""
        bundles = max(int(options["bundles"]), 1)
        events_per_bundle = max(int(options["events_per_bundle"]), 1)
        work_center_count = max(int(options["work_centers"]), 2)
        reset = bool(options["reset"] or options["force"])

        if Bundle.objects.filter(code__startswith=f"{PREFIX}-").exists():
            if not reset:
                self.stdout.write(
                    self.style.WARNING(
                        f"Data benchmark sudah ada ({PREFIX}-*). Pakai --reset untuk seed ulang."
                    )
                )
                return
            self._purge()

        started = time.perf_counter()
        with transaction.atomic():
            work_centers = self._make_work_centers(work_center_count)
            self._make_routing(work_centers)
            order_line = self._make_order_line(bundles)
            work_orders = self._make_work_orders(order_line, bundles)
            created = self._make_bundles(bundles, work_orders, work_centers)
            self._make_events(created, events_per_bundle)
        elapsed = time.perf_counter() - started

        self.stdout.write(
            self.style.SUCCESS(
                f"seed_benchmark_data OK: bundles={bundles} "
                f"events_per_bundle={events_per_bundle} work_centers={work_center_count} "
                f"dalam {elapsed:.2f}s"
            )
        )

    # ------------------------------------------------------------------ internal
    def _purge(self) -> None:
        """Hapus SEMUA baris benchmark (aman: hanya prefix `BENCH-`)."""
        BundleEvent.objects.filter(bundle__code__startswith=f"{PREFIX}-").delete()
        Bundle.objects.filter(code__startswith=f"{PREFIX}-").delete()
        WorkOrder.objects.filter(code__startswith=f"{PREFIX}-").delete()
        OrderLine.objects.filter(order__code__startswith=f"{PREFIX}-").delete()
        Order.objects.filter(code__startswith=f"{PREFIX}-").delete()
        Product.objects.filter(code__startswith=f"{PREFIX}-").delete()
        RoutingStep.objects.filter(routing__code__startswith=f"{PREFIX}-").delete()
        ProcessRouting.objects.filter(code__startswith=f"{PREFIX}-").delete()
        WorkCenter.objects.filter(code__startswith=f"{PREFIX}-").delete()
        self.stdout.write(self.style.WARNING("Data benchmark lama dihapus (--reset)."))

    def _make_work_centers(self, count: int) -> list[WorkCenter]:
        """`count` work center ber-prefix (urut kode)."""
        return [
            WorkCenter.objects.create(
                code=f"{PREFIX}-WC-{index + 1:02d}",
                name=f"Bench WC {index + 1:02d}",
                config={"target_per_day": 100},
            )
            for index in range(count)
        ]

    def _make_routing(self, work_centers: list[WorkCenter]) -> ProcessRouting:
        """Routing linier; step TERAKHIR = terminal (dipakai klasifikasi FG)."""
        routing = ProcessRouting.objects.create(
            code=f"{PREFIX}-ROUTE", name="Bench Routing", is_active=True
        )
        for index, work_center in enumerate(work_centers, start=1):
            RoutingStep.objects.create(
                routing=routing,
                code=f"{PREFIX}-STEP-{index:02d}",
                label=work_center.name,
                order=index,
                work_center=work_center,
                is_terminal=index == len(work_centers),
            )
        return routing

    def _make_order_line(self, bundles: int) -> OrderLine:
        """Satu order + produk + order line untuk semua WO benchmark."""
        order = Order.objects.create(code=f"{PREFIX}-ORD-1", order_type="EXPORT")
        product = Product.objects.create(code=f"{PREFIX}-TS", name="Bench Kaos")
        return OrderLine.objects.create(
            order=order, product=product, tag="FAST_TRACK", qty=bundles * 10
        )

    def _make_work_orders(self, order_line: OrderLine, bundles: int) -> list[WorkOrder]:
        """WorkOrder secukupnya (`BUNDLES_PER_WORK_ORDER` bundle per WO)."""
        count = max(bundles // BUNDLES_PER_WORK_ORDER, 1)
        return [
            WorkOrder.objects.create(
                code=f"{PREFIX}-WO-{index + 1:05d}",
                order_line=order_line,
                state="IN_PROGRESS",
                qty_planned=BUNDLES_PER_WORK_ORDER,
            )
            for index in range(count)
        ]

    def _make_bundles(
        self,
        count: int,
        work_orders: list[WorkOrder],
        work_centers: list[WorkCenter],
    ) -> list[Bundle]:
        """`count` bundle tersebar merata antar WO/WC; `updated_at` disebar 7 hari.

        Bundle di WC **terminal** diberi `qty_done = qty` supaya klasifikasi FG
        (`TwoStageAggregator`) benar-benar terpicu saat benchmark.
        """
        wc_total = len(work_centers)
        rows = [
            Bundle(
                code=f"{PREFIX}-BND-{index + 1:06d}",
                work_order=work_orders[index % len(work_orders)],
                size=("S", "M", "L", "XL")[index % 4],
                sku_variant=f"{PREFIX}-TS",
                qty=10 + (index % 20),
                qty_done=(10 + (index % 20)) if index % wc_total == wc_total - 1 else 0,
                state=BENCH_STATES[index % len(BENCH_STATES)],
                current_work_center=work_centers[index % wc_total],
            )
            for index in range(count)
        ]
        Bundle.objects.bulk_create(rows, batch_size=CHUNK)

        created = list(Bundle.objects.filter(code__startswith=f"{PREFIX}-").order_by("code"))
        now = timezone.localtime(timezone.now())
        for offset in range(TREND_DAYS):
            anchor = (now - timedelta(days=offset)).replace(
                hour=8, minute=0, second=0, microsecond=0
            )
            pks = [
                bundle.pk for index, bundle in enumerate(created) if index % TREND_DAYS == offset
            ]
            Bundle.objects.filter(pk__in=pks).update(updated_at=anchor)

        return created

    def _make_events(self, bundles: list[Bundle], events_per_bundle: int) -> None:
        """Event per bundle: 1 START + (M-1) TRANSFER (+ FINISH tiap 4 bundle).

        `BundleEvent.ts` = `auto_now_add` → `ts` tidak bisa diisi lewat
        `bulk_create`; disebar 7 hari setelah insert (2 UPDATE per hari).
        """
        rows: list[BundleEvent] = []
        for index, bundle in enumerate(bundles):
            rows.append(BundleEvent(bundle=bundle, event_type=EVENT_START, text="bench"))
            for extra in range(events_per_bundle - 1):
                rows.append(
                    BundleEvent(bundle=bundle, event_type=EVENT_TRANSFER, text=f"bench {extra}")
                )
            if index % 4 == 0:
                rows.append(BundleEvent(bundle=bundle, event_type=EVENT_FINISH, text="bench"))
        BundleEvent.objects.bulk_create(rows, batch_size=CHUNK)

        now = timezone.localtime(timezone.now())
        for offset in range(TREND_DAYS):
            anchor = (now - timedelta(days=offset)).replace(
                hour=8, minute=0, second=0, microsecond=0
            )
            pks = [
                bundle.pk for index, bundle in enumerate(bundles) if index % TREND_DAYS == offset
            ]
            BundleEvent.objects.filter(bundle_id__in=pks).update(ts=anchor)
            BundleEvent.objects.filter(bundle_id__in=pks, event_type=EVENT_FINISH).update(
                ts=anchor + timedelta(hours=6)
            )

