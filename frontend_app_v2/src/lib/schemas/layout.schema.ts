import { z } from 'zod';

/**
 * layout.schema.ts — kontrak layout/field metadata (§5.1).
 * Satu file = satu konsep (larangan §12.2: semua schema di satu file → circular reference).
 */

/** Tipe field yang diizinkan backend. */
export const LAYOUT_FIELD_TYPES = [
  'string',
  'number',
  'boolean',
  'date',
  'enum',
  'reference',
] as const;

export type LayoutFieldType = (typeof LAYOUT_FIELD_TYPES)[number];

export interface LayoutFieldOption {
  value: string;
  label: string;
}

export interface LayoutField {
  name: string;
  label: string;
  type: LayoutFieldType;
  /**
   * Kanonik snake_case — KONTRAK TERKUNCI (20 Sep 2026). Django WAJIB kirim `read_only`;
   * alias `readonly` TIDAK diterima (field kontrak lain juga snake_case: `schema_version`,
   * `current_state`, `action_id`, `next_cursor` — sejalan dengan default DRF).
   */
  read_only?: boolean;
  required?: boolean;
  options?: LayoutFieldOption[];
  widget?: string;
  /**
   * Batas nilai: **angka** untuk `type: 'number'`, **ISO date string** untuk `type: 'date'`.
   * Satu name untuk dua maksud supaya backend tidak perlu dua field; renderer memfilter sesuai tipe
   * (`pickNumericBound` / `pickDateBound` di `core/fields/field-props.ts`).
   */
  min?: number | string;
  max?: number | string;
  /** Hanya dipakai `type: 'number'`. */
  step?: number;
  /** Hanya dipakai `type: 'string'`. */
  maxLength?: number;
}

export interface LayoutSection {
  id: string;
  label: string;
  fields: LayoutField[];
  columns?: number;
}

export interface LayoutMeta {
  sections: LayoutSection[];
  columns?: LayoutField[];
}

export const LayoutFieldOptionSchema: z.ZodType<LayoutFieldOption> = z.object({
  value: z.string(),
  label: z.string(),
});

export const LayoutFieldSchema: z.ZodType<LayoutField> = z.object({
  name: z.string().min(1),
  label: z.string(),
  type: z.enum(LAYOUT_FIELD_TYPES),
  read_only: z.boolean().optional(),
  required: z.boolean().optional(),
  options: z.array(LayoutFieldOptionSchema).optional(),
  widget: z.string().optional(),
  min: z.union([z.number(), z.string()]).optional(),
  max: z.union([z.number(), z.string()]).optional(),
  step: z.number().optional(),
  maxLength: z.number().int().positive().optional(),
});

export const LayoutSectionSchema: z.ZodType<LayoutSection> = z.object({
  id: z.string().min(1),
  label: z.string(),
  fields: z.array(LayoutFieldSchema),
  columns: z.number().int().positive().optional(),
});

export const LayoutMetaSchema: z.ZodType<LayoutMeta> = z.object({
  sections: z.array(LayoutSectionSchema),
  columns: z.array(LayoutFieldSchema).optional(),
});
