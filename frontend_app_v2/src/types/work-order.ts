export interface WorkOrderRow {
  id: number;
  code: string;
  state: string;
  qty_planned: number;
  qty_done: number;
}

// Detail WO belum di-curl di 5a — biarkan tipis dulu; nanti ditambah saat Fase 8 kalau perlu.
export type WorkOrderDetail = WorkOrderRow;

// ---------------------------------------------------------------------------
// H2.3 — Work Order CRUD (MES-only)
// ---------------------------------------------------------------------------
// Bentuk baris = PERSIS `django_app/apps_industry/garment/services/work_order_services.py`
// (`wo_row`/`wo_detail_row`, superset) yang dipakai endpoint H2.3:
//   * `GET|POST /api/v1/garmen/work-orders/` (POST = create; GET list tetap 5 key F3);
//   * `GET|PUT|DELETE /api/v1/garmen/work-orders/<id>/`;
//   * `POST /api/v1/garmen/work-orders/<id>/split/`;
//   * `POST /api/v1/garmen/orders/<id>/generate-wo/`;
//   * transisi state memakai endpoint aksi EXISTING (`WO_START`/`WO_CLOSE`/`WO_CANCEL`
//     pada `/work-orders/<id>/<ACTION>/`).
//
// Work Order = **MES-only** (probe H2.3: Odoo `mrp.workorder` = operasi per
// `mrp.production`, `sale.order.line` tanpa field workorder) ⇒ TIDAK ada `odoo_id`;
// jejaknya hanya ledger `SyncRecord` status `SKIPPED` (`ledger_id`).

/** State WO MES = state machine yang di-SEED `garment.work_order` (§14). */
export type WorkOrderState = 'DRAFT' | 'IN_PROGRESS' | 'DONE' | 'CANCELLED';

/** Satu baris bundle milik WO (ringkas, untuk halaman detail). */
export interface WorkOrderBundleRow {
  id: number;
  code: string;
  state: string;
  size: string;
  qty: number;
  qty_done: number;
}

/** Baris list 5 key dari endpoint F3 (`GET /garmen/work-orders/`). */
export interface WorkOrderCrudListRow {
  id: number;
  code: string;
  state: string;
  qty_planned: number;
  qty_done: number;
}

/** Baris WO versi H2.3 (`wo_row`) — dipakai detail/split/generate. */
export interface WorkOrderCrudRow extends WorkOrderCrudListRow {
  order_line_id: number | null;
  order_id: number | null;
  order_code: string | null;
  product_id: number | null;
  product_code: string | null;
  bundles_count: number;
  allowed_actions: string[];
  created_at: string | null;
  updated_at: string | null;
}

/** Detail WO (`wo_detail_row` + `version` + `allowed_actions`). */
export interface WorkOrderCrudDetail extends WorkOrderCrudRow {
  bundles: WorkOrderBundleRow[];
  version: string;
}

/** Hasil CUD (create/update/delete): detail + jejak ledger (MES-only). */
export interface WorkOrderCrudSaved extends WorkOrderCrudDetail {
  ledger_id: number | null;
  cancelled: boolean;
  deleted: boolean;
}

/** Body POST/PUT WO (nama field backend). */
export interface WorkOrderCrudInput {
  order_line_id: number | null;
  code: string;
  qty_planned: number | null;
}

/** Hasil split (`POST /work-orders/<id>/split/`). */
export interface WorkOrderSplitSaved extends WorkOrderCrudSaved {
  work_orders: WorkOrderCrudRow[];
  summary: { parts?: number[]; created: number };
}

/** Hasil batch generate (`POST /orders/<id>/generate-wo/`). */
export interface WorkOrderGenerateResult {
  order_id: number;
  order_code: string;
  summary: { created: number; skipped: number };
  work_orders: WorkOrderCrudRow[];
}
