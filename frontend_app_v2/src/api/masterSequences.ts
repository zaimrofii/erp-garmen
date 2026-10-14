// ADAPTER - satu-satunya pintu data Number Sequence (Sprint C, TANPA logic domain).
//
// Sprint C: endpoint `/api/v1/settings/sequences/` (+ `/<code>/preview/`, `/<code>/`)
// SUDAH ADA di backend → MODE.masterSequences = 'real' (`_adapter.ts`), tanpa dummy.
// **MES-only**: `ir.sequence` Odoo = counter internal dokumen Odoo sendiri ⇒ nomor MES
// tidak disinkronkan (ledger `SKIPPED`), tanpa `odoo_id`.
import { pickAdapter } from './_adapter';
import * as real from './real/masterSequences';

/** Daftar sequence (`GET /settings/sequences/`) — REAL (Sprint C). */
export const fetchSequences = pickAdapter(
  'masterSequences',
  real.fetchSequences,
  real.fetchSequences,
);

/** Pratinjau nomor berikutnya (`GET …/<code>/preview/`, tanpa increment) — REAL. */
export const previewSequenceNumber = pickAdapter(
  'masterSequences',
  real.previewNumber,
  real.previewNumber,
);

/** Ubah prefix/padding/aktif/nama (`PUT …/<code>/`, ADMIN/OWNER) — REAL. */
export const updateSequence = pickAdapter(
  'masterSequences',
  real.updateSequence,
  real.updateSequence,
);

/** Buat sequence baru (`POST /settings/sequences/`, ADMIN/OWNER) — REAL (H5.3). */
export const createSequence = pickAdapter(
  'masterSequences',
  real.createSequence,
  real.createSequence,
);

/** Nonaktifkan/soft delete (`DELETE …/<code>/`, ADMIN/OWNER) — REAL (H5.3). */
export const deleteSequence = pickAdapter(
  'masterSequences',
  real.deleteSequence,
  real.deleteSequence,
);

export {
  buildMasterSequencesPath,
  readMasterSequencePage,
  readMasterSequenceRow,
  readSequencePreview,
  SEQUENCES_LIMIT_DEFAULT,
  SEQUENCES_LIMIT_MAX,
  sequenceCreatePath,
  sequenceDetailPath,
  sequencePreviewPath,
  SETTINGS_SEQUENCES_PATH,
  toMasterSequenceBody,
  toMasterSequenceCreateBody,
} from './real/masterSequences';
export type { MasterSequencePage, MasterSequencesParams } from './real/masterSequences';
export type {
  MasterSequenceCreateInput,
  MasterSequenceInput,
  MasterSequenceRow,
  SequencePreview,
} from '@/types/master-sequence';
