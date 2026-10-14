import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { UomDetailPage } from '@/pages/master/UomDetailPage';
import { UomFormPage } from '@/pages/master/UomFormPage';
import { UomsPage } from '@/pages/master/UomsPage';
import {
  EMPTY_UOM_FORM,
  isUomFormValid,
  isUomType,
  uomDetailItems,
  uomFormFromRow,
  uomInputFromForm,
  uomOptionLabel,
  validateUomForm,
  type UomFormValues,
} from '@/lib/master-uom';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterUomRow } from '@/types/master-uom';

/**
 * H1.2 — halaman master UoM (`/master/uoms*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun dengan `createElement`
 *      supaya file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter`
 *      + konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, dan validasi form
 *      (`lib/master-uom.ts`) — termasuk "submit code/kategori kosong".
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/master/UomsPage.tsx';
const FORM_PAGE = 'src/pages/master/UomFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/UomDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(element: ReactElement, initialPath: string): { html: string; text: string } {
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
        createElement(Routes, null, createElement(Route, { path: initialPath, element })),
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

/** Nilai form UoM yang SAH dipakai beberapa test "submit". */
const VALID_FORM: UomFormValues = {
  code: 'PCS',
  name: 'Pieces',
  category: 'Unit',
  uom_type: 'reference',
  factor: '1',
  rounding: '0.01',
  active: true,
};

const ROW: MasterUomRow = {
  id: 5,
  code: 'PCS',
  name: 'Pieces',
  category: 'Unit',
  uom_type: 'reference',
  factor: 1,
  rounding: 0.01,
  active: true,
  odoo_id: null,
};

describe('H1.2 — route & guard (App.tsx)', () => {
  it('4 route master UoM terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/uoms',
      '/master/uoms/new',
      '/master/uoms/:id',
      '/master/uoms/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterUomsPage />');
    expect(APP).toContain('<MasterUomFormPage />');
    expect(APP).toContain('<MasterUomDetailPage />');
    expect(APP).toMatch(/path="\/master\/uoms"[\s\S]{0,200}INVENTORY_ROLES/);
  });

  it('path `/master/uoms*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ prefix: '/master/uoms', appId: 'inventory' }",
    );
  });

  it('menu Inventory punya item Master UoM (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master UoM');

    expect(item?.path).toBe('/master/uoms');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.2 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter status, dan CTA UoM Baru', () => {
    const { html, text } = renderPage(createElement(UomsPage), '/master/uoms');

    expect(text).toContain('Master UoM');
    expect(text).toContain('UoM Baru');
    for (const label of [
      'Kode',
      'Nama',
      'Kategori',
      'Tipe',
      'Rasio',
      'Presisi',
      'Status',
      'Odoo ID',
    ]) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Nonaktif');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): 7 field + checkbox aktif + tombol submit', () => {
    const { html, text } = renderPage(createElement(UomFormPage), '/master/uoms/new');

    expect(text).toContain('UoM Baru');
    for (const label of [
      'Kode *',
      'Nama *',
      'Kategori *',
      'Tipe',
      'Rasio (factor) *',
      'Presisi pembulatan *',
    ]) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('UoM aktif');
    expect(text).toContain('Simpan UoM');
    // dropdown tipe = 3 opsi Odoo (bigger|reference|smaller)
    expect(text).toContain('Referensi (unit dasar kategori)');
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html } = renderPage(createElement(UomDetailPage), '/master/uoms/5');

    expect(html).toContain('Detail UoM');
    expect(html).toContain('Edit');
    expect(html).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

describe('H1.2 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server, tabel dense, klik baris → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterUoms'");
    expect(page).toContain('fetchUoms(client, {');
    expect(page).toContain('UOMS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-uoms'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/uoms/${String(row.id)}`)");
  });

  it('form: create & update lewat adapter + validasi pure + submit handler', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createUom(client, input)');
    expect(page).toContain('updateUom(client, uomId, input)');
    expect(page).toContain('validateUomForm(values)');
    expect(page).toContain('uomInputFromForm(values)');
    expect(page).toContain("from '@/components/atoms/Select'");
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + Sync placeholder disabled ber-tooltip H2', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchUom(client, uomId ?? 0)');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/uoms/${String(uomId)}/edit');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteUom');
  });
});

describe('H1.2 — submit form: valid & field wajib', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateUomForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isUomFormValid(errors)).toBe(true);
    expect(uomInputFromForm(VALID_FORM)).toEqual({
      code: 'PCS',
      name: 'Pieces',
      category: 'Unit',
      uom_type: 'reference',
      factor: 1,
      rounding: 0.01,
      active: true,
    });
  });

  it('form code KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validateUomForm({ ...VALID_FORM, code: '  ' });

    expect(errors.code).toBe('Kode UoM wajib diisi.');
    expect(isUomFormValid(errors)).toBe(false);
  });

  it('form awal (EMPTY_UOM_FORM) tidak valid: code/name/category kosong', () => {
    expect(Object.keys(validateUomForm(EMPTY_UOM_FORM)).sort()).toEqual([
      'category',
      'code',
      'name',
    ]);
  });

  it('kategori kosong & angka tidak > 0 → error (Odoo menolak 0)', () => {
    const errors = validateUomForm({
      ...VALID_FORM,
      category: ' ',
      factor: '0',
      rounding: 'abc',
    });

    expect(errors.category).toContain('Kategori wajib diisi');
    expect(errors.factor).toContain('lebih besar dari 0');
    expect(errors.rounding).toContain('Isi angka');
    expect(isUomFormValid(errors)).toBe(false);
  });

  it('edit: uomFormFromRow ↔ uomInputFromForm konsisten', () => {
    expect(uomFormFromRow(ROW)).toEqual(VALID_FORM);
    expect(uomInputFromForm(uomFormFromRow(ROW))).toEqual(uomInputFromForm(VALID_FORM));
    // Odoo ID tetap dibawa (read-only) — tidak dikirim ulang di body.
    expect('odoo_id' in uomInputFromForm(VALID_FORM)).toBe(false);
  });
});

describe('H1.2 — helper tampilan (lib)', () => {
  it('isUomType hanya menerima 3 nilai Odoo', () => {
    expect(isUomType('reference')).toBe(true);
    expect(isUomType('bigger')).toBe(true);
    expect(isUomType('smaller')).toBe(true);
    expect(isUomType('BESAR')).toBe(false);
  });

  it('uomOptionLabel: KODE - nama (fallback kalau salah satu kosong)', () => {
    expect(uomOptionLabel(ROW)).toBe('PCS - Pieces');
    expect(uomOptionLabel({ ...ROW, code: '' })).toBe('Pieces');
    expect(uomOptionLabel({ ...ROW, name: ' ' })).toBe('PCS');
  });

  it('uomDetailItems: 7 baris + odoo_id null → "belum dikirim"', () => {
    const items = uomDetailItems(ROW);

    expect(items).toHaveLength(7);
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Tipe')?.value).toBe(
      'Referensi (unit dasar kategori)',
    );
    expect(uomDetailItems({ ...ROW, odoo_id: 10 })[6]?.value).toBe('10');
  });
});


