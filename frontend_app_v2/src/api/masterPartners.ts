// ADAPTER - satu-satunya pintu data master partner (H1.6, TANPA logic domain).
//
// H1.6: endpoint `/api/v1/master/partners/` SUDAH ADA di backend (MES = source of
// truth master) → MODE.masterPartners = 'real' (`_adapter.ts`), jadi tidak ada
// implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterPartners';

/** Daftar partner + filter (`GET /master/partners/`) — REAL (H1.6). */
export const fetchPartners = pickAdapter('masterPartners', real.fetchPartners, real.fetchPartners);

/** Detail partner + `orders_count` (`GET /master/partners/<id>/`) — REAL (H1.6). */
export const fetchPartner = pickAdapter('masterPartners', real.fetchPartner, real.fetchPartner);

/** Buat partner (`POST /master/partners/`) — REAL (H1.6; izin admin/owner). */
export const createPartner = pickAdapter('masterPartners', real.createPartner, real.createPartner);

/** Ubah partner (`PUT /master/partners/<id>/`) — REAL (H1.6). */
export const updatePartner = pickAdapter('masterPartners', real.updatePartner, real.updatePartner);

/** Nonaktifkan partner (`DELETE` = soft delete) — REAL (H1.6). */
export const deletePartner = pickAdapter('masterPartners', real.deletePartner, real.deletePartner);

export {
  buildMasterPartnersPath,
  MASTER_PARTNERS_PATH,
  PARTNERS_LIMIT_DEFAULT,
  PARTNERS_LIMIT_MAX,
  readMasterPartnerDetail,
  readMasterPartnerPage,
  readMasterPartnerRow,
  readMasterPartnerSaved,
  toMasterPartnerBody,
} from './real/masterPartners';
export type { MasterPartnerPage, MasterPartnersParams } from './real/masterPartners';
export type {
  MasterPartnerDetail,
  MasterPartnerInput,
  MasterPartnerRow,
  MasterPartnerSaved,
} from '@/types/master-partner';
