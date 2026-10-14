from django.apps import AppConfig


class IdempotencyConfig(AppConfig):
    """App `core.idempotency` — idempotency key untuk endpoint aksi (kontrak §5.1).

    Frontend mengirim header `Idempotency-Key` di setiap POST aksi; backend
    menyimpan response pertama untuk key itu. Request ulang dengan key sama
    mengembalikan response pertama lagi + penanda `duplicate-ignored`, sehingga
    aksi tidak dieksekusi dua kali (mis. operator menekan tombol dua kali).

    `label` ditulis eksplisit (`idempotency`) karena label inilah yang dipakai
    `makemigrations idempotency` dan nama tabel (`idempotency_idempotencyrecord`).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "core.idempotency"
    label = "idempotency"
    verbose_name = "Core Idempotency"
