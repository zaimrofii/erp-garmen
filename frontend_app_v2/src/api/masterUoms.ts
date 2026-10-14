// ADAPTER - satu-satunya pintu data master UoM (H1.2, TANPA logic domain).
//
// H1.2: endpoint `/api/v1/master/uoms/` SUDAH ADA di backend (MES = source of
// truth master) → MODE.masterUoms = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterUoms';

/** Daftar UoM + filter (`GET /master/uoms/`) — REAL (H1.2). */
export const fetchUoms = pickAdapter('masterUoms', real.fetchUoms, real.fetchUoms);

/** Detail UoM (`GET /master/uoms/<id>/`) — REAL (H1.2). */
export const fetchUom = pickAdapter('masterUoms', real.fetchUom, real.fetchUom);

/** Buat UoM (`POST /master/uoms/`) — REAL (H1.2; izin admin/owner). */
export const createUom = pickAdapter('masterUoms', real.createUom, real.createUom);

/** Ubah UoM (`PUT /master/uoms/<id>/`) — REAL (H1.2). */
export const updateUom = pickAdapter('masterUoms', real.updateUom, real.updateUom);

/** Nonaktifkan UoM (`DELETE` = soft delete `active=False`) — REAL (H1.2). */
export const deleteUom = pickAdapter('masterUoms', real.deleteUom, real.deleteUom);

export {
  buildMasterUomsPath,
  MASTER_UOMS_PATH,
  readMasterUomPage,
  readMasterUomRow,
  readMasterUomSaved,
  readUomType,
  toMasterUomBody,
  UOMS_LIMIT_DEFAULT,
  UOMS_LIMIT_MAX,
} from './real/masterUoms';
export type { MasterUomPage, MasterUomsParams } from './real/masterUoms';
export type { MasterUomInput, MasterUomRow, MasterUomSaved, UomType } from '@/types/master-uom';
