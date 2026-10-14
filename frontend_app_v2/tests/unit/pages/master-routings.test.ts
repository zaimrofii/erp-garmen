import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { RoutingDetailPage } from '@/pages/master/RoutingDetailPage';
import { RoutingFormPage } from '@/pages/master/RoutingFormPage';
import { RoutingsPage } from '@/pages/master/RoutingsPage';
import {
  AUTO_ORDER_STEP,
  cycleMessage,
  detailToForm,
  detailToGraph,
  EMPTY_ROUTING_FORM,
  findFormCycle,
  formRowToStepPayload,
  formRowsToB22Steps,
  formToGraph,
  makeStepFormRow,
  MAX_DAG_DEPTH,
  nextStepOrder,
  routingStatusLabel,
  stepRowToForm,
  stepsSummary,
  validateRoutingForm,
  validateStepRows,
  type RoutingStepFormRow,
} from '@/lib/master-routing';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterRoutingDetail } from '@/types/master-routing';

/**
 * H1.9 — halaman master Routing DAG (`/master/routings*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form/DAG
 *      (**deteksi siklus**), konversi form ↔ payload, dan helper tampilan.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

/** Konteks feedback palsu — `useFeedback()` di halaman detail/form butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(
  element: ReactElement,
  initialPath: string,
  routePath = initialPath,
): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: [initialPath] },
      createElement(
        FeedbackRuntimeContext.Provider,
        { value: FEEDBACK },
        createElement(Routes, null, createElement(Route, { path: routePath, element })),
      ),
    ),
  );
  const html = htmlOf(tree);

  return { html, text: textOf(html) };
}

const DETAIL: MasterRoutingDetail = {
  id: 7,
  code: 'RT-H19',
  name: 'Routing H1.9',
  description: 'sablon dulu, baru jahit',
  is_active: true,
  steps: [
    {
      id: 11,
      step_no: 1,
      wc_type: 'CUTTING',
      depends_on: [],
      rework_target_step: null,
      is_initial: true,
      is_terminal: false,
    },
    {
      id: 12,
      step_no: 2,
      wc_type: 'SEWING',
      depends_on: [1],
      rework_target_step: 1,
      is_initial: false,
      is_terminal: true,
    },
  ],
  capability_tags: ['JAHIT', 'OBRAS'],
  steps_count: 2,
  nodes: [
    { id: 11, label: 'CUTTING', step_no: 1 },
    { id: 12, label: 'SEWING', step_no: 2 },
  ],
  edges: [
    { from: 11, to: 12, overlap_pct: 0, is_rework: false },
    { from: 12, to: 11, overlap_pct: 0, is_rework: true },
  ],
  created_at: '2026-10-11T04:00:00+00:00',
  updated_at: '2026-10-11T05:00:00+00:00',
};

describe('H1.9 — route, guard & nav', () => {
  it('App.tsx: 4 route master routing (INVENTORY_ROLES) + /settings/routing tetap ada', () => {
    expect(APP).toContain('path="/master/routings"');
    expect(APP).toContain('path="/master/routings/new"');
    expect(APP).toContain('path="/master/routings/:id/edit"');
    expect(APP).toContain('path="/master/routings/:id"');
    expect(APP).toContain('<MasterRoutingsPage />');
    expect(APP).toContain('<MasterRoutingFormPage />');
    expect(APP).toContain('<MasterRoutingDetailPage />');
    expect(APP).toContain("import('@/pages/master/RoutingsPage')");
    // endpoint = B22 di tempat: TIDAK ada endpoint API paralel /master/routings/
    expect(APP).not.toContain('api/v1/master/routings');
    // route editor DAG Settings (B22 F3A) tetap hidup
    expect(APP).toContain('path="/settings/routing"');
  });

  it('nav-config menambah topbar "Master Routing" di app Inventory', () => {
    expect(NAV).toContain("label: 'Master Routing', path: '/master/routings'");
    expect(legacyAppIdForPath('/master/routings')).toBe('inventory');

    const inventory = NAV_APPS.find((app) => app.id === 'inventory');

    expect(inventory?.topbar.some((item) => item.path === '/master/routings')).toBe(true);
  });
});

describe('H1.9 — lib form & DAG (PURE)', () => {
  it('makeStepFormRow/nextStepOrder memakai AUTO_ORDER_STEP (10) seperti backend', () => {
    expect(AUTO_ORDER_STEP).toBe(10);
    expect(nextStepOrder([])).toBe(10);

    const first = makeStepFormRow(10, 'CUTTING');
    const second = makeStepFormRow(nextStepOrder([first]), 'SEWING');

    expect(second.order).toBe(20);
    expect(first.depends_on_keys).toEqual([]);
    expect(first.id).toBeNull();
  });

  it('detailToForm mengubah depends_on step_no → key lokal (key `step-<id>` stabil)', () => {
    const form = detailToForm(DETAIL);

    expect(form.values).toEqual({
      name: 'Routing H1.9',
      code: 'RT-H19',
      description: 'sablon dulu, baru jahit',
      capability_tags: ['JAHIT', 'OBRAS'],
      active: true,
    });
    expect(form.steps.map((step) => step.key)).toEqual(['step-11', 'step-12']);
    expect(form.steps[1]?.depends_on_keys).toEqual(['step-11']);
    expect(form.steps[1]?.rework_target_step).toBe(1);

    const row = stepRowToForm(DETAIL.steps[1]!, DETAIL.steps);

    expect(row.key).toBe('step-12');
    expect(row.id).toBe(12);
    expect(row.label).toBe('SEWING');
  });

  it('validateRoutingForm: nama wajib, tag harus array string', () => {
    expect(validateRoutingForm(EMPTY_ROUTING_FORM).name).toContain('wajib');
    expect(validateRoutingForm({ ...EMPTY_ROUTING_FORM, name: '  ' }).name).toContain('wajib');
    expect(
      validateRoutingForm({ ...EMPTY_ROUTING_FORM, name: 'X', capability_tags: [] }),
    ).toEqual({});
  });
});

describe('H1.9 — validasi DAG (deteksi siklus sisi klien)', () => {
  function row(key: string, order: number, depends: string[], label = key): RoutingStepFormRow {
    return {
      key,
      id: null,
      label,
      order,
      work_center_id: null,
      depends_on_keys: depends,
      rework_target_step: null,
    };
  }

  it('graf linear bersih → null; siklus A→B→C→A terdeteksi + pesan label', () => {
    const linear = [row('a', 1, []), row('b', 2, ['a']), row('c', 3, ['b'])];

    expect(findFormCycle(linear)).toBeNull();
    expect(validateStepRows(linear)).toBeUndefined();

    const cyclic = [
      row('a', 1, ['c'], 'CUTTING'),
      row('b', 2, ['a'], 'SEWING'),
      row('c', 3, ['b'], 'QC'),
    ];
    const cycle = findFormCycle(cyclic);

    expect(cycle).not.toBeNull();
    expect(cycle?.[0]).toBe(cycle?.[cycle.length - 1]);
    expect(cycleMessage(cyclic, cycle ?? [])).toContain('siklus');
    expect(validateStepRows(cyclic)).toContain('siklus');
  });

  it('MAX_DAG_DEPTH = 10 (sama backend) dan validateStepRows menolak input cacat', () => {
    expect(MAX_DAG_DEPTH).toBe(10);

    const dalam = Array.from({ length: 13 }, (_, index) =>
      row(`s${index}`, index + 1, index === 0 ? [] : [`s${index - 1}`]),
    );

    expect(findFormCycle(dalam)).not.toBeNull();
    expect(validateStepRows([])).toContain('minimal satu step');
    expect(validateStepRows([row('a', 1, [], '')])).toContain('belum punya label');
    expect(validateStepRows([row('a', 1, []), row('b', 1, [])])).toContain('Order 1');
  });

  it('formRowToStepPayload memakai id backend & mengabaikan step baru (id null)', () => {
    const existing = { ...row('step-11', 1, []), id: 11, label: 'CUTTING' };
    const baru = { ...row('step-local-1', 2, ['step-11', 'step-local-2']), label: 'QC' };
    const payload = formRowToStepPayload(baru, [existing, baru]);

    expect(payload.label).toBe('QC');
    expect(payload.depends_on_step_ids).toEqual([11]);
    expect(payload.work_center_id).toBeNull();
  });

  it('formRowsToB22Steps menyusun steps[] bentuk B22 (depends_on = step_no)', () => {
    const steps = [row('a', 10, []), row('b', 20, ['a']), row('c', 30, ['a', 'b'])];

    expect(formRowsToB22Steps(steps)).toEqual([
      { step_no: 10, wc_type: 'a', depends_on: [], rework_target_step: null },
      { step_no: 20, wc_type: 'b', depends_on: [10], rework_target_step: null },
      { step_no: 30, wc_type: 'c', depends_on: [10, 20], rework_target_step: null },
    ]);
  });
});

describe('H1.9 — helper tampilan & graf', () => {
  it('label status, ringkasan step, detailToGraph, dan formToGraph', () => {
    expect(routingStatusLabel(true)).toBe('Aktif');
    expect(routingStatusLabel(false)).toBe('Nonaktif');
    expect(stepsSummary(DETAIL)).toBe('2 step · 1 awal · 1 akhir');

    const detail = detailToGraph(DETAIL);

    expect(detail.nodes.map((node) => node.id)).toEqual(['step-11', 'step-12']);
    expect(detail.nodes[0]?.position).toEqual({ x: 100, y: 120 });
    expect(detail.edges).toEqual([
      { id: 'edge-11-12-next', from: 'step-11', to: 'step-12', isRework: false },
      { id: 'edge-12-11-rework', from: 'step-12', to: 'step-11', isRework: true },
    ]);

    const form = formToGraph(detailToForm(DETAIL).steps);

    expect(form.nodes.map((node) => node.step_no)).toEqual([1, 2]);
    expect(form.edges).toContainEqual({
      id: 'edge-step-11-step-12',
      from: 'step-11',
      to: 'step-12',
      isRework: false,
    });
    expect(form.edges).toContainEqual({
      id: 'edge-step-12-step-11-rework',
      from: 'step-12',
      to: 'step-11',
      isRework: true,
    });
  });
});

describe('H1.9 — render halaman (react-dom/server)', () => {
  it('RoutingsPage (list) & RoutingFormPage (create) render elemen kunci', () => {
    const list = renderPage(createElement(RoutingsPage), '/master/routings');

    expect(list.text).toContain('Master Routing');
    expect(list.text).toContain('Routing Baru');

    const form = renderPage(
      createElement(RoutingFormPage),
      '/master/routings/new',
      '/master/routings/new',
    );

    expect(form.text).toContain('Routing Baru');
    expect(form.text).toContain('Nama *');
    expect(form.text).toContain('Tag Kapabilitas Routing');
    expect(form.text).toContain('Step / Node DAG');
    expect(form.text).toContain('Tambah Step');
    expect(form.text).toContain('Pratinjau DAG');
  });

  it('RoutingDetailPage: id tidak valid & query pending', () => {
    const invalid = renderPage(
      createElement(RoutingDetailPage),
      '/master/routings/abc',
      '/master/routings/:id',
    );

    expect(invalid.text).toContain('Id routing tidak valid');

    const pending = renderPage(
      createElement(RoutingDetailPage),
      '/master/routings/7',
      '/master/routings/:id',
    );

    expect(pending.text).toContain('Detail Routing');
    expect(pending.text).toContain('Memuat routing');
  });
});



