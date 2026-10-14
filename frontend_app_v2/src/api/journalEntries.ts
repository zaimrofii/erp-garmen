// ADAPTER - satu-satunya pintu data Journal Entry manual MES (H3.4, TANPA logic domain).
//
// H3.4: endpoint `/api/v1/finance/journal-entries/` SUDAH ADA di backend (CRUD model MES
// double-entry + push `account.move` `move_type='entry'` **draft**) → MODE.journalEntries
// = 'real'. `masterAccounts`/`masterJournals` (dropdown akun & journal, read-only) juga
// 'real' — H3.1–H3.3 tidak diubah; posting tetap di Odoo.
import { pickAdapter } from './_adapter';
import * as real from './real/journalEntries';

/** Daftar journal entry + filter (`GET /finance/journal-entries/`) — REAL (H3.4). */
export const fetchJournalEntries = pickAdapter(
  'journalEntries',
  real.fetchJournalEntries,
  real.fetchJournalEntries,
);

/** Detail journal entry (`GET …/<id>/`) — REAL (H3.4). */
export const fetchJournalEntry = pickAdapter(
  'journalEntries',
  real.fetchJournalEntry,
  real.fetchJournalEntry,
);

/** Buat journal entry (`POST …/`) — REAL (H3.4; izin admin/owner). */
export const createJournalEntry = pickAdapter(
  'journalEntries',
  real.createJournalEntry,
  real.createJournalEntry,
);

/** Ubah journal entry (`PUT …/<id>/`, DRAFT-only) — REAL (H3.4). */
export const updateJournalEntry = pickAdapter(
  'journalEntries',
  real.updateJournalEntry,
  real.updateJournalEntry,
);

/** Hapus journal entry (`DELETE …/<id>/`, DRAFT-only) — REAL (H3.4). */
export const deleteJournalEntry = pickAdapter(
  'journalEntries',
  real.deleteJournalEntry,
  real.deleteJournalEntry,
);

/** Transisi journal entry (`confirm`/`done`/`cancel`) — REAL (H3.4). */
export const actJournalEntry = pickAdapter(
  'journalEntries',
  real.actJournalEntry,
  real.actJournalEntry,
);

export {
  buildJournalEntriesPath,
  JOURNAL_ENTRIES_LIMIT_DEFAULT,
  JOURNAL_ENTRIES_LIMIT_MAX,
  JOURNAL_ENTRIES_PATH,
  JOURNAL_ENTRY_ACTIONS,
  journalEntryActionPath,
  readAllowedActions,
  readJournalEntryDetail,
  readJournalEntryLineRow,
  readJournalEntryLines,
  readJournalEntryPage,
  readJournalEntryRow,
  readJournalEntrySaved,
  readJournalEntryState,
  toJournalEntryBody,
  toJournalEntryLineBody,
} from './real/journalEntries';
export type { JournalEntriesParams, JournalEntryAction, JournalEntryPage } from './real/journalEntries';
export { JOURNAL_ENTRY_STATE_LABELS } from '@/types/journal-entry';
export type {
  JournalEntryDetail,
  JournalEntryInput,
  JournalEntryLineInput,
  JournalEntryLineRow,
  JournalEntryRow,
  JournalEntrySaved,
  JournalEntryState,
} from '@/types/journal-entry';
