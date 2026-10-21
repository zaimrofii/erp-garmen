"""Test integrasi unggah gambar master (K5.2).

Cakupan:
  * ``POST|DELETE /api/v1/master/products/<id>/image/``;
  * ``POST|DELETE /api/v1/master/partners/<id>/image/``;
  * validasi format (jpg/jpeg/png/webp) + ukuran maks 5 MB + isi berkas (Pillow);
  * thumbnail 256px ``<nama>_thumb.<ext>`` (best-effort, tidak menggagalkan unggah);
  * izin ADMIN/OWNER (role OPERATOR & anonim → 403), id tidak ada → 404;
  * berkas benar-benar dibuat/dihapus di ``MEDIA_ROOT`` (unggah ulang = ganti);
  * jejak ``AuditLog`` ``master.upload_image``/``master.delete_image``;
  * ``image_file_url``/``image_display_url``/``image_thumbnail_url`` muncul di
    baris list/detail produk & partner (unggahan menang atas ``image_url``).

``MEDIA_ROOT`` di-override ke direktori sementara supaya berkas test tidak
mengotori ``media/`` repo (dibersihkan lagi di ``tearDownModule``).
"""

from __future__ import annotations

import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image as PILImage
from rest_framework.test import APIClient

from core.audit.models import AuditLog
from core.auth.models import Role, User
from master.image_services import MAX_IMAGE_BYTES, thumbnail_name
from master.models import Partner, Product

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix="mes-k52-media-")

PRODUCTS_URL = "/api/v1/master/products/"
PARTNERS_URL = "/api/v1/master/partners/"
#: Kunci kontrak response unggah/hapus gambar (K5.2).
PAYLOAD_KEYS = {"id", "image_file_url", "image_display_url", "image_thumbnail_url", "message"}
#: Pola folder unggahan: ``products/YYYY/MM/`` (dari ``upload_to``).
FOLDER_PATTERN = re.compile(r"^products/\d{4}/\d{2}/")
PARTNER_FOLDER_PATTERN = re.compile(r"^partners/\d{4}/\d{2}/")


def image_upload(name: str = "kaos.jpg", *, fmt: str = "JPEG") -> SimpleUploadedFile:
    """Berkas gambar asli (dibuat Pillow) dengan nama + format sesuai permintaan."""
    buffer = BytesIO()
    PILImage.new("RGB", (900, 700), (200, 30, 30)).save(buffer, format=fmt)
    content_type = "image/jpeg" if fmt == "JPEG" else f"image/{fmt.lower()}"

    return SimpleUploadedFile(name, buffer.getvalue(), content_type=content_type)


def tearDownModule() -> None:
    """Bersihkan direktori media sementara setelah seluruh test modul selesai."""
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class MasterImageUploadTests(TestCase):
    """Unggah/hapus gambar produk & partner: sukses, validasi, izin, audit."""

    @classmethod
    def setUpTestData(cls):
        """2 user: admin (ADMIN) dan operator (OPERATOR) untuk uji izin."""
        cls.admin = User.objects.create_user(
            username="admin-image",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.ADMIN),
        )
        cls.operator = User.objects.create_user(
            username="op-image",
            password="rahasia123",  # noqa: S106 - kredensial test
            role=Role.objects.get(code=Role.Code.OPERATOR),
        )

    def setUp(self):
        """Klien admin (utama), klien operator, 1 produk + 1 partner."""
        self.api = APIClient()
        self.api.force_authenticate(self.admin)
        self.operator_api = APIClient()
        self.operator_api.force_authenticate(self.operator)
        self.product = Product.objects.create(code="IMG-001", name="Kaos Gambar")
        self.partner = Partner.objects.create(code="PT-IMG", name="PT Gambar")

    # ------------------------------------------------------------------ helper
    def product_image_url(self, pk: int | None = None) -> str:
        """URL endpoint gambar produk (default: produk di ``setUp``)."""
        return f"{PRODUCTS_URL}{self.product.pk if pk is None else pk}/image/"

    def partner_image_url(self, pk: int | None = None) -> str:
        """URL endpoint gambar partner (default: partner di ``setUp``)."""
        return f"{PARTNERS_URL}{self.partner.pk if pk is None else pk}/image/"

    def upload(self, url: str, file: SimpleUploadedFile, client: APIClient | None = None):
        """POST multipart field ``image`` (default klien admin)."""
        return (client or self.api).post(url, {"image": file}, format="multipart")

    def disk_path(self, name: str) -> Path:
        """Path absolut berkas di ``MEDIA_ROOT`` test."""
        return Path(settings.MEDIA_ROOT) / name

    def audit_rows(self, *, action: str, resource: str, resource_id: int):
        """QuerySet ``AuditLog`` untuk aksi gambar tertentu."""
        return AuditLog.objects.filter(
            action=action, resource=resource, resource_id=str(resource_id)
        )

    # ------------------------------------------- produk: unggah sukses (jpg/png/webp)
    def test_upload_jpg_produk_membuat_berkas_dan_thumbnail(self):
        """JPG valid → 200 + berkas asli & thumbnail 256px ada di disk."""
        response = self.upload(self.product_image_url(), image_upload("kaos.jpg"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), PAYLOAD_KEYS)
        self.assertEqual(body["id"], self.product.pk)
        self.assertEqual(body["message"], "Gambar produk berhasil diunggah.")
        self.assertNotIn("warning", body)

        self.product.refresh_from_db()
        name = self.product.image_file.name
        self.assertTrue(FOLDER_PATTERN.match(name), name)
        self.assertTrue(self.disk_path(name).exists())
        self.assertTrue(self.disk_path(thumbnail_name(name)).exists())
        self.assertEqual(body["image_file_url"], f"{settings.MEDIA_URL}{name}")

    def test_upload_png_produk(self):
        """PNG valid → 200 + ``image_display_url`` menunjuk berkas unggahan."""
        response = self.upload(self.product_image_url(), image_upload("kaos.png", fmt="PNG"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.product.refresh_from_db()
        self.assertIn(".png", self.product.image_file.name)
        self.assertEqual(body["image_display_url"], body["image_file_url"])

    def test_upload_webp_produk(self):
        """WEBP valid → 200 (format modern diterima)."""
        response = self.upload(self.product_image_url(), image_upload("kaos.webp", fmt="WEBP"))

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertIn(".webp", self.product.image_file.name)

    def test_thumbnail_dibatasi_256px(self):
        """Thumbnail sisi terpanjang ≤ 256px (gambar 900x700 diperkecil)."""
        self.upload(self.product_image_url(), image_upload("besar.jpg"))

        self.product.refresh_from_db()
        thumb = self.disk_path(thumbnail_name(self.product.image_file.name))
        with PILImage.open(thumb) as image:
            self.assertLessEqual(max(image.size), 256)

    def test_upload_ulang_mengganti_berkas_lama(self):
        """Unggah kedua = GANTI: berkas + thumbnail lama dihapus, nama baru dipakai."""
        self.upload(self.product_image_url(), image_upload("lama.jpg"))
        self.product.refresh_from_db()
        first_name = self.product.image_file.name

        response = self.upload(self.product_image_url(), image_upload("baru.jpg"))

        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        second_name = self.product.image_file.name
        self.assertNotEqual(first_name, second_name)
        self.assertTrue(self.disk_path(second_name).exists())
        self.assertFalse(self.disk_path(first_name).exists())
        self.assertFalse(self.disk_path(thumbnail_name(first_name)).exists())

    def test_upload_menambah_audit_log(self):
        """AuditLog action ``master.upload_image`` (metadata nama berkas + ukuran)."""
        self.upload(self.product_image_url(), image_upload("audit.jpg"))

        rows = self.audit_rows(
            action="master.upload_image", resource="master.product", resource_id=self.product.pk
        )
        self.assertEqual(rows.count(), 1)
        log = rows.first()
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.result, AuditLog.Result.OK)
        self.product.refresh_from_db()
        self.assertEqual(log.metadata["image_file"], self.product.image_file.name)
        self.assertGreater(log.metadata["size"], 0)

    # ----------------------------------------------------- produk: ekspos di baris API
    def test_detail_produk_memuat_url_gambar_unggahan(self):
        """GET detail produk → 3 field gambar; unggahan menang atas ``image_url``."""
        self.product.image_url = "https://cdn.klien.com/lama.png"
        self.product.save(update_fields=["image_url"])
        self.upload(self.product_image_url(), image_upload("detail.jpg"))

        response = self.api.get(f"{PRODUCTS_URL}{self.product.pk}/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.product.refresh_from_db()
        self.assertEqual(body["image_file_url"], f"{settings.MEDIA_URL}{self.product.image_file.name}")
        self.assertEqual(body["image_display_url"], body["image_file_url"])
        self.assertEqual(body["image_thumbnail_url"], f"{settings.MEDIA_URL}{thumbnail_name(self.product.image_file.name)}")
        self.assertEqual(body["image_url"], "https://cdn.klien.com/lama.png")

    def test_list_produk_tanpa_gambar_memakai_image_url(self):
        """Produk tanpa unggahan: 3 field gambar ``None`` + ``image_display_url`` = ``image_url``."""
        self.product.image_url = "https://cdn.klien.com/eksternal.png"
        self.product.save(update_fields=["image_url"])

        response = self.api.get(PRODUCTS_URL)

        row = next(item for item in response.json()["rows"] if item["id"] == self.product.pk)
        self.assertIsNone(row["image_file_url"])
        self.assertIsNone(row["image_thumbnail_url"])
        self.assertEqual(row["image_display_url"], "https://cdn.klien.com/eksternal.png")

    # ------------------------------------------------------------ validasi unggahan
    def test_upload_tanpa_berkas_400(self):
        """Field ``image`` tidak dikirim → 400 + pesan 'wajib dikirim'."""
        response = self.api.post(self.product_image_url(), {}, format="multipart")

        self.assertEqual(response.status_code, 400)
        self.assertIn("wajib dikirim", response.json()["detail"])
        self.product.refresh_from_db()
        self.assertFalse(self.product.image_file)

    def test_upload_ekstensi_tidak_didukung_400(self):
        """Ekstensi ``.gif`` ditolak (whitelist jpg/jpeg/png/webp)."""
        response = self.upload(self.product_image_url(), image_upload("animasi.gif", fmt="GIF"))

        self.assertEqual(response.status_code, 400)
        self.assertIn("Format tidak didukung", response.json()["detail"])

    def test_upload_berkas_bukan_gambar_400(self):
        """Ekstensi ``.jpg`` tapi isi bukan gambar → 400 dari verifikasi Pillow."""
        file = SimpleUploadedFile(
            "palsu.jpg", b"bukan gambar sama sekali", content_type="image/jpeg"
        )

        response = self.upload(self.product_image_url(), file)

        self.assertEqual(response.status_code, 400)
        self.assertIn("bukan gambar yang valid", response.json()["detail"])

    def test_upload_melebihi_5mb_400(self):
        """Berkas di atas ``MAX_IMAGE_BYTES`` (5 MB) ditolak sebelum disimpan."""
        file = SimpleUploadedFile(
            "besar.jpg", b"\xff" * (MAX_IMAGE_BYTES + 1), content_type="image/jpeg"
        )

        response = self.upload(self.product_image_url(), file)

        self.assertEqual(response.status_code, 400)
        self.assertIn("melebihi 5 MB", response.json()["detail"])
        self.product.refresh_from_db()
        self.assertFalse(self.product.image_file)

    def test_upload_berkas_kosong_400(self):
        """Berkas 0 byte ditolak ('Berkas kosong.')."""
        file = SimpleUploadedFile("kosong.jpg", b"", content_type="image/jpeg")

        response = self.upload(self.product_image_url(), file)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Berkas kosong.")

    # ---------------------------------------------------------------------- izin
    def test_upload_produk_operator_403(self):
        """Role OPERATOR tidak boleh mengunggah gambar produk (ADMIN/OWNER saja)."""
        response = self.upload(
            self.product_image_url(), image_upload("op.jpg"), self.operator_api
        )

        self.assertEqual(response.status_code, 403)

    def test_hapus_produk_operator_403(self):
        """Role OPERATOR juga tidak boleh menghapus gambar produk."""
        self.upload(self.product_image_url(), image_upload("op2.jpg"))

        response = self.operator_api.delete(self.product_image_url())

        self.assertEqual(response.status_code, 403)
        self.product.refresh_from_db()
        self.assertTrue(self.product.image_file)

    def test_upload_partner_operator_403(self):
        """Role OPERATOR tidak boleh mengunggah gambar partner."""
        response = self.operator_api.post(
            self.partner_image_url(), {"image": image_upload("op3.jpg")}, format="multipart"
        )

        self.assertEqual(response.status_code, 403)

    def test_upload_produk_tanpa_login_403(self):
        """Tanpa autentikasi → 403 (endpoint tidak publik)."""
        response = APIClient().post(
            self.product_image_url(), {"image": image_upload("anon.jpg")}, format="multipart"
        )

        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------- 404
    def test_upload_produk_tidak_ada_404(self):
        """Produk id tidak dikenal → 404 walau berkas valid."""
        response = self.upload(self.product_image_url(999_999), image_upload("hantu.jpg"))

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    def test_hapus_partner_tidak_ada_404(self):
        """Partner id tidak dikenal → 404."""
        response = self.api.delete(self.partner_image_url(999_999))

        self.assertEqual(response.status_code, 404)
        self.assertIn("tidak ditemukan", response.json()["detail"])

    # ---------------------------------------------------------------- hapus gambar
    def test_hapus_gambar_produk_menghapus_berkas(self):
        """DELETE → berkas + thumbnail hilang, field kosong, ``deleted_files`` terisi."""
        self.upload(self.product_image_url(), image_upload("hapus.jpg"))
        self.product.refresh_from_db()
        name = self.product.image_file.name
        thumb = thumbnail_name(name)

        response = self.api.delete(self.product_image_url())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["message"], "Gambar produk dihapus.")
        self.assertEqual(set(body["deleted_files"]), {name, thumb})
        self.assertIsNone(body["image_file_url"])
        self.assertIsNone(body["image_display_url"])
        self.assertIsNone(body["image_thumbnail_url"])

        self.product.refresh_from_db()
        self.assertFalse(self.product.image_file)
        self.assertFalse(self.disk_path(name).exists())
        self.assertFalse(self.disk_path(thumb).exists())

    def test_hapus_gambar_idempotent_tanpa_berkas(self):
        """DELETE saat belum ada gambar → tetap 200 + pesan 'memang belum ada'."""
        response = self.api.delete(self.product_image_url())

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["message"], "Gambar produk memang belum ada.")
        self.assertEqual(body["deleted_files"], [])

    def test_hapus_gambar_menambah_audit_log(self):
        """AuditLog action ``master.delete_image`` mencatat berkas yang dihapus."""
        self.upload(self.product_image_url(), image_upload("audit-hapus.jpg"))
        self.product.refresh_from_db()
        name = self.product.image_file.name

        self.api.delete(self.product_image_url())

        rows = self.audit_rows(
            action="master.delete_image", resource="master.product", resource_id=self.product.pk
        )
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().metadata["previous_name"], name)

    # -------------------------------------------------------------------- partner
    def test_upload_gambar_partner(self):
        """Partner: unggah → folder ``partners/`` + URL berkas di response."""
        response = self.api.post(
            self.partner_image_url(), {"image": image_upload("toko.png", fmt="PNG")}, format="multipart"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), PAYLOAD_KEYS)
        self.assertEqual(body["message"], "Gambar partner berhasil diunggah.")

        self.partner.refresh_from_db()
        name = self.partner.image_file.name
        self.assertTrue(PARTNER_FOLDER_PATTERN.match(name), name)
        self.assertEqual(body["image_file_url"], f"{settings.MEDIA_URL}{name}")
        self.assertTrue(self.disk_path(thumbnail_name(name)).exists())

    def test_hapus_gambar_partner(self):
        """Partner: DELETE menghapus berkas + mengosongkan field."""
        self.api.post(
            self.partner_image_url(), {"image": image_upload("toko.jpg")}, format="multipart"
        )
        self.partner.refresh_from_db()
        name = self.partner.image_file.name

        response = self.api.delete(self.partner_image_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Gambar partner dihapus.")
        self.partner.refresh_from_db()
        self.assertFalse(self.partner.image_file)
        self.assertFalse(self.disk_path(name).exists())

    def test_detail_partner_memuat_url_gambar(self):
        """Baris detail partner memuat 3 field gambar (kontrak K5.2)."""
        self.api.post(
            self.partner_image_url(), {"image": image_upload("toko2.jpg")}, format="multipart"
        )

        response = self.api.get(f"{PARTNERS_URL}{self.partner.pk}/")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["image_display_url"], body["image_file_url"])
        self.assertIn("image_thumbnail_url", body)
