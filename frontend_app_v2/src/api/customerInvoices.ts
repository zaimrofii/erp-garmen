// ADAPTER - satu-satunya pintu data Customer Invoice MES (H3.1, TANPA logic domain).
//
// H3.1: endpoint `/api/v1/finance/customer-invoices/` SUDAH ADA di backend (CRUD
// model MES + push `account.move`) → MODE.customerInvoices = 'real'.
// `MODE.invoiceQueue` (F15, antrean I5 read-only) TIDAK diubah.
import { pickAdapter } from './_adapter';
import * as real from './real/customerInvoices';

/** Daftar invoice + filter (`GET /finance/customer-invoices/`) — REAL (H3.1). */
export const fetchCustomerInvoices = pickAdapter(
  'customerInvoices',
  real.fetchCustomerInvoices,
  real.fetchCustomerInvoices,
);

/** Detail invoice (`GET …/<id>/`) — REAL (H3.1). */
export const fetchCustomerInvoice = pickAdapter(
  'customerInvoices',
  real.fetchCustomerInvoice,
  real.fetchCustomerInvoice,
);

/** Buat invoice (`POST …/`) — REAL (H3.1; izin admin/owner). */
export const createCustomerInvoice = pickAdapter(
  'customerInvoices',
  real.createCustomerInvoice,
  real.createCustomerInvoice,
);

/** Ubah invoice (`PUT …/<id>/`, DRAFT-only) — REAL (H3.1). */
export const updateCustomerInvoice = pickAdapter(
  'customerInvoices',
  real.updateCustomerInvoice,
  real.updateCustomerInvoice,
);

/** Hapus invoice (`DELETE …/<id>/`, DRAFT-only) — REAL (H3.1). */
export const deleteCustomerInvoice = pickAdapter(
  'customerInvoices',
  real.deleteCustomerInvoice,
  real.deleteCustomerInvoice,
);

/** Transisi invoice (`confirm`/`done`/`cancel`) — REAL (H3.1). */
export const actCustomerInvoice = pickAdapter(
  'customerInvoices',
  real.actCustomerInvoice,
  real.actCustomerInvoice,
);

export {
  buildCustomerInvoicesPath,
  CUSTOMER_INVOICE_ACTIONS,
  CUSTOMER_INVOICES_PATH,
  customerInvoiceActionPath,
  INVOICES_LIMIT_DEFAULT,
  INVOICES_LIMIT_MAX,
  readCustomerInvoiceDetail,
  readCustomerInvoiceLineRow,
  readCustomerInvoicePage,
  readCustomerInvoiceRow,
  readCustomerInvoiceSaved,
  readCustomerInvoiceState,
  toCustomerInvoiceBody,
  toCustomerInvoiceLineBody,
} from './real/customerInvoices';
export type {
  CustomerInvoiceAction,
  CustomerInvoicePage,
  CustomerInvoicesParams,
} from './real/customerInvoices';
export {
  CUSTOMER_INVOICE_STATE_LABELS,
} from '@/types/customer-invoice';
export type {
  CustomerInvoiceDetail,
  CustomerInvoiceInput,
  CustomerInvoiceLineInput,
  CustomerInvoiceLineRow,
  CustomerInvoiceRow,
  CustomerInvoiceSaved,
  CustomerInvoiceState,
} from '@/types/customer-invoice';
