"""Test endpoint auth hybrid (F6.1) — session, kode operator, device cookie.

Cakupan kontrak:

  ================================================ =========================
  Route                                            Bukti yang dijaga
  ================================================ =========================
  ``POST /api/v1/auth/login/``                     session + 401 + 429 (5/menit)
  ``POST /api/v1/auth/login-operator/``            kode 4/6 digit + 429 (10/menit)
  ``POST /api/v1/auth/logout/``                    session dibuang + 401 anonim
  ``GET  /api/v1/auth/me/``                        401 anonim, sesi & device token
  ``POST /api/v1/auth/change-password/``           hash berubah, sesi tetap hidup
  ``POST /api/v1/auth/reset-password/<id>/``       admin 200, non-admin 403
  ================================================ =========================

Plus perilaku model/migrasi `User.operator_code` (auto-generate, unik, hanya
OPERATOR/QC, retry saat tabrakan) dan perintah `generate_operator_codes`.

Catatan teknis:

  * limiter auth memakai Django cache (LocMem di mode test) → `cache.clear()`
    di `setUp` supaya hitungan 429 tidak bocor antar test;
  * rate limit diuji dengan **angka produksi** (5 & 10 per menit) karena limiter
    ini tidak ikut dilonggarkan mode test (berbeda dari throttle DRF — lihat
    docstring `core/auth/ratelimit.py`).

Jalankan (di dalam container):

    docker compose exec django python -m pytest tests/integration/test_auth_api.py -q
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from core.auth.models import Role, User
from core.device_profile.models import DeviceBinding, DeviceProfile
from core.device_profile.services import DEVICE_COOKIE_NAME

LOGIN_URL = "/api/v1/auth/login/"
LOGIN_OPERATOR_URL = "/api/v1/auth/login-operator/"
LOGOUT_URL = "/api/v1/auth/logout/"
ME_URL = "/api/v1/auth/me/"
CHANGE_PASSWORD_URL = "/api/v1/auth/change-password/"

PASSWORD = "rahasia123"
NEW_PASSWORD = "rahasia456"

#: Field balasan E1 (`role_code` = `Role.code`, bukan objek role).
SESSION_USER_KEYS = {
    "id",
    "username",
    "email",
    "full_name",
    "role_code",
    "is_superuser",
    "is_staff",
}


def reset_password_url(user_id: int) -> str:
    """URL E6 (admin reset password user lain)."""
    return f"/api/v1/auth/reset-password/{user_id}/"


class AuthTestBase(TestCase):
    """Role bawaan + user uji yang dipakai seluruh test auth."""

    @classmethod
    def setUpTestData(cls):
        # Role bawaan sudah di-seed migrasi `core_auth.0002` → ambil, bukan create.
        cls.role_admin = Role.objects.get(code=Role.Code.ADMIN)
        cls.role_operator = Role.objects.get(code=Role.Code.OPERATOR)
        cls.role_qc = Role.objects.get(code=Role.Code.QC)
        cls.role_supervisor = Role.objects.get(code=Role.Code.SUPERVISOR)

        cls.admin = User.objects.create_user(
            username="admin1",
            email="admin1@klien.com",
            password=PASSWORD,
            role=cls.role_admin,
        )
        # `operator_code` terisi otomatis oleh `User.save()` (F6.1).
        cls.operator = User.objects.create_user(
            username="operator1",
            email="op1@klien.com",
            password=PASSWORD,
            first_name="Operator",
            last_name="Satu",
            role=cls.role_operator,
        )
        cls.supervisor = User.objects.create_user(
            username="spv1",
            email="spv1@klien.com",
            password=PASSWORD,
            role=cls.role_supervisor,
        )
        cls.inactive = User.objects.create_user(
            username="bekas",
            email="bekas@klien.com",
            password=PASSWORD,
            role=cls.role_operator,
            is_active=False,
        )

    def setUp(self):
        """Klien bersih + cache limiter dikosongkan (LocMem di mode test)."""
        cache.clear()
        self.addCleanup(cache.clear)
        self.client = APIClient()

    def login(self, username: str = "admin1", password: str = PASSWORD):
        """POST E1 dengan kredensial default."""
        return self.client.post(
            LOGIN_URL, {"username": username, "password": password}, format="json"
        )


class AuthLoginTests(AuthTestBase):
    """E1 — `POST /api/v1/auth/login/`."""

    def test_login_valid_200_dan_session_cookie(self):
        """Kredensial benar → 200 + data user + sesi tersimpan."""
        response = self.login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), SESSION_USER_KEYS)
        self.assertEqual(body["username"], "admin1")
        self.assertEqual(body["role_code"], "ADMIN")
        self.assertEqual(body["full_name"], "")

        # Sesi benar-benar tersimpan (bukan hanya cookie kosong) …
        self.assertEqual(str(self.client.session["_auth_user_id"]), str(self.admin.pk))
        # … dan `last_login` ikut diperbarui (sinyal user_logged_in).
        self.admin.refresh_from_db()
        self.assertIsNotNone(self.admin.last_login)

    def test_login_set_cookie_csrf(self):
        """Cookie `csrftoken` ikut dikirim supaya klien bisa mengirim X-CSRFToken."""
        response = self.login()

        self.assertIn("csrftoken", response.cookies)

    def test_login_password_salah_401(self):
        """Password salah → 401 dengan pesan yang disepakati kontrak."""
        response = self.login(password="salah-banget")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Username atau password salah")

    def test_login_username_tidak_ada_401(self):
        """Username tidak dikenal → 401 (pesan sama, tidak membocorkan akun)."""
        response = self.login(username="hantu")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Username atau password salah")

    def test_login_user_nonaktif_401(self):
        """User nonaktif → 401 walau passwordnya benar."""
        response = self.login(username="bekas")

        self.assertEqual(response.status_code, 401)

    def test_login_rate_limit_429_setelah_5_kali(self):
        """Percobaan ke-6 dalam satu menit → 429 + header Retry-After."""
        statuses = [self.login().status_code for _ in range(5)]
        blocked = self.login()

        self.assertEqual(statuses, [200] * 5)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        self.assertGreaterEqual(int(blocked.headers["Retry-After"]), 1)

    def test_login_body_kosong_400(self):
        """Body tanpa username/password → 400 (bukan 500)."""
        response = self.client.post(LOGIN_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)


class AuthLoginOperatorTests(AuthTestBase):
    """E2 — `POST /api/v1/auth/login-operator/`."""

    def operator_login(self, code: str | None = None):
        """POST E2 dengan kode operator (default: kode milik `operator`)."""
        return self.client.post(
            LOGIN_OPERATOR_URL,
            {"operator_code": self.operator.operator_code if code is None else code},
            format="json",
        )

    def test_login_operator_valid_200_dan_session_8_jam(self):
        """Kode valid → 200 + data ringkas + sesi berumur 8 jam."""
        response = self.operator_login()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {"id", "username", "full_name", "role_code"})
        self.assertEqual(body["username"], "operator1")
        self.assertEqual(body["full_name"], "Operator Satu")
        self.assertEqual(body["role_code"], "OPERATOR")

        self.assertEqual(
            str(self.client.session["_auth_user_id"]), str(self.operator.pk)
        )
        self.assertAlmostEqual(
            self.client.session.get_expiry_age(), 8 * 60 * 60, delta=5
        )

    def test_login_operator_kode_invalid_401(self):
        """Kode yang formatnya sah tetapi tidak dikenal → 401."""
        unknown = "999999"
        self.assertFalse(User.objects.filter(operator_code=unknown).exists())

        response = self.operator_login(unknown)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Kode operator tidak valid")

    def test_login_operator_kode_tidak_ada_di_db_401(self):
        """DB tanpa user ber-kode (mis. kode kosong) → 401, bukan error."""
        User.objects.update(operator_code=None)

        response = self.operator_login("1234")

        self.assertEqual(response.status_code, 401)

    def test_login_operator_user_nonaktif_401(self):
        """Kode milik user nonaktif → 401 (dicari hanya yang `is_active`)."""
        response = self.operator_login(self.inactive.operator_code)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Kode operator tidak valid")

    def test_login_operator_rate_limit_429_setelah_10_kali(self):
        """Percobaan ke-11 dalam satu menit → 429."""
        statuses = [self.operator_login().status_code for _ in range(10)]
        blocked = self.operator_login()

        self.assertEqual(statuses, [200] * 10)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_login_operator_body_kosong_400(self):
        """Body tanpa `operator_code` → 400."""
        response = self.client.post(LOGIN_OPERATOR_URL, {}, format="json")

        self.assertEqual(response.status_code, 400)


class AuthLogoutTests(AuthTestBase):
    """E3 — `POST /api/v1/auth/logout/`."""

    def test_logout_menghapus_session(self):
        """Sesudah logout: 200 `{ok:true}`, sesi kosong, cookie dihapus."""
        self.login()
        self.assertEqual(
            str(self.client.session["_auth_user_id"]), str(self.admin.pk)
        )

        response = self.client.post(LOGOUT_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertIsNone(self.client.session.get("_auth_user_id"))
        self.assertEqual(response.cookies["sessionid"]["max-age"], 0)

    def test_logout_tanpa_login_401(self):
        """Anonim → 401 (bukan 403) supaya klien tahu perlu login."""
        response = self.client.post(LOGOUT_URL)

        self.assertEqual(response.status_code, 401)


class AuthCsrfTests(AuthTestBase):
    """CSRF pada endpoint `/auth/*` (klien memegang cookie `csrftoken`)."""

    def test_csrf_diwajibkan_saat_cookie_csrf_sudah_ada(self):
        """Klien bersesi wajib mengirim `X-CSRFToken`; dengan token → lolos.

        Untuk request yang sudah bersesi, DRF `SessionAuthentication` yang lebih
        dulu menolak (403 "CSRF Failed"); token dari cookie login diterima.
        """
        client = APIClient(enforce_csrf_checks=True)
        logged_in = client.post(
            LOGIN_URL, {"username": "admin1", "password": PASSWORD}, format="json"
        )
        self.assertEqual(logged_in.status_code, 200)

        # Klien kini memegang cookie `csrftoken` (di-set `get_token()` saat login).
        secret = logged_in.cookies["csrftoken"].value
        self.assertTrue(secret)

        self.assertEqual(client.post(LOGOUT_URL).status_code, 403)
        # Django menerima nilai cookie (secret 32 karakter) sebagai token header.
        self.assertEqual(
            client.post(LOGOUT_URL, HTTP_X_CSRFTOKEN=secret).status_code, 200
        )

    def test_login_dengan_cookie_csrf_tanpa_header_403(self):
        """Login: begitu cookie `csrftoken` dipegang klien, header menjadi wajib."""
        client = APIClient(enforce_csrf_checks=True)
        client.cookies["csrftoken"] = "a" * 32  # secret berformat sah, header kosong

        response = client.post(
            LOGIN_URL, {"username": "admin1", "password": PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "CSRF token tidak valid.")

    def test_login_pertama_tanpa_cookie_csrf_tetap_bisa_masuk(self):
        """Browser baru (belum punya cookie CSRF) tetap bisa login → cookie di-set."""
        client = APIClient(enforce_csrf_checks=True)

        response = client.post(
            LOGIN_URL, {"username": "admin1", "password": PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)

        # Login ulang dengan cookie+header dari login pertama → tetap 200.
        secret = response.cookies["csrftoken"].value
        client.cookies["csrftoken"] = secret
        again = client.post(
            LOGIN_URL,
            {"username": "admin1", "password": PASSWORD},
            format="json",
            HTTP_X_CSRFTOKEN=secret,
        )
        self.assertEqual(again.status_code, 200)



class AuthMeTests(AuthTestBase):
    """E4 — `GET /api/v1/auth/me/`."""

    def test_me_dengan_session_200(self):
        """Sesi aktif → 200 + data user (tanpa info device)."""
        self.login(username="operator1")

        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), SESSION_USER_KEYS | {"device_profile", "wc_code"})
        self.assertEqual(body["username"], "operator1")
        self.assertEqual(body["full_name"], "Operator Satu")
        self.assertEqual(body["role_code"], "OPERATOR")
        self.assertIsNone(body["device_profile"])
        self.assertIsNone(body["wc_code"])

    def test_me_tanpa_auth_401(self):
        """Tanpa kredensial → 401."""
        response = self.client.get(ME_URL)

        self.assertEqual(response.status_code, 401)

    def test_me_dengan_device_token_200_dan_device_profile(self):
        """Cookie `device_token` → user dari binding + info profil perangkat."""
        profile = DeviceProfile.objects.get(code="OPERATOR_HP")
        binding = DeviceBinding.objects.create(
            wc_code="WC-AUTH",
            device_profile=profile,
            cookie_token="token-auth-01",
            user=self.operator,
        )

        perangkat = APIClient()
        perangkat.cookies[DEVICE_COOKIE_NAME] = binding.cookie_token
        response = perangkat.get(ME_URL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["username"], "operator1")
        self.assertEqual(body["device_profile"], "OPERATOR_HP")
        self.assertEqual(body["wc_code"], "WC-AUTH")

    def test_me_device_token_tanpa_user_401(self):
        """Binding yang belum terhubung user → tetap 401 (bukan data bisnis)."""
        profile = DeviceProfile.objects.get(code="KIOS")
        binding = DeviceBinding.objects.create(
            wc_code="WC-KIOS",
            device_profile=profile,
            cookie_token="token-auth-anon",
        )

        perangkat = APIClient()
        perangkat.cookies[DEVICE_COOKIE_NAME] = binding.cookie_token

        self.assertEqual(perangkat.get(ME_URL).status_code, 401)


class AuthChangePasswordTests(AuthTestBase):
    """E5 — `POST /api/v1/auth/change-password/`."""

    def test_change_password_valid_200_dan_password_berubah(self):
        """Password lama benar → hash berubah, sesi yang dipakai tetap hidup."""
        self.login(username="operator1")

        response = self.client.post(
            CHANGE_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password(NEW_PASSWORD))
        self.assertFalse(self.operator.check_password(PASSWORD))
        # `update_session_auth_hash` → request berikutnya tidak 401.
        self.assertEqual(self.client.get(ME_URL).status_code, 200)

    def test_change_password_old_salah_400(self):
        """Password lama salah → 400 dan password TIDAK berubah."""
        self.login(username="operator1")

        response = self.client.post(
            CHANGE_PASSWORD_URL,
            {"old_password": "salah-sekali", "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Password lama salah")
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password(PASSWORD))

    def test_change_password_baru_terlalu_pendek_400(self):
        """Password baru < 8 karakter → 400 (aturan sama dengan B26)."""
        self.login(username="operator1")

        response = self.client.post(
            CHANGE_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": "pendek"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_change_password_tanpa_login_401(self):
        """Anonim → 401."""
        response = self.client.post(
            CHANGE_PASSWORD_URL,
            {"old_password": PASSWORD, "new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 401)


class AuthResetPasswordTests(AuthTestBase):
    """E6 — `POST /api/v1/auth/reset-password/<user_id>/`."""

    def test_reset_password_admin_200(self):
        """Admin → 200 `{ok, user_id}` dan password target benar-benar berubah."""
        self.login()  # admin1 (role ADMIN)

        response = self.client.post(
            reset_password_url(self.operator.pk),
            {"new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "user_id": self.operator.pk})
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password(NEW_PASSWORD))

    def test_reset_password_superuser_tanpa_role_200(self):
        """`createsuperuser` (tanpa role) dihitung admin."""
        root = User.objects.create_superuser(
            username="root", email="root@klien.com", password=PASSWORD
        )
        self.login(username="root")

        response = self.client.post(
            reset_password_url(self.supervisor.pk),
            {"new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json())
        self.assertEqual(response.json()["user_id"], self.supervisor.pk)

    def test_reset_password_non_admin_403(self):
        """SUPERVISOR bukan admin → 403 dan password target tidak berubah."""
        self.login(username="spv1")

        response = self.client.post(
            reset_password_url(self.operator.pk),
            {"new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password(PASSWORD))

    def test_reset_password_user_tidak_ada_404(self):
        """User target tidak ada → 404."""
        self.login()

        response = self.client.post(
            reset_password_url(999999), {"new_password": NEW_PASSWORD}, format="json"
        )

        self.assertEqual(response.status_code, 404)

    def test_reset_password_tanpa_login_401(self):
        """Anonim → 401 (bukan 403)."""
        response = self.client.post(
            reset_password_url(self.operator.pk),
            {"new_password": NEW_PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 401)


class OperatorCodeModelTests(AuthTestBase):
    """Migrasi & perilaku kolom `User.operator_code` (F6.1)."""

    @staticmethod
    def free_code() -> str:
        """Kode 4 digit yang dijamin belum dipakai (menghindari flake)."""
        candidate = 5000
        while User.objects.filter(operator_code=f"{candidate:04d}").exists():
            candidate += 1
        return f"{candidate:04d}"

    def test_auto_generate_4_digit_untuk_operator_dan_qc(self):
        """`create_user(role=OPERATOR/QC)` → kode 4 digit terisi otomatis."""
        operator = User.objects.create_user(
            username="op-auto", password=PASSWORD, role=self.role_operator
        )
        qc = User.objects.create_user(
            username="qc-auto", password=PASSWORD, role=self.role_qc
        )

        self.assertRegex(operator.operator_code, r"^\d{4}$")
        self.assertRegex(qc.operator_code, r"^\d{4}$")

    def test_tidak_ada_kode_untuk_role_lain(self):
        """Role SUPERVISOR/ADMIN/tanpa role → `operator_code` tetap kosong."""
        for username, role in (
            ("spv-auto", self.role_supervisor),
            ("admin-auto", self.role_admin),
            ("teknis-auto", None),
        ):
            user = User.objects.create_user(username=username, password=PASSWORD, role=role)
            self.assertIsNone(user.operator_code, msg=username)

    def test_kode_selalu_unik(self):
        """20 operator baru → 20 kode berbeda (generator memeriksa DB)."""
        codes = {
            User.objects.create_user(
                username=f"op-unik-{index}", password=PASSWORD, role=self.role_operator
            ).operator_code
            for index in range(20)
        }

        self.assertEqual(len(codes), 20)
        self.assertTrue(all(len(code) == 4 for code in codes))

    def test_kode_dilepas_kalau_role_bukan_operator_lagi(self):
        """Ganti role ke SUPERVISOR → `save()` melepas kode (invariant F6.1)."""
        user = User.objects.create_user(
            username="op-pindah", password=PASSWORD, role=self.role_operator
        )
        self.assertIsNotNone(user.operator_code)

        user.role = self.role_supervisor
        user.save()

        user.refresh_from_db()
        self.assertIsNone(user.operator_code)

    def test_clean_menolak_kode_untuk_role_lain(self):
        """`clean()` (dipakai admin/form) menolak kode untuk role non-operator."""
        user = User(
            username="spv-clean", role=self.role_supervisor, operator_code="4242"
        )

        with self.assertRaises(ValidationError):
            user.clean()

    def test_fallback_6_digit_kalau_4_digit_selalu_bentrok(self):
        """Kalau seluruh undian 4 digit bentrok → generator memakai 6 digit."""
        six_digit = "123456"
        self.assertFalse(User.objects.filter(operator_code=six_digit).exists())

        def fake_random(digits=4):
            """Undian 4 digit selalu mengembalikan kode yang sudah dipakai."""
            return self.operator.operator_code if digits == 4 else six_digit

        with mock.patch("core.auth.models.random_operator_code", side_effect=fake_random):
            user = User.objects.create_user(
                username="op-6digit", password=PASSWORD, role=self.role_operator
            )

        self.assertEqual(user.operator_code, six_digit)

    def test_retry_saat_kode_bentrok_antar_admin(self):
        """Tabrakan `unique` saat INSERT → kode diundi ulang, user tetap dibuat."""
        free = self.free_code()
        codes = [self.operator.operator_code, free]  # undian pertama = duplikat

        with mock.patch(
            "core.auth.models.generate_unique_operator_code", side_effect=codes
        ):
            user = User.objects.create_user(
                username="op-retry", password=PASSWORD, role=self.role_operator
            )

        self.assertEqual(user.operator_code, free)
        self.assertTrue(
            User.objects.filter(username="op-retry", operator_code=free).exists()
        )


class GenerateOperatorCodesCommandTests(AuthTestBase):
    """Perintah backfill `generate_operator_codes` (F6.1)."""

    def test_backfill_mengisi_kode_user_lama(self):
        """User OPERATOR/QC tanpa kode (data pra-migrasi) terisi; role lain tidak."""
        User.objects.update(operator_code=None)

        call_command("generate_operator_codes", stdout=StringIO())

        self.assertRegex(User.objects.get(pk=self.operator.pk).operator_code, r"^\d{4}$")
        self.assertRegex(
            User.objects.get(pk=self.inactive.pk).operator_code, r"^\d{4}$"
        )
        self.assertIsNone(User.objects.get(pk=self.supervisor.pk).operator_code)

    def test_dry_run_tidak_mengubah_db(self):
        """`--dry-run` hanya melaporkan; kolom tetap NULL."""
        User.objects.update(operator_code=None)
        output = StringIO()

        call_command("generate_operator_codes", "--dry-run", stdout=output)

        self.assertIn("[dry-run]", output.getvalue())
        self.assertIsNone(User.objects.get(pk=self.operator.pk).operator_code)

    def test_filter_role_hanya_menyentuh_role_terpilih(self):
        """`--role OPERATOR` meninggalkan QC apa adanya."""
        User.objects.update(operator_code=None)
        qc = User.objects.create_user(
            username="qc-backfill", password=PASSWORD, role=self.role_qc
        )
        User.objects.filter(pk=qc.pk).update(operator_code=None)

        call_command("generate_operator_codes", "--role", "OPERATOR", stdout=StringIO())

        self.assertIsNotNone(User.objects.get(pk=self.operator.pk).operator_code)
        self.assertIsNone(User.objects.get(pk=qc.pk).operator_code)





