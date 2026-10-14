// REAL — device binding (F6.4). Satu pintu untuk: state perangkat ini (`GET /devices/me`),
// aksi bind/unbind, dan (setelah endpoint tersedia) daftar binding.
//
// Kontrak backend yang dipakai APA ADANYA (diverifikasi live):
//
//   GET  /devices/me   → 200 `{"device_profile":"OPERATOR_HP","confidence":"low",
//                              "source":"fallback","wc_code":null}`  ← TANPA cookie device
//                        200 `{"device_profile":"KIOS","confidence":"high",
//                              "source":"device_binding","wc_code":"WC-01"}` ← cookie device ada
//   POST /devices/bind   {"device_profile":"KIOS","wc_code":"WC-01"} → cookie `device_token`
//   POST /devices/unbind {} → cookie dihapus
//
// PENTING (F6.4): `/devices/me` **selalu 200** (fallback profile) sehingga status code TIDAK
// bisa dipakai mendeteksi binding. Sinyal yang sah = `source === 'device_binding'` — itulah
// yang dipakai `bound` di sini (sebelum F6.4, `bound` hanya melihat ada/tidaknya
// `device_profile`, sehingga perangkat yang belum di-bind ikut dilaporkan "Bound").
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

export const DEVICES_ME_PATH = '/devices/me';
export const DEVICE_BIND_PATH = '/devices/bind';
export const DEVICE_UNBIND_PATH = '/devices/unbind';

/** Respons bind/unbind tetap ditangani `integrations/device-binding.ts` (satu implementasi). */
export { bindDevice, unbindDevice } from '@/integrations/device-binding';

export interface DeviceBindingState {
  /** true = backend mengenali cookie `device_token` (`source === 'device_binding'`). */
  bound: boolean;
  /** Kode profil MENTAH dari backend (mis. `KIOS`, `OPERATOR_HP`) atau `null`. */
  profile: string | null;
  /** Kode work center binding (dari cookie device) atau `null`. */
  wcCode: string | null;
  /** `fallback` | `device_binding` | `url_override` | `metadata_hint` | `user_preference`. */
  source: string;
  /** `high` | `medium` | `low`. */
  confidence: string;
  /** Pesan siap-tampil saat request gagal (network/HTTP), selain itu `null`. */
  message: string | null;
}

/** Alias historis (dipakai barrel `api/devices.ts` sebelum F6.4). */
export type MyDeviceState = DeviceBindingState;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readText(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value.trim() : null;
}

/** PURE — respons `/devices/me` → state binding (tidak pernah throw). */
export function readDeviceBindingState(response: ApiResponse<unknown>): DeviceBindingState {
  if (!response.ok) {
    return {
      bound: false,
      profile: null,
      wcCode: null,
      source: 'error',
      confidence: 'low',
      message: response.error?.message ?? `HTTP ${response.status} saat membaca /devices/me.`,
    };
  }

  const body = isRecord(response.data) ? response.data : null;
  const profile = readText(body?.['device_profile']);
  const source = readText(body?.['source']) ?? 'fallback';

  return {
    bound: source === 'device_binding',
    profile,
    wcCode: readText(body?.['wc_code']),
    source,
    confidence: readText(body?.['confidence']) ?? 'low',
    message: null,
  };
}

/** Baca state perangkat ini. Kegagalan jadi state (`message`), bukan exception. */
export async function fetchDeviceBindingState(client: ApiClient): Promise<DeviceBindingState> {
  try {
    return readDeviceBindingState(await client.get<unknown>(DEVICES_ME_PATH));
  } catch {
    return {
      bound: false,
      profile: null,
      wcCode: null,
      source: 'error',
      confidence: 'low',
      message: 'Gagal menghubungi server (/devices/me).',
    };
  }
}
