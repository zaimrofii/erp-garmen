import type { AllowedAction } from '@/lib/schemas/action.schema';

export type BundleState = 'DRAFT' | 'CUTTING' | 'SEWING' | 'QC' | 'DONE' | 'SCRAPPED';

// Row dari GET /garmen/bundles/ (curl A).
export interface BundleRow {
  id: number;
  code: string;
  state: BundleState | string;
  size: string;
  qty: number;
  qty_done: number;
  version: string;
  current_work_center_code: string | null;
  allowed_actions: AllowedAction[];
}

// Detail dari GET /garmen/bundles/{id}/ (curl B).
export interface BundleDetail extends BundleRow {
  sku_variant: string;
  work_order_id: number | null;
  production_line_code: string | null;
  updated_at: string; // ISO 8601
}

export type { AllowedAction };

// ---------------------------------------------------------------------------
// H2.4 — Bundle CRUD (create/update/delete/split/merge; MES-only)
// ---------------------------------------------------------------------------
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/bundle_services.py`
// (`bundle_row`/`bundle_detail_row`, superset) + reader di `api/real/bundlesCrud.ts`.
//
// Endpoint H2.4: `GET|POST /api/v1/garmen/bundles/` (POST create; GET list ber-filter),
// `POST /api/v1/garmen/bundles/preview/`, `GET|PUT|DELETE /bundles/<id>/`,
// `POST /bundles/<id>/split/`, `POST /bundles/<id>/merge/`.
// Transisi state TETAP memakai aksi existing (`BUNDLE_START`/`BUNDLE_ADVANCE`/
// `BUNDLE_QC`/`BUNDLE_FINISH`/`BUNDLE_SCRAP`) — H2.4 tidak menambah endpoint aksi.
//
// Bundle = **MES-only sebagai objek** (Odoo tidak punya model bundle); pergerakan stok
// tetap lewat WIP/FG (bukan bagian H2.4).

/** Satu baris bundle versi H2.4 (`bundle_row`). */
export interface BundleCrudRow extends Omit<BundleRow, 'allowed_actions'> {
  /** Daftar id aksi diizinkan (dari seed machine; dinormalisasi di adapter H2.4). */
  allowed_actions: string[];
  sku_variant: string;
  work_order_id: number | null;
  work_order_code: string | null;
  order_line_id: number | null;
  order_code: string | null;
  product_code: string | null;
  current_work_center_id: number | null;
  production_line_id: number | null;
  production_line_code: string | null;
  events_count: number;
  ledger_status: string;
  created_at: string | null;
  updated_at: string | null;
}

/** Detail bundle versi H2.4 (`bundle_detail_row`; `allowed_actions` dari seed machine). */
export interface BundleCrudDetail extends BundleCrudRow {
  allowed_actions: string[];
}
/** Body create H2.4 (dikirim ke `POST /bundles/`). */
export interface BundleCrudCreateInput {
  work_order_id: number | null;
  size_matrix: Record<string, number>;
  bundle_size: number | null;
  sku_variant: string;
}

/** Body update H2.4 (`PUT /bundles/<id>/`). */
export interface BundleCrudUpdateInput {
  size: string;
  sku_variant: string;
  qty: number | null;
  current_work_center_id: number | null;
  production_line_id: number | null;
}

/** Satu item rencana bundle (`POST /bundles/preview/`). */
export interface BundlePlanRow {
  code: string;
  size: string;
  sku_variant: string;
  qty: number;
  work_order_id: number;
}

/** Hasil preview (tanpa menyimpan). */
export interface BundlePreviewResult {
  plan: BundlePlanRow[];
  summary: { created?: number; planned: number; total_qty: number };
}

/** Hasil create (`POST /bundles/`). */
export interface BundleCrudCreated extends BundleCrudDetail {
  created: number;
  summary: { created: number; total_qty: number };
  bundles: BundleCrudRow[];
  ledger_id: number | null;
}

/** Hasil CUD/split/merge (baris + jejak ledger MES-only). */
export interface BundleCrudSaved extends BundleCrudDetail {
  ledger_id: number | null;
  deleted: boolean;
  bundles?: BundleCrudRow[];
  summary?: Record<string, unknown>;
}

/** Hasil merge (`POST /bundles/<id>/merge/`). */
export interface BundleMergeSaved extends BundleCrudSaved {
  summary: { merged: number; qty: number; merged_ids: number[] };
}
