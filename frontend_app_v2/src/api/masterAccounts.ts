// ADAPTER - satu-satunya pintu data master Account (H3.4, TANPA logic domain).
//
// H3.4: endpoint `/api/v1/master/accounts/` SUDAH ADA di backend (chart of accounts
// hasil pull Odoo, **read-only**) → MODE.masterAccounts = 'real' (`_adapter.ts`), jadi
// tidak ada implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterAccounts';

/** Daftar akun + filter (`GET /master/accounts/`) — REAL (H3.4). */
export const fetchAccounts = pickAdapter('masterAccounts', real.fetchAccounts, real.fetchAccounts);

/** Detail akun (`GET /master/accounts/<id>/`) — REAL (H3.4). */
export const fetchAccount = pickAdapter('masterAccounts', real.fetchAccount, real.fetchAccount);

export {
  ACCOUNTS_LIMIT_DEFAULT,
  ACCOUNTS_LIMIT_MAX,
  buildMasterAccountsPath,
  MASTER_ACCOUNTS_PATH,
  readMasterAccountPage,
  readMasterAccountRow,
} from './real/masterAccounts';
export type { MasterAccountPage, MasterAccountsParams } from './real/masterAccounts';
export type { MasterAccountRow } from '@/types/master-account';
