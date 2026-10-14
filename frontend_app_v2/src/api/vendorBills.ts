// ADAPTER - satu-satunya pintu data Vendor Bill MES (H3.2, TANPA logic domain).
//
// H3.2: endpoint `/api/v1/finance/vendor-bills/` SUDAH ADA di backend (CRUD model
// MES + push `account.move` **in_invoice**) → MODE.vendorBills = 'real'.
// `MODE.purchaseOrders` (B10 monitoring Odoo) & I6 (`MaterialReadiness.vendor_bill_*`)
// TIDAK diubah.
import { pickAdapter } from './_adapter';
import * as real from './real/vendorBills';

/** Daftar bill + filter (`GET /finance/vendor-bills/`) — REAL (H3.2). */
export const fetchVendorBills = pickAdapter(
  'vendorBills',
  real.fetchVendorBills,
  real.fetchVendorBills,
);

/** Detail bill (`GET …/<id>/`) — REAL (H3.2). */
export const fetchVendorBill = pickAdapter(
  'vendorBills',
  real.fetchVendorBill,
  real.fetchVendorBill,
);

/** Buat bill (`POST …/`) — REAL (H3.2; izin admin/owner). */
export const createVendorBill = pickAdapter(
  'vendorBills',
  real.createVendorBill,
  real.createVendorBill,
);

/** Ubah bill (`PUT …/<id>/`, DRAFT-only) — REAL (H3.2). */
export const updateVendorBill = pickAdapter(
  'vendorBills',
  real.updateVendorBill,
  real.updateVendorBill,
);

/** Hapus bill (`DELETE …/<id>/`, DRAFT-only) — REAL (H3.2). */
export const deleteVendorBill = pickAdapter(
  'vendorBills',
  real.deleteVendorBill,
  real.deleteVendorBill,
);

/** Transisi bill (`confirm`/`done`/`cancel`) — REAL (H3.2). */
export const actVendorBill = pickAdapter(
  'vendorBills',
  real.actVendorBill,
  real.actVendorBill,
);

export {
  buildVendorBillsPath,
  readTaxIds,
  readVendorBillDetail,
  readVendorBillLineRow,
  readVendorBillPage,
  readVendorBillRow,
  readVendorBillSaved,
  readVendorBillState,
  toVendorBillBody,
  toVendorBillLineBody,
  VENDOR_BILL_ACTIONS,
  VENDOR_BILLS_LIMIT_DEFAULT,
  VENDOR_BILLS_LIMIT_MAX,
  VENDOR_BILLS_PATH,
  vendorBillActionPath,
} from './real/vendorBills';
export type {
  VendorBillAction,
  VendorBillPage,
  VendorBillsParams,
} from './real/vendorBills';
export {
  VENDOR_BILL_STATE_LABELS,
} from '@/types/vendor-bill';
export type {
  VendorBillDetail,
  VendorBillInput,
  VendorBillLineInput,
  VendorBillLineRow,
  VendorBillRow,
  VendorBillSaved,
  VendorBillState,
} from '@/types/vendor-bill';
