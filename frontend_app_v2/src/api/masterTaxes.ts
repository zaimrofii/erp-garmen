// ADAPTER - satu-satunya pintu data master Tax (H3.6, TANPA logic domain).
//
// H3.6: endpoint `/api/v1/master/taxes/` SUDAH ADA di backend (MES = source of
// truth master) → MODE.masterTaxes = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterTaxes';

/** Daftar pajak + filter (`GET /master/taxes/`) — REAL (H3.6). */
export const fetchTaxes = pickAdapter('masterTaxes', real.fetchTaxes, real.fetchTaxes);

/** Detail pajak (`GET /master/taxes/<id>/`) — REAL (H3.6). */
export const fetchTax = pickAdapter('masterTaxes', real.fetchTax, real.fetchTax);

/** Buat pajak (`POST /master/taxes/`) — REAL (H3.6; izin admin/owner). */
export const createTax = pickAdapter('masterTaxes', real.createTax, real.createTax);

/** Ubah pajak (`PUT /master/taxes/<id>/`) — REAL (H3.6). */
export const updateTax = pickAdapter('masterTaxes', real.updateTax, real.updateTax);

/** Nonaktifkan pajak (`DELETE` = soft delete `active=False`) — REAL (H3.6). */
export const deleteTax = pickAdapter('masterTaxes', real.deleteTax, real.deleteTax);

/** Jadikan pajak default MES (`POST …/set-default/`) — REAL (H3.6). */
export const setDefaultTax = pickAdapter('masterTaxes', real.setDefaultTax, real.setDefaultTax);

/** Pajak default MES (`GET …/default/`) — REAL (H3.6). */
export const fetchDefaultTax = pickAdapter(
  'masterTaxes',
  real.fetchDefaultTax,
  real.fetchDefaultTax,
);

export {
  buildMasterTaxesPath,
  MASTER_TAXES_PATH,
  readMasterTaxDefault,
  readMasterTaxPage,
  readMasterTaxRow,
  readMasterTaxSaved,
  readTaxAmountType,
  readTaxUse,
  TAXES_LIMIT_DEFAULT,
  TAXES_LIMIT_MAX,
  toMasterTaxBody,
} from './real/masterTaxes';
export type { MasterTaxPage, MasterTaxesParams } from './real/masterTaxes';
export type {
  MasterTaxInput,
  MasterTaxRow,
  MasterTaxSaved,
  TaxAmountType,
  TaxUse,
} from '@/types/master-tax';
