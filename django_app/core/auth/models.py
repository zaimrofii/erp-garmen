"""Model auth & role — app `core.auth` (app_label = `core_auth`).

Prinsip blueprint: **role = data di DB, bukan enum di kode**. Karena itu kolom
`Role.code` sengaja TIDAK memakai `choices=` — role baru (mis. "SABLON_LEAD")
tetap bisa ditambah lewat admin tanpa mengubah kode. `Role.Code` (TextChoices)
dipakai hanya sebagai template nilai untuk seeding awal di
`migrations/0002_seed_default_roles.py`.

Model `User` memakai `AbstractUser` apa adanya: `username`, `email`, dan
`password` TIDAK di-override, hanya ditambah relasi ke `Role` dan kolom
`operator_code` (F6.1 — login cepat HP operator, lihat di bawah).

F6.1 (auth hybrid) — `operator_code`:
  * **Hanya** role OPERATOR/QC yang boleh punya kode (invariant dijaga di
    `User._normalize_operator_code()`: kode dilepas kalau role berubah keluar
    dari dua role itu);
  * kode di-generate **otomatis** saat user dibuat (4 digit; 6 digit kalau
    seluruh 9000 kode 4 digit sudah terpakai);
  * `unique=True` + `null=True` → user tanpa kode tetap boleh banyak (Postgres
    mengizinkan banyak NULL pada kolom unique), dan tabrakan kode ditolak DB;
  * backfill user lama: `manage.py generate_operator_codes`.
"""

from __future__ import annotations

import logging
import secrets

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import IntegrityError, models, transaction

logger = logging.getLogger(__name__)

#: Role yang **boleh** punya `operator_code` (UPPERCASE — hasil migrasi `0002`).
#: Role penyelia/admin tidak perlu kode: mereka login pakai username+password.
OPERATOR_CODE_ROLES = ("OPERATOR", "QC")

#: Panjang kode operator: 4 digit (normal) atau 6 digit (kalau 4 digit penuh).
OPERATOR_CODE_DIGITS = (4, 6)

#: Validator format kode (dipakai `full_clean()`/admin; `save()` tidak memaksa
#: lewat validator supaya jalur cepat tidak berubah).
OPERATOR_CODE_VALIDATOR = RegexValidator(
    r"^\d{4}$|^\d{6}$",
    "Kode operator harus 4 atau 6 digit angka.",
)


def random_operator_code(digits: int = 4) -> str:
    """Kode acak `digits` digit (``secrets`` — bukan ``random`` untuk kode yang
    diucapkan operator; nilainya tidak rahasia tetapi tetap jangan mudah ditebak).
    """
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def generate_unique_operator_code(
    exclude_pk: int | None = None,
    *,
    digits: tuple[int, ...] = OPERATOR_CODE_DIGITS,
    attempts_per_length: int = 30,
) -> str:
    """Kode operator unik (belum dipakai user lain).

    Strategi: coba ``attempts_per_length`` kode acak untuk tiap panjang digit
    yang diizinkan (4 lalu 6). Kalau semuanya bentrok, telusuri ruang 4 digit
    berurutan sebagai fallback **deterministik** supaya user baru tidak pernah
    gagal dibuat hanya karena kehabisan undian acak.
    """
    for length in digits:
        for _ in range(attempts_per_length):
            candidate = random_operator_code(length)
            if not User.objects.filter(operator_code=candidate).exclude(pk=exclude_pk).exists():
                return candidate

    for number in range(10**OPERATOR_CODE_DIGITS[0]):
        candidate = f"{number:0{OPERATOR_CODE_DIGITS[0]}d}"
        if not User.objects.filter(operator_code=candidate).exclude(pk=exclude_pk).exists():
            return candidate

    raise ValidationError(
        "Tidak ada kode operator yang tersedia — tambah panjang kode di "
        "`OPERATOR_CODE_DIGITS` sebelum menambah user operator lagi."
    )


class Role(models.Model):
    """Role pengguna (operator, QC, supervisor, admin, owner, ...)."""

    class Code(models.TextChoices):
        """Kode role bawaan — template seeding, bukan pembatas nilai kolom."""

        OPERATOR = "OPERATOR", "Operator"
        QC = "QC", "QC"
        SUPERVISOR = "SUPERVISOR", "Supervisor"
        ADMIN = "ADMIN", "Admin"
        OWNER = "OWNER", "Owner"
        # H1.1 — role purchasing (input master & dokumen pembelian di MES).
        PURCHASING = "PURCHASING", "Purchasing"

    code = models.CharField("kode", max_length=32, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    is_active = models.BooleanField("aktif", default=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Role"
        verbose_name_plural = "Roles"
        ordering = ("code",)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class RolePermission(models.Model):
    """Baris **profil** izin role × resource × action (H5.4) — **overlay**, bukan enforcement.

    **Keputusan STEP 0 (Opsi A′ — "matrix tersimpan + viewer efektif")**:

    * baris di sini menyimpan **profil izin** yang bisa diedit dari UI Settings
      (ber-jejak ledger ``SKIPPED`` + ``AuditLog``);
    * ⚠️ **enforcement TIDAK membaca tabel ini** — penjaga izin yang benar-benar
      berlaku tetap **hardcoded di kode**: ``_require_admin`` (27 pemakaian di
      ``apps_industry/.../settings/views.py``), ``OPERATOR_CODE_ROLES`` (F6.1), dan
      16 daftar role di frontend (``frontend_app_v2/src/App.tsx``). Kolom
      ``allowed`` di sini = **profil/niat**, sedangkan aturan yang berlaku sekarang
      dilaporkan endpoint sebagai ``effective`` (snapshot ``ROLE_CAPABILITIES``);
    * sprint **enforcement** terpisah (belum dijadwalkan) yang akan menghubungkan
      matrix ini ke guard — sampai itu terjadi, UI menampilkan banner jujur
      "profil ≠ enforcement".

    ``unique_together (role, resource, action)`` ⇒ satu sel matrix = satu baris;
    menyimpan ulang sel yang sama tidak menduplikasi baris (idempotent).
    """

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
        verbose_name="role",
        help_text="Role yang diprofilkan (hapus role ⇒ profil izinnya ikut terhapus).",
    )
    resource = models.CharField(
        "resource",
        max_length=64,
        db_index=True,
        help_text="Nama resource MES (mis. 'bundles', 'settings') — lihat PERMISSION_RESOURCES.",
    )
    action = models.CharField(
        "aksi",
        max_length=32,
        help_text="Aksi CRUD ('read'|'create'|'update'|'delete') — lihat PERMISSION_ACTIONS.",
    )
    allowed = models.BooleanField(
        "diizinkan",
        default=False,
        help_text="Profil izin (belum dipakai enforcement — lihat docstring model).",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Role Permission"
        verbose_name_plural = "Role Permissions"
        ordering = ("role_id", "resource", "action")
        constraints = (
            models.UniqueConstraint(
                fields=("role", "resource", "action"),
                name="core_auth_role_resource_action_uniq",
            ),
        )

    def __str__(self) -> str:
        return f"{self.role.code}:{self.resource}.{self.action}={self.allowed}"


class User(AbstractUser):
    """User custom (`AUTH_USER_MODEL`) = AbstractUser + FK `role` + `operator_code`.

    `role` nullable + `on_delete=PROTECT`: user teknis (mis. akun integrasi)
    boleh belum punya role, tapi Role yang sudah dipakai tidak bisa dihapus
    supaya jejak audit tetap utuh.

    `operator_code` (F6.1): kode 4/6 digit untuk login cepat dari HP pribadi
    operator (`POST /api/v1/auth/login-operator/`) — operator tidak perlu
    mengetik username+password di lantai produksi. Kode hanya dimiliki role
    OPERATOR/QC dan **di-generate otomatis** (lihat `_normalize_operator_code`).
    """

    #: Batas percobaan ulang saat tabrakan kode (race antara cek & insert).
    MAX_OPERATOR_CODE_ATTEMPTS = 3

    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name="role",
    )
    operator_code = models.CharField(
        "kode operator",
        max_length=6,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        validators=[OPERATOR_CODE_VALIDATOR],
        help_text=(
            "Kode login cepat HP operator (4 atau 6 digit). Otomatis diisi untuk "
            "role OPERATOR/QC; dikosongkan untuk role lain."
        ),
    )

    class Meta:
        # Sengaja TIDAK mewarisi `AbstractUser.Meta` (Meta itu abstract=True);
        # hanya perlu nama tampilan, sisanya ikut AbstractUser.
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self) -> str:
        return self.get_username()

    # ------------------------------------------------- operator code (F6.1)
    @property
    def has_operator_role(self) -> bool:
        """True kalau user ber-role OPERATOR/QC (pemilik sah `operator_code`)."""
        if self.role_id is None:
            return False
        role = self.role  # FK: satu query, lalu di-cache di `fields_cache`
        return str(role.code or "").strip().upper() in OPERATOR_CODE_ROLES

    def _normalize_operator_code(self) -> bool:
        """Selaraskan `operator_code` dengan role; ``True`` kalau nilainya berubah.

        * role OPERATOR/QC tanpa kode → kode baru di-generate;
        * role lain yang masih memegang kode → kode dilepas (invariant F6.1);
        * ``self._operator_code_generated`` menandai kode yang dibuat **di call
          ini** (dipakai `save()` untuk retry saat tabrakan unik).
        """
        self._operator_code_generated = False

        if self.has_operator_role:
            if not self.operator_code:
                self.operator_code = generate_unique_operator_code(exclude_pk=self.pk)
                self._operator_code_generated = True
                return True
            return False

        if self.operator_code:
            logger.info(
                "user '%s': operator_code dilepas karena role bukan OPERATOR/QC.",
                self.get_username(),
            )
            self.operator_code = None
            return True
        return False

    def clean(self) -> None:
        """Validasi model (dipakai admin/form): kode hanya untuk OPERATOR/QC."""
        super().clean()
        if self.operator_code and not self.has_operator_role:
            raise ValidationError(
                {
                    "operator_code": (
                        "Kode operator hanya boleh dimiliki user dengan role "
                        f"{' atau '.join(OPERATOR_CODE_ROLES)}."
                    )
                }
            )

    def save(self, *args, **kwargs):
        """`Model.save` + sinkronisasi `operator_code` (F6.1).

        Kode yang di-generate di call ini disimpan dengan retry singkat: cek
        ketersediaan kode dan `INSERT` tidak atomik, jadi race antar admin bisa
        menghasilkan `IntegrityError` — di situ kode diundi ulang, bukan
        digagalkan. `update_fields` ikut disesuaikan supaya perubahan kode yang
        eksplisit tidak diam-diam hilang (mis. `save(update_fields=[...])`).
        """
        changed = self._normalize_operator_code()
        update_fields = kwargs.get("update_fields")
        if changed and update_fields is not None and "operator_code" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "operator_code"]

        if not self._operator_code_generated:
            return super().save(*args, **kwargs)

        for attempt in range(1, self.MAX_OPERATOR_CODE_ATTEMPTS + 1):
            try:
                # Savepoint: setelah IntegrityError transaksi luar tetap sehat
                # (Django TestCase membungkus tiap test dalam transaksi).
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if attempt == self.MAX_OPERATOR_CODE_ATTEMPTS:
                    raise
                logger.warning(
                    "user '%s': kode operator '%s' bentrok, diundi ulang (%s/%s).",
                    self.get_username(),
                    self.operator_code,
                    attempt,
                    self.MAX_OPERATOR_CODE_ATTEMPTS,
                )
                self.operator_code = generate_unique_operator_code(exclude_pk=self.pk)

        return super().save(*args, **kwargs)  # pragma: no cover - tidak tercapai
