// Helper PURE Inventory Adjustment (H2.5) — TANPA I/O, dipakai halaman & unit test.
//
// Aturan bisnis yang di-pin backend (`inventory_adjustment_services.py`) dan WAJIB
// dicerminkan di form (supaya error terlihat sebelum menembak API):
//   * `qty_delta` ≠ 0 dan |qty_delta| ≤ 1.000.000 (boleh negatif);
//   * `reason` wajib (≤ 500 karakter);
//   * lokasi wajib `usage === 'internal'`.
import type {
  AdjustmentState,
  InventoryAdjustmentCreateInput,
  InventoryAdjustmentRow,
} from '@/types/inventory-adjustment';
import type { StatusChipStatus } from '@/lib/state-display';

/** Label state (bahasa UI). */
export const ADJUSTMENT_STATE_LABELS: Record<AdjustmentState, string> = {
  DRAFT: 'Draft (belum dikirim)',
  COMMITTED: 'Dikirim (menunggu Odoo)',
  SYNCED: 'Tersinkron',
  FAILED: 'Gagal',
};

/** Batas `|qty_delta|` — sama dengan `MAX_DELTA` backend. */
export const MAX_QTY_DELTA = 1_000_000;
/** Panjang maksimum `reason` — sama dengan `MAX_REASON_LENGTH` backend. */
export const MAX_REASON_LENGTH = 500;

/** Nilai awal form create. */
export const EMPTY_ADJUSTMENT_FORM = {
  productId: '',
  locationId: '',
  qtyDelta: '',
  reason: '',
};

/** Bentuk nilai form create (semua string karena `<input>` HTML). */
export interface AdjustmentFormValues {
  productId: string;
  locationId: string;
  qtyDelta: string;
  reason: string;
}

/** Error per field (kosong = valid). */
export interface AdjustmentFormErrors {
  productId?: string;
  locationId?: string;
  qtyDelta?: string;
  reason?: string;
}

/** PURE — label state (fallback ke nilai apa adanya kalau tak dikenal). */
export function adjustmentStateLabel(state: string): string {
  return ADJUSTMENT_STATE_LABELS[state as AdjustmentState] ?? state;
}

/** PURE — hanya `DRAFT` yang boleh di-commit (COMMITTED+ = final/terkirim). */
export function isAdjustmentCommittable(state: string): boolean {
  return state === 'DRAFT';
}

/** PURE — parse `qty_delta` form → number (`null` kalau bukan angka). */
export function parseQtyDelta(raw: string): number | null {
  const text = raw.trim().replace(',', '.');
  if (text.length === 0) return null;
  const value = Number(text);

  return Number.isFinite(value) ? value : null;
}

/** PURE — validasi form create (cermin guard backend). */
export function validateAdjustmentForm(values: AdjustmentFormValues): AdjustmentFormErrors {
  const errors: AdjustmentFormErrors = {};

  if (values.productId.trim().length === 0) {
    errors.productId = 'Produk wajib dipilih.';
  }

  if (values.locationId.trim().length === 0) {
    errors.locationId = 'Lokasi wajib dipilih (usage internal).';
  }

  const delta = parseQtyDelta(values.qtyDelta);
  if (delta === null) {
    errors.qtyDelta = 'Qty delta wajib angka (boleh negatif).';
  } else if (delta === 0) {
    errors.qtyDelta = 'Qty delta tidak boleh 0.';
  } else if (Math.abs(delta) > MAX_QTY_DELTA) {
    errors.qtyDelta = `Qty delta maksimal ±${String(MAX_QTY_DELTA)}.`;
  }

  const reason = values.reason.trim();
  if (reason.length === 0) {
    errors.reason = 'Alasan wajib diisi.';
  } else if (reason.length > MAX_REASON_LENGTH) {
    errors.reason = `Alasan maksimal ${String(MAX_REASON_LENGTH)} karakter.`;
  }

  return errors;
}

/** PURE — form valid? */
export function isAdjustmentFormValid(errors: AdjustmentFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — form → payload API (`qty_delta` = string 2 desimal). */
export function adjustmentCreateInputFromForm(
  values: AdjustmentFormValues,
): InventoryAdjustmentCreateInput {
  const delta = parseQtyDelta(values.qtyDelta) ?? 0;

  return {
    product_id: Number(values.productId),
    location_id: Number(values.locationId),
    qty_delta: delta.toFixed(2),
    reason: values.reason.trim(),
  };
}

/** PURE — tampilan delta dengan tanda (`"+5.00"` / `"-2.50"`). */
export function signedDelta(value: string): string {
  const parsed = parseQtyDelta(value);
  if (parsed === null) return value;

  return parsed > 0 ? `+${parsed.toFixed(2)}` : parsed.toFixed(2);
}

/** PURE — teks qty (null → em dash). */
export function qtyLabel(value: string | null): string {
  return value === null || value.length === 0 ? '—' : value;
}

/** PURE — teks on-hand Odoo (null = tidak bisa dibaca, bukan 0). */
export function stockQtyLabel(qty: string | null): string {
  return qty === null ? 'tidak terbaca (Odoo?)' : qty;
}

/** PURE — label baris list: `KODe — product @ location`. */
export function adjustmentRowLabel(row: InventoryAdjustmentRow): string {
  const product = row.product_code ?? row.product_name ?? `#${String(row.product_id)}`;
  const location = row.location_code ?? row.location_name ?? `#${String(row.location_id)}`;

  return `${row.code} — ${product} @ ${location}`;
}

/** PURE — state adjustment → status `StatusChip` (SYNCED = on_track, FAILED = delay). */
export function adjustmentChipStatus(state: string): StatusChipStatus {
  switch (state.trim().toUpperCase()) {
    case 'SYNCED':
      return 'on_track';
    case 'FAILED':
      return 'delay';
    default:
      return 'neutral';
  }
}
