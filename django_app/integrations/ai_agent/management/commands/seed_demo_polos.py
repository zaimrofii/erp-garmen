"""Seed 5 produk demo "Kaos Polos" (Fix #15) — idempoten, hanya master produk."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from integrations.ai_agent.demo_products import ensure_demo_polos_products


class Command(BaseCommand):
    help = "Pastikan produk ODOO-65..69 punya nama/harga/kategori pembeda."

    def handle(self, *args, **options):
        from master.models import UoM

        unit = (
            UoM.objects.filter(name__iexact="Units").first()
            or UoM.objects.first()
        )
        products = ensure_demo_polos_products(uom=unit)
        for product in products:
            self.stdout.write(
                f"{product.code} | {product.name} | {product.sale_price} | "
                f"{product.category or '-'}"
            )
        self.stdout.write(
            self.style.SUCCESS(f"{len(products)} produk demo Kaos Polos siap.")
        )
