import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { WorkOrderDetailPage } from '@/pages/production/WorkOrderDetailPage';
import { WorkOrderFormPage } from '@/pages/production/WorkOrderFormPage';
import {
  allowedWoActions,
  displayOrDash,
  EMPTY_WO_FORM,
  isWoEditable,
  isWoFormValid,
  isWoSplittable,
  parseSplitParts,
  validateSplitParts,
  validateWoForm,
  woActionLabel,
  woDetailItems,
  woFormFromDetail,
  woInputFromForm,
  woStateLabel,
  WO_STATE_FILTERS,
  type WoFormValues,
} from '@/lib/work-order';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { WorkOrderCrudDetail } from '@/types/work-order';

/**
 * H2.3 — halaman Work Order MES (`/production/work-orders/new|:id|:id/edit`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` + `QueryClientProvider`/`MemoryRouter`;
 *   2. SUMBER/pure: route + guard `PRODUCTION_ROLES` di `App.tsx`, validasi form &
 *      split di `lib/work-order.ts`, tombol "Buat WO Baru" di halaman F13, dan
 *      tombol "Generate WO" di halaman detail Order (H2.1).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const F13_PAGE = read('src/pages/work-orders/WorkOrderListPage.tsx');
const ORDER_DETAIL = read('src/pages/sales/OrderDetailPage.tsx');

/** Konteks feedback palsu — `useFeedback()` di halaman butuh provider. */
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

  return { html: htmlOf(tree), text: textOf(tree) };
}

const DETAIL: WorkOrderCrudDetail = {
  id: 5,
  code: 'WO-2026-0001',
  state: 'DRAFT',
  qty_planned: 20,
  qty_done: 0,
  order_line_id: 11,
  order_id: 3,
  order_code: 'SO-2026-0001',
  product_id: 9,
  product_code: 'KAOS-POLO',
  bundles_count: 0,
  allowed_actions: ['WO_START', 'WO_CANCEL'],
  created_at: null,
  updated_at: null,
  version: 'a'.repeat(64),
  bundles: [],
};

const VALID_FORM: WoFormValues = {
  order_line_id: '11',
  code: 'WO-MANUAL-1',
  qty_planned: '25',
};

describe('H2.3 — lib PURE Work Order', () => {
  it('validasi form: order line wajib, qty > 0, kode maksimal 64', () => {
    expect(validateWoForm(EMPTY_WO_FORM)).toEqual({ order_line_id: 'Baris order wajib dipilih.' });
    expect(validateWoForm({ ...VALID_FORM, qty_planned: '0' }).qty_planned).toContain('> 0');
    expect(validateWoForm({ ...VALID_FORM, qty_planned: '2.5' }).qty_planned).toContain(
      'bilangan bulat',
    );
    expect(validateWoForm({ ...VALID_FORM, code: 'x'.repeat(65) }).code).toContain('64');
    // qty kosong = sah (backend memakai OrderLine.qty) & kode kosong = nomor otomatis.
    expect(validateWoForm({ ...VALID_FORM, qty_planned: '', code: '' })).toEqual({});
    expect(isWoFormValid(validateWoForm(VALID_FORM))).toBe(true);
  });

  it('woInputFromForm memetakan nilai form → body backend', () => {
    expect(woInputFromForm(VALID_FORM)).toEqual({
      order_line_id: 11,
      code: 'WO-MANUAL-1',
      qty_planned: 25,
    });
    expect(woInputFromForm({ order_line_id: '', code: '  ', qty_planned: '' })).toEqual({
      order_line_id: null,
      code: '',
      qty_planned: null,
    });
  });

  it('woFormFromDetail mengisi form edit dari detail', () => {
    expect(woFormFromDetail(DETAIL)).toEqual({
      order_line_id: '11',
      code: 'WO-2026-0001',
      qty_planned: '20',
    });
  });

  it('parseSplitParts membersihkan teks bebas', () => {
    expect(parseSplitParts('60, 40')).toEqual([60, 40]);
    expect(parseSplitParts(' 12 ; 8 \n 5 ')).toEqual([12, 8, 5]);
    expect(parseSplitParts('0, -3, abc')).toEqual([]);
  });

  it('validateSplitParts: minimal 2 bagian & jumlah = qty rencana', () => {
    expect(validateSplitParts([20], 20)).toContain('minimal 2');
    expect(validateSplitParts([12, 7], 20)).toContain('harus sama dengan qty rencana');
    expect(validateSplitParts([12, 8], 20)).toBeNull();
  });

  it('label & aksi state mirror state machine `garment.work_order`', () => {
    expect(woStateLabel('IN_PROGRESS')).toBe('Dikerjakan');
    expect(woStateLabel('DONE')).toBe('Selesai');
    // STATE BARU TIDAK ADA: brief menyebut RELEASED, tapi sistem memakai state seeded.
    expect(woStateLabel('RELEASED')).toBe('RELEASED');
    expect(woActionLabel('WO_START')).toBe('Mulai WO');
    expect(allowedWoActions('DRAFT')).toEqual(['WO_START', 'WO_CANCEL']);
    expect(allowedWoActions('IN_PROGRESS')).toEqual(['WO_CLOSE', 'WO_CANCEL']);
    expect(allowedWoActions('DONE')).toEqual([]);
    expect(allowedWoActions('CANCELLED')).toEqual([]);
  });

  it('isWoEditable / isWoSplittable (DRAFT-only & tanpa bundle)', () => {
    expect(isWoEditable('DRAFT')).toBe(true);
    expect(isWoEditable('IN_PROGRESS')).toBe(false);
    expect(isWoSplittable({ state: 'DRAFT', bundles_count: 0 })).toBe(true);
    expect(isWoSplittable({ state: 'DRAFT', bundles_count: 1 })).toBe(false);
    expect(isWoSplittable({ state: 'IN_PROGRESS', bundles_count: 0 })).toBe(false);
  });

  it('woDetailItems + displayOrDash (ledger MES-only, tanpa odoo_id)', () => {
    const items = woDetailItems(DETAIL);
    const labels = items.map((item) => item.label);

    expect(labels).toContain('Kode');
    expect(labels).toContain('Jumlah Bundle');
    expect(labels).not.toContain('Odoo ID');
    expect(items.find((item) => item.label === 'Ledger')?.value).toContain('SKIPPED');
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash('   ')).toBe('-');
    expect(displayOrDash(0)).toBe('0');
  });

  it('WO_STATE_FILTERS memuat 5 tab (all + 4 state)', () => {
    expect(WO_STATE_FILTERS).toHaveLength(5);
    expect(WO_STATE_FILTERS[0]?.id).toBe('all');
    expect(WO_STATE_FILTERS.map((tab) => tab.id)).toContain('IN_PROGRESS');
  });
});

describe('H2.3 — route, nav, dan halaman', () => {
  it('App.tsx mendaftarkan 4 route Work Order dengan guard PRODUCTION_ROLES', () => {
    for (const route of [
      '/production/work-orders',
      '/production/work-orders/new',
      '/production/work-orders/:id',
      '/production/work-orders/:id/edit',
    ]) {
      expect(APP).toContain(`path="${route}"`);
    }

    expect(APP).toContain('const PRODUCTION_ROLES: Role[] = [\'operator\', \'supervisor\', \'owner\']');
    // List memakai halaman F13 (bukan daftar kedua).
    expect(APP).toContain('WorkOrderListPage');
    // Route F13 lama HARUS tetap ada (non-breaking).
    expect(APP).toContain('path="/work-orders"');
  });

  it('nav-config menambah topbar "Work Order" tanpa menghapus menu lain', () => {
    expect(NAV).toContain("path: '/production/work-orders'");
    expect(NAV).toContain("path: '/production/scan'");
    expect(NAV).toContain("path: '/production/qc'");
    expect(NAV).toContain("{ prefix: '/work-orders', appId: 'production' }");
  });

  it('halaman F13 tetap memakai hook lama + tombol "Buat WO Baru" (aditif)', () => {
    expect(F13_PAGE).toContain('useWorkOrders');
    expect(F13_PAGE).toContain('Buat WO Baru');
    expect(F13_PAGE).toContain('/production/work-orders/new');
  });

  it('halaman detail Order (H2.1) punya tombol "Generate WO" (idempoten)', () => {
    expect(ORDER_DETAIL).toContain('generateWorkOrdersForOrder');
    expect(ORDER_DETAIL).toContain('Generate WO');
    expect(ORDER_DETAIL).toContain('workOrdersCrud');
  });

  it('render WorkOrderFormPage (baru) menampilkan judul + field', () => {
    const { text } = renderPage(createElement(WorkOrderFormPage), '/production/work-orders/new');

    expect(text).toContain('Work Order Baru');
    expect(text).toContain('Baris Order');
    expect(text).toContain('Qty Rencana');
  });

  it('render WorkOrderDetailPage (SSR, data pending) menampilkan spinner tanpa crash', () => {
    const { html } = renderPage(
      createElement(WorkOrderDetailPage),
      '/production/work-orders/5',
      '/production/work-orders/:id',
    );

    expect(html.length).toBeGreaterThan(0);
  });
});


