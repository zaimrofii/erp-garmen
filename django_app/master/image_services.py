"""Service gambar master (K5.2) — validasi, simpan, thumbnail, hapus.

Dipakai endpoint `POST|DELETE /api/v1/master/<resource>/<id>/image/`. Modul ini
TIDAK mengimpor model apa pun (cukup duck-typing `instance.image_file`) supaya
`master/models.py` boleh memakai `thumbnail_name()` tanpa impor melingkar.

Aturan unggahan (keputusan K5.2):
  * format whitelist = JPEG, PNG, WEBP — dicek lewat **Pillow** (isi berkas),
    bukan sekadar ekstensi;
  * maks 5 MB (`MAX_IMAGE_BYTES`) — cek eksplisit di sini; setting
    `FILE_UPLOAD_MAX_MEMORY_SIZE`/`DATA_UPLOAD_MAX_MEMORY_SIZE` hanya mengatur
    kapan body dialirkan ke disk / ditolak Django;
  * thumbnail 256px `<nama>_thumb.<ext>` dibuat **best-effort**: kegagalan thumbnail
    tidak boleh menggagalkan unggahan (dilaporkan sebagai `warning`).
"""

from __future__ import annotations

import logging
import pathlib
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, UnidentifiedImageError

from core.audit.models import AuditLog
from core.audit.services import AuditLogger

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_DELETE_IMAGE",
    "ACTION_UPLOAD_IMAGE",
    "ALLOWED_EXTENSIONS",
    "ALLOWED_FORMATS",
    "MAX_IMAGE_BYTES",
    "THUMBNAIL_SIZE",
    "delete_image",
    "image_payload",
    "save_image",
    "thumbnail_name",
    "validate_image",
)

#: Format Pillow yang diterima (brief K5.2).
ALLOWED_FORMATS: tuple[str, ...] = ("JPEG", "PNG", "WEBP")
#: Ekstensi yang cocok dengan `ALLOWED_FORMATS` (pesan error lebih ramah).
ALLOWED_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
#: Batas ukuran berkas (5 MB) — selaras `FILE_UPLOAD_MAX_MEMORY_SIZE`.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
#: Ukuran sisi terpanjang thumbnail.
THUMBNAIL_SIZE = (256, 256)
#: Sufiks nama berkas thumbnail.
THUMBNAIL_SUFFIX = "_thumb"
#: Aksi audit (K5.2) — konsisten pola `master.create`/`master.update`/`master.delete`.
ACTION_UPLOAD_IMAGE = "master.upload_image"
#: Aksi audit saat gambar dihapus.
ACTION_DELETE_IMAGE = "master.delete_image"


def thumbnail_name(name: str) -> str:
    """PURE — `products/2026/10/a.jpg` → `products/2026/10/a_thumb.jpg`."""
    path = pathlib.PurePosixPath(str(name or ""))
    if not path.name:
        return str(name or "")

    return str(path.with_name(f"{path.stem}{THUMBNAIL_SUFFIX}{path.suffix}"))


def validate_image(file) -> tuple[bool, str | None]:
    """Cek ekstensi, ukuran, dan ISI berkas (Pillow). Return `(ok, pesan_error)`."""
    if file is None:
        return False, "Berkas 'image' wajib dikirim."

    name = str(getattr(file, "name", "") or "")
    if pathlib.PurePosixPath(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return False, "Format tidak didukung. Gunakan " + ", ".join(ALLOWED_EXTENSIONS) + "."

    size = int(getattr(file, "size", 0) or 0)
    if size <= 0:
        return False, "Berkas kosong."
    if size > MAX_IMAGE_BYTES:
        return False, f"Ukuran berkas melebihi {MAX_IMAGE_BYTES // (1024 * 1024)} MB."

    try:
        file.seek(0)
        with Image.open(file) as probe:
            probe.verify()
        file.seek(0)
        with Image.open(file) as probe:
            image_format = str(probe.format or "").upper()
        file.seek(0)
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "Berkas bukan gambar yang valid."

    if image_format not in ALLOWED_FORMATS:
        return False, f"Format {image_format or '?'} tidak didukung."

    return True, None


def _thumbnail_bytes(file) -> ContentFile | None:
    """Bytes thumbnail 256px memakai format asli (fallback JPEG); `None` kalau gagal."""
    buffer = BytesIO()
    try:
        file.seek(0)
        with Image.open(file) as image:
            image.thumbnail(THUMBNAIL_SIZE)
            image_format = str(image.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                image_format = "JPEG"
            if image_format == "JPEG" and image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            image.save(buffer, format=image_format)
        file.seek(0)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.warning("gagal membuat bytes thumbnail: %s", exc)
        return None

    return ContentFile(buffer.getvalue())


def _delete_storage_file(name: str) -> bool:
    """Hapus satu berkas di storage (best-effort); `True` kalau benar-benar hilang."""
    if not name:
        return False
    try:
        if default_storage.exists(name):
            default_storage.delete(name)
            return True
    except OSError as exc:
        logger.warning("hapus berkas %s gagal: %s", name, exc)

    return False


def _save_thumbnail(instance) -> str | None:
    """Tulis thumbnail ke storage (best-effort). Return pesan `warning` atau `None`."""
    file = instance.image_file
    if not file:
        return "Tidak ada berkas untuk dibuatkan thumbnail."

    name = thumbnail_name(file.name)
    try:
        file.open("rb")
        content = _thumbnail_bytes(file)
        file.close()
        if content is None:
            return "Thumbnail gagal dibuat (gambar tidak bisa diproses)."
        default_storage.delete(name)
        default_storage.save(name, content)
    except Exception as exc:  # noqa: BLE001 - thumbnail TIDAK boleh menggagalkan upload
        logger.warning("thumbnail %s gagal: %s", name, exc)
        return "Thumbnail gagal dibuat."

    return None


def save_image(
    instance, file, *, folder: str, resource: str, request=None
) -> tuple[object, str | None]:
    """Simpan `file` ke `instance.image_file` + thumbnail. Return `(instance, warning)`.

    `folder` (`products`/`partners`) hanya untuk log — lokasi berkas ditentukan
    `upload_to` field (`<folder>/%Y/%m/`). `resource` (`master.product`/
    `master.partner`) untuk `AuditLog`. Raise `ValidationError` kalau tidak valid.
    """
    ok, error = validate_image(file)
    if not ok:
        raise ValidationError(error)

    previous_name = instance.image_file.name if instance.image_file else None

    instance.image_file.save(str(getattr(file, "name", "image")), file, save=True)
    logger.info("gambar %s#%s disimpan: %s", folder, instance.pk, instance.image_file.name)

    # Unggah ulang = GANTI: berkas lama (+ thumbnail lama) dibersihkan supaya
    # `media/` tidak menumpuk. Kegagalan hapus tidak menggagalkan unggahan baru.
    replaced = None
    if previous_name and previous_name != instance.image_file.name:
        _delete_storage_file(previous_name)
        _delete_storage_file(thumbnail_name(previous_name))
        replaced = previous_name

    warning = _save_thumbnail(instance)
    _audit(
        instance,
        resource=resource,
        action=ACTION_UPLOAD_IMAGE,
        request=request,
        metadata={
            "image_file": instance.image_file.name,
            "size": int(getattr(file, "size", 0) or 0),
            "content_type": str(getattr(file, "content_type", "") or ""),
            "replaced_file": replaced,
            "thumbnail_warning": warning,
        },
    )

    return instance, warning


def delete_image(instance, *, resource: str, request=None) -> list[str]:
    """Hapus berkas fisik (asli + thumbnail) lalu kosongkan field. Return nama terhapus."""
    file = instance.image_file
    if not file:
        return []

    names = [file.name, thumbnail_name(file.name)]
    instance.image_file = None
    instance.save(update_fields=["image_file"])

    deleted: list[str] = []
    for name in names:
        if _delete_storage_file(name):
            deleted.append(name)

    _audit(
        instance,
        resource=resource,
        action=ACTION_DELETE_IMAGE,
        request=request,
        metadata={"previous_name": names[0], "deleted_files": deleted},
    )

    return deleted


def image_payload(instance, *, message: str) -> dict:
    """Bentuk response kontrak K5.2 (`id`, URL berkas/tampilan/thumbnail, `message`)."""
    return {
        "id": instance.pk,
        "image_file_url": instance.image_file.url if instance.image_file else None,
        "image_display_url": instance.image_display_url,
        "image_thumbnail_url": instance.image_thumbnail_url,
        "message": message,
    }


def _audit(instance, *, resource: str, action: str, request, metadata: dict) -> None:
    """Tulis `AuditLog` — best-effort (audit tidak boleh menggagalkan unggahan)."""
    try:
        AuditLogger().log(
            user=None,
            action=action,
            resource=resource,
            resource_id=instance.pk,
            request=request,
            payload={"image_file": instance.image_file.name if instance.image_file else None},
            result=AuditLog.Result.OK,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001 - audit best-effort
        logger.exception("gagal menulis audit %s (%s#%s).", action, resource, instance.pk)
