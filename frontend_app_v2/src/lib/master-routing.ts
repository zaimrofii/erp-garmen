/**
 * master-routing.ts — logic PURE halaman master Routing DAG (H1.9).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): konversi row ↔ form, validasi form, **deteksi siklus
 * sisi klien** (cermin `master/routing_services.py::find_cycle`, MAX_DAG_DEPTH=10),
 * dan penyusunan payload step endpoint H1.9.
 *
 * Server tetap penjaga terakhir: pesan 400 backend diteruskan ke Toast apa adanya.
 *
 * Model form memakai **id lokal** untuk step (`key`) karena step baru belum punya
 * `id` backend; konversi ke/dari `id` backend dilakukan di `formToStepPayloads()`
 * dan `detailToForm()`.
 */
import { normalizeTags } from '@/lib/master-work-center';
import type { DagEdge, DagNode, RoutingGraph } from '@/types/routing';
import type {
  MasterRoutingDetail,
  MasterRoutingEdge,
  MasterRoutingStepInput,
  MasterRoutingStepRow,
} from '@/types/master-routing';

/** Batas panjang (selaras service backend — beda = 400, bukan 500). */
export const MAX_ROUTING_NAME_LENGTH = 150;
export const MAX_ROUTING_CODE_LENGTH = 64;
export const MAX_ROUTING_DESCRIPTION_LENGTH = 2000;
export const MAX_STEP_LABEL_LENGTH = 150;

/** Kelipatan `order` step baru (backend: `AUTO_ORDER_STEP`). */
export const AUTO_ORDER_STEP = 10;

/** Kedalaman maksimum penelusuran DAG (backend: `MAX_DAG_DEPTH`). */
export const MAX_DAG_DEPTH = 10;

/** Satu node di form (id lokal `key`; `id` backend `null` = step baru). */
export interface RoutingStepFormRow {
  key: string;
  id: number | null;
  label: string;
  order: number;
  work_center_id: number | null;
  /** Predecessor (id lokal `key`). */
  depends_on_keys: string[];
  /** Nomor langkah tujuan rework (step_no) — form memakai step_no seperti B22. */
  rework_target_step: number | null;
}

/** Nilai form header routing. */
export interface RoutingFormValues {
  name: string;
  code: string;
  description: string;
  capability_tags: string[];
  active: boolean;
}

/** Pesan error per field (kosong = valid). */
export interface RoutingFormErrors {
  name?: string;
  code?: string;
  description?: string;
  capability_tags?: string;
  steps?: string;
}

/** Nilai awal form "Routing Baru". */
export const EMPTY_ROUTING_FORM: RoutingFormValues = {
  name: '',
  code: '',
  description: '',
  capability_tags: [],
  active: true,
};

let keyCounter = 0;

/** Key lokal deterministik (tanpa `crypto.randomUUID` supaya test stabil). */
export function nextStepKey(): string {
  keyCounter += 1;
  return `step-local-${keyCounter}`;
}

/** Step lokal baru (order otomatis = max + 10, seperti backend). */
export function makeStepFormRow(order: number, label = ''): RoutingStepFormRow {
  return {
    key: nextStepKey(),
    id: null,
    label,
    order,
    work_center_id: null,
    depends_on_keys: [],
    rework_target_step: null,
  };
}

/** Order berikutnya dari daftar step (max + 10; 10 kalau kosong). */
export function nextStepOrder(steps: RoutingStepFormRow[]): number {
  if (steps.length === 0) return AUTO_ORDER_STEP;
  return Math.max(...steps.map((step) => step.order)) + AUTO_ORDER_STEP;
}

/** Baris step form dari step backend (dipakai saat mode edit). */
export function stepRowToForm(step: MasterRoutingStepRow, steps: MasterRoutingStepRow[]): RoutingStepFormRow {
  const byNo = new Map(steps.map((item) => [item.step_no, item]));
  return {
    key: `step-${step.id}`,
    id: step.id,
    label: step.wc_type,
    order: step.step_no,
    work_center_id: null,
    depends_on_keys: step.depends_on
      .map((no) => byNo.get(no))
      .filter((item): item is MasterRoutingStepRow => item !== undefined)
      .map((item) => `step-${item.id}`),
    rework_target_step: step.rework_target_step,
  };
}

/** Detail backend → (header form, step form) untuk mode edit. */
export function detailToForm(detail: MasterRoutingDetail): {
  values: RoutingFormValues;
  steps: RoutingStepFormRow[];
} {
  return {
    values: {
      name: detail.name,
      code: detail.code,
      description: detail.description,
      capability_tags: [...detail.capability_tags],
      active: detail.is_active,
    },
    steps: detail.steps.map((step) => stepRowToForm(step, detail.steps)),
  };
}

/** Validasi header form → error per field. */
export function validateRoutingForm(values: RoutingFormValues): RoutingFormErrors {
  const errors: RoutingFormErrors = {};
  const name = values.name.trim();
  if (!name) {
    errors.name = 'Nama routing wajib diisi.';
  } else if (name.length > MAX_ROUTING_NAME_LENGTH) {
    errors.name = `Nama maksimal ${MAX_ROUTING_NAME_LENGTH} karakter.`;
  }
  const code = values.code.trim();
  if (code && code.length > MAX_ROUTING_CODE_LENGTH) {
    errors.code = `Kode maksimal ${MAX_ROUTING_CODE_LENGTH} karakter.`;
  }
  if (values.description.length > MAX_ROUTING_DESCRIPTION_LENGTH) {
    errors.description = `Deskripsi maksimal ${MAX_ROUTING_DESCRIPTION_LENGTH} karakter.`;
  }
  const [, tagError] = normalizeTags(values.capability_tags);
  if (tagError) errors.capability_tags = tagError;
  return errors;
}

/* ------------------------------------------------------------ validasi DAG klien */

/** Graf id lokal: `key` → daftar `key` tujuan (edge dari `depends_on_keys`). */
export function formAdjacency(steps: RoutingStepFormRow[]): Map<string, string[]> {
  const graph = new Map<string, string[]>(steps.map((step) => [step.key, []]));
  for (const step of steps) {
    for (const dep of step.depends_on_keys) {
      const current = graph.get(dep);
      if (current !== undefined && graph.has(step.key)) current.push(step.key);
    }
  }
  return graph;
}

/**
 * PURE — cari siklus pada graf id lokal; `null` kalau bersih.
 *
 * Cermin `master/routing_services.py::find_cycle` (DFS iteratif, batas
 * `MAX_DAG_DEPTH`); graf yang lebih dalam dianggap tidak valid.
 */
export function findFormCycle(steps: RoutingStepFormRow[]): string[] | null {
  const graph = formAdjacency(steps);
  const color = new Map<string, number>();
  for (const key of graph.keys()) color.set(key, 0);

  for (const start of graph.keys()) {
    if (color.get(start) !== 0) continue;
    const path: string[] = [];
    const stack: Array<[string, number]> = [[start, 0]];
    while (stack.length > 0) {
      const frame = stack[stack.length - 1];
      const [node, index] = frame;
      if (index === 0) {
        color.set(node, 1);
        path.push(node);
        if (path.length > MAX_DAG_DEPTH) return [...path];
      }
      const neighbours = [...(graph.get(node) ?? [])].sort();
      if (index < neighbours.length) {
        frame[1] = index + 1;
        const target = neighbours[index];
        if (color.get(target) === 1) {
          return [...path.slice(path.indexOf(target)), target];
        }
        if (color.get(target) === 0) stack.push([target, 0]);
        continue;
      }
      color.set(node, 2);
      path.pop();
      stack.pop();
    }
  }
  return null;
}

/** Pesan siklus yang enak dibaca (pakai label step, fallback `key`). */
export function cycleMessage(steps: RoutingStepFormRow[], cycle: string[]): string {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  const labels = cycle.map((key) => {
    const step = byKey.get(key);
    if (step === undefined) return key;
    return step.label.trim() || `order ${step.order}`;
  });
  return `Routing akan membentuk siklus: ${labels.join(' → ')}. Backend akan menolaknya (400).`;
}

/** Validasi daftar step (label wajib, order unik, siklus). */
export function validateStepRows(steps: RoutingStepFormRow[]): string | undefined {
  if (steps.length === 0) {
    return 'Routing harus punya minimal satu step (node DAG).';
  }
  const seen = new Set<number>();
  for (const step of steps) {
    if (!step.label.trim()) {
      return `Step order ${step.order} belum punya label/work center.`;
    }
    if (step.label.trim().length > MAX_STEP_LABEL_LENGTH) {
      return `Label step order ${step.order} maksimal ${MAX_STEP_LABEL_LENGTH} karakter.`;
    }
    if (seen.has(step.order)) {
      return `Order ${step.order} dipakai lebih dari satu step (harus unik per routing).`;
    }
    seen.add(step.order);
  }
  const cycle = findFormCycle(steps);
  if (cycle !== null) return cycleMessage(steps, cycle);
  return undefined;
}

/* ------------------------------------------------------------------- payload */

/** Payload step endpoint H1.9 dari satu baris form (id lokal → id backend). */
export function formRowToStepPayload(
  row: RoutingStepFormRow,
  steps: RoutingStepFormRow[],
): MasterRoutingStepInput {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  const dependsOnIds = row.depends_on_keys
    .map((key) => byKey.get(key))
    .filter((step): step is RoutingStepFormRow => step !== undefined)
    .map((step) => step.id)
    .filter((id): id is number => id !== null);

  return {
    label: row.label.trim(),
    order: row.order,
    work_center_id: row.work_center_id,
    depends_on_step_ids: dependsOnIds,
    rework_target_step_id:
      row.rework_target_step === null
        ? null
        : (steps.find((step) => step.order === row.rework_target_step)?.id ?? null),
  };
}

/** Payload `steps[]` bentuk B22 (`depends_on` = daftar `step_no`) untuk POST create. */
export function formRowsToB22Steps(steps: RoutingStepFormRow[]) {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  return steps
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((step) => ({
      step_no: step.order,
      wc_type: step.label.trim(),
      depends_on: step.depends_on_keys
        .map((key) => byKey.get(key))
        .filter((row): row is RoutingStepFormRow => row !== undefined)
        .map((row) => row.order)
        .sort((a, b) => a - b),
      rework_target_step: step.rework_target_step,
    }));
}

/* -------------------------------------------------------------------- display */

/** Label status routing untuk tabel (soft delete = Nonaktif). */
export function routingStatusLabel(active: boolean): string {
  return active ? 'Aktif' : 'Nonaktif';
}

/** Ringkasan jumlah step (kolom tabel & kartu detail). */
export function stepsSummary(detail: MasterRoutingDetail): string {
  const initial = detail.steps.filter((step) => step.is_initial).length;
  const terminal = detail.steps.filter((step) => step.is_terminal).length;
  return `${detail.steps_count} step · ${initial} awal · ${terminal} akhir`;
}

/** PURE — detail backend → graf view model molekul `RoutingGraph`. */
export function detailToGraph(detail: MasterRoutingDetail): RoutingGraph {
  const steps = [...detail.steps].sort((a, b) => a.step_no - b.step_no);
  const nodes: DagNode[] = steps.map((step, index) => ({
    id: `step-${step.id}`,
    label: step.wc_type || `STEP-${step.step_no}`,
    step_no: step.step_no,
    position: { x: 100 + index * 180, y: 120 },
  }));
  const edges: DagEdge[] = detail.edges.map((edge: MasterRoutingEdge) => ({
    id: `edge-${edge.from}-${edge.to}-${edge.is_rework ? 'rework' : 'next'}`,
    from: `step-${edge.from}`,
    to: `step-${edge.to}`,
    isRework: edge.is_rework,
  }));
  return { nodes, edges };
}

/** PURE — step form (belum tersimpan) → graf pratinjau; edge rework digambar putus. */
export function formToGraph(steps: RoutingStepFormRow[]): RoutingGraph {
  const ordered = [...steps].sort((a, b) => a.order - b.order);
  const nodes: DagNode[] = ordered.map((step, index) => ({
    id: step.key,
    label: step.label.trim() || `order ${step.order}`,
    step_no: step.order,
    position: { x: 100 + index * 180, y: 120 },
  }));
  const edges: DagEdge[] = [];
  for (const step of ordered) {
    for (const dep of step.depends_on_keys) {
      edges.push({
        id: `edge-${dep}-${step.key}`,
        from: dep,
        to: step.key,
        isRework: false,
      });
    }
    if (step.rework_target_step !== null) {
      const target = ordered.find((row) => row.order === step.rework_target_step);
      if (target !== undefined) {
        edges.push({
          id: `edge-${step.key}-${target.key}-rework`,
          from: step.key,
          to: target.key,
          isRework: true,
        });
      }
    }
  }
  return { nodes, edges };
}


