"""Model `Bundle` — unit pelacakan terkecil di lantai produksi.

Bundle = sekumpulan potongan dengan ukuran (size) dan varian SKU tertentu yang
bergerak bersama dari satu work center ke work center berikutnya.

``version`` = token **optimistic lock / jejak audit**: SHA-256 dari state kritis
(`code` + `state` + `qty_done` + `current_work_center_id` + timestamp). Token
ini dipakai UI operator (dan two-stage sync Odoo) untuk mendeteksi bahwa datanya
sudah berubah sejak terakhir dibaca; kalau berubah, aksi operator ditolak dan
data dimuat ulang.

Perhitungan version dilakukan di `save()` (bukan signal) supaya eksplisit dan
mudah ditelusuri.
"""

from __future__ import annotations

import hashlib

from django.db import models
from django.utils import timezone


class Bundle(models.Model):
    """Sekumpulan potongan (size + SKU variant) yang diproses bersama."""

    #: Field yang membuat `version` dianggap basi kalau nilainya berubah.
    CRITICAL_FIELDS = ("state", "qty_done", "current_work_center_id")

    code = models.CharField("kode", max_length=64, unique=True)
    work_order = models.ForeignKey(
        "garment.WorkOrder",
        on_delete=models.PROTECT,
        related_name="bundles",
        verbose_name="work order",
    )
    size = models.CharField("ukuran", max_length=32, blank=True, default="")
    sku_variant = models.CharField("varian SKU", max_length=64, blank=True, default="")
    qty = models.PositiveIntegerField("qty", default=0)
    qty_done = models.PositiveIntegerField("qty selesai", default=0)
    # `state` = data (definisi ada di core.state_machine), bukan enum di kode.
    state = models.CharField("state", max_length=32, default="DRAFT")
    current_work_center = models.ForeignKey(
        "garment.WorkCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bundles",
        verbose_name="work center saat ini",
    )
    production_line = models.ForeignKey(
        "garment.ProductionLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bundles",
        verbose_name="line produksi",
    )
    version = models.CharField(
        "version",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        editable=False,
        help_text="SHA-256 state kritis; dihitung otomatis di save().",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Bundle"
        verbose_name_plural = "Bundles"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} [{self.state}] x{self.qty}"

    # ------------------------------------------------------------------ version
    @classmethod
    def from_db(cls, db, field_names, values):
        """Catat nilai state kritis saat instance dibaca dari DB.

        Dipakai `save()` untuk tahu apakah state kritis berubah (tanpa query
        tambahan dan tanpa menyimpan salinan "original" di setiap view).
        """
        instance = super().from_db(db, field_names, values)
        instance._loaded_critical = {
            field: getattr(instance, field) for field in cls.CRITICAL_FIELDS
        }
        return instance

    def compute_version(self, timestamp=None) -> str:
        """SHA-256 dari state kritis + `timestamp` (default: sekarang)."""
        timestamp = timestamp or self.updated_at or timezone.now()
        raw = "|".join(
            (
                str(self.code or ""),
                str(self.state or ""),
                str(self.qty_done if self.qty_done is not None else 0),
                str(self.current_work_center_id or ""),
                timestamp.isoformat(),
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def critical_fields_changed(self) -> bool:
        """True kalau `state`/`qty_done`/`current_work_center` berubah sejak dibaca."""
        loaded = getattr(self, "_loaded_critical", None)
        if loaded is None:  # instance baru (belum pernah dibaca dari DB)
            return True
        return any(
            getattr(self, field) != loaded.get(field) for field in self.CRITICAL_FIELDS
        )

    def save(self, *args, **kwargs):
        """Isi/perbarui `version` lalu simpan.

        Aturan:
          * `version` kosong (record baru) -> generate;
          * `state`/`qty_done`/`current_work_center` berubah -> regenerate;
          * tidak ada perubahan state kritis -> version lama dipertahankan
            (token tetap valid selama state kritis tidak berubah).

        Fase C: kalau pemanggil memakai `update_fields` yang **memuat** field
        kritis, `version` otomatis ikut disimpan. Tanpa itu, baris DB bisa punya
        state kritis baru tapi `version` lama — optimistic lock frontend jadi
        tidak pernah mendeteksi perubahan (`X-Base-Version` tetap dianggap cocok).
        """
        timestamp = timezone.now()
        if not self.version or self.critical_fields_changed():
            self.version = self.compute_version(timestamp)
            self._ensure_version_in_update_fields(kwargs)

        super().save(*args, **kwargs)
        # Setelah tersimpan, resync penanda agar save() berikutnya akurat.
        self._loaded_critical = {
            field: getattr(self, field) for field in self.CRITICAL_FIELDS
        }

    def _ensure_version_in_update_fields(self, kwargs: dict) -> None:
        """Tambahkan `version` ke `update_fields` bila field kritis ikut disimpan.

        Aman di dua sisi:

          * field kritis TIDAK disimpan (mis. `save(update_fields=["qty"])`) →
            `version` tidak disentuh, jadi baris DB tetap konsisten;
          * `version` sudah ada di `update_fields` → tidak diapa-apakan.
        """
        update_fields = kwargs.get("update_fields")
        if update_fields is None:
            return

        fields = set(update_fields)
        persists_critical = any(field in fields for field in self.CRITICAL_FIELDS)
        if persists_critical and "version" not in fields:
            kwargs["update_fields"] = [*update_fields, "version"]
