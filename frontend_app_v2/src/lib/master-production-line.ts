/**
 * master-production-line.ts — logic PURE halaman master Production Line (H1.8).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, konversi row ↔ form, ringkasan anggota
 * work center, dan penyusunan item detail.
 *
 * Tag kapabilitas memakai **aturan & helper yang sama dengan Work Center H1.7**
 * (diimpor dari `lib/master-work-center.ts`): trim, buang kosong, dedupe
 * case-insensitive, huruf dipertahankan, ≤ 20 tag × ≤ 32 karakter. Backend tetap
 * penjaga terakhir (400 diteruskan ke Toast apa adanya).
 *
 * Aturan yang ditegakkan klien:
 *   * `code` & `name` wajib (kode lini = identitas, TIDAK auto-generate);
 *   * `description` ≤ 2000 karakter;
 *   * M2M `work_center_ids` **boleh kosong** (lini tanpa anggota) — replace penuh
 *     saat submit (backend `work_centers.set()` di dalam `transaction.atomic`).
 */
import {
  addTag,
  MAX_TAG_LENGTH,
  MAX_TAGS,
  normalizeTags,
  removeTag,
} from '@/lib/master-work-center';
import type {
  MasterProductionLineDetail,
  MasterProductionLineInput,
  MasterProductionLineRow,
} from '@/types/master-production-line';

/** Nilai form (input teks = string; tag & anggota WC = daftar; aktif = checkbox). */
export interface ProductionLineFormValues {
  code: string;
  name: string;
  description: string;
  capability_tags: string[];
  work_center_ids: number[];
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface ProductionLineFormErrors {
  code?: string;
  name?: string;
  description?: string;
  capability_tags?: string;
}

/** Nilai awal form "Production Line Baru". */
export const EMPTY_PRODUCTION_LINE_FORM: ProductionLineFormValues = {
  code: '',
  name: '',
  description: '',
  capability_tags: [],
  work_center_ids: [],
  active: true,
};

/** Batas panjang (selaras service backend — beda = 400, bukan 500). */
export const MAX_CODE_LENGTH = 64;
export const MAX_NAME_LENGTH = 150;
export const MAX_DESCRIPTION_LENGTH = 2000;

/** Batas tag direekspor supaya halaman tidak mengimpor dua modul lib. */
export { MAX_TAGS, MAX_TAG_LENGTH };

/**
 * Helper tag dipakai ulang dari H1.7 (WORK CENTER) supaya aturan klien identik:
 * `addTag` (tambah + dedupe) & `removeTag` (hapus per indeks, non-mutasi).
 */
export { addTag, removeTag };

/** PURE — tag: trim, buang kosong, dedupe case-insensitive (huruf dipertahankan). */
export function normalizeCapabilityTags(tags: readonly string[]): string[] {
  return normalizeTags(tags);
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateProductionLineForm(
  values: ProductionLineFormValues,
): ProductionLineFormErrors {
  const errors: ProductionLineFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode production line wajib diisi (mis. LINE-A).';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  const name = values.name.trim();
  if (name.length === 0) {
    errors.name = 'Nama production line wajib diisi.';
  } else if (name.length > MAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_NAME_LENGTH)} karakter.`;
  }

  const description = values.description.trim();
  if (description.length > MAX_DESCRIPTION_LENGTH) {
    errors.description = `Catatan maksimal ${String(MAX_DESCRIPTION_LENGTH)} karakter.`;
  }

  const tags = normalizeCapabilityTags(values.capability_tags);
  if (tags.length > MAX_TAGS) {
    errors.capability_tags = `Tag kapabilitas maksimal ${String(MAX_TAGS)} buah.`;
  } else {
    const tooLong = tags.find((tag) => tag.length > MAX_TAG_LENGTH);
    if (tooLong !== undefined) {
      errors.capability_tags = `Tag '${tooLong}' maksimal ${String(MAX_TAG_LENGTH)} karakter.`;
    }
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isProductionLineFormValid(errors: ProductionLineFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function productionLineFormFromRow(
  row: MasterProductionLineRow,
): ProductionLineFormValues {
  return {
    code: row.code,
    name: row.name,
    description: row.description,
    capability_tags: [...row.capability_tags],
    work_center_ids: [...row.work_center_ids],
    active: row.active,
  };
}

/** PURE — nilai form → body API (teks di-trim, tag dinormalisasi, M2M replace penuh). */
export function productionLineInputFromForm(
  values: ProductionLineFormValues,
): MasterProductionLineInput {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    description: values.description.trim(),
    capability_tags: normalizeCapabilityTags(values.capability_tags),
    work_center_ids: [...new Set(values.work_center_ids)].sort((a, b) => a - b),
    active: values.active,
  };
}

/** PURE — toggle satu work center di daftar anggota (urut naik, tanpa duplikat). */
export function toggleWorkCenter(ids: readonly number[], workCenterId: number): number[] {
  if (ids.includes(workCenterId)) {
    return ids.filter((id) => id !== workCenterId);
  }

  return [...ids, workCenterId].sort((a, b) => a - b);
}

/** PURE — teks aman untuk nilai kosong (`''`/`null` → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE — ringkasan anggota WC untuk kolom list: `SEWING-1, QC-1` (fallback '-'). */
export function workCentersSummary(row: MasterProductionLineRow): string {
  if (row.work_center_names.length === 0) return '-';

  const shown = row.work_center_names.slice(0, 3).join(', ');
  const extra = row.work_center_names.length - 3;

  return extra > 0 ? `${shown} +${String(extra)}` : shown;
}

/** PURE — label jumlah anggota WC (`3 work center`). */
export function workCentersCountLabel(row: MasterProductionLineRow): string {
  return `${String(row.work_centers_count)} work center`;
}

/** PURE — label jumlah bundle aktif (dasar guard soft delete). */
export function activeBundlesLabel(detail: MasterProductionLineDetail): string {
  return `${String(detail.active_bundles_count)} bundle aktif`;
}

/** PURE — label jumlah allocation rule (info, tidak memblokir soft delete). */
export function allocationRulesLabel(detail: MasterProductionLineDetail): string {
  return `${String(detail.allocation_rules_count)} aturan alokasi`;
}

/** Satu baris detail production line (label + nilai siap tampil). */
export interface MasterProductionLineDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail lini (urutan tetap). */
export function productionLineDetailItems(
  row: MasterProductionLineRow,
): MasterProductionLineDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Tag Kapabilitas', value: row.capability_tags.join(', ') || '-' },
    { label: 'Anggota', value: workCentersCountLabel(row) },
    { label: 'Aturan Alokasi', value: String(row.allocation_rules_count) },
    { label: 'Catatan', value: displayOrDash(row.description) },
    { label: 'Status', value: row.active ? 'Aktif' : 'Nonaktif' },
    { label: 'Sinkronisasi', value: 'MES-only (tidak dikirim ke Odoo)' },
  ];
}
