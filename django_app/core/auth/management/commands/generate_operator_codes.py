"""``generate_operator_codes`` — backfill `operator_code` untuk user OPERATOR/QC (F6.1).

Kapan dipakai: setelah migrasi `core_auth.0003`, user yang sudah ada belum punya
kode (kolom baru = NULL). Operasi normal tidak butuh perintah ini — user baru
otomatis dapat kode dari `User.save()`. Jadi perintah ini **sekali jalan** untuk
data lama, dan aman dijalankan berkali-kali (hanya user tanpa kode yang disentuh).

Contoh::

    python manage.py generate_operator_codes --dry-run
    python manage.py generate_operator_codes
    python manage.py generate_operator_codes --role OPERATOR
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from core.auth.models import (
    OPERATOR_CODE_ROLES,
    User,
    generate_unique_operator_code,
)


class Command(BaseCommand):
    """Isi kode operator yang masih kosong (4 digit, unik)."""

    help = (
        "Generate operator_code untuk user ber-role OPERATOR/QC yang belum punya kode. "
        "Idempotent: user yang sudah punya kode tidak diubah."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Hitung saja, tanpa menyimpan perubahan.",
        )
        parser.add_argument(
            "--role",
            type=str,
            default="",
            help=(
                "Batasi ke satu kode role (mis. OPERATOR); default semua role "
                f"pemilik kode: {', '.join(OPERATOR_CODE_ROLES)}."
            ),
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        role_filter = str(options["role"] or "").strip().upper()

        queryset = (
            User.objects.select_related("role")
            .filter(role__code__in=OPERATOR_CODE_ROLES)
            .filter(Q(operator_code__isnull=True) | Q(operator_code=""))
            .order_by("id")
        )
        if role_filter:
            queryset = queryset.filter(role__code__iexact=role_filter)

        users = list(queryset)
        if not users:
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada user OPERATOR/QC tanpa kode operator — tidak ada yang diubah."
                )
            )
            return

        for user in users:
            # Kode diundi di sini (bukan lewat `User.save()` penuh) supaya tidak
            # ada kolom lain yang tersentuh — `update_fields=["operator_code"]`.
            code = generate_unique_operator_code(exclude_pk=user.pk)
            if not dry_run:
                user.operator_code = code
                user.save(update_fields=["operator_code"])

            self.stdout.write(
                f"{'[dry-run] ' if dry_run else ''}{user.get_username()} "
                f"({user.role.code if user.role_id else '-'}) -> {code}"
            )

        prefix = "[dry-run] akan mengisi" if dry_run else "Terisi"
        self.stdout.write(
            self.style.SUCCESS(f"{prefix} kode operator untuk {len(users)} user.")
        )
