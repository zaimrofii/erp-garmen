/**
 * master-currency.ts — baris master Currency dari `/api/v1/settings/currencies/` (H5.2).
 *
 * Field = PERSIS `django_app/master/currency_services.py::currency_row`:
 *   * `code` = kode ISO 3 huruf (baris hasil **pull I1** ber-kode `ODOO-<id>` karena
 *     `res.currency` tidak punya kode natural yang ditarik);
 *   * `symbol` = simbol tampilan (boleh kosong);
 *   * `rate` = kurs terhadap mata uang utama — **mirror Odoo** (`null` = belum diisi);
 *   * `is_default` = penanda mata uang default MES (**mes-only**, bukan field Odoo,
 *     dijaga tunggal oleh `set_default_currency`);
 *   * `is_active` = nama publik `Currency.is_active` (DELETE = **soft delete**);
 *   * `odoo_id` = penanda baris hasil pull I1 (`null` = dibuat di MES). Baris ber-`odoo_id`
 *     **tidak** bisa dinonaktifkan dari MES (sync harian akan mengaktifkannya kembali).
 *
 * **MES-only**: ledger `SyncRecord` `master.currency`/`MASTER_PUSH` ditulis `SKIPPED`
 * (tidak ada push ke Odoo) — beda dari `master-tax.ts` yang membawa `task_id`/`queued`.
 */

export interface MasterCurrencyRow {
  id: number;
  code: string;
  name: string;
  symbol: string;
  rate: number | null;
  is_default: boolean;
  is_active: boolean;
  odoo_id: number | null;
}

/** Body `POST /settings/currencies/` (create) — nama field backend. */
export interface MasterCurrencyCreateInput {
  code: string;
  name: string;
  symbol?: string;
  rate?: number | null;
  is_default?: boolean;
}

/** Body `PUT /settings/currencies/<id>/` — hanya field yang dikirim yang diubah. */
export interface MasterCurrencyInput {
  code?: string;
  name?: string;
  symbol?: string;
  rate?: number | null;
  active?: boolean;
  is_default?: boolean;
}

/**
 * Respons `DELETE /settings/currencies/<id>/` — **200 + body** (pola Tax H3.6, bukan
 * 204 H5.3) supaya UI menerima jejak audit (`deleted`/`sync_record_id`).
 */
export interface MasterCurrencyDeleted {
  id: number;
  is_active: boolean;
  deleted: boolean;
  is_default: boolean;
  sync_record_id: number | null;
}
