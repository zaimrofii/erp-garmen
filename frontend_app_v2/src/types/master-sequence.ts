/**
 * master-sequence.ts — kontrak Number Sequence (Sprint C).
 *
 * Endpoint: `/api/v1/settings/sequences/` (+ `/<code>/preview/`, `/<code>/`)
 * di `apps_industry/garment/api/settings/views.py`. Nomor berbentuk
 * ``<PREFIX>-<YEAR>-<SEQ:04d>`` dan **reset per tahun** (satu baris per `(code, year)`).
 *
 * **MES-only**: `ir.sequence` Odoo = counter internal dokumen Odoo sendiri (probe
 * STEP 0: 19 field, 37 record hidup, `code` tidak required) ⇒ nomor MES tidak dikirim
 * (ledger `SKIPPED`), tanpa `odoo_id`.
 *
 * `snake_case` backend dipakai apa adanya (pola H1.1–H1.9/Sprint C).
 */

/** Satu baris sequence (list & respons PUT). */
export interface MasterSequenceRow {
  id: number;
  code: string;
  name: string;
  prefix: string;
  year: number;
  last_seq: number;
  padding: number;
  is_active: boolean;
  /** Pratinjau nomor berikutnya (dihitung backend, tanpa increment). */
  next_number: string;
  created_at: string;
  updated_at: string;
}

/** Respons `GET /settings/sequences/<code>/preview/` (tanpa `id`/timestamp). */
export interface SequencePreview {
  code: string;
  name: string;
  prefix: string;
  year: number;
  last_seq: number;
  padding: number;
  is_active: boolean;
  next_number: string;
}

/**
 * Payload `PUT /settings/sequences/<code>/`.
 *
 * Hanya `name`/`prefix`/`padding`/`active` — `code`/`year`/`last_seq` **ditolak backend**
 * (400) karena counter hanya naik lewat `next_number`.
 */
export interface MasterSequenceInput {
  name?: string;
  prefix?: string;
  padding?: number;
  active?: boolean;
}

/**
 * Payload `POST /settings/sequences/` (H5.3 — buat sequence baru).
 *
 * `code` wajib (`^[A-Z0-9]{2,16}$`, backend auto-upper) dan `name` wajib; `prefix`
 * opsional (default = `code`, `^[A-Z0-9-]{1,16}$`); `padding` opsional (default 4,
 * 1..10). `year`/`last_seq`/`is_active` **selalu** diisi backend (tahun berjalan /
 * `?year=`).
 */
export interface MasterSequenceCreateInput {
  code: string;
  name: string;
  prefix?: string;
  padding?: number;
}
