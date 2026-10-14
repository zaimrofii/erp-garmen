import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { BomDetailPage } from '@/pages/master/BomDetailPage';
import { BomFormPage } from '@/pages/master/BomFormPage';
import { BomsPage } from '@/pages/master/BomsPage';
import {
  addBomLine,
  bomDetailItems,
  bomFormFromDetail,
  bomInputFromForm,
  bomLineFormFromRow,
  EMPTY_BOM_FORM,
  isBomFormValid,
  productOptionLabel,
  removeBomLine,
  toNullableId,
  toNullableQty,
  updateBomLine,
  validateBomForm,
  type BomFormValues,
} from '@/lib/master-bom';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterBomDetail, MasterBomRow } from '@/types/master-bom';

/**
 * H1.5 — halaman master BOM (`/master/boms*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon dibangun `createElement` agar
 *      file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter` +
 *      konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form + operasi
 *      baris komponen (`lib/master-bom.ts`), dan halaman detail read-only.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const LIST_PAGE = 'src/pages/master/BomsPage.tsx';
const FORM_PAGE = 'src/pages/master/BomFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/BomDetailPage.tsx';

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

const ROW: MasterBomRow = {
  id: 12,
  code: 'BOM-KTS-EXPORT-L',
  name: 'BOM Kaos Export L',
  product_id: 5,
  product_code: 'KTS-EXPORT-L',
  product_name: 'Kaos Export L',
  output_qty: 1,
  uom_id: 3,
  uom_code: 'PCS',
  notes: 'catatan',
  active: true,
  odoo_id: null,
  lines_count: 2,
  created_at: null,
  updated_at: null,
};

const DETAIL: MasterBomDetail = {
  ...ROW,
  lines: [
    {
      id: 41,
      product_id: 9,
      product_code: 'KAIN-COTTON',
      product_name: 'Kain Cotton',
      qty: 1.5,
      uom_id: 3,
      uom_code: 'PCS',
      sequence: 10,
      notes: '',
      active: true,
      odoo_id: null,
    },
  ],
};

describe('H1.5 — route & guard (App.tsx)', () => {
  it('4 route master BOM terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/boms',
      '/master/boms/new',
      '/master/boms/:id',
      '/master/boms/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterBomsPage />');
    expect(APP).toContain('<MasterBomFormPage />');
    expect(APP).toContain('<MasterBomDetailPage />');
    expect(APP).toMatch(/path="\/master\/boms"[\s\S]{0,220}INVENTORY_ROLES/);
  });

  it('path `/master/boms*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(NAV).toContain("{ prefix: '/master/boms', appId: 'inventory' }");
    expect(legacyAppIdForPath('/master/boms')).toBe('inventory');
    expect(legacyAppIdForPath('/master/boms/12/edit')).toBe('inventory');
  });

  it('menu Inventory punya item Master BOM (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master BOM');

    expect(item?.path).toBe('/master/boms');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.5 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom (termasuk Produk & Komponen), filter, CTA BOM Baru', () => {
    const { html, text } = renderPage(createElement(BomsPage), '/master/boms');

    expect(text).toContain('Master BOM');
    expect(text).toContain('BOM Baru');
    for (const label of ['Kode', 'Nama', 'Produk', 'Output', 'Komponen', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Nonaktif');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): header + editor komponen + tombol Tambah Baris', () => {
    const { html, text } = renderPage(createElement(BomFormPage), '/master/boms/new');

    expect(text).toContain('BOM Baru');
    for (const label of ['Produk *', 'Jumlah Output *', 'Satuan Output', 'Kode (opsional)', 'Nama']) {
      expect(text, label).toContain(label);
    }
    expect(text).toMatch(/Komponen \(/);
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('Belum ada komponen');
    expect(text).toContain('— Pilih produk —');
    expect(text).toContain('BOM aktif');
    expect(text).toContain('Simpan BOM');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + breadcrumb Edit', () => {
    const { text } = renderPage(
      createElement(BomFormPage),
      '/master/boms/12/edit',
      '/master/boms/:id/edit',
    );

    expect(text).toContain('Edit BOM');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html, text } = renderPage(createElement(BomDetailPage), '/master/boms/12');

    expect(text).toContain('Detail BOM');
    expect(text).toContain('Edit');
    expect(text).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

const VALID_FORM: BomFormValues = {
  code: 'BOM-KTS-EXPORT-L',
  name: 'BOM Kaos Export L',
  product_id: '5',
  output_qty: '1',
  uom_id: '3',
  notes: 'catatan',
  active: true,
  lines: [
    { id: 41, odoo_id: null, product_id: '9', qty: '1.5', uom_id: '3', sequence: '10', notes: '' },
  ],
};

describe('H1.5 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server (search/active), tabel dense, klik → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterBoms'");
    expect(page).toContain('fetchBoms(client, {');
    expect(page).toContain('BOMS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-boms'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/boms/${String(row.id)}`)");
  });

  it('form: create/update lewat adapter + validasi pure + editor baris inline', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createBom(client, input)');
    expect(page).toContain('updateBom(client, bomId, input)');
    expect(page).toContain('validateBomForm(values)');
    expect(page).toContain('bomInputFromForm(values)');
    expect(page).toContain('addBomLine(values)');
    expect(page).toContain('removeBomLine(values, index)');
    expect(page).toContain('updateBomLine(values, index, patch)');
    expect(page).toContain("from '@/api/masterProducts'");
    expect(page).toContain("from '@/api/masterUoms'");
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + Sync placeholder H2 + tabel komponen', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchBom(client, bomId ?? 0)');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/boms/${String(bomId)}/edit');
    expect(page).toContain('bom?.lines ?? []');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteBom');
  });
});

describe('H1.5 — validasi form (header + baris komponen)', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateBomForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isBomFormValid(errors)).toBe(true);
    expect(bomInputFromForm(VALID_FORM)).toEqual({
      code: 'BOM-KTS-EXPORT-L',
      name: 'BOM Kaos Export L',
      product_id: 5,
      output_qty: 1,
      uom_id: 3,
      notes: 'catatan',
      active: true,
      lines: [
        { id: 41, odoo_id: null, product_id: 9, qty: 1.5, uom_id: 3, sequence: 10, notes: '' },
      ],
    });
  });

  it('kode boleh KOSONG (auto-generate di backend) → tetap valid', () => {
    const errors = validateBomForm({ ...VALID_FORM, code: '  ' });

    expect(errors).toEqual({});
    expect(isBomFormValid(errors)).toBe(true);
  });

  it('produk BOM kosong & output_qty <= 0 → error header', () => {
    expect(validateBomForm({ ...VALID_FORM, product_id: '' }).product_id).toBe(
      'Produk BOM wajib dipilih.',
    );
    expect(validateBomForm({ ...VALID_FORM, output_qty: '0' }).output_qty).toBe(
      'Jumlah output harus lebih besar dari 0.',
    );
    expect(validateBomForm({ ...VALID_FORM, output_qty: 'banyak' }).output_qty).toBe(
      'Jumlah output harus lebih besar dari 0.',
    );
  });

  it('baris komponen: produk wajib & qty > 0 → error per-baris (index)', () => {
    const values: BomFormValues = {
      ...VALID_FORM,
      lines: [
        { ...VALID_FORM.lines[0]!, product_id: '' },
        { ...VALID_FORM.lines[0]!, id: null, product_id: '9', qty: '0' },
      ],
    };

    const errors = validateBomForm(values);

    expect(errors.lines?.[0]?.product_id).toBe('Produk komponen wajib dipilih.');
    expect(errors.lines?.[1]?.qty).toBe('Qty komponen harus lebih besar dari 0.');
    expect(errors.lines?.[0]?.qty).toBeUndefined();
  });

  it('baris memakai produk BOM sendiri → error (self-reference)', () => {
    const errors = validateBomForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0]!, product_id: '5' }],
    });

    expect(errors.lines?.[0]?.product_id).toBe('Komponen tidak boleh produk BOM sendiri.');
  });

  it('form awal (EMPTY_BOM_FORM) tidak valid: produk wajib (output_qty default "1" sah)', () => {
    const errors = validateBomForm(EMPTY_BOM_FORM);

    expect(Object.keys(errors)).toEqual(['product_id']);
    expect(errors.product_id).toBe('Produk BOM wajib dipilih.');
    expect(errors.output_qty).toBeUndefined();
    expect(errors.lines).toBeUndefined();
  });
});

describe('H1.5 — operasi baris & pemetaan (lib)', () => {
  it('addBomLine menambah baris dengan sequence kelipatan 10', () => {
    const one = addBomLine(EMPTY_BOM_FORM);
    expect(one.lines).toHaveLength(1);
    expect(one.lines[0]?.sequence).toBe('10');

    const two = addBomLine(one);
    expect(two.lines[1]?.sequence).toBe('20');
    expect(two.lines[1]?.qty).toBe('1');
    expect(two.lines[1]?.id).toBeNull();
  });

  it('removeBomLine membuang baris ke-index (indeks invalid = tidak berubah)', () => {
    const values = addBomLine(addBomLine(EMPTY_BOM_FORM));

    expect(removeBomLine(values, 0).lines).toHaveLength(1);
    expect(removeBomLine(values, 9)).toBe(values);
    expect(removeBomLine(values, -1)).toBe(values);
  });

  it('updateBomLine hanya mengubah baris ke-index', () => {
    const values = addBomLine(addBomLine(EMPTY_BOM_FORM));

    const updated = updateBomLine(values, 1, { product_id: '9', qty: '2.5' });

    expect(updated.lines[0]?.product_id).toBe('');
    expect(updated.lines[1]?.product_id).toBe('9');
    expect(updated.lines[1]?.qty).toBe('2.5');
  });

  it('bomInputFromForm membuang baris tanpa produk (draft setengah jadi)', () => {
    const values: BomFormValues = {
      ...VALID_FORM,
      lines: [...VALID_FORM.lines, { ...VALID_FORM.lines[0]!, id: null, product_id: '' }],
    };

    expect(bomInputFromForm(values).lines).toHaveLength(1);
  });

  it('detail ↔ form konsisten (id baris dibawa agar PUT mencocokkan, bukan duplikat)', () => {
    const form = bomFormFromDetail(DETAIL);

    expect(form.product_id).toBe('5');
    expect(form.output_qty).toBe('1');
    expect(form.lines).toEqual([
      { id: 41, odoo_id: null, product_id: '9', qty: '1.5', uom_id: '3', sequence: '10', notes: '' },
    ]);
    expect(bomInputFromForm(form)).toEqual(bomInputFromForm(VALID_FORM));
    expect(bomLineFormFromRow(DETAIL.lines[0]!).id).toBe(41);
    expect('odoo_id' in bomInputFromForm(VALID_FORM)).toBe(false);
    expect('lines_count' in bomInputFromForm(VALID_FORM)).toBe(false);
  });

  it('toNullableId / toNullableQty: hanya nilai sah, sisanya null', () => {
    expect(toNullableId('12')).toBe(12);
    expect(toNullableId('  ')).toBeNull();
    expect(toNullableId('0')).toBeNull();
    expect(toNullableId('-3')).toBeNull();
    expect(toNullableId('abc')).toBeNull();

    expect(toNullableQty('1.5')).toBe(1.5);
    expect(toNullableQty('')).toBeNull();
    expect(toNullableQty('banyak')).toBeNull();
  });

  it('productOptionLabel & bomDetailItems (label manusiawi, odoo_id null jelas)', () => {
    expect(productOptionLabel({ code: 'KTS-EXPORT-L', name: 'Kaos Export L' })).toBe(
      'KTS-EXPORT-L - Kaos Export L',
    );
    expect(productOptionLabel({ code: '', name: 'Kaos' })).toBe('Kaos');
    expect(productOptionLabel({ code: 'KTS', name: ' ' })).toBe('KTS');

    const items = bomDetailItems(ROW);
    expect(items.find((item) => item.label === 'Produk')?.value).toBe(
      'KTS-EXPORT-L - Kaos Export L',
    );
    expect(items.find((item) => item.label === 'Output')?.value).toBe('1 PCS');
    expect(items.find((item) => item.label === 'Jumlah Komponen')?.value).toBe('2');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(
      bomDetailItems({ ...ROW, odoo_id: 43 }).find((item) => item.label === 'Odoo ID')?.value,
    ).toBe('43');
  });

  it('bomDetailItems: BOM tanpa produk & catatan kosong ditampilkan "-"', () => {
    const items = bomDetailItems({
      ...ROW,
      product_id: null,
      product_code: null,
      product_name: null,
      notes: '',
    });

    expect(items.find((item) => item.label === 'Produk')?.value).toBe('-');
    expect(items.find((item) => item.label === 'Catatan')?.value).toBe('-');
  });
});


