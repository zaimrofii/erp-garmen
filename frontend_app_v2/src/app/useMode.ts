import { useCallback, useState } from 'react';
import { readEnvString } from '@/app/runtime-env';
import type { DeviceProfile } from '@/core/useDeviceProfile';

/**
 * useMode.ts — mode UX state-based (SEAM untuk migrasi ke React Router nanti).
 *
 * 3 mode: `management` (desktop/glass-card) · `operator` (HP/Kiosk, tombol besar) · `telemetry`
 * (fullscreen). Semua mode memakai **engine yang sama** (`DynamicCanvas` + 4 view standar) —
 * yang berbeda hanya shell/layout-nya.
 *
 * Routing belum pakai URL: state + `localStorage['mes-mode']` (opsional). Kalau nanti butuh
 * deep-link, cukup ganti isi hook ini (1 file) tanpa menyentuh layout/view.
 */

export const UI_MODES = ['management', 'operator', 'telemetry'] as const;

export type UiMode = (typeof UI_MODES)[number];

export const DEFAULT_UI_MODE: UiMode = 'management';

export const MODE_STORAGE_KEY = 'mes-mode';

/** Label tombol pemilih mode — tombol **navigasi/utility**, bukan aksi bisnis (§12.1). */
export const MODE_LABELS: Record<UiMode, string> = {
  management: 'Management',
  operator: 'Operator',
  telemetry: 'Telemetry',
};

export interface ModeOption {
  id: UiMode;
  label: string;
}

export interface StorageLike {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

export function isUiMode(value: unknown): value is UiMode {
  return typeof value === 'string' && (UI_MODES as readonly string[]).includes(value);
}

export function toModeOptions(modes: readonly UiMode[] = UI_MODES): ModeOption[] {
  return modes.map((id) => ({ id, label: MODE_LABELS[id] }));
}

function resolveStorage(override?: StorageLike): StorageLike | null {
  if (override !== undefined) return override;

  const globalLike = globalThis as { localStorage?: StorageLike };

  return globalLike.localStorage ?? null;
}

/** Mode default dari env (`VITE_DEFAULT_MODE`), fallback `management`. */
export function readEnvDefaultMode(): UiMode {
  const raw = (readEnvString('VITE_DEFAULT_MODE') ?? '').toLowerCase();

  return isUiMode(raw) ? raw : DEFAULT_UI_MODE;
}

/** Nilai tersimpan menang kalau valid; selain itu `fallback`. Murni. */
export function resolveInitialMode(stored: string | null | undefined, fallback: UiMode): UiMode {
  return isUiMode(stored) ? stored : fallback;
}

/**
 * PURE — saran mode UX dari profil device (Fase D.2).
 *
 * Dipakai `App` **hanya** kalau operator belum pernah memilih mode sendiri (localStorage kosong):
 * device menuntun layout awal, tapi tombol pemilih mode tetap menang (mode = preferensi user).
 * Profil tak dikenal → `null` (jangan menebak).
 */
export function modeForDeviceProfile(profile: DeviceProfile | null | undefined): UiMode | null {
  switch (profile) {
    case 'OPERATOR_HP':
    case 'SCANNER_USB':
      return 'operator';
    case 'KIOSK_TABLET':
    case 'DESKTOP':
      return 'management';
    default:
      return null;
  }
}

/** Baca mode tersimpan (localStorage bisa tidak ada / diblokir → `null`, tidak throw). */
export function readStoredMode(storage?: StorageLike): UiMode | null {
  try {
    const raw = resolveStorage(storage)?.getItem(MODE_STORAGE_KEY);

    return isUiMode(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Simpan mode — gagal (private mode/quota) diabaikan, tidak pernah throw. */
export function persistMode(mode: UiMode, storage?: StorageLike): void {
  try {
    resolveStorage(storage)?.setItem(MODE_STORAGE_KEY, mode);
  } catch {
    /* diabaikan dengan sengaja */
  }
}

export interface UseModeResult {
  mode: UiMode;
  setMode: (mode: UiMode) => void;
  availableModes: UiMode[];
  options: ModeOption[];
}

export function useMode(): UseModeResult {
  const [mode, setModeState] = useState<UiMode>(() =>
    resolveInitialMode(readStoredMode(), readEnvDefaultMode())
  );

  const setMode = useCallback((next: UiMode): void => {
    setModeState(next);
    persistMode(next);
  }, []);

  return { mode, setMode, availableModes: [...UI_MODES], options: toModeOptions() };
}
