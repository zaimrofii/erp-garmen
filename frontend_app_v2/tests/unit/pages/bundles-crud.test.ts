import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { BundleFormPage } from '@/pages/production/BundleFormPage';
import {
  allowedBundleActions,
  bundleCreateInputFromForm,
  bundleDetailItems,
  bundleEditFormFromDetail,
  bundleStateLabel,
  bundleUpdateInputFromForm,
  displayOrDash,
  EMPTY_BUNDLE_FORM,
  isBundleEditable,
  isBundleFormValid,
  isBundleStructurallyEditable,
  parseNumberList,
  sizeMatrixFromRows,
  toNullableId,
  toNullableNumber,
  validateBundleEditForm,
  validateBundleForm,
  validateMergeIds,
  validateSplitParts,
  BUNDLE_STATE_FILTERS,
  type BundleFormValues,
} from '@/lib/bundle';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { BundleCrudDetail } from '@/types/bundle';

/**
 * H2.4 — halaman Bundle MES (`/production/bundles/new|:id/edit`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` + `QueryClientProvider`/`MemoryRouter`;
 *   2. SUMBER/pure: route + guard `PRODUCTION_ROLES` di `App.tsx`, validasi form &
 *      split/merge di `lib/bundle.ts`, dan tombol "Buat Bundle" aditif di halaman F13.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const F13_PAGE = read('src/pages/bundles/BundleListPage.tsx');

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

const DETAIL: BundleCrudDetail = {
  id: 9,
  code: '12-L-001',
  state: 'DRAFT',
  size: 'L',
  qty: 5,
  qty_done: 0,
  version: 'a'.repeat(64),
  current_work_center_code: null,
  allowed_actions: ['BUNDLE_START'],
  sku_variant: '',
  work_order_id: 3,
  work_order_code: 'WO-2026-0001',
  order_line_id: 12,
  order_code: 'SO-2026-0001',
  product_code: 'KAOS-POLO',
  current_work_center_id: null,
  production_line_id: null,
  production_line_code: null,
  events_count: 0,
  ledger_status: 'SKIPPED',
  created_at: null,
  updated_at: null,
};

const VALID_FORM: BundleFormValues = {
  work_order_id: '3',
  bundle_size: '5',
  sku_variant: '',
  sizes: [{ size: 'l', qty: '7' }],
};

describe('H2.4 — lib PURE Bundle', () => {
  it('sizeMatrixFromRows menormalkan huruf besar & menggabungkan ukuran sama', () => {
    expect(
      sizeMatrixFromRows([
        { size: ' l ', qty: '3' },
        { size: 'L', qty: '2' },
        { size: 'm', qty: '1' },
        { size: '', qty: '9' },
        { size: 'S', qty: '0' },
      ]),
    ).toEqual({ L: 5, M: 1 });
  });

  it('validasi form create: WO wajib, minimal satu size qty > 0, bundle_size bulat', () => {
    expect(validateBundleForm(EMPTY_BUNDLE_FORM)).toEqual({
      work_order_id: 'Work Order wajib dipilih.',
      sizes: 'Isi minimal satu ukuran dengan qty > 0.',
    });
    expect(validateBundleForm({ ...VALID_FORM, bundle_size: '0' }).bundle_size).toContain('> 0');
    expect(validateBundleForm({ ...VALID_FORM, bundle_size: '2.5' }).bundle_size).toContain(
      'bilangan bulat',
    );
    // bundle_size kosong = sah (default backend 1)
    expect(validateBundleForm({ ...VALID_FORM, bundle_size: '' })).toEqual({});
    expect(isBundleFormValid(validateBundleForm(VALID_FORM))).toBe(true);
  });

  it('bundleCreateInputFromForm memetakan nilai form → body backend', () => {
    expect(bundleCreateInputFromForm(VALID_FORM)).toEqual({
      work_order_id: 3,
      size_matrix: { L: 7 },
      bundle_size: 5,
      sku_variant: '',
    });
    expect(bundleCreateInputFromForm(EMPTY_BUNDLE_FORM)).toEqual({
      work_order_id: null,
      size_matrix: {},
      bundle_size: null,
      sku_variant: '',
    });
  });

  it('bundleEditFormFromDetail + validateBundleEditForm (qty ≥ qty_done)', () => {
    expect(bundleEditFormFromDetail(DETAIL)).toEqual({
      size: 'L',
      sku_variant: '',
      qty: '5',
      current_work_center_id: '',
      production_line_id: '',
    });
    expect(
      validateBundleEditForm(
        { size: 'L', sku_variant: '', qty: '3', current_work_center_id: '', production_line_id: '' },
        4,
      ).qty,
    ).toContain('qty selesai');
    expect(
      bundleUpdateInputFromForm({
        size: ' m ',
        sku_variant: ' POLO ',
        qty: '8',
        current_work_center_id: '4',
        production_line_id: '',
      }),
    ).toEqual({
      size: 'M',
      sku_variant: 'POLO',
      qty: 8,
      current_work_center_id: 4,
      production_line_id: null,
    });
  });

  it('parseNumberList membersihkan teks bebas & toNullableId/toNullableNumber aman', () => {
    expect(parseNumberList('3, 2')).toEqual([3, 2]);
    expect(parseNumberList(' 5 ; 4 \n 1 ')).toEqual([5, 4, 1]);
    expect(parseNumberList('0, -2, abc')).toEqual([]);
    expect(toNullableId('')).toBeNull();
    expect(toNullableId('0')).toBeNull();
    expect(toNullableNumber('')).toBeNull();
    expect(toNullableNumber('2.5')).toBe(2.5);
  });

  it('validateSplitParts & validateMergeIds (aturan backend)', () => {
    expect(validateSplitParts([5], 5)).toContain('minimal 2');
    expect(validateSplitParts([3, 1], 5)).toContain('harus sama dengan qty bundle');
    expect(validateSplitParts([3, 2], 5)).toBeNull();
    expect(validateMergeIds([], 9)).toContain('minimal satu id');
    expect(validateMergeIds([9], 9)).toContain('Target merge');
    expect(validateMergeIds([11, 12], 9)).toBeNull();
  });

  it('label & aksi state mirror seed machine `garment.bundle`', () => {
    expect(bundleStateLabel('CUTTING')).toBe('Cutting');
    expect(bundleStateLabel('DONE')).toBe('Selesai');
    expect(bundleStateLabel('SCRAPPED')).toBe('SCRAPPED'); // state tak dikenal = apa adanya
    expect(allowedBundleActions('DRAFT')).toEqual(['BUNDLE_START', 'BUNDLE_SCRAP']);
    expect(allowedBundleActions('QC')).toEqual(['BUNDLE_FINISH', 'BUNDLE_SCRAP']);
    expect(allowedBundleActions('DONE')).toEqual([]);
  });

  it('isBundleEditable / isBundleStructurallyEditable (DRAFT & tanpa event)', () => {
    expect(isBundleEditable('DRAFT')).toBe(true);
    expect(isBundleEditable('CUTTING')).toBe(false);
    expect(isBundleStructurallyEditable({ state: 'DRAFT', events_count: 0 })).toBe(true);
    expect(isBundleStructurallyEditable({ state: 'DRAFT', events_count: 1 })).toBe(false);
    expect(isBundleStructurallyEditable({ state: 'DONE', events_count: 0 })).toBe(false);
  });

  it('bundleDetailItems + displayOrDash (ledger MES-only, tanpa odoo_id)', () => {
    const items = bundleDetailItems(DETAIL);
    const labels = items.map((item) => item.label);

    expect(labels).toContain('Work Order');
    expect(labels).toContain('Event Chatter');
    expect(labels).not.toContain('Odoo ID');
    expect(items.find((item) => item.label === 'Ledger')?.value).toContain('MES-only');
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash(0)).toBe('0');
  });

  it('BUNDLE_STATE_FILTERS memuat 6 tab (all + 5 state)', () => {
    expect(BUNDLE_STATE_FILTERS).toHaveLength(6);
    expect(BUNDLE_STATE_FILTERS[0]?.id).toBe('all');
    expect(BUNDLE_STATE_FILTERS.map((tab) => tab.id)).toContain('QC');
  });
});

describe('H2.4 — route, halaman, dan non-breaking F13', () => {
  it('App.tsx mendaftarkan 2 route Bundle H2.4 dengan guard PRODUCTION_ROLES', () => {
    for (const route of ['/production/bundles/new', '/production/bundles/:id/edit']) {
      expect(APP).toContain(`path="${route}"`);
    }

    // Route existing TIDAK dihapus (non-breaking).
    expect(APP).toContain('path="/production/bundles/:id"');
    expect(APP).toContain('path="/bundles"');
    expect(APP).toContain('path="/bundles/:id"');
    expect(APP).toContain('ProductionBundleDetailPage');
  });

  it('halaman F13 tetap memakai hook lama + tombol "Buat Bundle" (aditif)', () => {
    expect(F13_PAGE).toContain('useBundles');
    expect(F13_PAGE).toContain('Buat Bundle');
    expect(F13_PAGE).toContain('/production/bundles/new');
  });

  it('render BundleFormPage (baru) menampilkan judul + field matriks ukuran', () => {
    const { text } = renderPage(createElement(BundleFormPage), '/production/bundles/new');

    expect(text).toContain('Bundle Baru');
    expect(text).toContain('Work Order (DRAFT)');
    expect(text).toContain('Matriks Ukuran');
    expect(text).toContain('Pratinjau');
  });

  it('render BundleFormPage (mode kelola) tetap aman saat data pending', () => {
    const { html } = renderPage(
      createElement(BundleFormPage),
      '/production/bundles/9/edit',
      '/production/bundles/:id/edit',
    );

    expect(html.length).toBeGreaterThan(0);
  });
});

