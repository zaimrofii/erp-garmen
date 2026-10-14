"""``seed_demo_bundles`` — seed bundle **ACTIONABLE** untuk demo/UAT (FASE 4.2).

Kenapa perlu: setelah banyak run simulator/e2e, hampir semua bundle berakhir
``DONE`` sehingga tombol aksi di UI mati (tidak ada yang bisa di-START/QC/FINISH).
Command ini menyiapkan ulang data demo **tanpa mengubah model/service** — ia
memakai `BundleEngine.create_bundles()`, satu-satunya pembuat bundle di repo.

Arti ``--count``: **jumlah WorkOrder DRAFT** yang disiapkan (tiap WO → bundle
sesuai ``--size-matrix``). WO DRAFT yang sudah ada **dipakai ulang**; kalau
kurang, WO baru dibuat dari ``OrderLine`` yang belum punya WorkOrder (supaya WO
baru itu = WO **pertama** order line — syarat `BundleEngine._resolve_work_order`).

Contoh::

    python manage.py seed_demo_bundles --count 5
    python manage.py seed_demo_bundles --count 2 --size-matrix '{"M": 10}' --bundle-size 5
"""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError

from apps_industry.garment.models import Bundle, OrderLine, WorkOrder
from apps_industry.garment.services.bundle_engine import BundleEngine
from apps_industry.garment.services.exceptions import BundleEngineError

#: Matriks ukuran default (2 bundle per WO dengan `--bundle-size 5`).
DEFAULT_SIZE_MATRIX = '{"M": 5, "L": 5}'


class Command(BaseCommand):
    """Buat WorkOrder DRAFT + bundle ber-state ``DRAFT`` (langsung bisa di-action)."""

    help = (
        "Seed WorkOrder DRAFT + bundle ACTIONABLE (state DRAFT) untuk demo/UAT. "
        'Tanpa argumen: 5 WorkOrder DRAFT, matriks {"M":5,"L":5}, bundle_size 5.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=5,
            help="Jumlah WorkOrder DRAFT yang disiapkan (default 5).",
        )
        parser.add_argument(
            "--size-matrix",
            type=str,
            default=DEFAULT_SIZE_MATRIX,
            help=f"Matriks ukuran (JSON), default {DEFAULT_SIZE_MATRIX!r}.",
        )
        parser.add_argument(
            "--bundle-size",
            type=int,
            default=5,
            help="Qty maksimum per bundle (default 5).",
        )

    # ------------------------------------------------------------------- handle
    def handle(self, *args, **options):
        count = max(int(options["count"]), 0)
        bundle_size = options["bundle_size"]
        size_matrix = self._parse_size_matrix(options["size_matrix"])

        if count == 0:
            self.stdout.write(self.style.WARNING("--count 0 → tidak ada yang di-seed."))
            return

        targets = self._plan_targets(count)
        if not targets:
            raise CommandError(
                "Tidak ada kandidat: tidak ada WorkOrder DRAFT dan tidak ada "
                "OrderLine yang bisa dipakai. Buat Order/OrderLine dulu "
                "(mis. lewat sync SO Odoo)."
            )

        created_total = 0
        for work_order, order_line in targets:
            bundles = self._create_bundles(
                work_order, order_line, size_matrix, bundle_size
            )
            if bundles is None:
                continue
            created_total += len(bundles)
            self.stdout.write(
                f"Created {len(bundles)} bundle untuk WO {work_order.code}:"
            )
            for bundle in bundles:
                self.stdout.write(
                    f"  id={bundle.id} code={bundle.code} size={bundle.size} "
                    f"qty={bundle.qty} state={bundle.state}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Total: {created_total} bundle DRAFT baru dari {len(targets)} WorkOrder."
            )
        )

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _parse_size_matrix(raw: str) -> dict:
        """Parse `--size-matrix` (JSON objek `{size: qty}`); invalid → CommandError."""
        try:
            size_matrix = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise CommandError(
                f"--size-matrix bukan JSON valid: {exc}. Contoh: {DEFAULT_SIZE_MATRIX}"
            ) from exc

        if not isinstance(size_matrix, dict) or not size_matrix:
            raise CommandError(
                "--size-matrix harus objek JSON {size: qty} yang tidak kosong. "
                f"Contoh: {DEFAULT_SIZE_MATRIX}"
            )
        return size_matrix

    @staticmethod
    def _next_work_order_code(order_line: OrderLine) -> str:
        """Kode WO unik: ``WO-SEED-<order_line_id>-<epoch>`` (+ suffix bila bentrok)."""
        base = f"WO-SEED-{order_line.id}-{int(time.time())}"
        code = base
        seq = 1
        while WorkOrder.objects.filter(code=code).exists():
            seq += 1
            code = f"{base}-{seq}"
        return code

    @staticmethod
    def _candidate_order_lines() -> list[OrderLine]:
        """OrderLine yang **belum punya** WorkOrder (WO baru = WO pertama).

        Yang punya produk didahulukan supaya rantai `product_ref` (bundle → WO →
        OrderLine → Product) berfungsi; sisanya dipakai sebagai fallback.
        """
        base = OrderLine.objects.filter(work_orders__isnull=True)
        return list(base.filter(product__isnull=False).order_by("id")) + list(
            base.filter(product__isnull=True).order_by("id")
        )

    def _plan_targets(self, count: int) -> list[tuple[WorkOrder, OrderLine]]:
        """Pasangan `(WorkOrder DRAFT, OrderLine)` sampai ``count`` (reuse dulu)."""
        targets: list[tuple[WorkOrder, OrderLine]] = []
        used_lines: set = set()

        draft = (
            WorkOrder.objects.filter(state="DRAFT")
            .order_by("id")
            .select_related("order_line")
        )
        for work_order in draft:
            if len(targets) >= count:
                return targets
            if work_order.order_line_id in used_lines:
                continue  # satu order line cukup satu target
            used_lines.add(work_order.order_line_id)
            targets.append((work_order, work_order.order_line))

        for order_line in self._candidate_order_lines():
            if len(targets) >= count:
                break
            if order_line.pk in used_lines:
                continue
            used_lines.add(order_line.pk)
            work_order = WorkOrder.objects.create(
                code=self._next_work_order_code(order_line),
                order_line=order_line,
                state="DRAFT",
                qty_planned=order_line.qty,
            )
            if order_line.product_id is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  PERINGATAN: OrderLine {order_line.pk} tanpa product → "
                        f"GET /garmen/work-orders/{work_order.pk}/ berisiko 500."
                    )
                )
            targets.append((work_order, order_line))

        return targets

    def _create_bundles(
        self, work_order: WorkOrder, order_line: OrderLine, size_matrix: dict, bundle_size
    ) -> "list[Bundle] | None":
        """Buat bundle untuk satu order line; ``None`` = di-skip (bundle sudah ada).

        Dicek lebih dulu lewat `BundleEngine.preview_bundles` (kode bundle
        deterministik `"<order_line_id>-<size>-<seq>"`, unik) supaya seed yang
        dijalankan dua kali **tidak** menabrak constraint `Bundle.code`.
        """
        try:
            plan = BundleEngine.preview_bundles(order_line, size_matrix, bundle_size)
            codes = [item["code"] for item in plan]
            existing = sorted(
                Bundle.objects.filter(code__in=codes).values_list("code", flat=True)
            )
            if existing:
                sisa = "..." if len(existing) > 3 else ""
                self.stdout.write(
                    self.style.WARNING(
                        f"SKIP WO {work_order.code}: bundle sudah ada "
                        f"({', '.join(existing[:3])}{sisa})."
                    )
                )
                return None
            return BundleEngine.create_bundles(order_line, size_matrix, bundle_size)
        except BundleEngineError as exc:
            raise CommandError(f"BundleEngineError: {exc}") from exc

