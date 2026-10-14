// ADAPTER - satu-satunya pintu data Quality Control (TANPA logic domain).
//
// F3A.CLOSE: SELURUH key `/quality/*` = REAL (backend B4/B5/B6/B7b):
//   qcRows   GET  /garmen/qc/           (ScrapAccumulator, kontrak §4.5)
//   qcLog    GET  /quality/defects/     (B4 + G3)
//   qcAql    GET  /quality/aql/         (B5)
//   qcRework GET  /quality/rework/      (B6)
//   qcSubmit POST /quality/defects/     (B7b — scrap delegasi BUNDLE_SCRAP / rework → siklus QC_REWORK)
import { pickAdapter } from './_adapter';
import * as real from './real/qc';
import * as realAql from './real/qcAql';
import * as realDefects from './real/qcLog';
import * as realRework from './real/qcRework';
import * as realSubmit from './real/qcSubmit';

/**
 * Catatan QC nyata (ScrapAccumulator) - offset paginasi.
 * Slot `dummy` diisi implementasi real karena resource ini tidak punya fixture dummy
 * (pola sama `api/devices.ts`); `MODE` tetap satu-satunya saklar.
 */
export const getQcRows = pickAdapter('qcRows', real.getQcRows, real.getQcRows);

/** Detail satu catatan QC nyata (+ `version` untuk optimistic lock). */
export const getQcRow = pickAdapter('qcRows', real.getQcRow, real.getQcRow);

export { QC_PATH, readQcRow, readQcRows } from './real/qc';
export type { QcDetail, QcRow } from '@/types/qc-row';

/** Log defect per bundle (QCPage, DefectLogPage) — REAL (`GET /quality/defects/`). */
export const fetchQCLogs = pickAdapter('qcLog', realDefects.fetchDefects, realDefects.fetchDefects);

export {
  buildQualityDefectsPath,
  QUALITY_DEFECTS_PATH,
  readDefectPage,
  readDefectRow,
} from './real/qcLog';
export type { DefectEntry, DefectPage, DefectRow } from './real/qcLog';

/** Agregat AQL per work center (AQLDashboardPage) — REAL (F3A.CLOSE, `GET /quality/aql/`). */
export const fetchAQLSummaries = pickAdapter(
  'qcAql',
  realAql.fetchAqlSummary,
  realAql.fetchAqlSummary,
);

export { buildQualityAqlPath, QUALITY_AQL_PATH, readAqlReport } from './real/qcAql';
export type { AqlReport, AqlRow, AqlSeverity } from './real/qcAql';

/** Riwayat rework antar work center (ReworkTrackingPage) — REAL (`GET /quality/rework/`). */
export const fetchReworkRecords = pickAdapter(
  'qcRework',
  realRework.fetchRework,
  realRework.fetchRework,
);

export {
  buildQualityReworkPath,
  QUALITY_REWORK_PATH,
  readReworkPage,
  readReworkRow,
} from './real/qcRework';
export type { ReworkPage, ReworkRow } from './real/qcRework';

/**
 * SUBMIT defect dari form QC (QCPage) — REAL (F3A.CLOSE, `POST /quality/defects/`).
 *
 * Body backend memakai `bundle_id` (bukan `bundle_code`); `action='scrap'` didelegasikan
 * server ke aksi bundle `BUNDLE_SCRAP`, `action='rework'` mencatat jejak + siklus QC_REWORK.
 */
export const submitQCRecord = pickAdapter(
  'qcSubmit',
  realSubmit.submitDefect,
  realSubmit.submitDefect,
);

export { readDefectSubmitResult } from './real/qcSubmit';
export type { DefectAction, DefectSubmitInput, DefectSubmitResult } from './real/qcSubmit';


