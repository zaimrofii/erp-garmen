import type { AuthUser } from '@/api/auth';

/**
 * device-mode.ts — logika PURE auto-detect 3 mode operasi (F6.4, dikoreksi FIX ROUTE).
 *
 * Konsep (backend sudah mendukung ketiganya sejak F6.1/Fase G):
 *  1. **device**  — perangkat bersama milik perusahaan: cookie `device_token` dikenali
 *     (`source === 'device_binding'`) → badge device di TopBar (identitas perangkat/WC);
 *  2. **session** — cookie device ber-user ATAU login username+password/kode operator:
 *     `/auth/me` 200 → `user` terisi;
 *  3. **none**    — belum ada keduanya → `AuthGuard` mengarahkan ke `/login`.
 *
 * FIX ROUTE: mode `device` **bukan izin masuk**. Backend hanya mengautentikasi cookie
 * device kalau binding-nya punya user (`core/auth/authentication.py`), jadi perangkat
 * dengan binding tanpa user tetap anonim dan tidak boleh melewati login (dulu lolos →
 * semua API 401/403 → halaman kosong). Lihat `requiresLogin()`.
 *
 * CATATAN KONTRAK: `GET /devices/me` **selalu 200** (fallback profile) sehingga status code
 * tidak bisa dipakai; sinyal yang sah hanya `source === 'device_binding'` — lihat
 * `api/real/deviceBinding.ts`.
 */

export type DeviceMode = 'device' | 'session' | 'none';

export interface DeviceModeInput {
  /** true kalau cookie device dikenali backend (`source === 'device_binding'`). */
  deviceBound: boolean;
  /** true kalau ada user sesi (login admin/operator). */
  hasSession: boolean;
}

/** PURE — mode efektif; prioritas: device (bersama) → session → none. */
export function deviceModeFor(input: DeviceModeInput): DeviceMode {
  if (input.deviceBound) return 'device';
  if (input.hasSession) return 'session';

  return 'none';
}

/**
 * PURE — apakah pengguna ini MASIH harus login?
 *
 * FIX ROUTE (koreksi F6.4): mode `device` saja TIDAK cukup. Backend hanya memakai cookie
 * device sebagai sesi kalau binding-nya punya user (`core/auth/authentication.py`); binding
 * tanpa user tetap anonim → semua API 401/403. Karena itu satu-satunya bukti yang sah
 * adalah `hasSession` (`/auth/me` 200) — dan kios ber-user otomatis TIDAK perlu login
 * karena cookie-nya sendiri yang mengisi sesi itu.
 *
 * Dipakai `AuthGuard`; sengaja TIDAK menerima "loading" supaya pemanggil wajib memeriksa
 * `loading` lebih dulu (jangan pernah redirect saat probe belum selesai).
 */
export function requiresLogin(input: DeviceModeInput): boolean {
  return !input.hasSession;
}

/** PURE — label badge TopBar: `Device: KIOS @ WC-01` / `Device: KIOS`. */
export function deviceBadgeLabel(profile: string | null, wcCode: string | null): string {
  const code = (profile ?? '').trim();
  if (code.length === 0) return 'Device';

  const wc = (wcCode ?? '').trim();

  return wc.length === 0 ? `Device: ${code}` : `Device: ${code} @ ${wc}`;
}

/** PURE — kalimat info di halaman login saat cookie device ter-bind (informatif saja). */
export function deviceInfoText(profile: string | null, wcCode: string | null): string {
  const label = deviceBadgeLabel(profile, wcCode);

  return label === 'Device'
    ? 'Perangkat ini belum ter-bind.'
    : `${label} — perangkat ini sudah terikat ke work center tersebut.`;
}

/** PURE — `?switch=1` = user sengaja meminta form login walau perangkat sudah ter-bind. */
export function isSwitchIntent(search: string): boolean {
  try {
    return new URLSearchParams(search).has('switch');
  } catch {
    return false;
  }
}

/** PURE — profil perangkat terpilih dari katalog; `null` = tidak ada pilihan. */
export function resolveBindProfile(
  selected: string,
  currentProfile: string | null,
  catalog: readonly string[],
): string {
  if (selected.trim().length > 0) return selected.trim();
  if (currentProfile !== null && currentProfile.trim().length > 0) return currentProfile.trim();

  return catalog[0]?.trim() ?? '';
}

/** PURE — validasi form bind (`null` = boleh dikirim). */
export function bindDeviceError(input: { profile: string }): string | null {
  return input.profile.trim().length === 0 ? 'Profil perangkat wajib dipilih.' : null;
}

/** PURE — pilihan dropdown WC: "(tanpa WC)" + kode yang diketahui + "Lainnya (manual)". */
export const NO_WC_VALUE = '';
export const MANUAL_WC_VALUE = '__manual__';

export function isManualWc(value: string): boolean {
  return value === MANUAL_WC_VALUE;
}

export function wcSelectOptions(wcOptions: readonly string[]): { value: string; label: string }[] {
  return [
    { value: NO_WC_VALUE, label: '(tanpa WC)' },
    ...wcOptions.map((code) => ({ value: code, label: code })),
    // Master WorkCenter belum punya endpoint sendiri → admin boleh mengetik kode manual.
    { value: MANUAL_WC_VALUE, label: 'Lainnya (isi manual)…' },
  ];
}

/** PURE — kode WC final dari dropdown + input manual. */
export function resolveWcCode(selection: string, manual: string): string {
  return isManualWc(selection) ? manual.trim() : selection.trim();
}

/**
 * PURE — daftar kode WC unik untuk dropdown modal bind, diambil dari sumber yang SUDAH
 * ADA: `GET /reports/wip/by-wc/` (B21) — satu baris per work center yang punya WIP.
 *
 * Master WorkCenter belum punya endpoint sendiri sehingga WC yang belum pernah muncul di
 * laporan bisa diketik manual (opsi "Lainnya (isi manual)…" di modal).
 */
export function readWcOptions(rows: readonly { wc_code: string }[]): string[] {
  const codes = new Set<string>();

  for (const row of rows) {
    const code = row.wc_code.trim();
    if (code.length > 0) codes.add(code);
  }

  return [...codes].sort((a, b) => a.localeCompare(b));
}

/** PURE — nama tampilan user binding (dipakai daftar binding): `full_name` → `username`. */
export function bindingUserLabel(user: AuthUser | null): string {
  if (user === null) return '—';

  const name = user.full_name.trim();

  return name.length > 0 ? name : user.username;
}
