// @dummy - endpoint masa depan: GET /routing/graph
import type { DagEdge, DagNode, RoutingGraph } from '@/types/routing';
import { delay } from './_delay';

/**
 * PURE - fixture DAG garmen.
 * Diekspor supaya fixture lain (mis. `settings/routing`) memakai graf yang SAMA
 * tanpa menggandakan data.
 */
export function buildRoutingGraphFixture(): RoutingGraph {
  const nodes: DagNode[] = [
    {
      id: 'cutting',
      label: 'Cutting',
      capability: ['cutting', 'spreading'],
      smv: 1.2,
      maxWip: 120,
      status: 'idle',
      position: { x: 0, y: 120 },
    },
    {
      id: 'sablon',
      label: 'Sablon',
      capability: ['screen_print', 'curing'],
      smv: 2.4,
      maxWip: 90,
      status: 'active',
      position: { x: 180, y: 40 },
    },
    {
      id: 'jahit-01',
      label: 'Jahit-01',
      capability: ['overlock', 'single_needle'],
      smv: 6.8,
      maxWip: 60,
      status: 'bottleneck',
      position: { x: 360, y: 120 },
    },
    {
      id: 'jahit-02',
      label: 'Jahit-02',
      capability: ['single_needle', 'bartack'],
      smv: 5.5,
      maxWip: 75,
      status: 'active',
      position: { x: 540, y: 40 },
    },
    {
      id: 'qc',
      label: 'QC',
      capability: ['inspection', 'aql'],
      smv: 1.8,
      maxWip: 45,
      status: 'active',
      position: { x: 720, y: 120 },
    },
    {
      id: 'finishing',
      label: 'Finishing',
      capability: ['steam', 'trimming'],
      smv: 2.1,
      maxWip: 100,
      status: 'idle',
      position: { x: 900, y: 40 },
    },
    {
      id: 'packing',
      label: 'Packing',
      capability: ['folding', 'cartoning'],
      smv: 1.1,
      maxWip: 150,
      status: 'idle',
      position: { x: 1080, y: 120 },
    },
  ];

  const edges: DagEdge[] = [
    { id: 'e-cutting-sablon', from: 'cutting', to: 'sablon', isRework: false },
    { id: 'e-sablon-jahit01', from: 'sablon', to: 'jahit-01', isRework: false },
    { id: 'e-jahit01-jahit02', from: 'jahit-01', to: 'jahit-02', isRework: false },
    { id: 'e-jahit02-qc', from: 'jahit-02', to: 'qc', isRework: false },
    { id: 'e-qc-finishing', from: 'qc', to: 'finishing', isRework: false },
    { id: 'e-finishing-packing', from: 'finishing', to: 'packing', isRework: false },
    // Loop rework: cacat dari QC kembali ke jahit -> digambar putus-putus accent-coral.
    { id: 'e-qc-jahit01-rework', from: 'qc', to: 'jahit-01', isRework: true },
  ];

  return { nodes, edges };
}

/** Graf routing aktif (RoutingVisualizationPage + DAG editor). */
export async function fetchRoutingGraph(): Promise<RoutingGraph> {
  await delay(100 + Math.random() * 200);

  return buildRoutingGraphFixture();
}
