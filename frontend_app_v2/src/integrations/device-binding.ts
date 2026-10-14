import type { ApiClient, ApiResponse } from './api-client';

/**
 * device-binding.ts — bind/unbind perangkat sendiri (Fase G), murni & tanpa throw.
 *
 * Backend (Fase G):
 *
 *     POST /api/v1/devices/bind    {"device_profile": "SCANNER_USB", "wc_code": "WC-01"}
 *       → 200 {"device_profile": "SCANNER_USB", "confidence": "high",
 *              "source": "device_binding", "wc_code": "WC-01"} + Set-Cookie `device_token`
 *     POST /api/v1/devices/unbind  {}
 *       → 200 {"ok": true, "revoked": true, "source": "fallback", ...} + cookie dihapus
 *
 * **Cookie yang menyimpan identitas**: HttpOnly (JavaScript tidak bisa membaca),
 * jadi modul ini tidak pernah menyentuh nilainya — cukup memanggil endpoint dan
 * membaca status. Gagal (400/profil tak dikenal) dikembalikan sebagai union,
 * bukan exception, supaya UI bisa menampilkan pesan.
 */

export const DEVICE_BIND_PATH = '/devices/bind';
export const DEVICE_UNBIND_PATH = '/devices/unbind';

export interface BindingOutcome {
  ok: boolean;
  deviceProfile: string | null;
  source: string;
  wcCode: string | null;
  /** Daftar kode profil yang sah (dari backend, saat 400). */
  allowed?: string[];
  message: string;
}

export interface UnbindOutcome {
  ok: boolean;
  revoked: boolean;
  message: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readAllowed(body: Record<string, unknown> | null): string[] | undefined {
  const allowed = body?.['allowed'];
  return Array.isArray(allowed) ? allowed.filter((item): item is string => typeof item === 'string') : undefined;
}

/** PURE — ubah response bind jadi hasil siap-tampil. */
export function readBindingOutcome(response: ApiResponse<unknown>): BindingOutcome {
  const body = isRecord(response.data) ? response.data : null;

  if (response.ok && body?.['source'] === 'device_binding') {
    const profile = body['device_profile'];
    const wcCode = body['wc_code'];

    return {
      ok: true,
      deviceProfile: typeof profile === 'string' ? profile : null,
      source: 'device_binding',
      wcCode: typeof wcCode === 'string' ? wcCode : null,
      message: `Perangkat terikat ke profil ${typeof profile === 'string' ? profile : '?'}.`,
    };
  }

  const detail = body?.['detail'];
  const allowed = readAllowed(body);
  const message =
    typeof detail === 'string' && detail.trim().length > 0
      ? detail
      : (response.error?.message ?? 'Gagal mengikat perangkat.');

  return {
    ok: false,
    deviceProfile: null,
    source: 'fallback',
    wcCode: null,
    ...(allowed === undefined ? {} : { allowed }),
    message,
  };
}

/** PURE — ubah response unbind jadi hasil siap-tampil. */
export function readUnbindOutcome(response: ApiResponse<unknown>): UnbindOutcome {
  const body = isRecord(response.data) ? response.data : null;

  if (response.ok && body?.['ok'] === true) {
    const revoked = body['revoked'] === true;
    return {
      ok: true,
      revoked,
      message: revoked ? 'Ikatan perangkat dicabut.' : 'Perangkat ini memang belum terikat.',
    };
  }

  return {
    ok: false,
    revoked: false,
    message: response.error?.message ?? 'Gagal mencabut ikatan perangkat.',
  };
}

/**
 * PURE (F7) — boleh submit bind? Profil wajib terisi & tidak sedang sibuk.
 * Ditaruh di sini supaya guard halaman bisa diuji tanpa DOM.
 */
export function canBindDevice(input: { deviceProfile: string; busy: boolean }): boolean {
  return !input.busy && input.deviceProfile.trim().length > 0;
}

/** PURE (F7) — boleh unbind? Hanya kalau perangkat memang sedang terikat & tidak sibuk. */
export function canUnbindDevice(input: { busy: boolean; isBound: boolean }): boolean {
  return !input.busy && input.isBound;
}

/** Ikat perangkat ini ke sebuah profil device (tidak pernah throw). */
export async function bindDevice(
  apiClient: ApiClient,
  deviceProfile: string,
  wcCode?: string
): Promise<BindingOutcome> {
  const body = {
    device_profile: deviceProfile,
    ...(wcCode === undefined || wcCode.trim() === '' ? {} : { wc_code: wcCode.trim() }),
  };

  try {
    const response = await apiClient.post<unknown>(DEVICE_BIND_PATH, body);
    return readBindingOutcome(response);
  } catch {
    return {
      ok: false,
      deviceProfile: null,
      source: 'fallback',
      wcCode: null,
      message: 'Gagal menghubungi server (bind device).',
    };
  }
}

/** Cabut ikatan perangkat ini (tidak pernah throw). */
export async function unbindDevice(apiClient: ApiClient): Promise<UnbindOutcome> {
  try {
    const response = await apiClient.post<unknown>(DEVICE_UNBIND_PATH, {});
    return readUnbindOutcome(response);
  } catch {
    return { ok: false, revoked: false, message: 'Gagal menghubungi server (unbind device).' };
  }
}
