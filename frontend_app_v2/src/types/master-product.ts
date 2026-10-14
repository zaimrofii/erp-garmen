/**
 * master-product.ts — baris master produk dari `/api/v1/master/products/` (H1.1).
 *
 * Field = PERSIS `django_app/master/services.py::product_row`:
 *   * `active` = nama publik dari `Product.is_active` (bukan `is_active`);
 *   * `odoo_id` = kunci idempotensi sync (null = belum pernah terkirim ke Odoo);
 *   * `uom_id`/`uom_code` = satuannya; master UoM di-CRUD di H1.2 (sementara `null`).
 *
 * Respons POST/PUT menambahkan info sinkronisasi (`sync_record_id`/`task_id`/`queued`)
 * → lihat `MasterProductSaved`.
 */
export interface MasterProductRow {
  id: number;
  code: string;
  name: string;
  category: string;
  uom_id: number | null;
  uom_code: string | null;
  sale_price: number;
  cost_price: number;
  /** H3.5 — waktu terakhir harga diubah dari MES (`null` = belum pernah). */
  price_updated_at: string | null;
  weight: number | null;
  image_url: string;
  active: boolean;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Body POST/PUT ke backend (nama field backend, bukan nama UI). */
export interface MasterProductInput {
  code: string;
  name: string;
  category: string;
  uom_id: number | null;
  sale_price: number;
  cost_price: number;
  weight: number | null;
  image_url: string;
  active: boolean;
}

/**
 * Baris hasil simpan (POST/PUT): row + jejak sinkronisasi H1.1.
 * `queued=false` artinya broker/task tidak menerima pekerjaan (mis. Redis mati) —
 * `SyncRecord` tetap `PENDING` dan bisa dilihat di `/settings/sync`.
 */
export interface MasterProductSaved extends MasterProductRow {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}

/**
 * H3.5 — body `PUT /master/products/<id>/price/`.
 *
 * Minimal satu dari `sale_price`/`cost_price` harus dikirim; **0 diizinkan**
 * (produk gratis), negatif ditolak backend.
 */
export interface MasterProductPriceInput {
  sale_price?: number;
  cost_price?: number;
}

/** H3.5 — satu baris riwayat perubahan harga (dari `AuditLog` `master.update_price`). */
export interface MasterProductPriceHistoryRow {
  id: number;
  action: string;
  /** Asal perubahan: `price_endpoint` (endpoint harga) atau `product_update` (PUT produk). */
  source: string;
  /** Field harga yang berubah pada baris ini (mis. `['sale_price']`). */
  fields: string[];
  /** Nilai sebelum perubahan (string 2 desimal), mis. `{sale_price: '50000.00'}`. */
  before: Record<string, string>;
  /** Nilai sesudah perubahan. */
  after: Record<string, string>;
  user: string | null;
  timestamp: string | null;
  request_id: string;
}

/** H3.5 — respons `GET /master/products/<id>/price-history/` (envelope §3). */
export interface MasterProductPriceHistoryPage {
  rows: MasterProductPriceHistoryRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}
