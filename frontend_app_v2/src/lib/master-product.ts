/**
 * master-product.ts — logic PURE halaman master produk (H1.1).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * lihat `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, dan
 * pemetaan filter status ke param backend semuanya fungsi murni di sini.
 */
import type {
  MasterProductInput,
  MasterProductPriceHistoryRow,
  MasterProductRow,
} from '@/types/master-product';

/** Nilai form (semua input = string; `active` = checkbox). */
export interface ProductFormValues {
  code: string;
  name: string;
  category: string;
  /** ID UoM sebagai teks — dipilih dari dropdown master UoM (H1.2). */
  uom: string;
  sale_price: string;
  cost_price: string;
  weight: string;
  image_url: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface ProductFormErrors {
  code?: string;
  name?: string;
  uom?: string;
  sale_price?: string;
  cost_price?: string;
  weight?: string;
  image_url?: string;
}

export type ProductStatusFilter = 'all' | 'active' | 'inactive';

/** Nilai awal form "Produk Baru" (`active` true, angka 0 — sama dengan default backend). */
export const EMPTY_PRODUCT_FORM: ProductFormValues = {
  code: '',
  name: '',
  category: '',
  uom: '',
  sale_price: '0',
  cost_price: '0',
  weight: '',
  image_url: '',
  active: true,
};

/** Tab filter status di halaman daftar (`all` = param `active` TIDAK dikirim). */
export const STATUS_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'active', label: 'Aktif' },
  { id: 'inactive', label: 'Nonaktif' },
];

/** Kode produk maksimal 64 karakter (kolom `master.Product.code`). */
export const MAX_CODE_LENGTH = 64;

/** PURE — nilai angka form → number, atau `null` kalau bukan angka. */
export function parseFormNumber(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed.length === 0) return 0;

  const parsed = Number(trimmed);

  return Number.isFinite(parsed) ? parsed : null;
}

/** Opsi validasi tambahan (mis. daftar id UoM aktif dari dropdown). */
export interface ProductFormValidateOptions {
  /** Kalau diisi: `uom` harus salah satu id ini (menangkap pilihan nonaktif/kadaluarsa). */
  uomIds?: readonly number[];
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateProductForm(
  values: ProductFormValues,
  options: ProductFormValidateOptions = {},
): ProductFormErrors {
  const errors: ProductFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode produk wajib diisi.';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  if (values.name.trim().length === 0) {
    errors.name = 'Nama produk wajib diisi.';
  }

  const uom = values.uom.trim();
  if (uom.length > 0 && !/^\d+$/.test(uom)) {
    errors.uom = 'UoM harus dipilih dari daftar (dropdown master UoM).';
  } else if (uom.length > 0 && options.uomIds !== undefined) {
    // H1.2 — dropdown sudah terisi: nilai di luar daftar (mis. UoM dinonaktifkan)
    // ditolak di klien supaya tidak berakhir 400 dari backend.
    const ids = options.uomIds;
    const chosen = Number(uom);
    if (!ids.includes(chosen)) {
      errors.uom = 'UoM yang dipilih tidak ada di daftar aktif — pilih ulang.';
    }
  }

  for (const field of ['sale_price', 'cost_price'] as const) {
    const parsed = parseFormNumber(values[field]);

    if (parsed === null) {
      errors[field] = 'Isi angka (boleh 0).';
    } else if (parsed < 0) {
      errors[field] = 'Harga tidak boleh negatif.';
    }
  }

  const weight = values.weight.trim();
  if (weight.length > 0) {
    const parsed = Number(weight);
    if (!Number.isFinite(parsed)) {
      errors.weight = 'Berat harus berupa angka.';
    } else if (parsed < 0) {
      errors.weight = 'Berat tidak boleh negatif.';
    }
  }

  const imageUrl = values.image_url.trim();
  if (imageUrl.length > 0 && !/^https?:\/\//.test(imageUrl)) {
    errors.image_url = 'URL gambar harus diawali http:// atau https://.';
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isProductFormValid(errors: ProductFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function productFormFromRow(row: MasterProductRow): ProductFormValues {
  return {
    code: row.code,
    name: row.name,
    category: row.category,
    uom: row.uom_id === null ? '' : String(row.uom_id),
    sale_price: String(row.sale_price),
    cost_price: String(row.cost_price),
    weight: row.weight === null ? '' : String(row.weight),
    image_url: row.image_url,
    active: row.active,
  };
}

/** PURE — nilai form → body API (`weight` kosong → `null`). */
export function productInputFromForm(values: ProductFormValues): MasterProductInput {
  const uom = values.uom.trim();
  const weight = values.weight.trim();

  return {
    code: values.code.trim(),
    name: values.name.trim(),
    category: values.category.trim(),
    uom_id: uom.length === 0 ? null : Number(uom),
    sale_price: parseFormNumber(values.sale_price) ?? 0,
    cost_price: parseFormNumber(values.cost_price) ?? 0,
    weight: weight.length === 0 ? null : Number(weight),
    image_url: values.image_url.trim(),
    active: values.active,
  };
}

/** PURE — filter status UI → param `active` backend (`null` = tidak difilter). */
export function activeParamForStatus(status: ProductStatusFilter): boolean | null {
  if (status === 'active') return true;
  if (status === 'inactive') return false;

  return null;
}

/** PURE — harga `15000.5` → `15.000,50` (format Indonesia, tanpa Intl/ICU). */
export function formatPrice(value: number): string {
  const [whole, decimals] = value.toFixed(2).split('.');
  const grouped = (whole ?? '0').replace(/\B(?=(\d{3})+(?!\d))/g, '.');

  return `${grouped},${decimals ?? '00'}`;
}

/** Satu baris detail produk (label + nilai siap tampil). */
export interface MasterProductDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail (urutan tetap; `null`/'' → '-' atau label kosong khusus). */
export function productDetailItems(row: MasterProductRow): MasterProductDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Kategori', value: displayOrDash(row.category) },
    { label: 'UoM', value: displayOrDash(row.uom_code) },
    { label: 'Harga Jual', value: formatPrice(row.sale_price) },
    { label: 'Harga Pokok (HPP)', value: formatPrice(row.cost_price) },
    { label: 'Berat (kg)', value: row.weight === null ? '-' : String(row.weight) },
    { label: 'URL Gambar', value: displayOrDash(row.image_url) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
    { label: 'Dibuat', value: displayOrDash(row.created_at) },
    { label: 'Diubah', value: displayOrDash(row.updated_at) },
  ];
}

/** PURE — teks sel yang aman untuk nilai nullable (`null`/'' → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

// ---------------------------------------------------------------------------
// H3.5 — harga produk: label & ringkasan riwayat (PURE, tanpa I/O)
// ---------------------------------------------------------------------------
/** Label field harga di UI (kunci = nama field backend). */
export const PRICE_FIELD_LABELS: Record<string, string> = {
  sale_price: 'Harga Jual',
  cost_price: 'Harga Pokok (HPP)',
};

/** PURE — label sumber perubahan harga (metadata audit backend). */
export function priceSourceLabel(source: string): string {
  if (source === 'price_endpoint') return 'Endpoint harga';
  if (source === 'product_update') return 'Form produk';

  return displayOrDash(source);
}

/** PURE — label field harga (`sale_price` → 'Harga Jual'). */
export function priceFieldLabel(field: string): string {
  return PRICE_FIELD_LABELS[field] ?? field;
}

/** PURE — pasangan nilai lama → baru untuk satu field (aman kalau metadata kosong). */
export function priceHistoryValues(
  row: MasterProductPriceHistoryRow,
  field: string,
): { before: string; after: string } {
  return {
    before: displayOrDash(row.before[field]),
    after: displayOrDash(row.after[field]),
  };
}

/** PURE — ringkasan satu baris riwayat: `Harga Jual: 50000.00 → 61000.00`. */
export function priceHistorySummary(row: MasterProductPriceHistoryRow): string {
  if (row.fields.length === 0) return 'Perubahan harga';

  return row.fields
    .map((field) => {
      const { before, after } = priceHistoryValues(row, field);

      return `${priceFieldLabel(field)}: ${before} → ${after}`;
    })
    .join(' · ');
}

/** PURE — item detail satu baris riwayat (label/value) untuk halaman riwayat. */
export function priceHistoryItems(row: MasterProductPriceHistoryRow): MasterProductDetailItem[] {
  return [
    { label: 'Perubahan', value: priceHistorySummary(row) },
    { label: 'Sumber', value: priceSourceLabel(row.source) },
    { label: 'Diubah oleh', value: displayOrDash(row.user) },
    { label: 'Waktu', value: displayOrDash(row.timestamp) },
    { label: 'Aksi audit', value: displayOrDash(row.action), mono: true },
  ];
}
