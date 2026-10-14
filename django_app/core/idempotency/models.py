"""Model idempotency record (core, generik) — kontrak §5.1.

Satu baris = satu `Idempotency-Key` yang sudah pernah dieksekusi beserta response
pertamanya. Tabel ini append-mostly: baris dibuat saat aksi sukses pertama kali,
lalu dikembalikan apa adanya saat request ulang (replay).

`response_status` + `response_body` disimpan supaya replay bisa mengembalikan
response **identik** dengan yang pertama (bukan cuma "sukses"), sesuai kontrak
§5.1 ("Request ulang dengan key sama → 200 duplicate-ignored").
"""

from __future__ import annotations

from django.db import models


class IdempotencyRecord(models.Model):
    """Catatan request aksi yang sudah pernah dieksekusi (per Idempotency-Key)."""

    # `unique=True` sudah membuat index di PostgreSQL — tidak ditambah
    # `db_index=True` agar tidak ada index dobel untuk kolom yang sama.
    key = models.CharField(
        "kunci",
        max_length=255,
        unique=True,
        help_text="Nilai header Idempotency-Key (string apa pun, tidak divalidasi UUID).",
    )
    resource = models.CharField("resource", max_length=64)
    resource_id = models.CharField("id resource", max_length=64)
    action = models.CharField("aksi", max_length=64)
    request_hash = models.CharField(
        "hash request",
        max_length=64,
        help_text=(
            "SHA-256 dari method+resource+id+action+body; kalau hash beda, key "
            "dianggap dipakai untuk request lain."
        ),
    )
    response_status = models.PositiveSmallIntegerField("status respons", default=200)
    response_body = models.JSONField("body respons", default=dict, blank=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    expires_at = models.DateTimeField(
        "kedaluwarsa",
        null=True,
        blank=True,
        help_text="Setelah lewat waktu ini record boleh dibersihkan (Celery beat).",
    )

    class Meta:
        verbose_name = "Idempotency Record"
        verbose_name_plural = "Idempotency Records"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.key} -> {self.resource}#{self.resource_id}:{self.action}"
