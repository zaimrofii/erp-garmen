// REAL - graf DAG routing (F2c.1). Endpoint: GET /api/v1/routing/graph/
//
// Backend `integrations/erp_sync/monitoring.py::RoutingGraphView` (B3):
//   * `IsAuthenticated` (anon 403); read-only DB (`ProcessRouting` + `RoutingStep`);
//   * query opsional `?product_id` (resolusi lewat TagRouter);
//   * respons (BUKAN ListPage):
//     `{routing_id, routing_name, version,
//       nodes:[{id,label,step_no}], edges:[{from,to,overlap_pct,is_rework}]}`.
//
// Field yang TIDAK ada di backend: `capability`/`smv`/`maxWip`/`status` -> DIBUANG.
// `position{x,y}` TIDAK dikirim backend -> dilayout di klien: linear horizontal
// (`x = step_no * 200`, `y = 0`). `edge.id` diturunkan dari `from->to`.
import type { ApiClient } from '@/integrations/api-client';
import type { DagEdge, DagNode, RoutingGraph } from '@/types/routing';
import { unwrap } from '../client';

/** Path relatif terhadap `VITE_API_BASE_URL`. */
export const ROUTING_GRAPH_PATH = '/routing/graph/';

/** Jarak antar-node saat auto-layout (px) + baris Y tetap. */
export const NODE_STEP_SPACING = 200;
export const NODE_ROW_Y = 0;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function isIdLike(value: unknown): value is number | string {
  return typeof value === 'number' || typeof value === 'string';
}

/** PURE — posisi auto-layout dari `step_no` (linear horizontal). */
export function layoutPosition(stepNo: number): { x: number; y: number } {
  return { x: stepNo * NODE_STEP_SPACING, y: NODE_ROW_Y };
}

/** PURE — path + query `GET /routing/graph/` (hanya `product_id` bila diisi). */
export function buildRoutingGraphPath(
  params: { product_id?: number | string | null } = {},
): string {
  const productId = params.product_id;

  if (productId === undefined || productId === null || String(productId) === '') {
    return ROUTING_GRAPH_PATH;
  }

  return `${ROUTING_GRAPH_PATH}?product_id=${encodeURIComponent(String(productId))}`;
}

/** PURE — satu node backend → `DagNode` (+ auto-layout); `null` kalau tanpa id. */
export function readRoutingNode(raw: unknown): DagNode | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (!isIdLike(id)) return null;

  const stepNo = readNumber(raw['step_no']);

  return {
    id: String(id),
    label: readText(raw['label']),
    step_no: stepNo,
    position: layoutPosition(stepNo),
  };
}

/** PURE — satu edge backend → `DagEdge`; `null` kalau `from`/`to` tidak valid. */
export function readRoutingEdge(raw: unknown): DagEdge | null {
  if (!isRecord(raw)) return null;

  const from = raw['from'];
  const to = raw['to'];
  if (!isIdLike(from) || !isIdLike(to)) return null;

  const fromId = String(from);
  const toId = String(to);

  return {
    id: `${fromId}->${toId}`,
    from: fromId,
    to: toId,
    isRework: raw['is_rework'] === true,
  };
}

/**
 * PURE — respons mentah → `RoutingGraph`; `null` kalau envelope tak dikenali.
 * Edge yang endpointnya tidak ada di `nodes` dibuang (molecule butuh node valid).
 */
export function readRoutingGraph(raw: unknown): RoutingGraph | null {
  if (!isRecord(raw)) return null;

  const nodes = raw['nodes'];
  const edges = raw['edges'];
  if (!Array.isArray(nodes) || !Array.isArray(edges)) return null;

  const parsedNodes: DagNode[] = [];
  for (const node of nodes) {
    const parsed = readRoutingNode(node);
    if (parsed !== null) parsedNodes.push(parsed);
  }

  const nodeIds = new Set(parsedNodes.map((node) => node.id));
  const parsedEdges: DagEdge[] = [];
  for (const edge of edges) {
    const parsed = readRoutingEdge(edge);
    if (parsed !== null && nodeIds.has(parsed.from) && nodeIds.has(parsed.to)) {
      parsedEdges.push(parsed);
    }
  }

  return { nodes: parsedNodes, edges: parsedEdges };
}

/**
 * Baca graf routing. Gagal HTTP (403 anon / 404 product) → melempar pesan backend
 * (`unwrap`); bentuk tak dikenal → melempar pesan jelas.
 */
export async function fetchRoutingGraph(
  client: ApiClient,
  params: { product_id?: number | string | null } = {},
): Promise<RoutingGraph> {
  const res = await client.get<unknown>(buildRoutingGraphPath(params));
  const graph = readRoutingGraph(unwrap(res));

  if (graph === null) {
    throw new Error('Bentuk respons graf routing tidak dikenali.');
  }

  return graph;
}

export type { DagEdge, DagNode, RoutingGraph } from '@/types/routing';
