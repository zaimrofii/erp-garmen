// ADAPTER - satu-satunya pintu data Company Profile (H5.1, TANPA logic domain).
//
// H5.1: endpoint `/api/v1/settings/company/` SUDAH ADA di backend → MODE.company =
// 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **SINGLETON**: GET (boleh `null`) + PUT (create-on-first-PUT) — tanpa list/POST/DELETE.
// **MES-only**: ledger `SyncRecord` `master.company`/`MASTER_PUSH` ditulis `SKIPPED`
// (identitas perusahaan TIDAK dikirim ke `res.company` Odoo — konfigurasi akuntansi).
import { pickAdapter } from './_adapter';
import * as real from './real/company';

/** Profil perusahaan (`GET /settings/company/`; `null` = belum diisi) — REAL (H5.1). */
export const fetchCompany = pickAdapter('company', real.fetchCompany, real.fetchCompany);

/** Simpan profil perusahaan (`PUT /settings/company/`) — REAL (H5.1; izin admin/owner). */
export const updateCompany = pickAdapter('company', real.updateCompany, real.updateCompany);

export {
  readCompanyCurrency,
  readCompanyEnvelope,
  readCompanyRow,
  SETTINGS_COMPANY_PATH,
  toCompanyBody,
} from './real/company';
export type {
  CompanyCurrency,
  CompanyEnvelope,
  CompanyInput,
  CompanyRow,
} from '@/types/company';
