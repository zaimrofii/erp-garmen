// ADAPTER - satu-satunya pintu data Routing/DAG (TANPA logic domain).
//
// F2c.1: MODE `routing` === 'real' (`GET /api/v1/routing/graph/`, B3).
// Catatan: `api/dummy/routing.ts` TETAP ADA (dipakai `settingsRouting` — editor DAG
// Settings masih dummy) — jangan dihapus.
import { pickAdapter } from './_adapter';
import * as real from './real/routing';

/** Graf DAG routing aktif (RoutingVisualizationPage). */
export const fetchRoutingGraph = pickAdapter(
  'routing',
  real.fetchRoutingGraph,
  real.fetchRoutingGraph,
);

export {
  buildRoutingGraphPath,
  layoutPosition,
  NODE_ROW_Y,
  NODE_STEP_SPACING,
  readRoutingEdge,
  readRoutingGraph,
  readRoutingNode,
  ROUTING_GRAPH_PATH,
} from './real/routing';
export type { DagEdge, DagNode, RoutingGraph } from './real/routing';

