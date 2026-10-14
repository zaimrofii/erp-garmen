"""Model `ProductionLine` — lini produksi & work center yang tergabung di dalamnya.

Dipakai capability-based line allocator (Sprint 2.2): bundle hanya boleh
dialokasikan ke line yang punya work center dengan kemampuan yang dibutuhkan.

H1.8 menambah ``capability_tags`` (daftar tag kapabilitas lini, CHANGES-DETAIL §8)
dan mengelola keanggotaan `work_centers` (M2M) lewat CRUD master
(`/api/v1/master/production-lines/`). Field lama tidak diubah.

Catatan keputusan H1.8: ProductionLine **MES-only** — tidak di-push/di-pull ke Odoo.
Probe Odoo 17: model ``mrp.routing`` **sudah tidak ada** (Routing dihapus sejak
Odoo 15) dan ``mrp.routing.workcenter`` ternyata **Operation** yang wajib menempel
ke ``bom_id`` + satu ``workcenter_id`` (tanpa ``code``/``routing_id``) — jadi Odoo
17 tidak punya wadah "lini/kumpulan work center". Sumber kebenaran lini = MES.

Arah M2M: **`ProductionLine.work_centers` adalah jalur tulis** (API master
memakai ``work_centers.set()`` di dalam ``transaction.atomic``); reverse
``related_name="production_lines"`` dipakai read-only (mis. detail Work Center H1.7).
"""

from __future__ import annotations

from django.db import models


class ProductionLine(models.Model):
    """Satu lini produksi (kumpulan work center yang beroperasi bersama)."""

    code = models.CharField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    work_centers = models.ManyToManyField(
        "garment.WorkCenter",
        blank=True,
        related_name="production_lines",
        verbose_name="work centers",
    )
    # --- H1.8 (master Production Line; MES-only) ------------------------------
    capability_tags = models.JSONField(
        "tag kapabilitas",
        default=list,
        blank=True,
        help_text=(
            'Daftar tag kapabilitas lini, mis. ["JAHIT", "OBRAS"] — tag bebas '
            "(huruf dipertahankan, sama seperti WorkCenter.capability_tags)."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Production Line"
        verbose_name_plural = "Production Lines"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
