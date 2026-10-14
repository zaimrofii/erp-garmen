"""Seed default pajak MES (H3.6 — `docs/CHANGES-DETAIL-H1H5.md` §6).

Aditif + **idempoten**: baris dicocokkan berdasarkan **`(amount, type_tax_use)`**, BUKAN
nama (sample dev Odoo: tax bernama `'12% (Non-Luxury Good)'` ternyata `amount=11.0` —
label vs angka tidak konsisten, jadi pencocokan nama berbahaya).

Yang di-seed (hanya bila belum ada pasangannya):

  * `amount=11`, `type_tax_use='sale'`     → **PPN 11%** (kode `PPN11-SALE`), **default**;
  * `amount=11`, `type_tax_use='purchase'` → PPN 11% (Pembelian) (kode `PPN11-PURCHASE`);
  * `amount=0`,  `type_tax_use='sale'`     → PPN 0% (Export) (kode `PPN0-SALE`).

Penjaminan default: kalau SETELAH seed tidak ada satu pun `Tax` ber-`is_default=True`,
baris PPN 11% penjualan di-set default (idempoten — baris hasil pull Odoo tidak
ditimpa nilainya; hanya penanda default yang dipastikan ada).

Sync dua arah: seed ini **tidak** memanggil Odoo; push ke Odoo terjadi lewat CRUD/push
master (stage `MASTER_PUSH`, resource `master.tax`).
"""

from django.db import migrations
from django.utils import timezone

#: (amount, type_tax_use, code, name, is_default) — urutan aman untuk didokumentasikan.
SEEDS: tuple[tuple[str, str, str, str, bool], ...] = (
    ("11.00", "sale", "PPN11-SALE", "PPN 11%", True),
    ("11.00", "purchase", "PPN11-PURCHASE", "PPN 11% (Pembelian)", False),
    ("0.00", "sale", "PPN0-SALE", "PPN 0% (Export)", False),
)


def seed_default_taxes(apps, schema_editor):
    """Buat pajak default MES bila belum ada (idempoten by amount + type_tax_use).

    Catatan penting (temuan STEP 0 di dev): MES sudah berisi puluhan baris `Tax`
    hasil **pull Odoo** dengan `amount=0` & `type_tax_use='sale'` (mapper lama
    membuang `amount`). Karena itu pencocokan `(amount, type_tax_use)` dibatasi ke
    baris **milik MES** (`odoo_id IS NULL`) + kode seed, supaya seed ini tidak
    "menempel" pada baris mirror Odoo dan tidak pernah ambigu.
    """
    tax = apps.get_model("master", "Tax")

    for amount, type_tax_use, code, name, is_default in SEEDS:
        row = tax.objects.filter(code=code).first()
        if row is None:
            row = tax.objects.filter(
                amount=amount, type_tax_use=type_tax_use, odoo_id__isnull=True
            ).first()
        if row is None:
            row = tax.objects.create(
                code=code,
                name=name,
                amount=amount,
                amount_type="percent",
                type_tax_use=type_tax_use,
                price_include=False,
                is_default=False,
                is_active=True,
            )

        # Lengkapi penanda default SETELAH semua baris dibuat (lihat docstring).
        if is_default and not tax.objects.filter(is_default=True).exists():
            row.is_default = True
            row.save(update_fields=("is_default",))


def unseed_default_taxes(apps, schema_editor):
    """Hapus hanya baris yang dibuat seed ini (kode seed, tanpa odoo_id)."""
    tax = apps.get_model("master", "Tax")
    tax.objects.filter(code__in=[seed[2] for seed in SEEDS], odoo_id__isnull=True).delete()


class Migration(migrations.Migration):
    """Data migration: seed pajak default MES (PPN 11%)."""

    dependencies = [
        ("master", "0018_tax_h3_fields"),
    ]

    operations = [
        migrations.RunPython(seed_default_taxes, unseed_default_taxes),
    ]
