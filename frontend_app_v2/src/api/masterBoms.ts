// ADAPTER - satu-satunya pintu data master BOM (H1.5, TANPA logic domain).
//
// H1.5: endpoint `/api/v1/master/boms/` SUDAH ADA di backend (MES = source of
// truth master) → MODE.masterBoms = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterBoms';

/** Daftar BOM + filter (`GET /master/boms/`) — REAL (H1.5). */
export const fetchBoms = pickAdapter('masterBoms', real.fetchBoms, real.fetchBoms);

/** Detail BOM + `lines[]` (`GET /master/boms/<id>/`) — REAL (H1.5). */
export const fetchBom = pickAdapter('masterBoms', real.fetchBom, real.fetchBom);

/** Buat BOM (`POST /master/boms/`) — REAL (H1.5; izin admin/owner). */
export const createBom = pickAdapter('masterBoms', real.createBom, real.createBom);

/** Ubah BOM (`PUT /master/boms/<id>/`) — REAL (H1.5; `lines` menggantikan baris). */
export const updateBom = pickAdapter('masterBoms', real.updateBom, real.updateBom);

/** Nonaktifkan BOM (`DELETE` = soft delete) — REAL (H1.5). */
export const deleteBom = pickAdapter('masterBoms', real.deleteBom, real.deleteBom);

export {
  BOMS_LIMIT_DEFAULT,
  BOMS_LIMIT_MAX,
  buildMasterBomsPath,
  MASTER_BOMS_PATH,
  readMasterBomDetail,
  readMasterBomLineRow,
  readMasterBomPage,
  readMasterBomRow,
  readMasterBomSaved,
  toMasterBomBody,
  toMasterBomLineBody,
} from './real/masterBoms';
export type { MasterBomPage, MasterBomsParams } from './real/masterBoms';
export type {
  MasterBomDetail,
  MasterBomInput,
  MasterBomLineInput,
  MasterBomLineRow,
  MasterBomRow,
  MasterBomSaved,
} from '@/types/master-bom';
