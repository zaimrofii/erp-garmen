// ADAPTER - satu-satunya pintu data Currency (H5.2, TANPA logic domain).
//
// H5.2: endpoint `/api/v1/settings/currencies/` SUDAH ADA di backend →
// MODE.masterCurrencies = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **MES-only** (keputusan STEP 0): ledger `SyncRecord` `master.currency`/`MASTER_PUSH`
// ditulis `SKIPPED` — mata uang TIDAK di-push ke Odoo (`res.currency` = konfigurasi
// akuntansi; `Payment.currency` = teks bebas; invoice/journal tidak mengirim
// `currency_id`). Pull I1 (`sync_master_currencies`) tetap jalur Odoo → MES.
import { pickAdapter } from './_adapter';
import * as real from './real/masterCurrencies';

/** Daftar mata uang + filter (`GET /settings/currencies/`) — REAL (H5.2). */
export const fetchCurrencies = pickAdapter(
  'masterCurrencies',
  real.fetchCurrencies,
  real.fetchCurrencies,
);

/** Detail mata uang (`GET /settings/currencies/<id>/`) — REAL (H5.2). */
export const fetchCurrency = pickAdapter(
  'masterCurrencies',
  real.fetchCurrency,
  real.fetchCurrency,
);

/** Mata uang default MES (`GET /settings/currencies/default/`) — REAL (H5.2). */
export const fetchDefaultCurrency = pickAdapter(
  'masterCurrencies',
  real.fetchDefaultCurrency,
  real.fetchDefaultCurrency,
);

/** Buat mata uang (`POST /settings/currencies/`) — REAL (H5.2; izin admin/owner). */
export const createCurrency = pickAdapter(
  'masterCurrencies',
  real.createCurrency,
  real.createCurrency,
);

/** Ubah mata uang (`PUT /settings/currencies/<id>/`) — REAL (H5.2). */
export const updateCurrency = pickAdapter(
  'masterCurrencies',
  real.updateCurrency,
  real.updateCurrency,
);

/** Nonaktifkan mata uang (`DELETE` = soft delete) — REAL (H5.2). */
export const deleteCurrency = pickAdapter(
  'masterCurrencies',
  real.deleteCurrency,
  real.deleteCurrency,
);

/** Jadikan mata uang default MES (`POST …/<id>/set-default/`) — REAL (H5.2). */
export const setDefaultCurrency = pickAdapter(
  'masterCurrencies',
  real.setDefaultCurrency,
  real.setDefaultCurrency,
);

export {
  buildMasterCurrenciesPath,
  CURRENCIES_DEFAULT_PATH,
  CURRENCIES_LIMIT_DEFAULT,
  CURRENCIES_LIMIT_MAX,
  currencyDetailPath,
  currencySetDefaultPath,
  readMasterCurrencyDefault,
  readMasterCurrencyDeleted,
  readMasterCurrencyPage,
  readMasterCurrencyRow,
  SETTINGS_CURRENCIES_PATH,
  toMasterCurrencyCreateBody,
  toMasterCurrencyUpdateBody,
} from './real/masterCurrencies';
export type { MasterCurrenciesParams, MasterCurrencyPage } from './real/masterCurrencies';
export type {
  MasterCurrencyCreateInput,
  MasterCurrencyDeleted,
  MasterCurrencyInput,
  MasterCurrencyRow,
} from '@/types/master-currency';
