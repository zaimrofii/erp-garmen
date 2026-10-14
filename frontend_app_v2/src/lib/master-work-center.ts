/**
 * master-work-center.ts — logic PURE halaman master Work Center (H1.7).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, tag input (tambah/hapus/dedupe),
 * konversi row ↔ form, pemformatan kapasitas, dan penyusunan item detail.
 *
 * Aturan yang ditegakkan klien (backend tetap penjaga terakhir → pesan 400-nya
 * diteruskan apa adanya ke Toast):
 *   * ``code`` & ``name`` wajib (kode WC = identitas operasional, TIDAK
 *     dibangkitkan otomatis seperti BOM/Partner);
 *   * ``capacity_per_hour`` angka ≥ 0;
 *   * ``capability_tags``: maksimal 20 tag, tiap tag ≤ 32 karakter;
 *   * ``wc_type`` ≤ 64 karakter (free-form — mis. SEWING/CUTTING/QC).
 */
import type {
  MasterWorkCenterDetail,
  MasterWorkCenterInput,
  MasterWorkCenterRow,
} from '@/types/master-work-center';

/** Nilai form (input teks = string; tag = daftar; aktif = checkbox). */
export interface WorkCenterFormValues {
  code: string;
  name: string;
  wc_type: string;
  capability_tags: string[];
  capacity_per_hour: string;
  description: string;
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface WorkCenterFormErrors {
  code?: string;
  name?: string;
  wc_type?: string;
  capability_tags?: string;
  capacity_per_hour?: string;
  description?: string;
}

/** Nilai awal form "Work Center Baru". */
export const EMPTY_WORK_CENTER_FORM: WorkCenterFormValues = {
  code: '',
  name: '',
  wc_type: '',
  capability_tags: [],
  capacity_per_hour: '0',
  description: '',
  active: true,
};

/** Batas panjang/angka (selaras model & service backend — beda = 400, bukan 500). */
export const MAX_CODE_LENGTH = 64;
export const MAX_NAME_LENGTH = 150;
export const MAX_WC_TYPE_LENGTH = 64;
export const MAX_DESCRIPTION_LENGTH = 2000;
export const MAX_TAGS = 20;
export const MAX_TAG_LENGTH = 32;
export const MAX_CAPACITY = 99999999.99;

/** Saran tipe stasiun (free-form tetap boleh — hanya usul di datalist/placeholder). */
export const WC_TYPE_SUGGESTIONS = ['CUTTING', 'SEWING', 'SABLON', 'QC', 'FINISHING', 'PACKING'];

/** PURE — tag: trim, buang kosong, dedupe case-insensitive (huruf dipertahankan). */
export function normalizeTags(tags: readonly string[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();

  for (const raw of tags) {
    const tag = raw.trim();
    if (tag.length === 0) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(tag);
  }

  return result;
}

/** PURE — tambah tag ke daftar (trim + dedupe); daftar baru, bukan mutasi. */
export function addTag(tags: readonly string[], value: string): string[] {
  return normalizeTags([...tags, value]);
}

/** PURE — hapus tag berdasarkan indeks (indeks ngawur = daftar apa adanya). */
export function removeTag(tags: readonly string[], index: number): string[] {
  if (!Number.isInteger(index) || index < 0 || index >= tags.length) return [...tags];

  return tags.filter((_, position) => position !== index);
}

/** PURE — validasi form; objek KOSONG berarti boleh dikirim. */
export function validateWorkCenterForm(values: WorkCenterFormValues): WorkCenterFormErrors {
  const errors: WorkCenterFormErrors = {};

  const code = values.code.trim();
  if (code.length === 0) {
    errors.code = 'Kode work center wajib diisi (mis. SEWING-1).';
  } else if (code.length > MAX_CODE_LENGTH) {
    errors.code = `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`;
  }

  const name = values.name.trim();
  if (name.length === 0) {
    errors.name = 'Nama work center wajib diisi.';
  } else if (name.length > MAX_NAME_LENGTH) {
    errors.name = `Nama maksimal ${String(MAX_NAME_LENGTH)} karakter.`;
  }

  const wcType = values.wc_type.trim();
  if (wcType.length > MAX_WC_TYPE_LENGTH) {
    errors.wc_type = `Tipe maksimal ${String(MAX_WC_TYPE_LENGTH)} karakter.`;
  }

  const tags = normalizeTags(values.capability_tags);
  if (tags.length > MAX_TAGS) {
    errors.capability_tags = `Tag kapabilitas maksimal ${String(MAX_TAGS)} buah.`;
  } else {
    const tooLong = tags.find((tag) => tag.length > MAX_TAG_LENGTH);
    if (tooLong !== undefined) {
      errors.capability_tags = `Tag '${tooLong}' maksimal ${String(MAX_TAG_LENGTH)} karakter.`;
    }
  }

  const capacityRaw = values.capacity_per_hour.trim();
  const capacity = Number(capacityRaw);
  if (capacityRaw.length === 0) {
    errors.capacity_per_hour = 'Kapasitas per jam wajib diisi (0 kalau belum diukur).';
  } else if (!Number.isFinite(capacity)) {
    errors.capacity_per_hour = 'Kapasitas per jam harus angka.';
  } else if (capacity < 0) {
    errors.capacity_per_hour = 'Kapasitas per jam tidak boleh negatif.';
  } else if (capacity > MAX_CAPACITY) {
    errors.capacity_per_hour = `Kapasitas per jam maksimal ${String(MAX_CAPACITY)}.`;
  }

  const description = values.description.trim();
  if (description.length > MAX_DESCRIPTION_LENGTH) {
    errors.description = `Catatan maksimal ${String(MAX_DESCRIPTION_LENGTH)} karakter.`;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isWorkCenterFormValid(errors: WorkCenterFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris backend → nilai form (dipakai halaman edit). */
export function workCenterFormFromRow(row: MasterWorkCenterRow): WorkCenterFormValues {
  return {
    code: row.code,
    name: row.name,
    wc_type: row.wc_type,
    capability_tags: [...row.capability_tags],
    capacity_per_hour: String(row.capacity_per_hour),
    description: row.description,
    active: row.active,
  };
}

/** PURE — nilai form → body API (kode/nama/tipe/catatan di-trim, tag dinormalisasi). */
export function workCenterInputFromForm(
  values: WorkCenterFormValues,
): MasterWorkCenterInput {
  const capacity = Number(values.capacity_per_hour.trim());

  return {
    code: values.code.trim(),
    name: values.name.trim(),
    wc_type: values.wc_type.trim(),
    capability_tags: normalizeTags(values.capability_tags),
    capacity_per_hour: Number.isFinite(capacity) ? capacity : 0,
    description: values.description.trim(),
    active: values.active,
  };
}

/** PURE — teks aman untuk nilai kosong (`''`/`null` → '-'). */
export function displayOrDash(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '-';
  const text = String(value).trim();

  return text.length === 0 ? '-' : text;
}

/** PURE — kapasitas siap tampil: `40.5` → `40,5/jam`, `0` → `-` (belum diukur). */
export function formatCapacity(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '-';
  const text = Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '');

  return `${text.replace('.', ',')}/jam`;
}

/** PURE — label jumlah bundle aktif (dasar guard soft delete). */
export function activeBundlesLabel(detail: MasterWorkCenterDetail): string {
  return `${String(detail.active_bundles_count)} bundle aktif`;
}

/** PURE — label lini produksi yang memuat WC ini (`-` kalau belum masuk lini). */
export function productionLinesLabel(detail: MasterWorkCenterDetail): string {
  if (detail.production_lines.length === 0) return '-';

  return detail.production_lines.map((line) => line.code).join(', ');
}

/** Satu baris detail work center (label + nilai siap tampil). */
export interface MasterWorkCenterDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE - daftar field halaman detail WC (urutan tetap). */
export function workCenterDetailItems(row: MasterWorkCenterRow): MasterWorkCenterDetailItem[] {
  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Nama', value: displayOrDash(row.name) },
    { label: 'Tipe Stasiun', value: displayOrDash(row.wc_type) || '—' },
    { label: 'Kapasitas', value: formatCapacity(row.capacity_per_hour) },
    { label: 'Tag Kapabilitas', value: row.capability_tags.join(', ') || '-' },
    { label: 'Catatan', value: displayOrDash(row.description) },
    { label: 'Status', value: row.active ? 'Aktif' : 'Nonaktif' },
    { label: 'Sinkronisasi', value: 'MES-only (tidak dikirim ke Odoo)' },
  ];
}
