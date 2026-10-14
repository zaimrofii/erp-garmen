"""Model app `core.device_profile` — profil perangkat & binding (generik).

UI multi-device (HP operator / kios / scanner USB) perlu tahu "perangkat ini
sebaiknya tampil bagaimana". Semua jawabannya = data di DB:

  * ``DeviceProfile`` — profil + `config` JSON (mis. {"input_mode": "scanner"});
  * ``DeviceBinding`` — perangkat yang sudah pernah dipakai, diikat ke work
    center (`wc_code`) dan sebuah cookie token, opsional ke user.

Resolusi profil ada di `core/device_profile/services.py`
(`DeviceProfileResolver`, 4 level + fallback) dan endpoint core-nya
`GET /api/v1/devices/me` di `core/device_profile/api.py`.

Catatan: ini profil perangkat **generik**. Model `DeviceProfile` domain garmen
(per work center) baru dibuat pada Fase 2.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class DeviceProfile(models.Model):
    """Profil perangkat (mis. SCANNER_USB, KIOS, OPERATOR_HP)."""

    code = models.SlugField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    is_active = models.BooleanField("aktif", default=True)
    config = models.JSONField(
        "konfigurasi",
        default=dict,
        blank=True,
        help_text=(
            "Preferensi UI/device, mis. "
            '{"input_mode": "scanner", "queue_poll_ms": 5000}.'
        ),
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Device Profile"
        verbose_name_plural = "Device Profiles"
        ordering = ("code",)

    def __str__(self) -> str:
        return self.code


class DeviceBinding(models.Model):
    """Perangkat fisik yang di-bind ke sebuah work center (lewat cookie token)."""

    wc_code = models.CharField("kode work center", max_length=64, db_index=True)
    device_profile = models.ForeignKey(
        DeviceProfile,
        on_delete=models.PROTECT,
        related_name="bindings",
        verbose_name="profil perangkat",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_bindings",
        verbose_name="user",
    )
    # `unique=True` sudah membuat index di DB — tidak ditambah `db_index=True`
    # agar tidak ada index dobel untuk kolom yang sama.
    cookie_token = models.CharField("cookie token", max_length=64, unique=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    last_seen_at = models.DateTimeField("terakhir dilihat", null=True, blank=True)

    class Meta:
        verbose_name = "Device Binding"
        verbose_name_plural = "Device Bindings"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.wc_code}@{self.device_profile.code}"

