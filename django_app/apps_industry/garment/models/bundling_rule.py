"""Model `BundlingRule` — aturan pembentukan bundle per varian/ukuran (F3A.2 / B24).

Aturan ini **data, bukan kode**: klien menentukan sendiri matriks ukuran
(mis. ``{"S": 10, "M": 12, "L": 12}``) dan berapa qty default per bundle.
Dipakai halaman *Bundling Rules* (settings) dan nantinya dipakai
`BundleEngine.create_bundles` saat memecah order line menjadi bundle.
"""

from __future__ import annotations

from django.db import models


class BundlingRule(models.Model):
    """Satu aturan bundling (matriks ukuran + ukuran bundle default)."""

    name = models.CharField("nama", max_length=150)
    size_matrix = models.JSONField(
        "matriks ukuran",
        default=dict,
        blank=True,
        help_text='Pemetaan {ukuran: qty}, mis. {"S": 10, "M": 12}.',
    )
    bundle_size_default = models.PositiveIntegerField(
        "ukuran bundle default",
        default=0,
        help_text="Qty default per bundle bila `size_matrix` tidak dipakai.",
    )
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Bundling Rule"
        verbose_name_plural = "Bundling Rules"
        ordering = ("name",)

    def __str__(self) -> str:
        return f"{self.name} (default={self.bundle_size_default})"
