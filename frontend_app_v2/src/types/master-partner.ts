/**
 * master-partner.ts — baris master Partner dari `/api/v1/master/partners/` (H1.6).
 *
 * Field = PERSIS `django_app/master/partner_services.py::partner_row` (+
 * `orders_count` di detail):
 *   * `active` = nama publik dari `Partner.is_active` (konsisten H1.1–H1.5);
 *   * `odoo_id` = kunci idempotensi sync (`null` = belum pernah terkirim ke Odoo);
 *   * `is_customer`/`is_vendor` = peran partner; **tidak boleh keduanya false**
 *     (dijaga backend: 400);
 *   * `is_company` = badan usaha vs perorangan (di Odoo field mandiri, bukan
 *     turunan NPWP);
 *   * `npwp` = NPWP Indonesia **digit-only** (Odoo `vat`), 15/16 digit bila diisi;
 *   * `customer_rank`/`supplier_rank` = hitungan transaksi dari Odoo (hasil tarikan;
 *     0 = belum pernah transaksi) — bukan penanda peran;
 *   * `address` = alamat bebas (Odoo `street`; tarikan menggabung `street`+`street2`).
 */

export interface MasterPartnerRow {
  id: number;
  code: string;
  name: string;
  email: string;
  phone: string;
  city: string;
  address: string;
  npwp: string;
  is_customer: boolean;
  is_vendor: boolean;
  is_company: boolean;
  customer_rank: number;
  supplier_rank: number;
  active: boolean;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail partner = row + jumlah order yang memakainya (`Order.customer`). */
export interface MasterPartnerDetail extends MasterPartnerRow {
  orders_count: number;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterPartnerInput {
  code: string;
  name: string;
  email: string;
  phone: string;
  city: string;
  address: string;
  npwp: string;
  is_customer: boolean;
  is_vendor: boolean;
  is_company: boolean;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): detail + jejak sinkronisasi H1.6.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterPartnerSaved extends MasterPartnerDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}
