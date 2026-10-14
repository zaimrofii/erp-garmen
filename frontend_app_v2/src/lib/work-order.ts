/**
 * work-order.ts — helper PURE halaman **Work Order MES** (H2.3).
 *
 * Bebas DOM/network supaya bisa diuji langsung (`tests/unit/pages/work-orders-crud.test.ts`)
 * dan dipakai `src/pages/production/WorkOrder{Form,Detail}Page.tsx`:
 *   * bentuk nilai form (`WoFormValues`) ↔ body backend (`WorkOrderCrudInput`);
 *   * validasi (order line wajib, qty > 0) + validasi split (jumlah = qty sumber);
 *   * label state + aksi yang boleh (mirror `work_order_services.ALLOWED_TRANSITIONS`
 *     dan aksi state machine yang di-SEED `garment.work_order`).
 */
import type {
  WorkOrderCrudDetail,
  WorkOrderCrudInput,
  WorkOrderCrudRow,
  WorkOrderState,
} from '@/types/work-order';

/** Satu nilai form WO (angka sebagai string, khas `<input>`). */
export interface WoFormValues {
  order_line_id: string;
  code: string;
  qty_planned: string;
}

/** Pesan error per field (kosong = tidak ada error). */
export interface WoFormErrors {
  order_line_id?: string;
  code?: string;
  qty_planned?: string;
}

/** Form kosong (kode & qty dikosongkan ⇒ backend memakai default-nya). */
export const EMPTY_WO_FORM: WoFormValues = {
  order_line_id: '',
  code: '',
  qty_planned: '',
};

/** Label bahasa Indonesia untuk state WO MES (state machine `garment.work_order`). */
export const WO_STATE_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  IN_PROGRESS: 'Dikerjakan',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};

/**
 * Aksi state machine yang boleh dari sebuah state (mirror seed machine):
 * DRAFT → `WO_START`/`WO_CANCEL`, IN_PROGRESS → `WO_CLOSE`/`WO_CANCEL`.
 */
export const WO_ALLOWED_ACTIONS: Record<string, string[]> = {
  DRAFT: ['WO_START', 'WO_CANCEL'],
  IN_PROGRESS: ['WO_CLOSE', 'WO_CANCEL'],
};

/** Semua state WO MES (validasi filter tabs). */
export const WO_STATES: readonly WorkOrderState[] = [
  'DRAFT',
  'IN_PROGRESS',
  'DONE',
  'CANCELLED',
];

/** PURE — label aksi siap tampil (`WO_START` → `Mulai WO`). */
export const WO_ACTION_LABELS: Record<string, string> = {
  WO_START: 'Mulai WO',
  WO_CLOSE: 'Tutup WO',
  WO_CANCEL: 'Batalkan WO',
};

/** PURE — label state siap tampil (`DRAFT` → `Draft`; tak dikenal = apa adanya). */
export function woStateLabel(state: string): string {
  return WO_STATE_LABELS[state] ?? state;
}

/** PURE — label aksi siap tampil (`WO_START` → `Mulai WO`). */
export function woActionLabel(action: string): string {
  return WO_ACTION_LABELS[action] ?? action;
}

/** PURE — aksi yang boleh dari state (PURE, mirror backend state machine). */
export function allowedWoActions(state: string): string[] {
  return [...(WO_ALLOWED_ACTIONS[state] ?? [])];
}

/** PURE — `true` kalau WO masih boleh diubah/dihapus (DRAFT-only, backend). */
export function isWoEditable(state: string): boolean {
  return state === 'DRAFT';
}

/** PURE — `true` kalau WO boleh di-split (DRAFT & belum punya bundle). */
export function isWoSplittable(row: Pick<WorkOrderCrudRow, 'state' | 'bundles_count'>): boolean {
  return row.state === 'DRAFT' && row.bundles_count === 0;
}

// ---------------------------------------------------------------------------
// Form (PURE)
// ---------------------------------------------------------------------------
/** PURE — string angka → number; `null` kalau kosong/tidak valid. */
export function toNullableNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return null;

  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/** PURE — id dari `<select>` (`''` → `null`). */
export function toNullableId(value: string): number | null {
  const parsed = toNullableNumber(value);
  if (parsed === null || !Number.isInteger(parsed) || parsed <= 0) return null;

  return parsed;
}

/** PURE — validasi form WO (order line wajib; qty > 0 bila diisi). */
export function validateWoForm(values: WoFormValues): WoFormErrors {
  const errors: WoFormErrors = {};

  if (toNullableId(values.order_line_id) === null) {
    errors.order_line_id = 'Baris order wajib dipilih.';
  }

  const qty = values.qty_planned.trim();
  if (qty.length > 0) {
    const parsed = toNullableNumber(qty);
    if (parsed === null || !Number.isInteger(parsed) || parsed <= 0) {
      errors.qty_planned = 'Qty rencana harus bilangan bulat > 0.';
    }
  }

  const code = values.code.trim();
  if (code.length > 64) {
    errors.code = 'Kode maksimal 64 karakter.';
  }

  return errors;
}

/** PURE — `true` kalau form siap dikirim (tidak ada error). */
export function isWoFormValid(errors: WoFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — nilai form → body backend (`qty_planned` kosong ⇒ backend pakai OrderLine.qty). */
export function woInputFromForm(values: WoFormValues): WorkOrderCrudInput {
  return {
    order_line_id: toNullableId(values.order_line_id),
    code: values.code.trim(),
    qty_planned: toNullableNumber(values.qty_planned),
  };
}

/** PURE — detail WO → nilai form (mode edit; `order_line_id` tidak boleh dipindah). */
export function woFormFromDetail(detail: WorkOrderCrudDetail): WoFormValues {
  return {
    order_line_id: detail.order_line_id === null ? '' : String(detail.order_line_id),
    code: detail.code,
    qty_planned: String(detail.qty_planned),
  };
}

// ---------------------------------------------------------------------------
// Split (PURE)
// ---------------------------------------------------------------------------
/** PURE — teks textarea/'' → daftar qty split (integer > 0 yang valid saja). */
export function parseSplitParts(raw: string): number[] {
  return raw
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map((part) => Number(part))
    .filter((part) => Number.isInteger(part) && part > 0);
}

/**
 * PURE — validasi split: minimal 2 bagian & jumlahnya WAJIB = `qty_planned` sumber
 * (backend menolak 400 kalau tidak sama supaya total rencana produksi tidak berubah).
 */
export function validateSplitParts(parts: number[], qtyPlanned: number): string | null {
  if (parts.length < 2) return 'Split minimal 2 bagian (mis. 60, 40).';

  const total = parts.reduce((sum, part) => sum + part, 0);
  if (total !== qtyPlanned) {
    return `Total split (${total}) harus sama dengan qty rencana (${qtyPlanned}).`;
  }

  return null;
}

// ---------------------------------------------------------------------------
// Tampilan (PURE)
// ---------------------------------------------------------------------------
/** PURE — teks aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** Satu field halaman detail WO (label + nilai siap tampil). */
export interface WoDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — daftar field halaman detail WO (urutan tetap). */
export function woDetailItems(row: WorkOrderCrudDetail): WoDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'State', value: woStateLabel(row.state), mono: true },
    { label: 'Order', value: displayOrDash(row.order_code) },
    { label: 'Baris Order', value: displayOrDash(row.order_line_id) },
    { label: 'Produk', value: displayOrDash(row.product_code) },
    { label: 'Qty Rencana', value: String(row.qty_planned) },
    { label: 'Qty Selesai', value: String(row.qty_done) },
    { label: 'Jumlah Bundle', value: String(row.bundles_count) },
    { label: 'Ledger', value: 'MES-only (SyncRecord SKIPPED)' },
  ];
}

/** PURE — daftar state untuk filter daftar (`all` + 4 state WO). */
export const WO_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'IN_PROGRESS', label: 'Dikerjakan' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

