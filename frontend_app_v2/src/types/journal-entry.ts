/**
 * journal-entry.ts — baris Journal Entry manual MES dari `/api/v1/finance/journal-entries/` (H3.4).
 *
 * Field = PERSIS `django_app/apps_industry/garment/services/journal_entry_services.py`:
 *   * `code` = nomor MES `JE-<TAHUN>-<URUT>` (dibuat `next_number('JE')`, MES-only);
 *   * `journal_*` = mirror `master.Journal` + field aditif `journal_type` (pull Odoo);
 *     entry manual **hanya boleh** di journal `general` (keputusan STEP 0 H3.4);
 *   * `total_debit`/`total_credit` = denormalisasi Σ baris (guard double-entry MES);
 *   * `state` = state BISNIS (`DRAFT`/`CONFIRMED`/`SENT`/`DONE`/`CANCELLED`); kegagalan
 *     push **bukan** state — terlihat di `odoo_sync_status` (`SyncRecord`);
 *   * `odoo_id` = id `account.move` Odoo (`null` = belum terkirim).
 *
 * Detail menambah `lines[]` (baris jurnal) + `line_count` + info sync + `allowed_actions`.
 * POST/PUT/aksi menambah `{sync_record_id, task_id, queued}`.
 *
 * ⚠️ **Posting BUKAN tanggung jawab MES**: entry dibuat **draft** di Odoo dan akuntan
 * yang mem-posting (`action_post` tidak pernah dipanggil).
 */

/** State bisnis journal entry (harus sama dengan `JournalEntry.State` backend). */
export type JournalEntryState = 'DRAFT' | 'CONFIRMED' | 'SENT' | 'DONE' | 'CANCELLED';

/** Satu baris jurnal (debit XOR credit; ≥ 2 baris per entry). */
export interface JournalEntryLineRow {
  id: number;
  account_id: number;
  account_code: string | null;
  account_name: string | null;
  partner_id: number | null;
  partner_name: string | null;
  name: string;
  debit: string;
  credit: string;
}

export interface JournalEntryRow {
  id: number;
  code: string;
  journal_id: number;
  journal_code: string | null;
  journal_name: string | null;
  journal_type: string;
  entry_date: string | null;
  ref: string;
  memo: string;
  total_debit: string;
  total_credit: string;
  state: JournalEntryState;
  odoo_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail entry = baris list + baris jurnal + info sync + aksi yang boleh. */
export interface JournalEntryDetail extends JournalEntryRow {
  lines: JournalEntryLineRow[];
  line_count: number;
  odoo_sync_status: string | null;
  odoo_sync_error: string | null;
  allowed_actions: string[];
}

/** Satu baris pada body POST/PUT (angka sudah `number`; backend menegakkan balance). */
export interface JournalEntryLineInput {
  account_id: number;
  partner_id?: number | null;
  name?: string;
  debit: number;
  credit: number;
}

/** Body POST/PUT: header + `lines[]` menyatu (baris diganti utuh saat PUT). */
export interface JournalEntryInput {
  journal_id: number;
  entry_date: string;
  ref?: string;
  memo?: string;
  notes?: string;
  lines: JournalEntryLineInput[];
}

/** Baris hasil simpan (POST/PUT/aksi): detail + jejak sinkronisasi H3.4. */
export interface JournalEntrySaved extends JournalEntryDetail {
  sync_record_id: number | null;
  task_id: string | null;
  queued: boolean;
}

/** Toleransi balance backend (`journal_entry_services.BALANCE_TOLERANCE`) — dipakai UI. */
export const JOURNAL_ENTRY_BALANCE_TOLERANCE = 0.01;

/** Batas `ref`/`memo` backend (`journal_entry_services.MAX_*_LENGTH`). */
export const JOURNAL_ENTRY_REF_MAX_LENGTH = 64;
export const JOURNAL_ENTRY_MEMO_MAX_LENGTH = 255;

/** Label state journal entry (bahasa Indonesia) untuk badge/tabel. */
export const JOURNAL_ENTRY_STATE_LABELS: Record<JournalEntryState, string> = {
  DRAFT: 'Draft',
  CONFIRMED: 'Terkonfirmasi',
  SENT: 'Terkirim ke Odoo',
  DONE: 'Selesai',
  CANCELLED: 'Dibatalkan',
};
