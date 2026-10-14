import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { WorkCenterDetailPage } from '@/pages/master/WorkCenterDetailPage';
import { WorkCenterFormPage } from '@/pages/master/WorkCenterFormPage';
import { WorkCentersPage } from '@/pages/master/WorkCentersPage';
import {
  activeBundlesLabel,
  addTag,
  displayOrDash,
  EMPTY_WORK_CENTER_FORM,
  formatCapacity,
  isWorkCenterFormValid,
  normalizeTags,
  productionLinesLabel,
  removeTag,
  validateWorkCenterForm,
  workCenterDetailItems,
  workCenterFormFromRow,
  workCenterInputFromForm,
  WC_TYPE_SUGGESTIONS,
  type WorkCenterFormValues,
} from '@/lib/master-work-center';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterWorkCenterDetail, MasterWorkCenterRow } from '@/types/master-work-center';

/**
 * H1.7 — halaman master Work Center (`/master/work-centers*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon dibangun `createElement` agar file
 *      tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form, tag input
 *      (add/remove/dedupe), dan helper tampilan (kapasitas, bundle aktif, lini).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const LIST_PAGE = 'src/pages/master/WorkCentersPage.tsx';
const FORM_PAGE = 'src/pages/master/WorkCenterFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/WorkCenterDetailPage.tsx';

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

const ROW: MasterWorkCenterRow = {
  id: 5,
  code: 'SEWING-1',
  name: 'Stasiun Jahit 1',
  wc_type: 'SEWING',
  capability_tags: ['JAHIT_LURUS', 'OBRAS'],
  capacity_per_hour: 40.5,
  description: 'Meja jahit utama',
  active: true,
  config: {},
  created_at: null,
  updated_at: null,
};

const DETAIL: MasterWorkCenterDetail = {
  ...ROW,
  active_bundles_count: 2,
  production_lines: [{ id: 3, code: 'LINE-A', name: 'Lini A' }],
};

const VALID_FORM: WorkCenterFormValues = {
  code: 'SEWING-1',
  name: 'Stasiun Jahit 1',
  wc_type: 'SEWING',
  capability_tags: ['JAHIT_LURUS', 'OBRAS'],
  capacity_per_hour: '40.5',
  description: 'Meja jahit utama',
  active: true,
};

describe('H1.7 — route & guard (App.tsx)', () => {
  it('4 route work center terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/work-centers',
      '/master/work-centers/new',
      '/master/work-centers/:id',
      '/master/work-centers/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterWorkCentersPage />');
    expect(APP).toContain('<MasterWorkCenterFormPage />');
    expect(APP).toContain('<MasterWorkCenterDetailPage />');
    expect(APP).toMatch(/path="\/master\/work-centers"[\s\S]{0,220}INVENTORY_ROLES/);
  });

  it('path `/master/work-centers*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(NAV).toContain("{ prefix: '/master/work-centers', appId: 'inventory' }");
    expect(legacyAppIdForPath('/master/work-centers')).toBe('inventory');
    expect(legacyAppIdForPath('/master/work-centers/5/edit')).toBe('inventory');
  });

  it('menu Inventory punya item Master Work Center (link biasa)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Work Center');

    expect(item?.path).toBe('/master/work-centers');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.7 — render halaman (react-dom/server)', () => {
  it('halaman list: judul MES-only, kolom (Tipe/Kapasitas/Tag), filter tipe, CTA', () => {
    const { html, text } = renderPage(createElement(WorkCentersPage), '/master/work-centers');

    expect(text).toContain('Master Work Center');
    expect(text).toContain('MES-only');
    expect(text).toContain('Work Center Baru');
    for (const label of ['Kode', 'Nama', 'Tipe', 'Kapasitas/jam', 'Tag Kapabilitas', 'Status']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua Tipe');
    expect(text).toContain('SEWING');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
    expect(text).not.toContain('Odoo ID'); // MES-only: tidak ada kolom Odoo ID
  });

  it('halaman form (baru): field wajib, saran tipe, input tag & checkbox aktif', () => {
    const { html, text } = renderPage(
      createElement(WorkCenterFormPage),
      '/master/work-centers/new',
    );

    expect(text).toContain('Work Center Baru');
    for (const label of ['Kode *', 'Nama *', 'Tipe Stasiun', 'Kapasitas per Jam', 'Catatan']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Tag Kapabilitas (maksimal 20; Enter atau koma untuk menambah)');
    expect(text).toContain('Tambah tag');
    expect(text).toContain('Belum ada tag kapabilitas.');
    expect(text).toContain('Work center aktif');
    expect(text).toContain('Simpan Work Center');
    for (const suggestion of WC_TYPE_SUGGESTIONS) {
      expect(text, suggestion).toContain(suggestion);
    }
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + tombol simpan perubahan', () => {
    const { text } = renderPage(
      createElement(WorkCenterFormPage),
      '/master/work-centers/5/edit',
      '/master/work-centers/:id/edit',
    );

    expect(text).toContain('Edit Work Center');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: badge MES-only + Sync DISABLED + catatan lini H1.8', () => {
    const { html, text } = renderPage(
      createElement(WorkCenterDetailPage),
      '/master/work-centers/5',
    );

    expect(text).toContain('Detail Work Center');
    expect(text).toContain('MES-only');
    expect(text).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Work Center MES-only');
  });
});

describe('H1.7 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server (search + wc_type), CSV, klik → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterWorkCenters'");
    expect(page).toContain('fetchWorkCenters(client, {');
    expect(page).toContain('WORK_CENTERS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-work-centers'");
    expect(page).toContain('wc_type: typeParamForStatus(wcType)');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/work-centers/${String(row.id)}`)");
    expect(page).not.toContain('odoo_id');
  });

  it('form: create/update lewat adapter + validasi pure + tag input', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createWorkCenter(client, input)');
    expect(page).toContain('updateWorkCenter(client, workCenterId, input)');
    expect(page).toContain('validateWorkCenterForm(values)');
    expect(page).toContain('workCenterInputFromForm(values)');
    expect(page).toContain('addTag(values.capability_tags, tagInput)');
    expect(page).toContain("removeTag(values.capability_tags, index)");
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + tanpa mutation/delete + pakai label helper', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchWorkCenter(client, workCenterId ?? 0)');
    expect(page).toContain('/master/work-centers/${String(workCenterId)}/edit');
    expect(page).toContain('activeBundlesLabel(workCenter)');
    expect(page).toContain('productionLinesLabel(workCenter)');
    expect(page).toContain('Lini Produksi');
    expect(page).toContain('H1.8');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteWorkCenter');
  });
});

describe('H1.7 — validasi form (kode, nama, kapasitas, tag)', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateWorkCenterForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isWorkCenterFormValid(errors)).toBe(true);
    expect(workCenterInputFromForm(VALID_FORM)).toEqual({
      code: 'SEWING-1',
      name: 'Stasiun Jahit 1',
      wc_type: 'SEWING',
      capability_tags: ['JAHIT_LURUS', 'OBRAS'],
      capacity_per_hour: 40.5,
      description: 'Meja jahit utama',
      active: true,
    });
    expect('odoo_id' in workCenterInputFromForm(VALID_FORM)).toBe(false);
  });

  it('kode KOSONG → error wajib (tidak dikirim) + nama kosong juga error', () => {
    const errors = validateWorkCenterForm({ ...VALID_FORM, code: '   ', name: '' });

    expect(errors.code).toBe('Kode work center wajib diisi (mis. SEWING-1).');
    expect(errors.name).toBe('Nama work center wajib diisi.');
    expect(isWorkCenterFormValid(errors)).toBe(false);
  });

  it('kapasitas: angka ≥ 0 valid, kosong/ngawur/negatif → error', () => {
    expect(validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: '0' }).capacity_per_hour).toBeUndefined();
    expect(
      validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: '12.75' }).capacity_per_hour,
    ).toBeUndefined();

    expect(
      validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: '' }).capacity_per_hour,
    ).toContain('wajib diisi');
    expect(
      validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: 'empat puluh' }).capacity_per_hour,
    ).toBe('Kapasitas per jam harus angka.');
    expect(
      validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: '-3' }).capacity_per_hour,
    ).toBe('Kapasitas per jam tidak boleh negatif.');
    expect(
      validateWorkCenterForm({ ...VALID_FORM, capacity_per_hour: '999999999' }).capacity_per_hour,
    ).toContain('maksimal');
  });

  it('tag: > 20 tag & tag > 32 karakter → error; tipe > 64 karakter → error', () => {
    const manyTags = Array.from({ length: 21 }, (_, index) => `TAG${String(index)}`);
    const errors = validateWorkCenterForm({
      ...VALID_FORM,
      capability_tags: manyTags,
      wc_type: 'T'.repeat(65),
    });

    expect(errors.capability_tags).toBe('Tag kapabilitas maksimal 20 buah.');
    expect(errors.wc_type).toBe('Tipe maksimal 64 karakter.');

    const longTag = validateWorkCenterForm({
      ...VALID_FORM,
      capability_tags: ['X'.repeat(33)],
    });
    expect(longTag.capability_tags).toContain('maksimal 32 karakter');
  });

  it('form awal (EMPTY_WORK_CENTER_FORM): hanya kode & nama yang error; kapasitas 0 valid', () => {
    const errors = validateWorkCenterForm(EMPTY_WORK_CENTER_FORM);

    expect(Object.keys(errors).sort()).toEqual(['code', 'name']);
    expect(errors.capacity_per_hour).toBeUndefined();
  });

  it('edit: workCenterFormFromRow ↔ workCenterInputFromForm konsisten', () => {
    const form = workCenterFormFromRow(ROW);

    expect(form).toEqual(VALID_FORM);
    expect(workCenterInputFromForm(form)).toEqual(workCenterInputFromForm(VALID_FORM));

    const inactive = workCenterFormFromRow({ ...ROW, active: false, capacity_per_hour: 0 });
    expect(inactive.active).toBe(false);
    expect(inactive.capacity_per_hour).toBe('0');
  });
});

describe('H1.7 — helper tampilan & tag input (lib)', () => {
  it('normalizeTags: trim, buang kosong, dedupe case-insensitive (huruf dipertahankan)', () => {
    expect(normalizeTags(['  OBRAS ', 'obras', '', '  ', 'Overdeck'])).toEqual([
      'OBRAS',
      'Overdeck',
    ]);
    expect(normalizeTags([])).toEqual([]);
  });

  it('addTag menambah (dedupe) & removeTag menghapus per indeks tanpa mutasi', () => {
    const base = ['JAHIT_LURUS'];
    const added = addTag(base, ' obras ');

    expect(added).toEqual(['JAHIT_LURUS', 'obras']);
    expect(base).toEqual(['JAHIT_LURUS']); // input tidak dimutasi
    expect(addTag(added, 'OBRAS')).toEqual(['JAHIT_LURUS', 'obras']); // duplikat dibuang

    expect(removeTag(added, 0)).toEqual(['obras']);
    expect(removeTag(added, 9)).toEqual(['JAHIT_LURUS', 'obras']); // indeks ngawur = no-op
  });

  it('formatCapacity: 0/negatif → "-", bulat tanpa desimal, pecahan pakai koma', () => {
    expect(formatCapacity(0)).toBe('-');
    expect(formatCapacity(-1)).toBe('-');
    expect(formatCapacity(40)).toBe('40/jam');
    expect(formatCapacity(40.5)).toBe('40,5/jam');
    expect(formatCapacity(12.75)).toBe('12,75/jam');
  });

  it('activeBundlesLabel & productionLinesLabel', () => {
    expect(activeBundlesLabel(DETAIL)).toBe('2 bundle aktif');
    expect(activeBundlesLabel({ ...DETAIL, active_bundles_count: 0 })).toBe('0 bundle aktif');

    expect(productionLinesLabel(DETAIL)).toBe('LINE-A');
    expect(productionLinesLabel({ ...DETAIL, production_lines: [] })).toBe('-');
    expect(
      productionLinesLabel({
        ...DETAIL,
        production_lines: [
          { id: 1, code: 'LINE-A', name: 'A' },
          { id: 2, code: 'LINE-B', name: 'B' },
        ],
      }),
    ).toBe('LINE-A, LINE-B');
  });

  it('workCenterDetailItems: tipe, kapasitas, tag, status & catatan MES-only', () => {
    const items = workCenterDetailItems(ROW);

    expect(items.find((item) => item.label === 'Tipe Stasiun')?.value).toBe('SEWING');
    expect(items.find((item) => item.label === 'Kapasitas')?.value).toBe('40,5/jam');
    expect(items.find((item) => item.label === 'Tag Kapabilitas')?.value).toBe('JAHIT_LURUS, OBRAS');
    expect(items.find((item) => item.label === 'Status')?.value).toBe('Aktif');
    expect(items.find((item) => item.label === 'Sinkronisasi')?.value).toBe(
      'MES-only (tidak dikirim ke Odoo)',
    );
    expect(
      workCenterDetailItems({ ...ROW, wc_type: '', capability_tags: [], active: false }).find(
        (item) => item.label === 'Status',
      )?.value,
    ).toBe('Nonaktif');
    expect(
      workCenterDetailItems({ ...ROW, active: false, capability_tags: [] }).find(
        (item) => item.label === 'Tag Kapabilitas',
      )?.value,
    ).toBe('-');
  });

  it('displayOrDash', () => {
    expect(displayOrDash('  SEWING-1  ')).toBe('SEWING-1');
    expect(displayOrDash('')).toBe('-');
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash(0)).toBe('0');
  });
});
