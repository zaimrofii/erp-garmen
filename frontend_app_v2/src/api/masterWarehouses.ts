// ADAPTER - satu-satunya pintu data master gudang (H1.3, TANPA logic domain).
//
// H1.3: endpoint `/api/v1/master/warehouses/` SUDAH ADA di backend (MES = source
// of truth master) → MODE.masterWarehouses = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterWarehouses';

/** Daftar gudang + filter (`GET /master/warehouses/`) — REAL (H1.3). */
export const fetchWarehouses = pickAdapter(
  'masterWarehouses',
  real.fetchWarehouses,
  real.fetchWarehouses,
);

/** Detail gudang (`GET /master/warehouses/<id>/`) — REAL (H1.3). */
export const fetchWarehouse = pickAdapter(
  'masterWarehouses',
  real.fetchWarehouse,
  real.fetchWarehouse,
);

/** Buat gudang (`POST /master/warehouses/`) — REAL (H1.3; izin admin/owner). */
export const createWarehouse = pickAdapter(
  'masterWarehouses',
  real.createWarehouse,
  real.createWarehouse,
);

/** Ubah gudang (`PUT /master/warehouses/<id>/`) — REAL (H1.3). */
export const updateWarehouse = pickAdapter(
  'masterWarehouses',
  real.updateWarehouse,
  real.updateWarehouse,
);

/** Nonaktifkan gudang (`DELETE` = soft delete `active=False`) — REAL (H1.3). */
export const deleteWarehouse = pickAdapter(
  'masterWarehouses',
  real.deleteWarehouse,
  real.deleteWarehouse,
);

export {
  buildMasterWarehousesPath,
  MASTER_WAREHOUSES_PATH,
  readDeliverySteps,
  readMasterWarehousePage,
  readMasterWarehouseRow,
  readMasterWarehouseSaved,
  readReceptionSteps,
  toMasterWarehouseBody,
  WAREHOUSES_LIMIT_DEFAULT,
  WAREHOUSES_LIMIT_MAX,
} from './real/masterWarehouses';
export type { MasterWarehousePage, MasterWarehousesParams } from './real/masterWarehouses';
export type {
  DeliverySteps,
  MasterWarehouseInput,
  MasterWarehouseRow,
  MasterWarehouseSaved,
  ReceptionSteps,
} from '@/types/master-warehouse';
