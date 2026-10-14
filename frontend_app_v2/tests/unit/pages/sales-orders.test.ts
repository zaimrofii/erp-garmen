import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { OrderDetailPage } from '@/pages/sales/OrderDetailPage';
import { OrderFormPage } from '@/pages/sales/OrderFormPage';
import { OrdersPage } from '@/pages/sales/OrdersPage';
import {
  addOrderLine,
  allowedOrderActions,
  displayDate,
  displayOrDash,
  EMPTY_ORDER_FORM,
  emptyOrderLine,
  isOrderEditable,
  isOrderFormValid,
  lineSubtotal,
  orderDetailItems,
  orderFormFromDetail,
  orderFormTotal,
  orderInputFromForm,
  orderLinesTotal,
  orderStateLabel,
  removeOrderLine,
  stateParamForFilter,
  toNullableId,
  toNullableNumber,
  updateOrderLine,
  validateOrderForm,
  type OrderFormValues,
} from '@/lib/sales-order';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { SalesOrderDetail, SalesOrderRow } from '@/types/sales-order';

/**
 * H2.1 — halaman Sales Order (`/sales/orders*`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon `createElement`, file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + konteks runtime palsu;
 *   2. SUMBER/pure: route + guard `SALES_ROLES` di `App.tsx`, item nav app Sales,
 *      validasi form + operasi baris + subtotal/total (`lib/sales-order.ts`).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

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

const ROW: SalesOrderRow = {
  id: 7,
  code: 'SO-2026-0001',
  client_order_ref: 'SO-2026-0001',
  customer_id: 51,
  customer_name: 'PT Buyer Export',
  order_type: 'EXPORT',
  state: 'DRAFT',
  priority: 0,
  deadline: '2026-11-30T00:00:00+00:00',
  lines_count: 1,
  amount_total: '900000.00',
  odoo_id: null,
  created_at: null,
  updated_at: null,
};

const DETAIL: SalesOrderDetail = {
  ...ROW,
  lines: [
    {
      id: 41,
      product_id: 9,
      product_code: 'KAOS-L',
      product_name: 'Kaos L',
      qty: 12,
      tag: 'EXPORT',
      ticket_code: null,
      price_unit: '75000.00',
      subtotal: '900000.00',
      tax_ids: [19],
      odoo_id: null,
      created_at: null,
      updated_at: null,
    },
  ],
  work_orders_count: 0,
  odoo_sync_status: 'PENDING',
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const VALID_FORM: OrderFormValues = {
  customer_id: '51',
  order_type: 'EXPORT',
  priority: '0',
  deadline: '2026-11-30',
  lines: [
    { id: null, product_id: '9', qty: '12', price_unit: '75000.00', tag: 'EXPORT', tax_ids: [] },
  ],
};

describe('H2.1 — route, guard & nav (sumber)', () => {
  it('4 route `/sales/orders*` terdaftar dengan guard SALES_ROLES (admin/owner)', () => {
    for (const routePath of [
      '/sales/orders',
      '/sales/orders/new',
      '/sales/orders/:id',
      '/sales/orders/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<SalesOrdersPage />');
    expect(APP).toContain('<SalesOrderFormPage />');
    expect(APP).toContain('<SalesOrderDetailPage />');
    expect(APP).toMatch(/path="\/sales\/orders"[\s\S]{0,260}SALES_ROLES/);
    expect(APP).toMatch(/const SALES_ROLES: Role\[\] = \['admin', 'owner'\];/);
  });

  it('nav punya app `sales` dengan item Orders (link biasa)', () => {
    const sales = NAV_APPS.find((app) => app.id === 'sales');
    const item = sales?.topbar.find((menu) => menu.label === 'Orders');

    expect(sales?.path).toBe('/sales');
    expect(item?.path).toBe('/sales/orders');
    expect(item?.children).toBeUndefined();
    expect(NAV).toContain("id: 'sales'");
  });
});

describe('H2.1 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter state, CTA Order Baru', () => {
    const { html, text } = renderPage(createElement(OrdersPage), '/sales/orders');

    expect(text).toContain('Sales Order');
    expect(text).toContain('Order Baru');
    for (const label of ['Kode', 'Customer', 'Deadline', 'Baris', 'Total', 'State', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Terkonfirmasi');
    expect(text).toContain('Dibatalkan');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): header + editor baris + tombol Tambah Baris', () => {
    const { html, text } = renderPage(createElement(OrderFormPage), '/sales/orders/new');

    expect(text).toContain('Order Baru');
    for (const label of ['Customer *', 'Tipe Order', 'Prioritas', 'Deadline']) {
      expect(text, label).toContain(label);
    }
    expect(text).toMatch(/Baris Order \(/);
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('— Pilih customer —');
    expect(text).toContain('— Pilih produk —');
    expect(text).toContain('Simpan Order');
    expect(text).toContain('Subtotal');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + tombol Simpan Perubahan', () => {
    const { text } = renderPage(
      createElement(OrderFormPage),
      '/sales/orders/7/edit',
      '/sales/orders/:id/edit',
    );

    expect(text).toContain('Edit Order');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: judul, tombol Edit/Hapus, label aksi transisi (sumber)', () => {
    const { text } = renderPage(
      createElement(OrderDetailPage),
      '/sales/orders/7',
      '/sales/orders/:id',
    );

    expect(text).toContain('Detail Order');
    expect(text).toContain('Kembali');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
    expect(text).toContain('Memuat order…');

    // Label tombol transisi (dipakai setelah data order termuat dari API).
    const page = read('src/pages/sales/OrderDetailPage.tsx');
    for (const label of ['Konfirmasi & Push Odoo', 'Tandai Selesai', 'Batalkan Order']) {
      expect(page, label).toContain(label);
    }
    expect(page).toContain('runOrderAction');
  });
});


describe('H2.1 — pure: form, validasi, baris, total', () => {
  it('validateOrderForm: customer/qty/harga wajib, deadline ISO', () => {
    const errors = validateOrderForm({
      ...VALID_FORM,
      customer_id: '',
      deadline: 'besok',
      lines: [{ id: null, product_id: '', qty: '0', price_unit: '', tag: '', tax_ids: [] }],
    });

    expect(errors.customer_id).toBeDefined();
    expect(errors.deadline).toBeDefined();
    expect(errors.lines?.[0]?.product_id).toBeDefined();
    expect(errors.lines?.[0]?.qty).toBeDefined();
    expect(errors.lines?.[0]?.price_unit).toBeDefined();
    expect(isOrderFormValid(errors)).toBe(false);
    expect(isOrderFormValid(validateOrderForm(VALID_FORM))).toBe(true);
  });

  it('validateOrderForm: tanpa baris → error baris pertama', () => {
    const errors = validateOrderForm({ ...VALID_FORM, lines: [] });

    expect(errors.lines?.[0]?.product_id).toBeDefined();
  });

  it('operasi baris + subtotal/total (form & backend)', () => {
    const added = addOrderLine(VALID_FORM);
    expect(added.lines).toHaveLength(2);

    const changed = updateOrderLine(added, 1, { product_id: '11', qty: '3', price_unit: '1000' });
    expect(changed.lines[1]?.qty).toBe('3');
    expect(updateOrderLine(changed, 9, { qty: '1' })).toBe(changed);

    const removed = removeOrderLine(changed, 1);
    expect(removed.lines).toHaveLength(1);
    expect(removeOrderLine(removed, 9).lines).toHaveLength(1);

    expect(lineSubtotal('12', '75000.00')).toBe(900000);
    expect(orderFormTotal(VALID_FORM)).toBe(900000);
    expect(orderLinesTotal([{ subtotal: '900000.00' }, { subtotal: '1000.50' }])).toBe(901000.5);
    expect(emptyOrderLine().qty).toBe('1');
    expect(EMPTY_ORDER_FORM.lines).toHaveLength(1);
  });

  it('orderInputFromForm: baris tanpa produk dibuang, harga 2 desimal', () => {
    const input = orderInputFromForm({
      ...VALID_FORM,
      lines: [
        ...VALID_FORM.lines,
        { id: null, product_id: '', qty: '5', price_unit: '1', tag: '', tax_ids: [] },
      ],
    });

    expect(input.customer_id).toBe(51);
    expect(input.order_type).toBe('EXPORT');
    expect(input.deadline).toBe('2026-11-30');
    expect(input.lines).toHaveLength(1);
    expect(input.lines[0]).toEqual({
      product_id: 9,
      qty: 12,
      price_unit: '75000.00',
      tag: 'EXPORT',
      tax_ids: [],
    });

    expect(orderInputFromForm({ ...VALID_FORM, deadline: '' }).deadline).toBeNull();
    expect(orderInputFromForm({ ...VALID_FORM, customer_id: '' }).customer_id).toBeNull();
  });

  it('orderFormFromDetail: roundtrip detail → form (deadline dipotong tanggalnya)', () => {
    const form = orderFormFromDetail(DETAIL);

    expect(form.customer_id).toBe('51');
    expect(form.deadline).toBe('2026-11-30');
    expect(form.lines[0]?.qty).toBe('12');
    expect(form.lines[0]?.price_unit).toBe('75000.00');

    const kosong = orderFormFromDetail({ ...DETAIL, lines: [] });
    expect(kosong.lines).toHaveLength(1);
    expect(kosong.lines[0]?.product_id).toBe('');
  });

  it('state helpers: label, transisi §14, DRAFT-only, filter & item detail', () => {
    expect(orderStateLabel('DRAFT')).toBe('Draft');
    expect(orderStateLabel('CONFIRMED')).toBe('Terkonfirmasi');
    expect(orderStateLabel('NGACO')).toBe('NGACO');
    expect(allowedOrderActions('DRAFT')).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(allowedOrderActions('CONFIRMED')).toEqual(['DONE', 'CANCELLED']);
    expect(allowedOrderActions('DONE')).toEqual([]);
    expect(isOrderEditable('DRAFT')).toBe(true);
    expect(isOrderEditable('CONFIRMED')).toBe(false);
    expect(stateParamForFilter('all')).toBeNull();
    expect(stateParamForFilter('DONE')).toBe('DONE');
    expect(toNullableId('5')).toBe(5);
    expect(toNullableId('')).toBeNull();
    expect(toNullableNumber('1.5')).toBe(1.5);
    expect(displayOrDash(null)).toBe('-');
    expect(displayDate(null)).toBe('-');
    expect(displayDate('2026-11-30T00:00:00+00:00')).toBe('2026-11-30');

    const items = orderDetailItems(ROW);
    expect(items.map((item) => item.label)).toContain('Ref Pelanggan');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Total')?.value).toBe('900000.00');
  });
});


