"""Model `GarmentDeviceProfile` — extension profil device (khusus garmen).

Profil perangkat **utama** tetap di `core.device_profile.DeviceProfile`
(generik: kode, config UI, binding cookie). Model di sini hanya menambah
informasi spesifik garmen: perangkat ini dipakai di work center mana.

Relasinya OneToOne — satu profil device core hanya punya satu extension garmen.
"""

from __future__ import annotations

from django.db import models


class GarmentDeviceProfile(models.Model):
    """Extension profil device core + work center (khusus garmen)."""

    device_profile = models.OneToOneField(
        "device_profile.DeviceProfile",
        on_delete=models.CASCADE,
        related_name="garment_profile",
        verbose_name="profil device (core)",
    )
    work_center = models.ForeignKey(
        "garment.WorkCenter",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_profiles",
        verbose_name="work center",
    )
    notes = models.TextField("catatan", blank=True, default="")
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Garment Device Profile"
        verbose_name_plural = "Garment Device Profiles"
        # Nama tabel default akan jadi `garment_garmentdeviceprofile`; di-set
        # eksplisit supaya rapi dan sama dengan nama file model-nya.
        db_table = "garment_device_profile"
        ordering = ("device_profile__code",)

    def __str__(self) -> str:
        return f"{self.device_profile.code} -> {self.work_center or '-'}"
