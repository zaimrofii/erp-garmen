/**
 * routing.ts - kontrak graf routing (DAG) produksi.
 * Dipakai halaman Routing Visualization (supervisor) dan DAG editor (admin).
 * `snake_case` dari backend dipakai apa adanya di dalam field.
 *
 * F2c.1: resource `routing` = `real` (backend `GET /api/v1/routing/graph/`).
 * Field yang TIDAK ada di backend (`capability`/`smv`/`maxWip`/`status`) dibuat
 * OPSIONAL supaya tetap kompatibel dengan editor Settings (masih dummy).
 */

/** Status visual simpul: idle (abu), active (biru), bottleneck (coral). */
export type NodeStatus = 'idle' | 'active' | 'bottleneck';

export interface DagNode {
  id: string;
  label: string;
  /** Nomor langkah dari backend (`RoutingStep.order`); opsional untuk node fixture. */
  step_no?: number;
  /** Kapabilitas work center — tidak ada di backend (opsional). */
  capability?: string[];
  /** Standard Minute Value — tidak ada di backend (opsional). */
  smv?: number;
  /** Batas WIP — tidak ada di backend (opsional). */
  maxWip?: number;
  /** Status visual — tidak ada di backend (opsional). */
  status?: NodeStatus;
  position: { x: number; y: number };
}

export interface DagEdge {
  id: string;
  /** id simpul asal. */
  from: string;
  /** id simpul tujuan. */
  to: string;
  /** Loop rework -> digambar garis putus-putus accent-coral. */
  isRework: boolean;
}

export interface RoutingGraph {
  nodes: DagNode[];
  edges: DagEdge[];
}
