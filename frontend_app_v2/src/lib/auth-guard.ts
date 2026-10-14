import type { AuthUser } from '@/api/auth';

/**
 * auth-guard.ts — keputusan PURE gerbang sesi (F6.2, dikoreksi FIX ROUTE).
 *
 * Dipisah dari `components/organisms/AuthGuard.tsx` supaya file komponen hanya mengekspor
 * komponen (aturan lint `react(only-export-components)` / Fast Refresh) dan keputusannya
 * bisa diuji tanpa React sama sekali.
 */

export type GuardDecision = 'loading' | 'redirect' | 'allow';

/**
 * PURE — keputusan gerbang dari state sesi.
 *
 * Prioritas: **loading** (jangan pernah redirect saat probe belum selesai) → **sesi ada**
 * (allow) → redirect ke `/login`.
 *
 * FIX ROUTE (koreksi F6.4): cookie `device_token` **TIDAK** pernah menjadi alasan
 * melewati login. Backend hanya memakai cookie itu sebagai SESI kalau binding-nya punya
 * user (`core/auth/authentication.py` → `authenticate()` mengembalikan `None` untuk binding
 * tanpa user, request tetap anonim). Akibatnya perangkat dengan binding tanpa user dulu
 * "diizinkan masuk" tetapi SEMUA panggilan API-nya 401/403 → halaman kosong. Karena kios
 * ber-user tetap auto-masuk lewat cookie (jadi `user !== null`), bypass `deviceBound`
 * memang tidak dibutuhkan — dan dihapus di sini supaya `user` menjadi satu-satunya bukti
 * boleh-tidaknya masuk.
 */
export function guardDecision(input: {
  loading: boolean;
  user: AuthUser | null;
}): GuardDecision {
  if (input.loading) return 'loading';
  if (input.user === null) return 'redirect';

  return 'allow';
}
