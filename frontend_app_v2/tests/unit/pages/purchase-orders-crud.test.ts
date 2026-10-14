import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { PurchaseOrderDetailPage } from '@/pages/purchase/PurchaseOrderDetailPage';
import { PurchaseOrderFormPage } from '@/pages/purchase/PurchaseOrderFormPage';
import {
  addPoLine,
  allowedPoActions,
  displayDate,
  displayOrDash,
  EMPTY_PO_FORM,
  emptyPoLine,
  isPoEditable,
  isPoFormValid,
  poDetailItems,
  poFormFromDetail,
  poFormTotal,
  poInputFromForm,
  poLineSubtotal,
  poLinesTotal,
  poStateLabel,
  poStateParamForFilter,
  removePoLine,
  toNullableId,
  toNullableNumber,
  updatePoLine,
  validatePoForm,
  type PoFormValues,
} from '@/lib/purchase-order';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { PurchaseOrderMesDetail, PurchaseOrderMesRow } from '@/types/purchase-order';

/**
 * H2.2 — halaman Purchase Order MES (`/purchase/orders/new|:id|:id/edit`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon `createElement`, file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + konteks runtime palsu;
 *   2. SUMBER/pure: route + guard `PURCHASING_ROLES` di `App.tsx`, validasi form +
 *      operasi baris + subtotal/total (`lib/purchase-order.ts`), dan tombol
 *      "Buat PO Baru" di halaman B10 (`PurchaseOrdersPage`).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const B10_PAGE = read('src/pages/purchase/PurchaseOrdersPage.tsx');

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

const ROW: PurchaseOrderMesRow = {
  id: 7,
  code: 'PO-2026-0001',
  partner_ref: 'PO-2026-0001',
  vendor_id: 45,
  vendor_name: 'PT Supplier A',
  vendor_code: 'VEND-A',
  state: 'DRAFT',
  expected_date: '2026-11-30',
  notes: 'PO uji',
  lines_count: 1,
  amount_total: '315000.00',
  odoo_id: null,
  created_at: null,
  updated_at: null,
};

const DETAIL: PurchaseOrderMesDetail = {
  ...ROW,
  lines: [
    {
      id: 41,
      product_id: 9,
      product_code: 'KAIN-COTTON',
      product_name: 'Kain Cotton 30s',
      qty: '10.50',
      price_unit: '30000.00',
      subtotal: '315000.00',
      tax_ids: [20],
      date_planned: '2026-11-25',
      odoo_id: null,
      created_at: null,
      updated_at: null,
    },
  ],
  odoo_sync_status: 'PENDING',
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const VALID_FORM: PoFormValues = {
  vendor_id: '45',
  expected_date: '2026-11-30',
  notes: 'PO uji',
  lines: [
    {
      id: null,
      product_id: '9',
      qty: '10.50',
      price_unit: '30000.00',
      date_planned: '2026-11-25',
      tax_ids: [],
    },
  ],
};

describe('H2.2 — route, guard & tombol B10 (sumber)', () => {
  it('3 route `/purchase/orders/*` terdaftar dengan guard PURCHASING_ROLES', () => {
    for (const routePath of [
      '/purchase/orders/new',
      '/purchase/orders/:id',
      '/purchase/orders/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<PurchaseOrderFormPage />');
    expect(APP).toContain('<PurchaseOrderDetailPage />');
    expect(APP).toMatch(/path="\/purchase\/orders\/new"[\s\S]{0,200}PURCHASING_ROLES/);
  });

  it('halaman B10 tetap hidup + tombol "Buat PO Baru" (aditif)', () => {
    expect(APP).toContain('path="/purchase/orders"');
    expect(B10_PAGE).toContain('Buat PO Baru');
    expect(B10_PAGE).toContain("navigate('/purchase/orders/new')");
    // Daftar B10 tetap memakai adapter monitoring (bukan adapter MES baru).
    expect(B10_PAGE).toContain("from '@/api/purchase'");
  });
});

describe('H2.2 — render halaman (react-dom/server)', () => {
  it('halaman form (baru): header vendor/tanggal + editor baris', () => {
    const { html, text } = renderPage(createElement(PurchaseOrderFormPage), '/purchase/orders/new');

    expect(text).toContain('PO Baru');
    for (const label of ['Vendor *', 'Tanggal Diharapkan', 'Catatan']) {
      expect(text, label).toContain(label);
    }
    expect(text).toMatch(/Baris PO \(/);
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('— Pilih vendor —');
    expect(text).toContain('— Pilih produk —');
    expect(text).toContain('Simpan PO');
    expect(text).toContain('Subtotal');
    expect(text).toContain('Rencana');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + tombol Simpan Perubahan', () => {
    const { text } = renderPage(
      createElement(PurchaseOrderFormPage),
      '/purchase/orders/7/edit',
      '/purchase/orders/:id/edit',
    );

    expect(text).toContain('Edit PO');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: judul, tombol Edit/Hapus + Cek state Odoo, label aksi (sumber)', () => {
    const { text } = renderPage(
      createElement(PurchaseOrderDetailPage),
      '/purchase/orders/7',
      '/purchase/orders/:id',
    );

    expect(text).toContain('Detail PO');
    expect(text).toContain('Kembali');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
    expect(text).toContain('Memuat PO…');

    // Tombol/label yang hanya muncul setelah data PO termuat dari API → dikunci
    // lewat pembacaan sumber (pola H2.1).
    const page = read('src/pages/purchase/PurchaseOrderDetailPage.tsx');
    for (const label of ['Konfirmasi & Push Odoo', 'Tandai Selesai', 'Batalkan PO']) {
      expect(page, label).toContain(label);
    }
    expect(page).toContain('Cek state Odoo');
    expect(page).toContain('fetchPurchaseOrderOdooState');
  });
});

describe('H2.2 — pure: form, validasi, baris, total', () => {
  it('validatePoForm: vendor/qty/harga wajib, tanggal ISO', () => {
    const errors = validatePoForm({
      ...VALID_FORM,
      vendor_id: '',
      expected_date: 'besok',
      lines: [
        {
          id: null,
          product_id: '',
          qty: '0',
          price_unit: '',
          date_planned: 'kemarin',
          tax_ids: [],
        },
      ],
    });

    expect(errors.vendor_id).toBeDefined();
    expect(errors.expected_date).toBeDefined();
    expect(errors.lines?.[0]?.product_id).toBeDefined();
    expect(errors.lines?.[0]?.qty).toBeDefined();
    expect(errors.lines?.[0]?.price_unit).toBeDefined();
    expect(errors.lines?.[0]?.date_planned).toBeDefined();
    expect(isPoFormValid(errors)).toBe(false);
    expect(isPoFormValid(validatePoForm(VALID_FORM))).toBe(true);
  });

  it('validatePoForm: tanpa baris → error baris pertama', () => {
    const errors = validatePoForm({ ...VALID_FORM, lines: [] });

    expect(errors.lines?.[0]?.product_id).toBeDefined();
  });

  it('operasi baris + subtotal/total (form & backend)', () => {
    const added = addPoLine(VALID_FORM);
    expect(added.lines).toHaveLength(2);

    const changed = updatePoLine(added, 1, { product_id: '11', qty: '3.00', price_unit: '1000' });
    expect(changed.lines[1]?.qty).toBe('3.00');
    expect(updatePoLine(changed, 9, { qty: '1' })).toBe(changed);

    const removed = removePoLine(changed, 1);
    expect(removed.lines).toHaveLength(1);
    expect(removePoLine(removed, 9).lines).toHaveLength(1);

    expect(poLineSubtotal('10.50', '30000.00')).toBe(315000);
    expect(poFormTotal(VALID_FORM)).toBe(315000);
    expect(poLinesTotal([{ subtotal: '315000.00' }, { subtotal: '1000.50' }])).toBe(316000.5);
    expect(emptyPoLine().qty).toBe('1');
    expect(EMPTY_PO_FORM.lines).toHaveLength(1);
  });

  it('poInputFromForm: baris tanpa produk dibuang, angka 2 desimal', () => {
    const input = poInputFromForm({
      ...VALID_FORM,
      lines: [
        ...VALID_FORM.lines,
        { id: null, product_id: '', qty: '5', price_unit: '1', date_planned: '', tax_ids: [] },
      ],
    });

    expect(input.vendor_id).toBe(45);
    expect(input.expected_date).toBe('2026-11-30');
    expect(input.notes).toBe('PO uji');
    expect(input.lines).toHaveLength(1);
    expect(input.lines[0]).toEqual({
      product_id: 9,
      qty: '10.50',
      price_unit: '30000.00',
      tax_ids: [],
      date_planned: '2026-11-25',
    });

    expect(poInputFromForm({ ...VALID_FORM, expected_date: '' }).expected_date).toBeNull();
    expect(poInputFromForm({ ...VALID_FORM, vendor_id: '' }).vendor_id).toBeNull();
  });

  it('poFormFromDetail: roundtrip detail → form (tanggal dipotong 10 char)', () => {
    const form = poFormFromDetail(DETAIL);

    expect(form.vendor_id).toBe('45');
    expect(form.expected_date).toBe('2026-11-30');
    expect(form.lines[0]?.qty).toBe('10.50');
    expect(form.lines[0]?.date_planned).toBe('2026-11-25');

    const kosong = poFormFromDetail({ ...DETAIL, lines: [] });
    expect(kosong.lines).toHaveLength(1);
    expect(kosong.lines[0]?.product_id).toBe('');
  });

  it('state helpers: label, transisi §14, DRAFT-only, filter & item detail', () => {
    expect(poStateLabel('DRAFT')).toBe('Draft');
    expect(poStateLabel('CONFIRMED')).toBe('Terkonfirmasi');
    expect(poStateLabel('NGACO')).toBe('NGACO');
    expect(allowedPoActions('DRAFT')).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(allowedPoActions('CONFIRMED')).toEqual(['DONE', 'CANCELLED']);
    expect(allowedPoActions('DONE')).toEqual([]);
    expect(isPoEditable('DRAFT')).toBe(true);
    expect(isPoEditable('CONFIRMED')).toBe(false);
    expect(poStateParamForFilter('all')).toBeNull();
    expect(poStateParamForFilter('DONE')).toBe('DONE');
    expect(toNullableId('45')).toBe(45);
    expect(toNullableId('')).toBeNull();
    expect(toNullableNumber('10.5')).toBe(10.5);
    expect(displayOrDash(null)).toBe('-');
    expect(displayDate(null)).toBe('-');
    expect(displayDate('2026-11-25')).toBe('2026-11-25');

    const items = poDetailItems(ROW);
    expect(items.map((item) => item.label)).toContain('Ref Vendor');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Total')?.value).toBe('315000.00');
  });
});


