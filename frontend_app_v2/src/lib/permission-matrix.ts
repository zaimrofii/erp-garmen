/**
 * permission-matrix.ts — logic PURE halaman Permission Matrix (H5.4).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): label resource/action, hitung ringkasan, cara membaca
 * satu sel, dan **diff** antara matrix profil awal vs draft (hanya sel yang berubah
 * yang dikirim ke `PUT /settings/permissions/<role_id>/`).
 *
 * **Opsi A′**: `matrix` = profil (draft yang diedit), `effective` = aturan berlaku
 * (snapshot kode, read-only) — halaman menampilkan keduanya dan memberi badge "beda".
 */
import type { SelectOption } from '@/components/atoms/Select';
import type {
  PermissionDivergence,
  PermissionDivergences,
  PermissionEnvelope,
  PermissionMatrix,
  PermissionRole,
  PermissionUpdate,
} from '@/types/permission-matrix';

/** Label ramah per aksi (dipakai header kolom). */
export const ACTION_LABELS: Record<string, string> = {
  read: 'Lihat',
  create: 'Tambah',
  update: 'Ubah',
  delete: 'Hapus',
};

/** Label ramah per resource (dipakai kolom pertama). */
export const RESOURCE_LABELS: Record<string, string> = {
  bundles: 'Bundle',
  dashboard: 'Dashboard',
  finance: 'Keuangan',
  inventory: 'Stok',
  master: 'Master',
  orders: 'Order',
  permissions: 'Izin',
  purchases: 'Pembelian',
  qc: 'QC',
  reports: 'Laporan',
  settings: 'Pengaturan',
  sync: 'Sync',
  'work-orders': 'Work Order',
};

/** PURE — label aksi (`read` → "Lihat"); tak dikenal → apa adanya. */
export function actionLabel(action: string): string {
  return ACTION_LABELS[action.trim().toLowerCase()] ?? action;
}

/** PURE — label resource (`work-orders` → "Work Order"); tak dikenal → apa adanya. */
export function resourceLabel(resource: string): string {
  return RESOURCE_LABELS[resource.trim()] ?? resource;
}

/** PURE — opsi dropdown role (`code — label`). */
export function roleOptions(roles: PermissionRole[]): SelectOption[] {
  return roles.map((role) => ({
    value: String(role.id),
    label: `${role.code} — ${role.label}`,
  }));
}

/** PURE — role pertama dari daftar (dipakai sebagai pilihan awal halaman). */
export function defaultRoleId(roles: PermissionRole[]): number | null {
  return roles.length > 0 ? roles[0].id : null;
}

/** PURE — sel `{resource: {action: bool}}` kosong untuk satu role. */
export function emptyCell(resources: string[], actions: string[]): Record<string, Record<string, boolean>> {
  const cell: Record<string, Record<string, boolean>> = {};

  for (const resource of resources) {
    const perAction: Record<string, boolean> = {};
    for (const action of actions) perAction[action] = false;
    cell[resource] = perAction;
  }

  return cell;
}

/**
 * PURE — draft satu role = nilai profil (default `false`) **lengkap** untuk semua
 * resource × action di daftar statis (supaya tabel selalu berbentuk sama).
 */
export function roleDraft(
  matrix: PermissionMatrix,
  roleId: number,
  resources: string[],
  actions: string[],
): Record<string, Record<string, boolean>> {
  const cell = emptyCell(resources, actions);
  const stored = matrix[String(roleId)] ?? {};

  for (const resource of resources) {
    for (const action of actions) {
      const value = stored[resource]?.[action];
      if (typeof value === 'boolean') cell[resource][action] = value;
    }
  }

  return cell;
}

/** PURE — nilai satu sel dari matrix (default `false`). */
export function readCell(
  matrix: PermissionMatrix,
  roleId: number,
  resource: string,
  action: string,
): boolean {
  return matrix[String(roleId)]?.[resource]?.[action] === true;
}

/** PURE — divergensi satu sel (atau `null` kalau sama). */
export function readDivergenceCell(
  diverges: PermissionDivergences,
  roleId: number,
  resource: string,
  action: string,
): PermissionDivergence | null {
  return diverges[String(roleId)]?.[resource]?.[action] ?? null;
}

/** Ringkasan satu role (jumlah sel aktif profil/efektif + jumlah beda). */
export interface RoleSummary {
  stored: number;
  effective: number;
  divergent: number;
  resources: number;
  divergingResources: string[];
}

/** PURE — ringkasan satu role: jumlah sel aktif (profil vs efektif) + resource yang beda. */
export function roleSummary(
  envelope: PermissionEnvelope,
  roleId: number,
): RoleSummary {
  let stored = 0;
  let effective = 0;
  const divergingResources: string[] = [];

  for (const resource of envelope.resources) {
    let resourceDiffers = false;

    for (const action of envelope.actions) {
      if (readCell(envelope.matrix, roleId, resource, action)) stored += 1;
      if (readCell(envelope.effective, roleId, resource, action)) effective += 1;
      if (readDivergenceCell(envelope.diverges, roleId, resource, action) !== null) {
        resourceDiffers = true;
      }
    }

    if (resourceDiffers) divergingResources.push(resource);
  }

  let divergent = 0;
  for (const resource of divergingResources) {
    for (const action of envelope.actions) {
      if (readDivergenceCell(envelope.diverges, roleId, resource, action) !== null) {
        divergent += 1;
      }
    }
  }

  return {
    stored,
    effective,
    divergent,
    resources: envelope.resources.length,
    divergingResources,
  };
}

/** PURE — draft penuh → sel yang **berubah** saja (`PermissionUpdate[]`). */
export function diffUpdates(
  baseline: Record<string, Record<string, boolean>>,
  draft: Record<string, Record<string, boolean>>,
  resources: string[],
  actions: string[],
): PermissionUpdate[] {
  const updates: PermissionUpdate[] = [];

  for (const resource of resources) {
    for (const action of actions) {
      const before = baseline[resource]?.[action] === true;
      const after = draft[resource]?.[action] === true;
      if (before !== after) updates.push({ resource, action, allowed: after });
    }
  }

  return updates;
}

/** PURE — draft setelah satu sel di-toggle (immutable; aman untuk setState React). */
export function toggleCell(
  draft: Record<string, Record<string, boolean>>,
  resource: string,
  action: string,
  allowed: boolean,
): Record<string, Record<string, boolean>> {
  const next: Record<string, Record<string, boolean>> = {};

  for (const [key, actions] of Object.entries(draft)) {
    next[key] = key === resource ? { ...actions, [action]: allowed } : { ...actions };
  }

  if (next[resource] === undefined) {
    next[resource] = { [action]: allowed };
  }

  return next;
}
