// Helper PURE Stock Transfer (H2.6) — TANPA I/O, dipakai halaman & unit test.
//
// Aturan bisnis yang di-pin backend (`stock_transfer_services.py`) dan WAJIB
// dicerminkan di form (supaya error terlihat sebelum menembak API):
//   * `qty` > 0 dan ≤ 1.000.000;
//   * lokasi asal & tujuan berbeda, keduanya `usage === 'internal'`;
//   * `reason` opsional (≤ 500 karakter).
import type { StatusChipStatus } from '@/lib/state-display';
import type { StockTransferCreateInput, StockTransferRow, TransferState } from '@/types/stock-transfer';

/** Label state (bahasa UI). */
export const TRANSFER_STATE_LABELS: Record<TransferState, string> = {
  DRAFT: 'Draft (belum dikirim)',
  COMMITTED: 'Dikirim (menunggu Odoo)',
  SYNCED: 'Tersinkron',
  FAILED: 'Gagal',
};

/** Batas `qty` — sama dengan `MAX_QTY` backend. */
export const MAX_TRANSFER_QTY = 1_000_000;
/** Panjang maksimum `reason` — sama dengan `MAX_REASON_LENGTH` backend. */
export const MAX_TRANSFER_REASON_LENGTH = 500;

/** Nilai awal form create. */
export const EMPTY_TRANSFER_FORM = {
  productId: '',
  fromLocationId: '',
  toLocationId: '',
  qty: '',
  reason: '',
};

/** Bentuk nilai form create (semua string karena `<input>` HTML). */
export interface TransferFormValues {
  productId: string;
  fromLocationId: string;
  toLocationId: string;
  qty: string;
  reason: string;
}

/** Error per field (kosong = valid). */
export interface TransferFormErrors {
  productId?: string;
  fromLocationId?: string;
  toLocationId?: string;
  qty?: string;
  reason?: string;
}

/** PURE — label state (fallback ke nilai apa adanya kalau tak dikenal). */
export function transferStateLabel(state: string): string {
  return TRANSFER_STATE_LABELS[state as TransferState] ?? state;
}

/** PURE — hanya `DRAFT` yang boleh di-commit. */
export function isTransferCommittable(state: string): boolean {
  return state === 'DRAFT';
}

/** PURE — parse `qty` form → number (`null` kalau bukan angka; koma diterima). */
export function parseTransferQty(raw: string): number | null {
  const text = raw.trim().replace(',', '.');
  if (text.length === 0) return null;
  const value = Number(text);

  return Number.isFinite(value) ? value : null;
}

/** PURE — validasi form create (cermin guard backend). */
export function validateTransferForm(values: TransferFormValues): TransferFormErrors {
  const errors: TransferFormErrors = {};

  if (values.productId.trim().length === 0) {
    errors.productId = 'Produk wajib dipilih.';
  }

  if (values.fromLocationId.trim().length === 0) {
    errors.fromLocationId = 'Lokasi asal wajib dipilih (usage internal).';
  }

  if (values.toLocationId.trim().length === 0) {
    errors.toLocationId = 'Lokasi tujuan wajib dipilih (usage internal).';
  }

  if (
    values.fromLocationId.trim().length > 0 &&
    values.fromLocationId.trim() === values.toLocationId.trim()
  ) {
    errors.toLocationId = 'Lokasi tujuan harus BEDA dari lokasi asal.';
  }

  const qty = parseTransferQty(values.qty);
  if (qty === null) {
    errors.qty = 'Qty wajib angka.';
  } else if (qty <= 0) {
    errors.qty = 'Qty harus lebih besar dari 0.';
  } else if (qty > MAX_TRANSFER_QTY) {
    errors.qty = `Qty maksimal ${String(MAX_TRANSFER_QTY)}.`;
  }

  if (values.reason.trim().length > MAX_TRANSFER_REASON_LENGTH) {
    errors.reason = `Catatan maksimal ${String(MAX_TRANSFER_REASON_LENGTH)} karakter.`;
  }

  return errors;
}

/** PURE — form valid? */
export function isTransferFormValid(errors: TransferFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — form → payload API (`qty` = string 2 desimal, reason di-trim). */
export function transferCreateInputFromForm(values: TransferFormValues): StockTransferCreateInput {
  const qty = parseTransferQty(values.qty) ?? 0;

  return {
    product_id: Number(values.productId),
    from_location_id: Number(values.fromLocationId),
    to_location_id: Number(values.toLocationId),
    qty: qty.toFixed(2),
    reason: values.reason.trim(),
  };
}

/** PURE — teks qty (null → em dash). */
export function transferQtyLabel(value: string | null): string {
  return value === null || value.length === 0 ? '—' : value;
}

/** PURE — rute ringkas `DARI → KE`. */
export function transferRouteLabel(row: StockTransferRow): string {
  const from = row.from_location_code ?? row.from_location_name ?? `#${String(row.from_location_id)}`;
  const to = row.to_location_code ?? row.to_location_name ?? `#${String(row.to_location_id)}`;

  return `${from} → ${to}`;
}

/** PURE — state transfer → status `StatusChip` (SYNCED = on_track, FAILED = delay). */
export function transferChipStatus(state: string): StatusChipStatus {
  switch (state.trim().toUpperCase()) {
    case 'SYNCED':
      return 'on_track';
    case 'FAILED':
      return 'delay';
    default:
      return 'neutral';
  }
}
