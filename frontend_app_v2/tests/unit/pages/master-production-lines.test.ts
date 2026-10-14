import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { ProductionLineDetailPage } from '@/pages/master/ProductionLineDetailPage';
import { ProductionLineFormPage } from '@/pages/master/ProductionLineFormPage';
import { ProductionLinesPage } from '@/pages/master/ProductionLinesPage';
import {
  activeBundlesLabel,
  addTag,
  allocationRulesLabel,
  displayOrDash,
  EMPTY_PRODUCTION_LINE_FORM,
  isProductionLineFormValid,
  normalizeCapabilityTags,
  productionLineDetailItems,
  productionLineFormFromRow,
  productionLineInputFromForm,
  removeTag,
  toggleWorkCenter,
  validateProductionLineForm,
  workCentersCountLabel,
  workCentersSummary,
  type ProductionLineFormValues,
} from '@/lib/master-production-line';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type {
  MasterProductionLineDetail,
  MasterProductionLineRow,
} from '@/types/master-production-line';

/**
 * H1.8 — halaman master Production Line (`/master/production-lines*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form, tag input,
 *      toggle anggota WC, dan helper tampilan (ringkasan anggota, label, detail item).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const LIST_PAGE = 'src/pages/master/ProductionLinesPage.tsx';
const FORM_PAGE = 'src/pages/master/ProductionLineFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/ProductionLineDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
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

const ROW: MasterProductionLineRow = {
  id: 3,
  code: 'LINE-A',
  name: 'Lini Jahit A',
  description: 'Lini utama shift 1',
  capability_tags: ['JAHIT', 'OBRAS'],
  work_centers_count: 2,
  work_center_ids: [5, 6],
  work_center_names: ['CUTTING-1', 'SEWING-1'],
  allocation_rules_count: 1,
  active: true,
  created_at: null,
  updated_at: null,
};

const DETAIL: MasterProductionLineDetail = {
  ...ROW,
  work_centers: [
    { id: 5, code: 'CUTTING-1', name: 'Stasiun CUTTING-1' },
    { id: 6, code: 'SEWING-1', name: 'Stasiun SEWING-1' },
  ],
  active_bundles_count: 2,
};

const VALID_FORM: ProductionLineFormValues = {
  code: 'LINE-A',
  name: 'Lini Jahit A',
  description: 'Lini utama shift 1',
  capability_tags: ['JAHIT', 'OBRAS'],
  work_center_ids: [5, 6],
  active: true,
};

describe('H1.8 — route, guard & halaman (react-dom/server)', () => {
  it('4 route production line terdaftar dengan guard INVENTORY_ROLES + alias nav', () => {
    for (const routePath of [
      '/master/production-lines',
      '/master/production-lines/new',
      '/master/production-lines/:id',
      '/master/production-lines/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterProductionLinesPage />');
    expect(APP).toContain('<MasterProductionLineFormPage />');
    expect(APP).toContain('<MasterProductionLineDetailPage />');
    expect(APP).toMatch(/path="\/master\/production-lines"[\s\S]{0,220}INVENTORY_ROLES/);

    expect(NAV).toContain("{ prefix: '/master/production-lines', appId: 'inventory' }");
    expect(legacyAppIdForPath('/master/production-lines')).toBe('inventory');
    expect(legacyAppIdForPath('/master/production-lines/3/edit')).toBe('inventory');

    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const menu = inventory?.topbar.find((item) => item.label === 'Master Production Line');
    expect(menu?.path).toBe('/master/production-lines');
    expect(menu?.children).toBeUndefined();
  });

  it('halaman list: judul MES-only, kolom (Tag/Anggota/Aturan), filter tag, CTA', () => {
    const { html, text } = renderPage(
      createElement(ProductionLinesPage),
      '/master/production-lines',
    );

    expect(text).toContain('Master Production Line');
    expect(text).toContain('MES-only');
    expect(text).toContain('Production Line Baru');
    for (const label of ['Kode', 'Nama', 'Tag Kapabilitas', 'Anggota', 'Aturan', 'Status']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua Tag');
    expect(text).toContain('JAHIT');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
    expect(text).not.toContain('Odoo ID'); // MES-only: tidak ada kolom Odoo ID
  });

  it('halaman form (baru): field utama, tag input, anggota WC, submit', () => {
    const { html, text } = renderPage(
      createElement(ProductionLineFormPage),
      '/master/production-lines/new',
    );

    expect(text).toContain('Production Line Baru');
    for (const label of ['Kode *', 'Nama *', 'Catatan']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Tag Kapabilitas Lini (maksimal 20; Enter atau koma untuk menambah)');
    expect(text).toContain('Tambah tag');
    expect(text).toContain('Tag Kapabilitas Lini');
    // Teks JSX berspasi (`{' '}` antarelemen) → diuji dengan regex (pola H1.5).
    expect(text).toMatch(/Anggota Work Center \(\s*0\s*dipilih — boleh kosong\)/);
    expect(text).toContain('Production line aktif');
    expect(text).toContain('Simpan Production Line');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit) & detail: mode edit, badge MES-only, Sync DISABLED', () => {
    const edit = renderPage(
      createElement(ProductionLineFormPage),
      '/master/production-lines/3/edit',
      '/master/production-lines/:id/edit',
    );
    expect(edit.text).toContain('Edit Production Line');
    expect(edit.text).toContain('Simpan Perubahan');

    const detail = renderPage(
      createElement(ProductionLineDetailPage),
      '/master/production-lines/3',
    );
    expect(detail.text).toContain('Detail Production Line');
    expect(detail.text).toContain('MES-only');
    expect(detail.text).toContain('Sync ke Odoo');
    expect(detail.html).toContain('disabled');
    expect(detail.html).toContain('Production Line MES-only');
  });
});

describe('H1.8 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server (search + capability_tag), CSV, klik → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterProductionLines'");
    expect(page).toContain('fetchProductionLines(client, {');
    expect(page).toContain('PRODUCTION_LINES_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-production-lines'");
    expect(page).toContain('capability_tag: tagParamForStatus(capabilityTag)');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/production-lines/${String(row.id)}`)");
    expect(page).not.toContain('odoo_id');
  });

  it('form: create/update + validasi pure + tag input + multi-select work center', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createProductionLine(client, input)');
    expect(page).toContain('updateProductionLine(client, lineId, input)');
    expect(page).toContain('validateProductionLineForm(values)');
    expect(page).toContain('productionLineInputFromForm(values)');
    expect(page).toContain('addTag(values.capability_tags, tagInput)');
    expect(page).toContain('toggleWorkCenter(values.work_center_ids, center.id)');
    expect(page).toContain(
      'fetchWorkCenters(client, { limit: WORK_CENTERS_LIMIT_MAX, active: true })',
    );
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + tabel anggota WC + tanpa mutation/delete', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchProductionLine(client, lineId ?? 0)');
    expect(page).toContain('/master/production-lines/${String(lineId)}/edit');
    expect(page).toContain('line.work_centers.map((center)');
    expect(page).toContain('activeBundlesLabel(line)');
    expect(page).toContain('allocationRulesLabel(line)');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteProductionLine');
  });
});

describe('H1.8 — validasi form & helper (lib, tag dipakai ulang dari H1.7)', () => {
  it('form valid → tanpa error; body API = trim + tag dinormalisasi + M2M urut', () => {
    const errors = validateProductionLineForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isProductionLineFormValid(errors)).toBe(true);
    expect(
      productionLineInputFromForm({
        ...VALID_FORM,
        code: ' LINE-A ',
        capability_tags: [' JAHIT ', 'jahit', 'OBRAS'],
        work_center_ids: [6, 5, 6],
      }),
    ).toEqual({
      code: 'LINE-A',
      name: 'Lini Jahit A',
      description: 'Lini utama shift 1',
      capability_tags: ['JAHIT', 'OBRAS'],
      work_center_ids: [5, 6],
      active: true,
    });
    expect('odoo_id' in productionLineInputFromForm(VALID_FORM)).toBe(false);
  });

  it('kode/nama kosong, teks & tag terlalu panjang → error (tidak dikirim)', () => {
    const errors = validateProductionLineForm({
      ...VALID_FORM,
      code: '  ',
      name: '',
      description: 'D'.repeat(2001),
    });

    expect(errors.code).toBe('Kode production line wajib diisi (mis. LINE-A).');
    expect(errors.name).toBe('Nama production line wajib diisi.');
    expect(errors.description).toContain('maksimal 2000 karakter');
    expect(isProductionLineFormValid(errors)).toBe(false);
    expect(validateProductionLineForm({ ...VALID_FORM, name: 'N'.repeat(151) }).name).toContain(
      'maksimal 150',
    );

    const many = validateProductionLineForm({
      ...VALID_FORM,
      capability_tags: Array.from({ length: 21 }, (_, index) => `T${String(index)}`),
    });
    expect(many.capability_tags).toBe('Tag kapabilitas maksimal 20 buah.');

    const long = validateProductionLineForm({
      ...VALID_FORM,
      capability_tags: ['X'.repeat(33)],
    });
    expect(long.capability_tags).toContain('maksimal 32 karakter');

    expect(Object.keys(validateProductionLineForm(EMPTY_PRODUCTION_LINE_FORM)).sort()).toEqual([
      'code',
      'name',
    ]);
  });

  it('edit: formFromRow ↔ inputFromForm konsisten (M2M kosong boleh) + helper tampilan', () => {
    const form = productionLineFormFromRow(ROW);
    expect(form).toEqual(VALID_FORM);
    expect(productionLineInputFromForm(form).work_center_ids).toEqual([5, 6]);

    const empty = productionLineFormFromRow({ ...ROW, work_center_ids: [], work_center_names: [] });
    expect(empty.work_center_ids).toEqual([]);
    expect(validateProductionLineForm(empty)).toEqual({});

    expect(normalizeCapabilityTags([' OBRAS ', 'obras', '', 'Overdeck'])).toEqual([
      'OBRAS',
      'Overdeck',
    ]);
    expect(addTag(['JAHIT'], ' obras ')).toEqual(['JAHIT', 'obras']);
    expect(removeTag(['JAHIT', 'OBRAS'], 0)).toEqual(['OBRAS']);
    expect(removeTag(['JAHIT'], 9)).toEqual(['JAHIT']);

    expect(toggleWorkCenter([5], 6)).toEqual([5, 6]);
    expect(toggleWorkCenter([5, 6], 5)).toEqual([6]);
    expect(toggleWorkCenter([], 5)).toEqual([5]);

    expect(workCentersSummary(ROW)).toBe('CUTTING-1, SEWING-1');
    expect(workCentersSummary({ ...ROW, work_center_names: [] })).toBe('-');
    expect(
      workCentersSummary({
        ...ROW,
        work_center_names: ['A', 'B', 'C', 'D'],
        work_centers_count: 4,
      }),
    ).toBe('A, B, C +1');
    expect(workCentersCountLabel(ROW)).toBe('2 work center');
    expect(activeBundlesLabel(DETAIL)).toBe('2 bundle aktif');
    expect(allocationRulesLabel(DETAIL)).toBe('1 aturan alokasi');

    const items = productionLineDetailItems(ROW);
    expect(items.find((item) => item.label === 'Tag Kapabilitas')?.value).toBe('JAHIT, OBRAS');
    expect(items.find((item) => item.label === 'Sinkronisasi')?.value).toBe(
      'MES-only (tidak dikirim ke Odoo)',
    );
    expect(items.find((item) => item.label === 'Status')?.value).toBe('Aktif');
    expect(displayOrDash('  LINE-A ')).toBe('LINE-A');
    expect(displayOrDash('')).toBe('-');
    expect(displayOrDash(null)).toBe('-');
  });
});

