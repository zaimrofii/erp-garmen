"""Model `WorkOrder` — pemecahan ``OrderLine`` menjadi unit kerja.

Satu ``OrderLine`` bisa dipecah menjadi beberapa work order (mis. per batch atau
per tahap besar). Bundle (unit pelacakan terkecil di lantai produksi) menggantung
ke WorkOrder, bukan langsung ke OrderLine.
"""

from __future__ import annotations

from django.db import models


class WorkOrder(models.Model):
    """Unit kerja untuk satu baris order."""

    code = models.CharField("kode", max_length=64, unique=True)
    order_line = models.ForeignKey(
        "garment.OrderLine",
        on_delete=models.PROTECT,
        related_name="work_orders",
        verbose_name="baris order",
    )
    # `state` = data (didefinisikan di core.state_machine), bukan enum di kode.
    state = models.CharField("state", max_length=32, default="DRAFT")
    qty_planned = models.PositiveIntegerField("qty rencana", default=0)
    qty_done = models.PositiveIntegerField("qty selesai", default=0)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Work Order"
        verbose_name_plural = "Work Orders"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} [{self.state}]"
