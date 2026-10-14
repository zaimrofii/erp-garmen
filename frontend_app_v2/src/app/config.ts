import { DEFAULT_INDUSTRY_PLUGIN, isIndustryPlugin, type IndustryPlugin } from '@/modules/loader';
import { readEnvString } from '@/app/runtime-env';
import { resolveWsEventsUrl } from '@/core/useWebSocket';

/**
 * config.ts — konfigurasi per-client dari `import.meta.env.VITE_CLIENT_*` (§ per-client theming).
 *
 * Semua pembacaan **tidak pernah throw**: nilai kosong / tidak valid → fallback default.
 * `primary` HARUS OKLCH (design token §F) — nilai non-OKLCH ditolak dan diganti default.
 */

export interface ClientConfig {
  name: string;
  logo: string;
  /** Warna brand OKLCH, mis. `oklch(0.6 0.15 250)`. */
  primary: string;
  industryPlugin: IndustryPlugin;
}

export interface ClientEnv {
  VITE_CLIENT_NAME?: string;
  VITE_CLIENT_LOGO?: string;
  VITE_CLIENT_PRIMARY?: string;
  VITE_INDUSTRY_PLUGIN?: string;
}

export const DEFAULT_CLIENT_CONFIG: ClientConfig = {
  name: 'MES Client',
  logo: '',
  primary: 'oklch(0.55 0.17 255)',
  industryPlugin: DEFAULT_INDUSTRY_PLUGIN,
};

/** Hanya menerima string OKLCH (`oklch(...)`) — hex/rgb ditolak (§F). */
export function isOklch(value: unknown): value is string {
  return typeof value === 'string' && /^oklch\(/i.test(value.trim());
}

function readOptionalString(value: unknown): string | null {
  if (typeof value !== 'string') return null;

  const trimmed = value.trim();

  return trimmed.length > 0 ? trimmed : null;
}

function normalizeOklch(value: unknown, fallback: string): string {
  return isOklch(value) ? value.trim() : fallback;
}

/** Env per-client dibaca lewat `runtime-env` (akses literal → Vite menggantinya saat build). */
export function readClientEnv(): ClientEnv {
  return {
    VITE_CLIENT_NAME: readEnvString('VITE_CLIENT_NAME') ?? undefined,
    VITE_CLIENT_LOGO: readEnvString('VITE_CLIENT_LOGO') ?? undefined,
    VITE_CLIENT_PRIMARY: readEnvString('VITE_CLIENT_PRIMARY') ?? undefined,
    VITE_INDUSTRY_PLUGIN: readEnvString('VITE_INDUSTRY_PLUGIN') ?? undefined,
  };
}

function readEnvValue(key: string): string | null {
  return readEnvString(key);
}

/** Base URL REST (`VITE_API_BASE_URL`) — `''` kalau belum diisi. */
export function readApiBaseUrl(): string {
  return readEnvValue('VITE_API_BASE_URL') ?? '';
}

/**
 * URL WebSocket event bus (`VITE_WS_URL` + path **`/events/`**) — `undefined` kalau env kosong.
 *
 * **Fix bug (Fase H+1):** `.env` sengaja menyimpan **host polos**
 * (`ws://localhost:8000/ws`); path `/events/` ditambahkan kode lewat
 * `resolveWsEventsUrl`. Sebelum ini fungsi ini mengembalikan nilai **mentah**,
 * sehingga `App.tsx` → `useWebSocket({url})` menimpa default hook yang sudah
 * di-resolve → browser membuka `ws://localhost:8000/ws` (404/close), bukan
 * `ws://localhost:8000/ws/events/` (101). Sekarang resolusi terjadi di sini;
 * `resolveWsEventsUrl` idempoten sehingga pemanggil boleh me-resolve lagi.
 */
export function readWsUrl(): string | undefined {
  const raw = readEnvValue('VITE_WS_URL');
  if (raw === null) return undefined;

  return resolveWsEventsUrl(raw) || undefined;
}

/**
 * PURE — nilai env dianggap aktif hanya kalau tepat `"true"` (case-insensitive, di-trim).
 * Selain itu (termasuk `1`, `yes`, kosong, undefined) → **false**.
 */
export function isWsEnabledValue(value: unknown): boolean {
  return typeof value === 'string' && value.trim().toLowerCase() === 'true';
}

/**
 * WebSocket hanya diaktifkan kalau `VITE_WS_ENABLED === 'true'` (**default false**).
 * Alasannya: consumer WS backend belum ada → kalau dipaksa aktif, browser akan reconnect
 * terus-menerus (spam jaringan/konsol). Aktifkan saat backend siap.
 */
export function readWsEnabled(): boolean {
  return isWsEnabledValue(readEnvValue('VITE_WS_ENABLED'));
}

/**
 * Konfigurasi client yang dipakai aplikasi. `env` bisa disuntik untuk test.
 * Nama kosong → default, `primary` non-OKLCH → default, plugin tak dikenal → default.
 */
export function loadClientConfig(env: ClientEnv = readClientEnv()): ClientConfig {
  const industry = (env.VITE_INDUSTRY_PLUGIN ?? '').trim().toLowerCase();

  return {
    name: readOptionalString(env.VITE_CLIENT_NAME) ?? DEFAULT_CLIENT_CONFIG.name,
    logo: readOptionalString(env.VITE_CLIENT_LOGO) ?? DEFAULT_CLIENT_CONFIG.logo,
    primary: normalizeOklch(env.VITE_CLIENT_PRIMARY, DEFAULT_CLIENT_CONFIG.primary),
    industryPlugin: isIndustryPlugin(industry) ? industry : DEFAULT_CLIENT_CONFIG.industryPlugin,
  };
}
