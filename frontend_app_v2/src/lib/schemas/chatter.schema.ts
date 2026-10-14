import { z } from 'zod';

/**
 * chatter.schema.ts — audit trail ter-paginasi (§5.1 + backend-contract §8).
 * Semua chatter dikirim paginated: preview + `next_cursor`, TIDAK semua event sekaligus.
 */

/** Batas preview yang dikirim backend (backend-contract §8: "preview 5 + next_cursor"). */
export const CHATTER_PREVIEW_LIMIT = 5;

export interface ChatterActor {
  id: string;
  name: string;
}

export interface ChatterEvent {
  /** Wajib — dipakai React `key={row.id}` (sabuk pengaman #12). */
  id: string;
  actor: ChatterActor;
  type: string;
  summary: string;
  payload?: Record<string, unknown>;
  created_at: string;
}

export interface ChatterPage {
  preview: ChatterEvent[];
  total_count: number;
  has_more: boolean;
  next_cursor: string | null;
}

export const ChatterActorSchema: z.ZodType<ChatterActor> = z.object({
  id: z.string().min(1),
  name: z.string(),
});

export const ChatterEventSchema: z.ZodType<ChatterEvent> = z.object({
  id: z.string().min(1),
  actor: ChatterActorSchema,
  type: z.string(),
  summary: z.string(),
  payload: z.record(z.string(), z.unknown()).optional(),
  created_at: z.string(),
});

export const ChatterPageSchema: z.ZodType<ChatterPage> = z.object({
  preview: z.array(ChatterEventSchema).max(CHATTER_PREVIEW_LIMIT),
  total_count: z.number().int().nonnegative(),
  has_more: z.boolean(),
  next_cursor: z.string().nullable(),
});
