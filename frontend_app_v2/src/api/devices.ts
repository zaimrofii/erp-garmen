// ADAPTER - satu-satunya pintu data Device (TANPA logic domain).
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*`.
// MODE.devices === 'real' (ditetapkan sejak Fase 14; konsumen: DeviceProfilesPage).
// Aksi bind/unbind tetap lewat `integrations/device-binding.ts` (Fase G), di-re-export
// oleh `real/deviceBinding.ts` supaya tidak ada dua implementasi HTTP.
//
// F6.4: implementasi pindah ke `./real/deviceBinding.ts` (state + bind/unbind dalam satu
// modul) dan `bound` kini dibaca dari `source === 'device_binding'` — sebelumnya hanya
// memeriksa ada/tidaknya `device_profile` sehingga perangkat belum-terikat dilaporkan "Bound".
import { pickAdapter } from './_adapter';
import * as real from './real/deviceBinding';

/** State perangkat ini (GET /devices/me) — nama lama dipertahankan untuk kompatibilitas. */
export const fetchMyDevice = pickAdapter(
  'devices',
  real.fetchDeviceBindingState,
  real.fetchDeviceBindingState,
);

export {
  DEVICE_BIND_PATH,
  DEVICE_UNBIND_PATH,
  DEVICES_ME_PATH,
  bindDevice,
  fetchDeviceBindingState,
  readDeviceBindingState,
  unbindDevice,
} from './real/deviceBinding';
export type { DeviceBindingState, MyDeviceState } from './real/deviceBinding';
