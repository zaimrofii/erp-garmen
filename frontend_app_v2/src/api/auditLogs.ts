// ADAPTER - satu-satunya pintu data Audit Log Viewer (H5.5, READ-ONLY).
//
// H5.5: endpoint `/api/v1/settings/audit/` (+ `/<id>/`) SUDAH ADA di backend →
// MODE.auditLogs = 'real' (`_adapter.ts`), jadi tidak ada implementasi dummy.
//
// **APPEND-ONLY**: adapter ini **hanya** GET (daftar + detail). Tidak ada
// create/update/delete — jejak audit tidak pernah diubah dari UI.
import { pickAdapter } from './_adapter';
import * as real from './real/auditLogs';

/** Daftar audit + filter + paging (`GET /settings/audit/`) — REAL (H5.5). */
export const fetchAuditLogs = pickAdapter(
  'auditLogs',
  real.fetchAuditLogs,
  real.fetchAuditLogs,
);

/** Detail satu audit (`GET /settings/audit/<id>/`) — REAL (H5.5). */
export const fetchAuditLog = pickAdapter(
  'auditLogs',
  real.fetchAuditLog,
  real.fetchAuditLog,
);

export {
  auditLogDetailPath,
  buildAuditLogsPath,
  EMPTY_AUDIT_FILTERS,
  parseAuditResult,
  parseUserId,
  readAuditLogDetail,
  readAuditLogPage,
  readAuditLogRow,
  readJsonObject,
  SETTINGS_AUDIT_PATH,
} from './real/auditLogs';
export type {
  AuditLogDetail,
  AuditLogFilters,
  AuditLogPage,
  AuditLogRow,
  AuditResult,
} from '@/types/audit-log';
export {
  AUDIT_CURSOR_MAX,
  AUDIT_LIMIT_DEFAULT,
  AUDIT_LIMIT_MAX,
  AUDIT_LIMIT_MIN,
  AUDIT_MASK,
  AUDIT_RESULTS,
} from '@/types/audit-log';
