/**
 * bundle.ts — helper PURE halaman **Bundle MES** (H2.4).
 *
 * Bebas DOM/network supaya bisa diuji langsung (`tests/unit/pages/bundles-crud.test.ts`)
 * dan dipakai `src/pages/production/BundleFormPage.tsx`:
 *   * bentuk nilai form (`BundleFormValues`) ↔ body backend (`BundleCrudCreateInput`);
 *   * validasi (WO wajib, minimal 1 size dengan qty > 0) + validasi split/merge;
 *   * label state + aksi state machine yang di-SEED `garment.bundle`;
 *   * helper tampilan (dash/angka) & daftar filter.
 */
import type {
  BundleCrudCreateInput,
  BundleCrudDetail,
  BundleCrudUpdateInput,
  BundleState,
} from '@/types/bundle';

/** Satu baris size di form create (`size` + `qty` sebagai string input). */
export interface BundleSizeFormRow {
  size: string;
  qty: string;
}

/** Nilai form create bundle. */
export interface BundleFormValues {
  work_order_id: string;
  bundle_size: string;
  sku_variant: string;
  sizes: BundleSizeFormRow[];
}

/** Nilai form edit bundle (mode `:id/edit`). */
export interface BundleEditFormValues {
  size: string;
  sku_variant: string;
  qty: string;
  current_work_center_id: string;
  production_line_id: string;
}

export interface BundleFormErrors {
  work_order_id?: string;
  bundle_size?: string;
  sizes?: string;
}

export interface BundleEditFormErrors {
  size?: string;
  qty?: string;
}

/** Form create kosong (satu baris size siap isi — pola form H2.1–H2.3). */
export const EMPTY_BUNDLE_FORM: BundleFormValues = {
  work_order_id: '',
  bundle_size: '',
  sku_variant: '',
  sizes: [{ size: '', qty: '' }],
};

/** Label bahasa Indonesia untuk state bundle (`garment.bundle`). */
export const BUNDLE_STATE_LABELS: Record<string, string> = {
  DRAFT: 'Draft',
  CUTTING: 'Cutting',
  SEWING: 'Sewing',
  QC: 'QC',
  DONE: 'Selesai',
};

/**
 * Aksi state machine yang boleh dari sebuah state (mirror seed machine):
 * DRAFT → `BUNDLE_START`/`BUNDLE_SCRAP`, CUTTING → `BUNDLE_ADVANCE`/`BUNDLE_SCRAP`,
 * SEWING → `BUNDLE_QC`/`BUNDLE_SCRAP`, QC → `BUNDLE_FINISH`/`BUNDLE_SCRAP`.
 */
export const BUNDLE_ALLOWED_ACTIONS: Record<string, string[]> = {
  DRAFT: ['BUNDLE_START', 'BUNDLE_SCRAP'],
  CUTTING: ['BUNDLE_ADVANCE', 'BUNDLE_SCRAP'],
  SEWING: ['BUNDLE_QC', 'BUNDLE_SCRAP'],
  QC: ['BUNDLE_FINISH', 'BUNDLE_SCRAP'],
};

/** Semua state bundle (untuk filter tabs). */
export const BUNDLE_STATES: readonly BundleState[] = [
  'DRAFT',
  'CUTTING',
  'SEWING',
  'QC',
  'DONE',
];

/** PURE — label state siap tampil (`DRAFT` → `Draft`; tak dikenal = apa adanya). */
export function bundleStateLabel(state: string): string {
  return BUNDLE_STATE_LABELS[state] ?? state;
}

/** PURE — aksi yang boleh dari state (mirror seed machine). */
export function allowedBundleActions(state: string): string[] {
  return [...(BUNDLE_ALLOWED_ACTIONS[state] ?? [])];
}

/** PURE — `true` kalau bundle masih boleh diubah/dipecah (DRAFT-only, backend). */
export function isBundleEditable(state: string): boolean {
  return state === 'DRAFT';
}

/** PURE — `true` kalau struktur bundle boleh diubah (DRAFT & belum ada event). */
export function isBundleStructurallyEditable(
  row: Pick<BundleCrudDetail, 'state' | 'events_count'>,
): boolean {
  return row.state === 'DRAFT' && row.events_count === 0;
}

// ---------------------------------------------------------------------------
// Form create (PURE)
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

/** PURE — daftar baris size → `size_matrix` `{SIZE: qty}` (baris kosong dibuang). */
export function sizeMatrixFromRows(rows: BundleSizeFormRow[]): Record<string, number> {
  const matrix: Record<string, number> = {};

  for (const row of rows) {
    const size = row.size.trim().toUpperCase();
    if (size.length === 0) continue;
    const qty = toNullableNumber(row.qty) ?? 0;
    if (qty <= 0) continue;
    matrix[size] = (matrix[size] ?? 0) + Math.trunc(qty);
  }

  return matrix;
}

/** PURE — validasi form create (WO wajib; minimal satu size dengan qty > 0). */
export function validateBundleForm(values: BundleFormValues): BundleFormErrors {
  const errors: BundleFormErrors = {};

  if (toNullableId(values.work_order_id) === null) {
    errors.work_order_id = 'Work Order wajib dipilih.';
  }

  const matrix = sizeMatrixFromRows(values.sizes);
  if (Object.keys(matrix).length === 0) {
    errors.sizes = 'Isi minimal satu ukuran dengan qty > 0.';
  }

  const bundleSize = values.bundle_size.trim();
  if (bundleSize.length > 0) {
    const parsed = toNullableNumber(bundleSize);
    if (parsed === null || !Number.isInteger(parsed) || parsed <= 0) {
      errors.bundle_size = 'Ukuran bundle harus bilangan bulat > 0.';
    }
  }

  return errors;
}

/** PURE — `true` kalau form create siap dikirim. */
export function isBundleFormValid(errors: BundleFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — form create → body backend (`bundle_size` kosong ⇒ default backend 1). */
export function bundleCreateInputFromForm(values: BundleFormValues): BundleCrudCreateInput {
  return {
    work_order_id: toNullableId(values.work_order_id),
    size_matrix: sizeMatrixFromRows(values.sizes),
    bundle_size: toNullableNumber(values.bundle_size),
    sku_variant: values.sku_variant.trim(),
  };
}

// ---------------------------------------------------------------------------
// Form edit (PURE)
// ---------------------------------------------------------------------------
/** PURE — detail bundle → nilai form edit. */
export function bundleEditFormFromDetail(detail: BundleCrudDetail): BundleEditFormValues {
  return {
    size: detail.size,
    sku_variant: detail.sku_variant,
    qty: String(detail.qty),
    current_work_center_id:
      detail.current_work_center_id === null ? '' : String(detail.current_work_center_id),
    production_line_id:
      detail.production_line_id === null ? '' : String(detail.production_line_id),
  };
}

/** PURE — validasi form edit (qty bila diisi harus > 0 & ≥ qty selesai). */
export function validateBundleEditForm(
  values: BundleEditFormValues,
  qtyDone = 0,
): BundleEditFormErrors {
  const errors: BundleEditFormErrors = {};

  const qty = values.qty.trim();
  if (qty.length > 0) {
    const parsed = toNullableNumber(qty);
    if (parsed === null || !Number.isInteger(parsed) || parsed <= 0) {
      errors.qty = 'Qty harus bilangan bulat > 0.';
    } else if (parsed < qtyDone) {
      errors.qty = `Qty tidak boleh lebih kecil dari qty selesai (${qtyDone}).`;
    }
  }

  if (values.size.trim().length > 32) {
    errors.size = 'Ukuran maksimal 32 karakter.';
  }

  return errors;
}

/** PURE — form edit → body backend. */
export function bundleUpdateInputFromForm(values: BundleEditFormValues): BundleCrudUpdateInput {
  return {
    size: values.size.trim().toUpperCase(),
    sku_variant: values.sku_variant.trim(),
    qty: toNullableNumber(values.qty),
    current_work_center_id: toNullableId(values.current_work_center_id),
    production_line_id: toNullableId(values.production_line_id),
  };
}

// ---------------------------------------------------------------------------
// Split / merge (PURE)
// ---------------------------------------------------------------------------
/** PURE — teks textarea → daftar angka (integer > 0 yang valid saja). */
export function parseNumberList(raw: string): number[] {
  return raw
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map((part) => Number(part))
    .filter((part) => Number.isInteger(part) && part > 0);
}

/** PURE — validasi split: minimal 2 bagian & jumlah = qty sumber (pesan error/null). */
export function validateSplitParts(parts: number[], qty: number): string | null {
  if (parts.length < 2) return 'Split minimal 2 bagian (mis. 3, 2).';

  const total = parts.reduce((sum, part) => sum + part, 0);
  if (total !== qty) {
    return `Total split (${total}) harus sama dengan qty bundle (${qty}).`;
  }

  return null;
}

/** PURE — validasi merge: minimal 1 sumber & target tidak ikut daftar. */
export function validateMergeIds(ids: number[], targetId: number): string | null {
  if (ids.length === 0) return 'Isi minimal satu id bundle yang digabung.';
  if (ids.includes(targetId)) return 'Target merge tidak boleh ikut di daftar sumber.';

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

/** Satu field halaman detail/manage bundle (label + nilai siap tampil). */
export interface BundleDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — daftar field halaman detail/manage bundle (urutan tetap). */
export function bundleDetailItems(row: BundleCrudDetail): BundleDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'State', value: bundleStateLabel(row.state), mono: true },
    { label: 'Work Order', value: displayOrDash(row.work_order_code) },
    { label: 'Order', value: displayOrDash(row.order_code) },
    { label: 'Produk', value: displayOrDash(row.product_code) },
    { label: 'Ukuran', value: displayOrDash(row.size) },
    { label: 'SKU Varian', value: displayOrDash(row.sku_variant) },
    { label: 'Qty', value: String(row.qty) },
    { label: 'Qty Selesai', value: String(row.qty_done) },
    { label: 'Work Center', value: displayOrDash(row.current_work_center_code) },
    { label: 'Line Produksi', value: displayOrDash(row.production_line_code) },
    { label: 'Event Chatter', value: String(row.events_count) },
    { label: 'Ledger', value: `${displayOrDash(row.ledger_status)} (MES-only)` },
  ];
}

/** PURE — daftar state untuk filter daftar (`all` + 5 state bundle). */
export const BUNDLE_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CUTTING', label: 'Cutting' },
  { id: 'SEWING', label: 'Sewing' },
  { id: 'QC', label: 'QC' },
  { id: 'DONE', label: 'Selesai' },
];

/** PURE — state filter UI → param `state` backend (`null` = tidak difilter). */
export function bundleStateParamForFilter(state: string): string | null {
  return state === 'all' ? null : state;
}