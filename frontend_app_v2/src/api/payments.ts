// ADAPTER - satu-satunya pintu data Payment MES (H3.3, TANPA logic domain).
//
// H3.3: endpoint `/api/v1/finance/payments/` SUDAH ADA di backend (CRUD model MES +
// push `account.payment` draft, satu model dua arah) → MODE.payments = 'real'.
// H3.1 (`customerInvoices`) & H3.2 (`vendorBills`) TIDAK diubah; rekonsiliasi
// tetap di Odoo (MES hanya membuat payment draft).
import { pickAdapter } from './_adapter';
import * as real from './real/payments';

/** Daftar payment + filter (`GET /finance/payments/`) — REAL (H3.3). */
export const fetchPayments = pickAdapter('payments', real.fetchPayments, real.fetchPayments);

/** Detail payment (`GET …/<id>/`) — REAL (H3.3). */
export const fetchPayment = pickAdapter('payments', real.fetchPayment, real.fetchPayment);

/** Buat payment (`POST …/`) — REAL (H3.3; izin admin/owner). */
export const createPayment = pickAdapter('payments', real.createPayment, real.createPayment);

/** Ubah payment (`PUT …/<id>/`, DRAFT-only) — REAL (H3.3). */
export const updatePayment = pickAdapter('payments', real.updatePayment, real.updatePayment);

/** Hapus payment (`DELETE …/<id>/`, DRAFT-only) — REAL (H3.3). */
export const deletePayment = pickAdapter('payments', real.deletePayment, real.deletePayment);

/** Transisi payment (`confirm`/`done`/`cancel`) — REAL (H3.3). */
export const actPayment = pickAdapter('payments', real.actPayment, real.actPayment);

export {
  buildPaymentsPath,
  PAYMENT_ACTIONS,
  PAYMENTS_LIMIT_DEFAULT,
  PAYMENTS_LIMIT_MAX,
  PAYMENTS_PATH,
  paymentActionPath,
  readPaymentDetail,
  readPaymentMethod,
  readPaymentPage,
  readPaymentRow,
  readPaymentSaved,
  readPaymentSourceType,
  readPaymentState,
  readPaymentType,
  toPaymentBody,
} from './real/payments';
export type { PaymentAction, PaymentPage, PaymentsParams } from './real/payments';
export {
  PAYMENT_METHOD_LABELS,
  PAYMENT_STATE_LABELS,
  PAYMENT_TYPE_LABELS,
} from '@/types/payment';
export type {
  PaymentDetail,
  PaymentInput,
  PaymentMethod,
  PaymentRow,
  PaymentSaved,
  PaymentSourceType,
  PaymentState,
  PaymentType,
} from '@/types/payment';
