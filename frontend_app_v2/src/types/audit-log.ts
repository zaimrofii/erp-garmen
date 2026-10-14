/**
 * audit-log.ts — kontrak **Audit Log Viewer** (`/api/v1/settings/audit/`, H5.5).
 *
 * **READ-ONLY** (append-only): halaman hanya membaca jejak audit — tidak ada
 * create/update/delete. Baris = PERSIS `core/audit/services.py::audit_row`
 * (12 field); detail (`audit_detail`) menambah `payload` + `metadata` + `user_agent`.
 *
 * ⚠️ `metadata_preview` di daftar = JSON **dipotong 100 karakter**; `payload`/
 * `metadata` di detail = **lengkap**. Keduanya **sudah** di-mask backend
 * (`api_key`/`password`/`secret`/`token`/`key` → `***`), jadi UI tidak perlu mem-mask
 * lagi — tetapi juga tidak boleh menampilkan nilai yang tidak dikirim backend.
 */

/** Mask rahasia dari backend (dipakai untuk assertion/test & tooltip). */
export const AUDIT_MASK = '***';

/** Nilai `result` yang dikenal backend (`AuditLog.Result`). */
export const AUDIT_RESULTS = ['OK', 'FAILED', 'CONFLICT', 'DENIED'] as const;
export type AuditResult = (typeof AUDIT_RESULTS)[number];

/** Batas paging backend (`core/audit/services.py`). */
export const AUDIT_LIMIT_DEFAULT = 50;
export const AUDIT_LIMIT_MIN = 1;
export const AUDIT_LIMIT_MAX = 200;
export const AUDIT_CURSOR_MAX = 100000;

/** Satu baris daftar audit (tanpa payload — daftar tetap ringan). */
export interface AuditLogRow {
  id: number;
  timestamp: string | null;
  /** Pelaku; `null` = anonim/sistem (atau user sudah dihapus). */
  user_id: number | null;
  username: string | null;
  full_name: string;
  action: string;
  /** Nama resource MES, mis. `master.product` (backend memakai nama `resource`). */
  resource: string;
  resource_id: string;
  /** `OK` | `FAILED` | `CONFLICT` | `DENIED`. */
  result: string;
  request_id: string;
  ip_address: string | null;
  /** JSON metadata dipotong 100 karakter (rahasia sudah di-mask). */
  metadata_preview: string;
}

/** Detail satu audit (`GET /settings/audit/<id>/` → `{audit: …}`). */
export interface AuditLogDetail extends AuditLogRow {
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  user_agent: string;
}

/** Amplop ListPage backend (`has_more`/`next_cursor` offset-based). */
export interface AuditLogPage {
  rows: AuditLogRow[];
  total_count: number;
  has_more: boolean;
  next_cursor: number | null;
}

/** Filter daftar (semua opsional; string kosong = dilewati). */
export interface AuditLogFilters {
  /** Angka ≥ 1 (string dari input supaya bisa dikosongkan). */
  user_id: string;
  /** Exact, atau **prefix** bila diakhiri titik (`master.`). */
  action: string;
  /** Sama dengan `resource` backend (alias `resource_type`). */
  resource: string;
  resource_id: string;
  /** `''` = semua, selain itu salah satu `AUDIT_RESULTS`. */
  result: string;
  /** `YYYY-MM-DD`. */
  date_from: string;
  date_to: string;
  search: string;
}
