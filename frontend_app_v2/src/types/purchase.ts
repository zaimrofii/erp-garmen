/**
 * purchase.ts - kontrak Purchase (PO, vendor, line PO).
 * Field `snake_case` backend dipakai apa adanya; `id` backend = number.
 */

export type POStatus = 'draft' | 'confirmed' | 'received' | 'cancelled';

export interface Vendor {
  id: number;
  code: string;
  name: string;
  contact: string;
  email: string;
}

export interface POLine {
  product_code: string;
  qty: number;
  unit_price: number;
}

export interface PurchaseOrder {
  id: number;
  code: string;
  vendor_code: string;
  status: POStatus;
  lines: POLine[];
  total: number;
  created_at: string;
}
