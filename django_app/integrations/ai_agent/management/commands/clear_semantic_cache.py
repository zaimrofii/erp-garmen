"""Invalidasi cache semantik AI (version bump; key lama tidak dipakai)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from integrations.ai_agent.memory import semantic_cache


class Command(BaseCommand):
    help = "Invalidasi seluruh cache semantik AI (tanpa menghapus tabel audit)."

    def handle(self, *args, **options):
        updated = semantic_cache.invalidate("manual_clear")
        self.stdout.write(
            self.style.SUCCESS(
                f"Cache semantik diinvalidasi (trigger=manual_clear, rows={updated})."
            )
        )
