import { z } from 'zod';
import {
  LAYOUT_FIELD_TYPES,
  LayoutFieldOptionSchema,
  type LayoutFieldOption,
  type LayoutFieldType,
} from './layout.schema';

/**
 * action.schema.ts — kontrak `allowed_actions` (§5.1 + backend-contract §2.2).
 * Tombol frontend TIDAK boleh hardcode: semua datang dari schema ini.
 */

/** Hint mode dari backend. Prioritas 2 — `TRANSITION_MODE` (transition-rules.ts) selalu menang. */
export const ACTION_MODES = ['optimistic', 'pessimistic'] as const;

export type ActionMode = (typeof ACTION_MODES)[number];

/**
 * PURE — D6: normalisasi `mode` dari metadata ke LOWERCASE kanonik.
 *
 * Kontrak backend v4.3 mengirim `"mode": "optimistic"` (lowercase). Kalau ada sumber lain
 * mengirim `"OPTIMISTIC"`, nilai itu **tidak boleh** dianggap valid apa adanya (bisa membuat
 * perbandingan `mode === 'optimistic'` gagal) → di-lowercase dulu; di luar
 * `optimistic`/`pessimistic` → `undefined` (biar `TRANSITION_MODE` yang menentukan).
 */
export function normalizeActionMode(value: unknown): ActionMode | undefined {
  if (typeof value !== 'string') return undefined;

  const candidate = value.trim().toLowerCase();

  return (ACTION_MODES as readonly string[]).includes(candidate)
    ? (candidate as ActionMode)
    : undefined;
}

export interface ActionConfirm {
  title: string;
  message: string;
}

export interface ActionFormField {
  name: string;
  label: string;
  type: LayoutFieldType;
  required?: boolean;
  options?: LayoutFieldOption[];
  widget?: string;
}

export interface AllowedAction {
  id: string;
  label: string;
  mode?: ActionMode;
  confirm?: ActionConfirm;
  form?: ActionFormField[];
  idempotent?: boolean;
  /**
   * Path aksi dari backend — **RELATIF** ke `VITE_API_BASE_URL` yang sudah termasuk
   * `/api/v1` (mis. `/garmen/bundles/16/BUNDLE_START/`; kontrak v4.3 §3.2). D1: jangan
   * prepend baseUrl sendiri. Dipakai lewat `resolveActionPath()` (`lib/action-runner.ts`)
   * atau dikirim apa adanya ke `ApiClient` (yang menambahkan baseUrl + anti double-prefix).
   * Kalau backend tidak mengirimnya → `defaultActionPath()` sebagai konvensi terakhir.
   */
  endpoint?: string;
}

export const ActionConfirmSchema: z.ZodType<ActionConfirm> = z.object({
  title: z.string(),
  message: z.string(),
});

export const ActionFormFieldSchema: z.ZodType<ActionFormField> = z.object({
  name: z.string().min(1),
  label: z.string(),
  type: z.enum(LAYOUT_FIELD_TYPES),
  required: z.boolean().optional(),
  options: z.array(LayoutFieldOptionSchema).optional(),
  widget: z.string().optional(),
});

export const AllowedActionSchema: z.ZodType<AllowedAction> = z.object({
  id: z.string().min(1),
  label: z.string(),
  mode: z.enum(ACTION_MODES).optional(),
  confirm: ActionConfirmSchema.optional(),
  form: z.array(ActionFormFieldSchema).optional(),
  idempotent: z.boolean().optional(),
  endpoint: z.string().min(1).optional(),
});
