/**
 * company.ts — kontrak Company Profile (`/api/v1/settings/company/`, H5.1).
 *
 * **Singleton**: satu baris per instalasi (bukan list). Field = PERSIS
 * `django_app/master/company_services.py::company_row`.
 *
 *   * `country` = kode ISO 3166-1 alpha-2 (2 huruf, auto-upper) — **teks**, bukan FK;
 *   * `npwp` = NPWP Indonesia tersimpan **digit-only** (15/16 digit; pola H1.6);
 *   * `currency_id` + `currency` = FK `master.Currency` (H5.2) + barisnya (`null` bila kosong);
 *   * `is_active` = nama publik `Company.is_active`.
 *
 * **MES-only**: ledger `SyncRecord` `master.company`/`MASTER_PUSH` ditulis `SKIPPED`
 * (tanpa push/pull ke Odoo) — tidak ada `task_id`/`queued`.
 */

/** Baris mata uang ringkas yang di-embed backend (bentuk `currency_row` H5.2). */
export interface CompanyCurrency {
  id: number;
  code: string;
  name: string;
  symbol: string;
}

export interface CompanyRow {
  id: number;
  name: string;
  legal_name: string;
  address: string;
  city: string;
  country: string;
  phone: string;
  email: string;
  npwp: string;
  website: string;
  logo_url: string;
  currency_id: number | null;
  currency: CompanyCurrency | null;
  timezone: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * Body `PUT /settings/company/` — **create-on-first-PUT** (tanpa POST terpisah).
 *
 * Field yang **tidak** dikirim tidak diubah; `name` wajib bila belum ada baris.
 * `currency_id: null` = kosongkan mata uang.
 */
export interface CompanyInput {
  name?: string;
  legal_name?: string;
  address?: string;
  city?: string;
  country?: string;
  phone?: string;
  email?: string;
  npwp?: string;
  website?: string;
  logo_url?: string;
  currency_id?: number | null;
  timezone?: string;
  active?: boolean;
}

/** Respons `GET`/`PUT`: `{company: …|null}` (`null` = belum diisi — pola `/taxes/default/`). */
export interface CompanyEnvelope {
  company: CompanyRow | null;
}
