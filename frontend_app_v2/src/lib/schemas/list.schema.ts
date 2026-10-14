import { z } from 'zod';
import {
  LAYOUT_FIELD_TYPES,
  LayoutFieldOptionSchema,
  LayoutFieldSchema,
  type LayoutField,
  type LayoutFieldOption,
  type LayoutFieldType,
} from './layout.schema';
import { AllowedActionSchema, type AllowedAction } from './action.schema';

/**
 * list.schema.ts — kontrak list view (§5.1).
 * `ListRow.id` WAJIB: dipakai React `key={row.id}` (sabuk pengaman #12, larangan §12.3).
 *
 * Kontrak terkunci (20 Sep 2026):
 * - `ListRow.id` menerima string ATAU number, **dinormalisasi ke string**
 *   (Odoo PK = integer, kode bundle = string).
 * - Filter dieksekusi **server-side** (query param) → tanpa `operator`/`multiple`.
 * - Rows TIDAK ada di metadata: dikirim lewat `ListPage` dari endpoint terpisah
 *   (`GET /api/v1/{resource}?cursor=`). Metadata murni "bentuk" (`ListMeta`).
 */

export interface ListRow {
  id: string;
  [column: string]: unknown;
}

export interface ListFilter {
  name: string;
  label: string;
  type: LayoutFieldType;
  options?: LayoutFieldOption[];
  /** Nilai awal filter. Server-side (query param) → selalu string atau null. */
  default_value?: string | null;
}

export interface ListMeta {
  columns: LayoutField[];
  filters?: ListFilter[];
  actions?: AllowedAction[];
}

/**
 * Envelope halaman data list — endpoint TERPISAH dari metadata.
 * Bentuk sengaja mengikuti `ChatterPage` (rows ↔ preview, cursor, has_more) agar konsisten.
 */
export interface ListPage {
  rows: ListRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: string | null;
}

/** Issue Zod untuk satu baris list (tipe resmi Zod 4 — `z.ZodIssue` deprecated). */
export type ListRowIssue = z.core.$ZodIssue;

export interface ListRowInvalid {
  index: number;
  issues: ListRowIssue[];
}

export type ListPageResult =
  | { ok: true; page: ListPage; invalid: ListRowInvalid[] }
  | { ok: false; message: string; issues: ListRowIssue[] };

export const ListRowSchema: z.ZodType<ListRow> = z
  .object({
    // Odoo PK = integer (`django_app/integrations/erp_sync/adapters/base.py`: `ids: Sequence[int]`),
    // kode bundle = string ("B-001-001"). Normalisasi ke string → `key={row.id}` selalu stabil.
    id: z.union([z.string().min(1), z.number()]).transform((value) => String(value)),
  })
  .catchall(z.unknown());

export const ListFilterSchema: z.ZodType<ListFilter> = z.object({
  name: z.string().min(1),
  label: z.string(),
  type: z.enum(LAYOUT_FIELD_TYPES),
  options: z.array(LayoutFieldOptionSchema).optional(),
  default_value: z.string().nullable().optional(),
});

export const ListMetaSchema: z.ZodType<ListMeta> = z.object({
  columns: z.array(LayoutFieldSchema),
  filters: z.array(ListFilterSchema).optional(),
  actions: z.array(AllowedActionSchema).optional(),
});

export const ListPageSchema: z.ZodType<ListPage> = z.object({
  rows: z.array(ListRowSchema),
  total_count: z.number().int().nonnegative(),
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
});

/**
 * Envelope tanpa validasi isi baris — dipakai `parseListPageSafe` supaya satu baris rusak
 * tidak menjatuhkan seluruh halaman (anti-WSoD). Sengaja tidak diekspor.
 */
const ListPageEnvelopeSchema = z.object({
  rows: z.array(z.unknown()),
  total_count: z.number().int().nonnegative(),
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
});

function isObjectLike(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function parseListPageRaw(raw: unknown): ListPageResult {
  if (!isObjectLike(raw)) {
    return { ok: false, message: 'ListPage harus berupa object JSON.', issues: [] };
  }

  const envelope = ListPageEnvelopeSchema.safeParse(raw);

  if (!envelope.success) {
    return {
      ok: false,
      message: `Envelope ListPage gagal divalidasi (${envelope.error.issues.length} issue).`,
      issues: envelope.error.issues,
    };
  }

  const rows: ListRow[] = [];
  const invalid: ListRowInvalid[] = [];

  for (const [index, candidate] of envelope.data.rows.entries()) {
    const parsed = ListRowSchema.safeParse(candidate);

    if (parsed.success) {
      rows.push(parsed.data);
    } else {
      invalid.push({ index, issues: parsed.error.issues });
    }
  }

  return {
    ok: true,
    page: {
      rows,
      total_count: envelope.data.total_count,
      has_more: envelope.data.has_more,
      next_cursor: envelope.data.next_cursor,
    },
    invalid,
  };
}

/**
 * Versi tahan-row-rusak: baris yang tidak valid (mis. tanpa `id`) **dibuang & dilaporkan**
 * di `invalid`, sisanya tetap dirender. Selalu return union, tidak pernah throw.
 */
export function parseListPageSafe(raw: unknown): ListPageResult {
  try {
    return parseListPageRaw(raw);
  } catch (caught) {
    const detail = caught instanceof Error ? caught.message : typeof caught;
    return { ok: false, message: `Tidak bisa memproses ListPage: ${detail}.`, issues: [] };
  }
}
