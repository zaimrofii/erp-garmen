/**
 * master-routing.ts — kontrak master Routing DAG (H1.9).
 *
 * Endpoint = **B22 yang di-extend di tempat** (`/api/v1/settings/routing/…`), bukan
 * endpoint paralel `/master/routings/` (keputusan H1.9 poin 2/11):
 *
 *   * `GET  /settings/routing/`            → list B22 (shape F3A apa adanya)
 *   * `GET  /settings/routing/<id>/`       → detail + `capability_tags`, `steps_count`,
 *                                            `nodes[]`, `edges[]`, `created_at/updated_at`
 *   * `PUT  /settings/routing/<id>/`       → ubah header
 *   * `DELETE /settings/routing/<id>/`     → soft delete (`is_active=false`)
 *   * `POST /settings/routing/<id>/steps/` → tambah step (node DAG)
 *   * `PUT|DELETE /settings/routing/<id>/steps/<step_id>/`
 *
 * Semua `snake_case` backend dipakai apa adanya (pola H1.1–H1.8). **Tanpa `odoo_id`** —
 * H1.9 MES-only (Odoo 17 tidak punya DAG routing; probe STEP 0).
 */

/** Satu step routing (node DAG) — bentuk B22 (`wc_type` = `RoutingStep.label`). */
export interface MasterRoutingStepRow {
  id: number;
  step_no: number;
  wc_type: string;
  /** Daftar `step_no` predecessor (backend: `allowed_from`). */
  depends_on: number[];
  /** `step_no` tujuan rework (self-FK) atau `null`. */
  rework_target_step: number | null;
  is_initial: boolean;
  is_terminal: boolean;
}

/** Simpul graf — shape `/api/v1/routing/graph/` (`{id, label, step_no}`). */
export interface MasterRoutingNode {
  id: number;
  label: string;
  step_no: number;
}

/** Sisi graf — shape `/api/v1/routing/graph/`. */
export interface MasterRoutingEdge {
  from: number;
  to: number;
  /** Selalu 0 — model belum menyimpan overlap (samakan dengan monitoring). */
  overlap_pct: number;
  is_rework: boolean;
}

/** Baris list B22 (`GET /settings/routing/`) — shape F3A, TIDAK diubah H1.9. */
export interface MasterRoutingRow {
  id: number;
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  steps: MasterRoutingStepRow[];
}

/** Detail routing (`GET /settings/routing/<id>/`) = baris B22 + field H1.9. */
export interface MasterRoutingDetail extends MasterRoutingRow {
  capability_tags: string[];
  steps_count: number;
  nodes: MasterRoutingNode[];
  edges: MasterRoutingEdge[];
  created_at: string;
  updated_at: string;
}

/** Respons tulis (PUT/DELETE header, POST/PUT/DELETE step) = detail routing. */
export type MasterRoutingSaved = MasterRoutingDetail;

/** Payload `POST /settings/routing/` (B22: `steps[]` pakai `step_no`/`depends_on`). */
export interface MasterRoutingCreateInput {
  name: string;
  description?: string;
  steps: MasterRoutingStepB22Input[];
}

/** Step bentuk B22 (`depends_on` = daftar `step_no`). */
export interface MasterRoutingStepB22Input {
  step_no: number;
  wc_type: string;
  depends_on: number[];
  rework_target_step?: number | null;
}

/** Payload `PUT /settings/routing/<id>/` — hanya field yang dikirim yang diubah. */
export interface MasterRoutingInput {
  name?: string;
  code?: string;
  description?: string;
  capability_tags?: string[];
  active?: boolean;
}

/**
 * Payload step endpoint H1.9 (id-based, bukan `step_no`).
 *
 * `depends_on_step_ids` = predecessor, `next_step_ids` = successor; keduanya
 * mengganti penuh sisi yang dikirim (sisi yang tidak dikirim dipertahankan).
 */
export interface MasterRoutingStepInput {
  label?: string;
  order?: number | null;
  code?: string;
  work_center_id?: number | null;
  depends_on_step_ids?: number[];
  next_step_ids?: number[];
  rework_target_step_id?: number | null;
}
