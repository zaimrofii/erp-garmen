/**
 * runtime-env.ts — SATU-SATUNYA tempat membaca `import.meta.env` (Fase D).
 *
 * Kenapa file ini ada (temuan Fase D, dibuktikan dengan probe build Vite 8):
 * Vite mengganti `import.meta.env` dengan nilai **hanya kalau bentuknya literal**. Akses
 * dinamis (`const meta = import.meta; meta.env?.[key]`) tidak diganti, sehingga di browser
 * `import.meta.env` bernilai `undefined` → `VITE_API_BASE_URL` hilang → semua request API
 * menjadi relatif (404) dan semua konfigurasi client jatuh ke fallback.
 *
 * Jadi: baca `import.meta.env` sekali di sini (bentuk literal, tanpa variabel perantara),
 * lalu seluruh app membaca dari `RUNTIME_ENV` / helper di bawah.
 */

export type RuntimeEnv = Record<string, string | boolean | undefined>;

/** Seluruh nilai env runtime; `?? {}` menjaga runtime tanpa Vite (mis. `bun file.ts`). */
export const RUNTIME_ENV: RuntimeEnv = (import.meta.env ?? {}) as RuntimeEnv;

/** PURE — nilai string env (di-trim; kosong/tipe lain → `null`). */
export function readEnvString(key: string): string | null {
  const raw = RUNTIME_ENV[key];
  if (typeof raw !== 'string') return null;

  const trimmed = raw.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/**
 * PURE — flag env: `true` boolean (Vite `DEV`) **atau** string (`"true"`, case-insensitive).
 * Selain itu (`false`, `"1"`, `"yes"`, kosong) → `false` — sengaja konservatif supaya
 * WebSocket/DEV-only tidak pernah menyala karena nilai asing.
 */
export function readEnvFlag(key: string): boolean {
  const raw = RUNTIME_ENV[key];
  if (raw === true) return true;

  return typeof raw === 'string' && raw.trim().toLowerCase() === 'true';
}
