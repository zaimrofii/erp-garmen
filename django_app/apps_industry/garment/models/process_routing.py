"""Model `ProcessRouting` — header DAG routing proses produksi.

Routing = **data, bukan kode**: klien A dan klien B boleh punya urutan proses
berbeda (mis. Sablon sebelum Sewing vs sebaliknya) tanpa mengubah kode.
Node/node DAG-nya ada di `routing_step.py` (``RoutingStep`` +
``allowed_next_steps`` + ``rework_target_step``).

Validasi graf (deteksi cycle, step awal/akhir, orphan node) TIDAK dilakukan di
model ini — itu tugas service layer (`master/routing_services.py`, H1.9) supaya
model tetap tipis.

H1.9 menambah ``capability_tags`` (daftar tag kapabilitas routing, CHANGES-DETAIL §8).
Keputusan H1.9: routing **MES-only** — tidak ada push/pull Odoo (probe Odoo 17:
model ``mrp.routing`` sudah dihapus, ``mrp.routing.workcenter`` = Operation per-BoM
yang wajib ``bom_id``+``workcenter_id``) ⇒ tidak ada ``odoo_id`` (hindari field mati)
dan tidak ada ``routing_type`` (tidak diminta CHANGES-DETAIL §8, tidak ada di repo).
"""

from __future__ import annotations

from django.db import models


class ProcessRouting(models.Model):
    """Header routing proses produksi (versionable lewat pembuatan header baru)."""

    code = models.CharField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    # --- H1.9 (master Routing DAG; MES-only) ----------------------------------
    capability_tags = models.JSONField(
        "tag kapabilitas",
        default=list,
        blank=True,
        help_text=(
            'Daftar tag kapabilitas routing, mis. ["JAHIT", "OBRAS"] — tag bebas '
            "(huruf dipertahankan, sama seperti WorkCenter/ProductionLine H1.7–H1.8)."
        ),
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Process Routing"
        verbose_name_plural = "Process Routings"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
