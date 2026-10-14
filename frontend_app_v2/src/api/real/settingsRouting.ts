// REAL - settings routing (F3A.CLOSE flip / backend B22). GET + POST /api/v1/settings/routing/
//
// Bentuk backend = routing + `steps[]` (step_no/wc_type/depends_on/rework_target_step).
// Halaman DAG editor memakai `RoutingConfig{graph}` → konversi dua arah ada di sini
// (auto-layout sederhana; backend TIDAK menyimpan posisi node).
import type { ApiClient } from '@/integrations/api-client';
import type { DagEdge, DagNode, RoutingGraph } from '@/types/routing';
import type { RoutingConfig } from '@/types/settings';
import { unwrap } from '../client';
import {
  buildQueryPath,
  getParsed,
  isRecord,
  readBool,
  readListPage,
  readNullableNum,
  readNum,
  readStr,
  type ListPage,
} from './_shape';

export const SETTINGS_ROUTING_PATH = '/settings/routing/';

export interface RoutingStepRow {
  id: number;
  step_no: number;
  wc_type: string;
  depends_on: number[];
  rework_target_step: number | null;
  is_initial: boolean;
  is_terminal: boolean;
}

export interface RoutingRow {
  id: number;
  code: string;
  name: string;
  description: string;
  is_active: boolean;
  steps: RoutingStepRow[];
}

/** Input POST `steps[]` (brief B22). */
export interface RoutingStepInput {
  step_no: number;
  wc_type: string;
  depends_on: number[];
  rework_target_step?: number | null;
}

export interface RoutingCreateInput {
  name: string;
  steps: RoutingStepInput[];
  description?: string;
}

function readSteps(value: unknown): RoutingStepRow[] {
  if (!Array.isArray(value)) return [];
  return value.filter(isRecord).map((row) => ({
    id: readNum(row['id']),
    step_no: readNum(row['step_no']),
    wc_type: readStr(row['wc_type']),
    depends_on: Array.isArray(row['depends_on'])
      ? row['depends_on'].filter((item): item is number => typeof item === 'number')
      : [],
    rework_target_step: readNullableNum(row['rework_target_step']),
    is_initial: readBool(row['is_initial']),
    is_terminal: readBool(row['is_terminal']),
  }));
}

/** PURE — satu routing mentah → `RoutingRow`. */
export function readRoutingRow(raw: unknown): RoutingRow | null {
  if (!isRecord(raw)) return null;
  return {
    id: readNum(raw['id']),
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    description: readStr(raw['description']),
    is_active: readBool(raw['is_active']),
    steps: readSteps(raw['steps']),
  };
}

/** PURE — respons ListPage routing. */
export function readRoutingPage(raw: unknown): ListPage<RoutingRow> | null {
  return readListPage<RoutingRow>(raw, readRoutingRow);
}

/* ------------------------------------------------------------------ konversi */

const NODE_X_STEP = 180;
const NODE_Y = 120;

/** PURE — `RoutingRow` → `RoutingConfig` (DAG view model halaman editor). */
export function toRoutingConfig(row: RoutingRow): RoutingConfig {
  const nodes: DagNode[] = row.steps.map((step, index) => ({
    id: `step-${step.step_no}`,
    label: step.wc_type,
    step_no: step.step_no,
    position: { x: 80 + index * NODE_X_STEP, y: NODE_Y },
  }));

  const edges: DagEdge[] = [];
  for (const step of row.steps) {
    for (const dep of step.depends_on) {
      edges.push({
        id: `e-${dep}-${step.step_no}`,
        from: `step-${dep}`,
        to: `step-${step.step_no}`,
        isRework: false,
      });
    }
    if (step.rework_target_step !== null) {
      edges.push({
        id: `rw-${step.step_no}-${step.rework_target_step}`,
        from: `step-${step.step_no}`,
        to: `step-${step.rework_target_step}`,
        isRework: true,
      });
    }
  }

  return { id: row.id, name: row.name, graph: { nodes, edges }, active: row.is_active };
}

/** PURE — `RoutingConfig` (dari editor) → `steps[]` body POST. */
export function toRoutingSteps(graph: RoutingGraph): RoutingStepInput[] {
  const stepNoById = new Map<string, number>();
  graph.nodes.forEach((node, index) => {
    stepNoById.set(node.id, node.step_no ?? index + 1);
  });

  return graph.nodes.map((node, index) => {
    const stepNo = node.step_no ?? index + 1;
    const dependsOn = graph.edges
      .filter((edge) => edge.to === node.id && !edge.isRework)
      .map((edge) => stepNoById.get(edge.from))
      .filter((value): value is number => typeof value === 'number');

    const reworkEdge = graph.edges.find((edge) => edge.from === node.id && edge.isRework);

    return {
      step_no: stepNo,
      wc_type: node.label,
      depends_on: dependsOn,
      rework_target_step:
        reworkEdge === undefined ? null : (stepNoById.get(reworkEdge.to) ?? null),
    };
  });
}

/* --------------------------------------------------------------------- fetch */

/** List routing (raw `RoutingRow`). Gagal HTTP → melempar. */
export async function fetchRoutingRows(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<ListPage<RoutingRow>> {
  return getParsed(
    client,
    buildQueryPath(SETTINGS_ROUTING_PATH, { limit: params.limit, cursor: params.cursor }),
    readRoutingPage,
    'konfigurasi routing',
  );
}

/** List routing sebagai `RoutingConfig[]` (dipakai halaman DAG editor). */
export async function fetchRoutingConfigs(
  client: ApiClient,
  params: { limit?: number | null; cursor?: number | null } = {},
): Promise<RoutingConfig[]> {
  const page = await fetchRoutingRows(client, params);
  return page.rows.map(toRoutingConfig);
}

/** Buat routing baru (POST). `config.id <= 0` diabaikan (backend selalu membuat baru). */
export async function saveRoutingConfig(
  client: ApiClient,
  config: RoutingConfig,
): Promise<RoutingConfig> {
  const res = await client.post<unknown>(SETTINGS_ROUTING_PATH, {
    name: config.name,
    steps: toRoutingSteps(config.graph),
  });

  const row = readRoutingRow(unwrap(res));
  if (row === null) {
    throw new Error('Bentuk respons simpan routing tidak dikenali.');
  }

  return toRoutingConfig(row);
}
