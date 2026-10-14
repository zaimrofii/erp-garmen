import { useCallback, useEffect, useState } from 'react';
import type { ApiClient } from '@/integrations/api-client';

/**
 * useDeviceProfile.ts — device resolver **5-level** (§6.1 prototype-v6.1).
 *
 * Prioritas:
 * 1. URL override `?device=` → high / url_override
 * 2. Device binding (`GET /devices/me`) → high / device_binding
 * 3. User preference (`localStorage['mes-device-profile']`) → medium / user_preference
 * 4. **Backend hint (`metadata.device_hint`)** → medium / backend_hint  ← §12.2: WAJIB dibaca
 * 5. Fallback `OPERATOR_HP` → low / fallback
 *
 * Tidak pernah throw: kegagalan `/devices/me` hanya mengisi `error`, profile tetap dari level lokal.
 */

export type DeviceProfile = 'OPERATOR_HP' | 'KIOSK_TABLET' | 'SCANNER_USB' | 'DESKTOP';

export const DEVICE_PROFILES: readonly DeviceProfile[] = [
  'OPERATOR_HP',
  'KIOSK_TABLET',
  'SCANNER_USB',
  'DESKTOP',
];

export const DEVICE_PROFILE_STORAGE_KEY = 'mes-device-profile';
export const FALLBACK_DEVICE_PROFILE: DeviceProfile = 'OPERATOR_HP';

export interface DeviceProfileSource {
  level: 1 | 2 | 3 | 4 | 5;
  confidence: 'high' | 'medium' | 'low';
  reason: 'url_override' | 'device_binding' | 'user_preference' | 'backend_hint' | 'fallback';
}

export interface DeviceProfileError {
  kind: string;
  message: string;
}

export interface UseDeviceProfileOptions {
  /** Untuk `GET /devices/me` (level 2). */
  apiClient?: ApiClient;
  /** Dari `metadata.device_hint` (level 4). */
  metadataDeviceHint?: DeviceProfile;
  /** Dari `?device=`; kalau tidak diisi, hook membaca `location.search` sendiri. */
  urlOverride?: DeviceProfile;
  /** Dari localStorage; kalau tidak diisi, hook membaca storage sendiri. */
  userPreference?: DeviceProfile;
  /** default true */
  enabled?: boolean;
}

export interface UseDeviceProfileResult {
  profile: DeviceProfile;
  source: DeviceProfileSource;
  isLoading: boolean;
  error?: DeviceProfileError;
  /**
   * `true` kalau `metadata.device_hint` ada dan BEDA dengan profile final.
   * Ini **bukan error** (§6.3): hint hanya saran backend, level di atasnya boleh menang.
   */
  mismatch: boolean;
  /**
   * F7 — paksa baca ulang `GET /devices/me` (tanpa reload). Dipanggil setelah
   * bind/unbind supaya role & layout ikut berubah.
   */
  refresh: () => void;
}

const PROFILE_SET: ReadonlySet<string> = new Set<string>(DEVICE_PROFILES);

/** PURE — tolak nilai asing (dari URL/storage/backend) tanpa throw. */
export function normalizeDeviceProfile(value: unknown): DeviceProfile | null {
  if (typeof value !== 'string') return null;

  const candidate = value.trim().toUpperCase();
  return PROFILE_SET.has(candidate) ? (candidate as DeviceProfile) : null;
}

/** PURE — level 1: baca `?device=` dari string query. */
export function readUrlDeviceOverride(search: string): DeviceProfile | null {
  try {
    return normalizeDeviceProfile(new URLSearchParams(search).get('device'));
  } catch {
    return null;
  }
}

/** PURE — level 1, 3, 4, 5 (level 2 butuh jaringan). */
export function resolveLocalProfile(input: {
  urlOverride?: unknown;
  userPreference?: unknown;
  metadataDeviceHint?: unknown;
}): { profile: DeviceProfile; source: DeviceProfileSource } {
  const fromUrl = normalizeDeviceProfile(input.urlOverride);
  if (fromUrl !== null) {
    return { profile: fromUrl, source: { level: 1, confidence: 'high', reason: 'url_override' } };
  }

  const fromPreference = normalizeDeviceProfile(input.userPreference);
  if (fromPreference !== null) {
    return {
      profile: fromPreference,
      source: { level: 3, confidence: 'medium', reason: 'user_preference' },
    };
  }

  const fromHint = normalizeDeviceProfile(input.metadataDeviceHint);
  if (fromHint !== null) {
    return {
      profile: fromHint,
      source: { level: 4, confidence: 'medium', reason: 'backend_hint' },
    };
  }

  return {
    profile: FALLBACK_DEVICE_PROFILE,
    source: { level: 5, confidence: 'low', reason: 'fallback' },
  };
}

/** PURE — hint backend beda dengan profile final? Hint **bukan** error (§6.3), hanya sinyal. */
export function isDeviceHintMismatch(profile: DeviceProfile, metadataDeviceHint: unknown): boolean {
  const hint = normalizeDeviceProfile(metadataDeviceHint);

  return hint !== null && hint !== profile;
}

/**
 * F7 — event global untuk memaksa SEMUA resolver (`useDeviceProfile` yang sedang
 * ter-mount, mis. di `App`) membaca ulang `GET /devices/me` tanpa reload halaman.
 * Dipakai setelah `POST /devices/bind|unbind` (cookie `device_token` berubah).
 */
export const DEVICE_PROFILE_REFRESH_EVENT = 'mes:device-profile-refresh';

/**
 * Panggil `deviceProfileRefresh()` setelah bind/unbind.
 *
 * Aman di runtime tanpa DOM (SSR/test): `window` yang tidak ada hanya jadi no-op,
 * tidak pernah throw.
 */
export function deviceProfileRefresh(): void {
  const target = globalThis as {
    dispatchEvent?: (event: Event) => boolean;
    CustomEvent?: typeof CustomEvent;
  };

  if (typeof target.dispatchEvent !== 'function' || typeof target.CustomEvent !== 'function') {
    return;
  }

  target.dispatchEvent(new target.CustomEvent(DEVICE_PROFILE_REFRESH_EVENT));
}

/** Level 2 — `GET /devices/me`; union, tidak throw. */
export async function fetchDeviceBinding(
  apiClient: ApiClient
): Promise<{ profile: DeviceProfile } | { error: DeviceProfileError }> {
  const response = await apiClient.get<unknown>('/devices/me');

  if (!response.ok) {
    return {
      error: {
        kind: response.error?.kind ?? 'http_error',
        message: response.error?.message ?? `HTTP ${response.status}`,
      },
    };
  }

  const record =
    typeof response.data === 'object' && response.data !== null
      ? (response.data as Record<string, unknown>)
      : undefined;

  // Kanonik: `{ device_profile: string }` (snake_case, konsisten dengan kontrak terkunci).
  const profile = normalizeDeviceProfile(record?.['device_profile']);

  if (profile === null) {
    return {
      error: {
        kind: 'invalid_device_profile',
        message: 'Respons /devices/me tidak memuat `device_profile` yang dikenal.',
      },
    };
  }

  return { profile };
}

function readStoragePreference(): DeviceProfile | null {
  const storage = (globalThis as { localStorage?: { getItem(key: string): string | null } })
    .localStorage;

  if (storage === undefined) return null;

  try {
    return normalizeDeviceProfile(storage.getItem(DEVICE_PROFILE_STORAGE_KEY));
  } catch {
    return null;
  }
}

function readGlobalUrlOverride(): DeviceProfile | null {
  const location = (globalThis as { location?: { search?: string } }).location;
  const search = location?.search;

  return typeof search === 'string' ? readUrlDeviceOverride(search) : null;
}

export function useDeviceProfile(options: UseDeviceProfileOptions = {}): UseDeviceProfileResult {
  const { apiClient, metadataDeviceHint, enabled = true } = options;

  const [binding, setBinding] = useState<DeviceProfile | null>(null);
  const [error, setError] = useState<DeviceProfileError | undefined>(undefined);
  // F7 — penanda refresh: naik saat `refresh()` / event global dipanggil.
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback((): void => {
    setNonce((current) => current + 1);
  }, []);

  const local = resolveLocalProfile({
    urlOverride: options.urlOverride ?? readGlobalUrlOverride(),
    userPreference: options.userPreference ?? readStoragePreference(),
    metadataDeviceHint,
  });

  // Level 1 sudah menang → tidak perlu panggil backend. Level 2 hanya dicoba kalau tidak ada override.
  const wantsBinding = enabled && apiClient !== undefined && local.source.level > 2;

  useEffect(() => {
    if (!wantsBinding || apiClient === undefined) return undefined;

    let cancelled = false;

    void fetchDeviceBinding(apiClient).then((result) => {
      if (cancelled) return;

      if ('error' in result) {
        // Gagal /devices/me → hanya catat error, profile tetap dari level lokal (tidak throw).
        setError(result.error);
        return;
      }

      setError(undefined);
      setBinding(result.profile);
    });

    return () => {
      cancelled = true;
    };
  }, [wantsBinding, apiClient, nonce]);

  /**
   * F7 — dengarkan event global `deviceProfileRefresh()` (dipicu halaman settings setelah
   * bind/unbind) supaya resolver ini membaca ulang `/devices/me` TANPA reload halaman.
   * Tanpa DOM (SSR/test) listener tidak dipasang - bukan error.
   */
  useEffect(() => {
    if (!enabled) return undefined;

    const target = globalThis as {
      addEventListener?: (type: string, listener: () => void) => void;
      removeEventListener?: (type: string, listener: () => void) => void;
    };

    if (typeof target.addEventListener !== 'function') return undefined;

    const listener = (): void => {
      setNonce((current) => current + 1);
    };

    target.addEventListener(DEVICE_PROFILE_REFRESH_EVENT, listener);

    return () => {
      target.removeEventListener?.(DEVICE_PROFILE_REFRESH_EVENT, listener);
    };
  }, [enabled]);

  const effectiveProfile = binding ?? local.profile;
  const mismatch = isDeviceHintMismatch(effectiveProfile, metadataDeviceHint);

  if (binding !== null) {
    return {
      profile: binding,
      source: { level: 2, confidence: 'high', reason: 'device_binding' },
      isLoading: false,
      mismatch,
      refresh,
      ...(error === undefined ? {} : { error }),
    };
  }

  return {
    profile: local.profile,
    source: local.source,
    isLoading: wantsBinding,
    mismatch,
    refresh,
    ...(error === undefined ? {} : { error }),
  };
}
