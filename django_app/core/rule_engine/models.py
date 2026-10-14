"""Model rule engine generik: `Rule`, `RuleCondition`, `RuleAction`.

Prinsip blueprint: **semua aturan = konfigurasi, bukan kode**. Rule disimpan di
DB supaya alur/aturan berbeda antar klien cukup dikonfigurasi lewat admin.

Semantik singkat (detail di `core/rule_engine/services.py`):

  * semua `RuleCondition` milik satu Rule harus terpenuhi (**AND**). Sprint 1.2
    belum mendukung OR/grouping — kalau perlu, buat rule terpisah dengan
    `priority` berbeda;
  * `field` boleh **dotted path** ke context bersarang (mis. `bundle.qty`);
  * key yang tidak ada di context → kondisi dianggap **tidak match**
    (fail-closed), bukan exception;
  * `RuleAction` hanya **dikembalikan** engine. Eksekusinya tanggung jawab app
    domain (rule engine tidak menyentuh garmen/Odoo sama sekali).
"""

from __future__ import annotations

from django.db import models


class Rule(models.Model):
    """Satu aturan: daftar kondisi (AND) + daftar aksi yang diusulkan."""

    code = models.SlugField("kode", max_length=64, unique=True)
    name = models.CharField("nama", max_length=150)
    description = models.TextField("deskripsi", blank=True, default="")
    is_active = models.BooleanField("aktif", default=True)
    priority = models.IntegerField(
        "prioritas",
        default=0,
        help_text="Urutan evaluasi: angka KECIL dievaluasi lebih dulu.",
    )
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diubah pada", auto_now=True)

    class Meta:
        verbose_name = "Rule"
        verbose_name_plural = "Rules"
        ordering = ("priority", "code")

    def __str__(self) -> str:
        return f"{self.code} (priority={self.priority})"


class RuleCondition(models.Model):
    """Satu kondisi Rule: bandingkan `field` di context dengan `value`."""

    class Operator(models.TextChoices):
        EQ = "EQ", "sama dengan"
        NE = "NE", "tidak sama dengan"
        GT = "GT", "lebih besar"
        GTE = "GTE", "lebih besar atau sama"
        LT = "LT", "lebih kecil"
        LTE = "LTE", "lebih kecil atau sama"
        IN = "IN", "termasuk salah satu (value harus list)"
        CONTAINS = "CONTAINS", "mengandung (substring / item list)"
        REGEX = "REGEX", "cocok regex"

    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name="rule",
    )
    field = models.CharField(
        "field",
        max_length=100,
        help_text="Key di context evaluasi; boleh dotted path, mis. 'bundle.qty'.",
    )
    operator = models.CharField(
        "operator",
        max_length=16,
        choices=Operator.choices,
        default=Operator.EQ,
    )
    value = models.JSONField("nilai", null=True, blank=True)
    order = models.PositiveIntegerField("urutan", default=0)

    class Meta:
        verbose_name = "Rule Condition"
        verbose_name_plural = "Rule Conditions"
        ordering = ("rule", "order")
        constraints = [
            models.UniqueConstraint(
                fields=["rule", "order"],
                name="uniq_condition_order_per_rule",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.field} {self.operator} {self.value!r}"


class RuleAction(models.Model):
    """Aksi yang diusulkan saat Rule match (dieksekusi oleh app domain)."""

    rule = models.ForeignKey(
        Rule,
        on_delete=models.CASCADE,
        related_name="actions",
        verbose_name="rule",
    )
    action_type = models.CharField(
        "tipe aksi",
        max_length=64,
        help_text='Mis. "SET_PRIORITY", "ASSIGN_LINE", "TAG_ADD".',
    )
    params = models.JSONField("params", default=dict, blank=True)

    class Meta:
        verbose_name = "Rule Action"
        verbose_name_plural = "Rule Actions"
        # Urutan = urutan pendefinisian (tidak ada field `order` di Sprint 1.2).
        ordering = ("rule", "id")

    def __str__(self) -> str:
        return f"{self.action_type} {self.params}"
