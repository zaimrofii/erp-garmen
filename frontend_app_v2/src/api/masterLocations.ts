// ADAPTER - satu-satunya pintu data master lokasi (H1.4, TANPA logic domain).
//
// H1.4: endpoint `/api/v1/master/locations/` SUDAH ADA di backend (MES = source
// of truth master) → MODE.masterLocations = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterLocations';

/** Daftar lokasi + filter (`GET /master/locations/`) — REAL (H1.4). */
export const fetchLocations = pickAdapter('masterLocations', real.fetchLocations, real.fetchLocations);

/** Detail lokasi (`GET /master/locations/<id>/`) — REAL (H1.4). */
export const fetchLocation = pickAdapter('masterLocations', real.fetchLocation, real.fetchLocation);

/** Buat lokasi (`POST /master/locations/`) — REAL (H1.4; izin admin/owner). */
export const createLocation = pickAdapter('masterLocations', real.createLocation, real.createLocation);

/** Ubah lokasi (`PUT /master/locations/<id>/`) — REAL (H1.4). */
export const updateLocation = pickAdapter('masterLocations', real.updateLocation, real.updateLocation);

/** Nonaktifkan lokasi (`DELETE` = soft delete; 400 kalau masih punya anak aktif). */
export const deleteLocation = pickAdapter('masterLocations', real.deleteLocation, real.deleteLocation);

export {
  buildMasterLocationsPath,
  LOCATIONS_LIMIT_DEFAULT,
  LOCATIONS_LIMIT_MAX,
  LOCATION_USAGE_VALUES,
  MASTER_LOCATIONS_PATH,
  readLocationUsage,
  readMasterLocationPage,
  readMasterLocationRow,
  readMasterLocationSaved,
  toMasterLocationBody,
} from './real/masterLocations';
export type { MasterLocationPage, MasterLocationsParams } from './real/masterLocations';
export type {
  LocationUsage,
  MasterLocationInput,
  MasterLocationRow,
  MasterLocationSaved,
} from '@/types/master-location';
