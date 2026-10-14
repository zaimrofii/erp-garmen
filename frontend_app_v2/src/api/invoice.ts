// ADAPTER - satu-satunya pintu antrean invoice (F15, revive F10). TANPA logic domain.
//
// Halaman WAJIB mengimpor dari sini - JANGAN dari `./real/*` langsung.
// MODE `invoiceQueue` === 'real': `GET /finance/invoices/` (Fase 4.4, IsAuthenticated).
import { pickAdapter } from './_adapter';
import * as real from './real/invoice';

/** Antrean invoice (`SyncRecord` stage INVOICE + Order). */
export const getInvoices = pickAdapter('invoiceQueue', real.getInvoices, real.getInvoices);

export {
  buildInvoicesPath,
  INVOICES_PATH,
  INVOICE_CURSOR_MAX,
  INVOICE_LIMIT_DEFAULT,
  INVOICE_LIMIT_MAX,
  INVOICE_LIMIT_MIN,
  INVOICE_STATUSES,
  parseIntParam,
  parseInvoiceStatus,
  readInvoicePage,
  readInvoiceRow,
} from './real/invoice';
export type { InvoicePage, InvoiceRow, InvoiceStatus } from './real/invoice';
