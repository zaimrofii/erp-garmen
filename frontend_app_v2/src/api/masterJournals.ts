// ADAPTER - satu-satunya pintu data master Journal (H3.4, TANPA logic domain).
//
// H3.4: endpoint `/api/v1/master/journals/` SUDAH ADA di backend (mirror I1 + field
// aditif `journal_type`, **read-only**) → MODE.masterJournals = 'real' (`_adapter.ts`),
// jadi tidak ada implementasi dummy untuk resource ini.
import { pickAdapter } from './_adapter';
import * as real from './real/masterJournals';

/** Daftar journal + filter (`GET /master/journals/`) — REAL (H3.4). */
export const fetchJournals = pickAdapter('masterJournals', real.fetchJournals, real.fetchJournals);

/** Detail journal (`GET /master/journals/<id>/`) — REAL (H3.4). */
export const fetchJournal = pickAdapter('masterJournals', real.fetchJournal, real.fetchJournal);

export {
  buildMasterJournalsPath,
  JOURNALS_LIMIT_DEFAULT,
  JOURNALS_LIMIT_MAX,
  MASTER_JOURNALS_PATH,
  readMasterJournalPage,
  readMasterJournalRow,
} from './real/masterJournals';
export type { MasterJournalPage, MasterJournalsParams } from './real/masterJournals';
export type { MasterJournalRow } from '@/types/master-journal';
