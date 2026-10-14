/**
 * master-tax.ts — baris master Tax dari `/api/v1/master/taxes/` (H3.6).
 *
 * Field = PERSIS `django_app/master/tax_services.py::tax_row`:
 *   * `amount` = tarif (persen atau nominal, `amount_type`); **0 diizinkan** (PPN 0%);
 *   * `amount_type`/`type_tax_use` = selection yang SAMA dengan `account.tax` Odoo;
 *   * `is_default` = penanda pajak default MES (**mes-only**, tidak dikirim/ditarik
 *     ke/dari Odoo) — dipakai form order/invoice untuk mengisi `tax_ids`;
 *   * `active` = nama publik `Tax.is_active` (DELETE API = soft delete);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo).
 *
 * Respons POST/PUT menambahkan info sinkronisasi (`sync_record_id`/`task_id`/`queued`)
 * → lihat `MasterTaxSaved`.
 */

/** Tipe nilai pajak — nilai HARUS sama dengan `account.tax.amount_type` (subset MES). */
export type TaxAmountType = 'percent' | 'fixed';

/** Jenis pemakaian pajak — nilai HARUS sama dengan `account.tax.type_tax_use` Odoo. */
export type TaxUse = 'sale' | 'purchase' | 'none';

export interface MasterTaxRow {
  id: number;
  code: string;
  name: string;
  amount: number;
  amount_type: TaxAmountType;
  type_tax_use: TaxUse;
  price_include: boolean;
  is_default: boolean;
  active: boolean;
  odoo_id: number | null;
}

/**
 * Body POST/PUT ke backend (nama field backend, bukan nama UI).
 *
 * `code` boleh dikosongkan — backend membuatnya dari `name` (`PPN 11%` → `PPN-11`).
 */
export interface MasterTaxInput {
  code: string;
  name: string;
  amount: number;
  amount_type: TaxAmountType;
  type_tax_use: TaxUse;
  price_include: boolean;
  is_default: boolean;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): row + jejak sinkronisasi H3.6.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 * Perubahan `is_default` saja (mes-only) membalas `sync_record_id=null`.
 */
export interface MasterTaxSaved extends MasterTaxRow {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
