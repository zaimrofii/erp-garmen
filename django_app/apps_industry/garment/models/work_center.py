"""Model `WorkCenter` — stasiun/meja kerja tempat bundle diproses.

Work center adalah "lokasi eksekusi" yang dipakai bundle, routing step,
device binding, dan scrap accumulator. Atribut bebas per WC (mis. mesin) tetap
ditaruh di ``config`` (JSON) supaya tidak perlu migration setiap ada tambahan.

H1.7 menambah 3 field **eksplisit** yang dipakai form master (CHANGES-DETAIL §8):
``wc_type`` (jenis stasiun), ``capability_tags`` (daftar tag kapabilitas), dan
``capacity_per_hour`` (target output per jam). ``config`` **tidak** diubah dan
tetap jadi tempat atribut bebas (mis. ``target_per_day`` yang dibaca monitoring).

Catatan keputusan H1.7: Work Center **MES-only** — tidak di-push/di-pull ke Odoo.
Probe Odoo 17 ``mrp.workcenter`` menunjukkan field wajib ``resource_id``
(many2one ``resource.resource``, **tanpa default**) + ``sequence``, serta tidak ada
padanan untuk ``wc_type``/``capability_tags``/``capacity_per_hour`` (bukan konsep
MES) → push akan mengarang data. Produksi LazyMES memakai model ini, bukan
work center Odoo.
"""

from __future__ import annotations

from django.db import models


class WorkCenter(models.Model):
    """Stasiun kerja (mis. "SEWING-1", "SABLON-2", "QC-1")."""

    code = models.CharField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    # --- H1.7 (master Work Center; MES-only) ---------------------------------
    wc_type = models.CharField(
        "tipe work center",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            'Jenis stasiun (bebas, mis. "SEWING"/"CUTTING"/"QC") — konvensi sama '
            "dengan LineAllocationRule.wc_type (tanpa enum di kode)."
        ),
    )
    capability_tags = models.JSONField(
        "tag kapabilitas",
        default=list,
        blank=True,
        help_text='Daftar tag kapabilitas, mis. ["JAHIT_LURUS", "OBRAS", "OVERDECK"].',
    )
    capacity_per_hour = models.DecimalField(
        "kapasitas per jam",
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Target output per jam (0 = belum diukur).",
    )
    description = models.TextField("deskripsi", blank=True, default="")
    is_active = models.BooleanField("aktif", default=True)
    config = models.JSONField(
        "konfigurasi",
        default=dict,
        blank=True,
        help_text='Atribut tambahan, mis. {"capacity_per_hour": 40, "machine": "JUKI"}.',
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Work Center"
        verbose_name_plural = "Work Centers"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
