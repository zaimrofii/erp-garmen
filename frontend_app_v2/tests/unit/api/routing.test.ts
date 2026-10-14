import { describe, expect, it } from 'vitest';
import {
  buildRoutingGraphPath,
  fetchRoutingGraph,
  layoutPosition,
  NODE_STEP_SPACING,
  readRoutingGraph,
  readRoutingNode,
  ROUTING_GRAPH_PATH,
} from '@/api/routing';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';

/**
 * F2c.1 — adapter REAL graf routing (`GET /api/v1/routing/graph/`, B3).
 * Bentuk = PERSIS `monitoring.RoutingGraphView`: `{routing_id, routing_name, version,
 * nodes:[{id,label,step_no}], edges:[{from,to,overlap_pct,is_rework}]}`.
 * `position` dilayout klien (`x = step_no * 200`); `edge.id` diturunkan `from->to`.
 */

const LIVE_BODY = {
  routing_id: 1,
  routing_name: 'Kaos Export',
  version: 1,
  nodes: [
    { id: 1, label: 'Cutting', step_no: 1 },
    { id: 2, label: 'Sewing', step_no: 2 },
  ],
  edges: [
    { from: 1, to: 2, overlap_pct: 0, is_rework: false },
    { from: 2, to: 1, overlap_pct: 0, is_rework: true },
  ],
};

function stubClient(data: unknown): { client: ApiClient; paths: string[] } {
  const paths: string[] = [];

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      paths.push(path);

      return { ok: true, status: 200, data: data as T };
    },
  } as unknown as ApiClient;

  return { client, paths };
}

describe('F2c.1 — MODE & path routing graph', () => {
  it('MODE routing = real (endpoint B3 ADA)', () => {
    expect(MODE['routing']).toBe('real');
  });

  it('path default + product_id', async () => {
    expect(ROUTING_GRAPH_PATH).toBe('/routing/graph/');
    expect(buildRoutingGraphPath()).toBe('/routing/graph/');
    expect(buildRoutingGraphPath({ product_id: 7 })).toBe('/routing/graph/?product_id=7');
    expect(buildRoutingGraphPath({ product_id: '' })).toBe('/routing/graph/');

    const { client, paths } = stubClient(LIVE_BODY);

    await fetchRoutingGraph(client);

    expect(paths).toEqual(['/routing/graph/']);
  });
});

describe('F2c.1 — readRoutingGraph', () => {
  it('respons backend → nodes (auto-layout) + edges', async () => {
    const { client } = stubClient(LIVE_BODY);

    const graph = await fetchRoutingGraph(client);

    expect(graph.nodes).toHaveLength(2);
    expect(graph.nodes[0]).toEqual({
      id: '1',
      label: 'Cutting',
      step_no: 1,
      position: { x: 1 * NODE_STEP_SPACING, y: 0 },
    });
    expect(graph.edges).toEqual([
      { id: '1->2', from: '1', to: '2', isRework: false },
      { id: '2->1', from: '2', to: '1', isRework: true },
    ]);
    expect(layoutPosition(3)).toEqual({ x: 600, y: 0 });
  });

  it('edge dengan endpoint tak dikenal dibuang; node tanpa id dibuang', () => {
    const graph = readRoutingGraph({
      nodes: [{ id: 1, label: 'A', step_no: 1 }, { label: 'rusak' }],
      edges: [
        { from: 1, to: 2, is_rework: false },
        { from: 1, to: 1, is_rework: true },
      ],
    });

    expect(graph?.nodes).toHaveLength(1);
    expect(graph?.edges).toEqual([{ id: '1->1', from: '1', to: '1', isRework: true }]);
    expect(readRoutingNode({ label: 'x' })).toBeNull();
  });

  it('envelope tak dikenal → null', () => {
    expect(readRoutingGraph(null)).toBeNull();
    expect(readRoutingGraph({ nodes: 'bukan-array', edges: [] })).toBeNull();
  });
});

describe('F2c.1 — error routing graph', () => {
  it('403 (perlu session) → melempar pesan', async () => {
    const client = {
      get: async <T,>(): Promise<ApiResponse<T>> => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'HTTP 403' },
      }),
    } as unknown as ApiClient;

    await expect(fetchRoutingGraph(client)).rejects.toThrow(/403/);
  });

  it('bentuk respons tak dikenali → melempar pesan jelas', async () => {
    const { client } = stubClient({ ok: true });

    await expect(fetchRoutingGraph(client)).rejects.toThrow(/tidak dikenali/);
  });
});
