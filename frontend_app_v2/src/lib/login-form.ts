/**
 * login-form.ts — logika PURE halaman login & ganti password (F6.2).
 *
 * Semua keputusan yang bisa diuji tanpa DOM/browser ada di sini (pola repo: `lib/dropdown-state`,
 * `lib/menu-config`, `lib/action-runner`). Komponen (`pages/auth/LoginPage.tsx`,
 * `components/molecules/ProfileMenu.tsx`) hanya merender + memanggil fungsi di sini.
 *
 * Aturan yang dipegang:
 *  - pesan error 401 **diambil dari backend** (F6.1 mengirim `{"detail": …}`), teks default
 *    dipakai kalau backend tidak mengirim detail;
 *  - 429 → "Terlalu banyak percobaan, coba lagi dalam X detik" (X dari header `Retry-After`
 *    yang diteruskan `ApiResponse.retryAfter`; fallback `DEFAULT_RETRY_SECONDS`);
 *  - `redirect` dari query HANYA menerima path internal (diawali `/`, bukan `//`) supaya
 *    tidak bisa dipakai mengarahkan ke situs lain (open redirect).
 */

export type LoginTab = 'admin' | 'operator';

/** Path halaman login (publik, di luar App Shell). */
export const LOGIN_PATH = '/login';

/** Tab yang ditampilkan (urutan = urutan render). */
export const LOGIN_TABS: readonly { id: LoginTab; label: string }[] = [
  { id: 'admin', label: 'Admin/Supervisor' },
  { id: 'operator', label: 'Operator' },
];

/** Tab default saat halaman dibuka (admin/supervisor). */
export const DEFAULT_LOGIN_TAB: LoginTab = 'admin';

/** Halaman tujuan setelah login sukses tanpa `?redirect=`. */
export const DEFAULT_POST_LOGIN_PATH = '/dashboard';

/** Panjang kode operator (backend F6.1: 4 digit). */
export const OPERATOR_CODE_LENGTH = 4;

/** Tombol numpad tab operator (urut tampil 3×4). */
export const NUMPAD_KEYS: readonly string[] = [
  '1',
  '2',
  '3',
  '4',
  '5',
  '6',
  '7',
  '8',
  '9',
  'clear',
  '0',
  'backspace',
];

/** Label tombol non-digit pada numpad. */
export const NUMPAD_LABELS: Record<string, string> = {
  clear: 'Bersihkan',
  backspace: 'Hapus',
};

/** Detik default saat header `Retry-After` tidak ada (window limiter backend = 60 s). */
export const DEFAULT_RETRY_SECONDS = 60;

// --------------------------------------------------------------------------- #
// Kode operator (numpad)
// --------------------------------------------------------------------------- #
/** PURE — digit 0-9 saja. */
export function isDigit(key: string): boolean {
  return /^[0-9]$/.test(key);
}

/** PURE — tambah digit di ujung kode; kode penuh (4 digit) → tidak berubah. */
export function appendOperatorDigit(code: string, digit: string): string {
  if (!isDigit(digit)) return code;
  if (code.length >= OPERATOR_CODE_LENGTH) return code;

  return `${code}${digit}`;
}

/** PURE — hapus digit terakhir. */
export function removeOperatorDigit(code: string): string {
  return code.slice(0, -1);
}

/**
 * PURE — hasil satu tekanan tombol numpad: `'0'`-`'9'` menambah digit,
 * `backspace` menghapus satu, `clear` mengosongkan, tombol lain → tidak berubah.
 */
export function applyOperatorKey(code: string, key: string): string {
  if (key === 'clear') return '';
  if (key === 'backspace') return removeOperatorDigit(code);

  return appendOperatorDigit(code, key);
}

/** PURE — kode sudah lengkap (4 digit) → tombol Login aktif. */
export function isOperatorCodeComplete(code: string): boolean {
  return new RegExp(`^[0-9]{${OPERATOR_CODE_LENGTH}}$`).test(code);
}

/** PURE — slot tampilan kode (`['1','2','','']` untuk "12") supaya kotak kosong terlihat. */
export function operatorCodeSlots(code: string): string[] {
  return Array.from({ length: OPERATOR_CODE_LENGTH }, (_, index) => code[index] ?? '');
}

// --------------------------------------------------------------------------- #
// Redirect
// --------------------------------------------------------------------------- #
/**
 * PURE — path internal dari string query (`?redirect=%2Fbundles%3Ftab%3Dx`).
 *
 * Hanya menerima path diawali `/` dan **bukan** `//` (protocol-relative → situs lain).
 * Nilai kosong/eksternal → `null` supaya pemanggil memakai tujuan default.
 */
export function readRedirectTarget(search: string): string | null {
  const raw = new URLSearchParams(search).get('redirect');
  if (raw === null) return null;

  const value = raw.trim();
  if (!value.startsWith('/') || value.startsWith('//')) return null;

  return value;
}

/** PURE — tujuan setelah login sukses: `?redirect=` kalau sah, selain itu `/dashboard`. */
export function postLoginPath(redirect: string | null): string {
  return redirect !== null && redirect.length > 0 ? redirect : DEFAULT_POST_LOGIN_PATH;
}

/** PURE — URL halaman login untuk AuthGuard (`?redirect=` = halaman yang sedang dibuka). */
export function loginRedirectPath(pathname: string, search = ''): string {
  const params = new URLSearchParams();

  // Halaman login sendiri TIDAK dijadikan target (hindari loop redirect).
  if (pathname !== LOGIN_PATH) params.set('redirect', `${pathname}${search}`);

  const query = params.toString();

  return query.length === 0 ? LOGIN_PATH : `${LOGIN_PATH}?${query}`;
}

// --------------------------------------------------------------------------- #
// Pesan error
// --------------------------------------------------------------------------- #
export const LOGIN_MESSAGES = {
  /** Fallback 401 tab admin (backend mengirim teks ini juga). */
  invalidCredentials: 'Username atau password salah',
  /** Fallback 401 tab operator. */
  invalidOperatorCode: 'Kode operator tidak valid',
  /** Status 0 = tidak sampai server (network error / abort). */
  network: 'Koneksi gagal, cek jaringan',
  /** Kredensial wajib diisi sebelum memanggil API. */
  missingCredentials: 'Username dan password wajib diisi',
  /** Kode operator belum 4 digit. */
  incompleteCode: `Kode operator harus ${OPERATOR_CODE_LENGTH} digit`,
  /** Ganti password: konfirmasi tidak sama. */
  passwordMismatch: 'Konfirmasi password tidak sama',
  /** Ganti password: password baru terlalu pendek (aturan backend F6.1: 8 karakter). */
  passwordTooShort: 'Password baru minimal 8 karakter',
  /** Ganti password: password lama wajib diisi. */
  missingOldPassword: 'Password lama wajib diisi',
  /** Ganti password gagal tanpa pesan dari backend. */
  changePasswordFailed: 'Gagal mengganti password',
  /** Ganti password sukses (ditampilkan di modal profil). */
  passwordChanged: 'Password berhasil diubah',
  /** Info kecil di bawah kartu login. */
  contactAdmin: 'Hubungi admin untuk pembuatan akun',
} as const;

/** Key penyimpanan username "Ingat saya" (localStorage; aman-akses seperti `persistRole`). */
export const REMEMBER_STORAGE_KEY = 'mes-login-username';

/** PURE (akses storage dijaga try/catch) — username yang terakhir diingat, `''` bila belum ada. */
export function readRememberedUsername(): string {
  if (typeof window === 'undefined') return '';

  try {
    return window.localStorage.getItem(REMEMBER_STORAGE_KEY) ?? '';
  } catch {
    return '';
  }
}

/**
 * Simpan/hapus username "Ingat saya".
 *
 * Backend F6.1 tidak punya opsi remember-me (umur sesi ditentukan server), jadi yang
 * diingat adalah **username** di perangkat ini — bukan sesi yang diperpanjang.
 */
export function persistRememberedUsername(username: string, remember: boolean): void {
  if (typeof window === 'undefined') return;

  try {
    if (remember && username.trim().length > 0) {
      window.localStorage.setItem(REMEMBER_STORAGE_KEY, username.trim());
      return;
    }

    window.localStorage.removeItem(REMEMBER_STORAGE_KEY);
  } catch {
    /* diabaikan dengan sengaja — preferensi login tidak boleh menjatuhkan aplikasi */
  }
}

export interface AuthErrorInput {
  /** HTTP status; `0` = network error. */
  status: number;
  /** `error.message` dari api-client (berisi `detail` backend bila ada). */
  detail?: string | null;
  /** `ApiResponse.retryAfter` (detik) untuk 429. */
  retryAfterSeconds?: number | null;
  /** Fallback pesan 401 (beda teks untuk tab admin vs operator). */
  fallback?: string;
}

/** PURE — pesan siap-tampil untuk kegagalan request auth. */
export function authErrorMessage(input: AuthErrorInput): string {
  const { status, detail, retryAfterSeconds, fallback } = input;
  const serverDetail =
    typeof detail === 'string' && detail.trim().length > 0 ? detail.trim() : null;

  if (status === 0) return LOGIN_MESSAGES.network;

  if (status === 429) {
    const seconds =
      typeof retryAfterSeconds === 'number' && retryAfterSeconds > 0
        ? Math.ceil(retryAfterSeconds)
        : DEFAULT_RETRY_SECONDS;

    return `Terlalu banyak percobaan, coba lagi dalam ${seconds} detik`;
  }

  // 401/400: pakai teks backend (kontrak F6.1) supaya tidak ada dua sumber kebenaran.
  if (serverDetail !== null) return serverDetail;

  return fallback ?? LOGIN_MESSAGES.invalidCredentials;
}

/**
 * PURE — pesan dari error yang dilempar adapter auth (`AuthError` sudah siap tampil).
 * Dipakai halaman login dan modal ganti password supaya keduanya menampilkan teks yang sama.
 */
export function errorMessageOf(caught: unknown): string {
  return caught instanceof Error && caught.message.length > 0
    ? caught.message
    : LOGIN_MESSAGES.network;
}

/** PURE — nama tampilan user: `full_name` → `username` → fallback "Belum login". */
export function displayNameOf(user: { full_name: string; username: string } | null): string {
  if (user === null) return 'Belum login';

  const fullName = user.full_name.trim();

  return fullName.length > 0 ? fullName : user.username;
}

/** PURE — inisial avatar (maks. 2 huruf) dari nama tampilan; kosong kalau tidak ada nama. */
export function initialsOf(user: { full_name: string; username: string } | null): string {
  const name = displayNameOf(user).trim();
  if (name.length === 0 || name === 'Belum login') return '';

  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0] ?? '')
    .join('')
    .toUpperCase();
}

/**
 * PURE — validasi form ganti password (`null` = boleh dikirim).
 *
 * Password lama TIDAK diperiksa panjangnya di klien (biar backend yang menilai);
 * yang dijaga di sini hanya aturan yang membuat request pasti ditolak.
 */
export function passwordChangeError(input: {
  oldPassword: string;
  newPassword: string;
  confirmPassword: string;
  /** Panjang minimum password baru (backend F6.1: 8). */
  minLength?: number;
}): string | null {
  const minLength = input.minLength ?? 8;

  if (input.oldPassword.length === 0) return LOGIN_MESSAGES.missingOldPassword;
  if (input.newPassword.length < minLength) return LOGIN_MESSAGES.passwordTooShort;
  if (input.newPassword !== input.confirmPassword) return LOGIN_MESSAGES.passwordMismatch;

  return null;
}

