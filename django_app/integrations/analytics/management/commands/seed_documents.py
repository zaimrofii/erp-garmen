"""Seed dokumen SOP/QC (TEMPORARY) — idempoten, marker kategori SOP."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from integrations.analytics.models import Document

DOCUMENTS = (
    (
        "SOP Rework Garment",
        "Rework dilakukan bila cacat jahitan < 3 cm. Bundle dipindah ke QC-1, "
        "dicatat di ScrapAccumulator dengan rework_qty, lalu dikembalikan ke "
        "SEWING-2 setelah lolos inspeksi.",
        "SOP",
        ["rework", "qc", "sewing"],
    ),
    (
        "SOP Quality Control",
        "QC memeriksa 100% bundle pertama dan sampling AQL 2.5 untuk batch "
        "berikutnya. Cacat kritis (lubang, sobek) langsung scrap; cacat minor "
        "masuk rework.",
        "SOP",
        ["qc", "aql", "inspeksi"],
    ),
    (
        "SOP Cutting",
        "Cutting mengikuti marker dan BOM. Sisa kain dicatat sebagai end-loss. "
        "Selisih qty cutting vs sewing > 10% wajib dilaporkan ke supervisor.",
        "SOP",
        ["cutting", "end-loss", "bom"],
    ),
    (
        "SOP Pindah Work Center",
        "Bundle dipindah setelah qty_done terisi dan QC lolos. Pindah WC dicatat "
        "sebagai BundleEvent BUNDLE_MOVE_OUT/BUNDLE_MOVE_IN; buffer WC tujuan "
        "maksimal 20 bundle.",
        "SOP",
        ["bundle", "work-center", "buffer"],
    ),
    (
        "SOP Scrap Reporting",
        "Setiap scrap wajib mencatat qty, alasan, work center, dan foto bila "
        "memungkinkan. Scrap > 10% dari qty cutting memicu cross-check order.",
        "SOP",
        ["scrap", "laporan", "qc"],
    ),
    (
        "SOP Shift Handover",
        "Handover shift 1 ke shift 2 mencatat WIP per WC, bundle rework, dan "
        "kejadian abnormal. Shift 2 mulai pukul 14.00.",
        "SOP",
        ["shift", "handover", "wip"],
    ),
    (
        "SOP Operator Input",
        "Operator scan bundle saat mulai dan selesai. Dilarang input massal di "
        "akhir shift; sistem menandai > 30 event dalam 30 menit sebagai anomali.",
        "SOP",
        ["operator", "anomali", "scan"],
    ),
    (
        "SOP OEE Monitoring",
        "OEE = Availability × Performance × Quality. Availability rendah berarti "
        "WC idle; Performance rendah berarti output di bawah kapasitas; Quality "
        "rendah berarti scrap tinggi.",
        "SOP",
        ["oee", "availability", "performance"],
    ),
)


class Command(BaseCommand):
    help = "Seed 8 dokumen SOP/QC untuk full-text search (idempoten)."

    def handle(self, *args, **options):
        created = 0
        for title, content, category, tags in DOCUMENTS:
            _document, was_created = Document.objects.get_or_create(
                title=title,
                defaults={"content": content, "category": category, "tags": tags},
            )
            created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed dokumen selesai: {created} baru, {len(DOCUMENTS)} total."
            )
        )
