/**
 * permission-matrix.ts — kontrak **Permission Matrix** (`/api/v1/settings/permissions/`, H5.4).
 *
 * **Opsi A′ (keputusan STEP 0)**: `matrix` = **profil tersimpan** (bisa diedit, ber-jejak
 * ledger SKIPPED + AuditLog), `effective` = aturan yang **benar-benar berlaku sekarang**
 * (snapshot `ROLE_CAPABILITIES` di backend — cermin guard kode, **bukan** sumber
 * kebenaran), `diverges` = sel yang beda, `banner` = peringatan jujur bahwa
 * **enforcement belum berubah** (guard masih hardcoded).
 *
 * Bentuk sel = PERSIS `core/auth/permission_services.py`:
 *   * `matrix`/`effective`: `{role_id: {resource: {action: bool}}}`;
 *   * `diverges`: `{role_id: {resource: {action: {profile, effective}}}}` (hanya beda);
 *   * `resources`/`actions`: daftar statis dari backend (jangan dikarang di UI);
 *   * `roles`: `[{id, code, label, is_active}]`.
 */

/** Sel matrix: ``{role_id: {resource: {action: bool}}}`` (key role = string id). */
export type PermissionMatrix = Record<string, Record<string, Record<string, boolean>>>;

/** Satu sel yang beda profil vs efektif. */
export interface PermissionDivergence {
  profile: boolean;
  effective: boolean;
}

/** ``{role_id: {resource: {action: {profile, effective}}}}`` (hanya sel yang beda). */
export type PermissionDivergences = Record<
  string,
  Record<string, Record<string, PermissionDivergence>>
>;

/** Baris role pada matrix (label = `Role.name`; kontrak B27). */
export interface PermissionRole {
  id: number;
  code: string;
  label: string;
  is_active: boolean;
}

/** Amplop `GET /settings/permissions/`. */
export interface PermissionEnvelope {
  matrix: PermissionMatrix;
  /** Aturan yang berlaku sekarang (snapshot kode) — read-only untuk UI. */
  effective: PermissionMatrix;
  diverges: PermissionDivergences;
  /** Daftar resource/action statis dari backend (kontrak UI). */
  resources: string[];
  actions: string[];
  roles: PermissionRole[];
  /** Peringatan wajib: profil ≠ enforcement. */
  banner: string;
}

/** Satu sel yang dikirim di body PUT. */
export interface PermissionUpdate {
  resource: string;
  action: string;
  allowed: boolean;
}

/** Body `PUT /settings/permissions/<role_id>/` (salah satu atau keduanya). */
export interface PermissionInput {
  updates?: PermissionUpdate[];
  matrix?: Record<string, Record<string, boolean>>;
}

/** Respons PUT = amplop + metadata tulis (ledger SKIPPED). */
export interface PermissionSaveResult extends PermissionEnvelope {
  role_id: number;
  updated_count: number;
  sync_record_id: number | null;
  sync_status: string | null;
}

/** Teks banner cadangan kalau backend tidak mengirim `banner` (tidak boleh bohong). */
export const PERMISSION_BANNER_FALLBACK =
  '⚠️ Perubahan di halaman ini disimpan sebagai PROFIL (audit trail). Enforcement belum berubah — backend masih memakai guard hardcoded. Sprint enforcement terpisah akan menghubungkan matrix ini ke guard.';
