import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { InvoiceDetailPage } from '@/pages/finance/InvoiceDetailPage';
import { InvoiceFormPage } from '@/pages/finance/InvoiceFormPage';
import { InvoicesPage } from '@/pages/finance/InvoicesPage';
import {
  addInvoiceLine,
  EMPTY_INVOICE_FORM,
  invoiceDetailItems,
  invoiceFormFromOrderDetail,
  invoiceFormTotal,
  invoiceInputFromForm,
  invoiceStateLabel,
  invoiceStateTone,
  isInvoiceFormValid,
  lineSubtotal,
  removeInvoiceLine,
  updateInvoiceLine,
  validateInvoiceForm,
  type InvoiceFormValues,
} from '@/lib/customer-invoice';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { CustomerInvoiceDetail } from '@/types/customer-invoice';

/**
 * H3.1 — halaman Customer Invoice (`/finance/customer-invoices*` + alias `/finance/invoices/*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun `createElement`), dibungkus
 *      `QueryClientProvider` + `MemoryRouter` + konteks feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, wiring API, validasi &
 *      helper form (`lib/customer-invoice.ts`), plus bonus tombol di detail order.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/finance/InvoicesPage.tsx';
const FORM_PAGE = 'src/pages/finance/InvoiceFormPage.tsx';
const DETAIL_PAGE = 'src/pages/finance/InvoiceDetailPage.tsx';
const ORDER_DETAIL = 'src/pages/sales/OrderDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form/detail butuh provider. */
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

/** Nilai form invoice yang SAH dipakai beberapa test "submit". */
const VALID_FORM: InvoiceFormValues = {
  order_id: '3',
  customer_id: '10',
  invoice_date: '2026-10-12',
  due_date: '',
  notes: '',
  lines: [
    { id: null, order_line_id: 5, product_id: '34', qty: '5', price_unit: '4000.00', tax_ids: [19] },
  ],
};

const DETAIL: CustomerInvoiceDetail = {
  id: 7,
  code: 'INV-2026-0001',
  order_id: 3,
  order_no: 'SO-2026-0001',
  customer_id: 10,
  customer_name: 'PT Buyer',
  customer_code: 'CUST-INV',
  invoice_date: '2026-10-12',
  due_date: null,
  state: 'DRAFT',
  notes: '',
  lines_count: 1,
  amount_total: '20000.00',
  odoo_id: null,
  created_at: null,
  updated_at: null,
  lines: [
    {
      id: 11,
      order_line_id: 5,
      product_id: 34,
      product_code: 'KAOS-INV',
      product_name: 'Kaos Invoice',
      qty: '5.00',
      price_unit: '4000.00',
      subtotal: '20000.00',
      tax_ids: [19],
      tax_odoo_ids: [19],
      line_total: '20000.00',
      created_at: null,
      updated_at: null,
    },
  ],
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

describe('H3.1 — route & guard (App.tsx)', () => {
  it('route CRUD + alias finance terdaftar dengan guard FINANCE_ROLES', () => {
    for (const routePath of [
      '/finance/customer-invoices',
      '/finance/customer-invoices/new',
      '/finance/customer-invoices/:id',
      '/finance/invoices/new',
      '/finance/invoices/:id',
      '/finance/invoices/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<CustomerInvoicesPage />');
    expect(APP).toContain('<CustomerInvoiceFormPage />');
    expect(APP).toContain('<CustomerInvoiceDetailPage />');
    expect(APP).toMatch(/path="\/finance\/customer-invoices"[\s\S]{0,200}FINANCE_ROLES/);
    // F15 (InvoiceQueuePage) tetap ada & tidak diubah guard-nya.
    expect(APP).toContain('<InvoiceQueuePage />');
  });

  it('menu Finance punya item Customer Invoices di samping Invoices (F15)', () => {
    const finance = NAV_APPS.find((app) => app.id === 'finance');
    const labels = (finance?.topbar ?? []).map((menu) => menu.label);

    expect(labels).toContain('Invoices');
    expect(labels).toContain('Customer Invoices');
    expect(finance?.topbar.find((menu) => menu.label === 'Customer Invoices')?.path).toBe(
      '/finance/customer-invoices',
    );
  });

  it('detail order (H2.1) punya tombol "Buat Invoice" → form dengan `?order=`', () => {
    const page = read(ORDER_DETAIL);

    expect(page).toContain('Buat Invoice');
    expect(page).toContain('navigate(`/finance/invoices/new?order=${String(orderId)}`)');
  });
});

describe('H3.1 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter state, dan CTA Invoice Baru', () => {
    const { html, text } = renderPage(createElement(InvoicesPage), '/finance/customer-invoices');

    expect(text).toContain('Customer Invoice');
    expect(text).toContain('Invoice Baru');
    for (const label of ['Kode', 'Order', 'Customer', 'Tanggal', 'Total', 'State', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Draft');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): field header + kolom baris + tombol submit', () => {
    const { html, text } = renderPage(createElement(InvoiceFormPage), '/finance/invoices/new');

    expect(text).toContain('Invoice Baru');
    for (const label of ['Order *', 'Customer', 'Tanggal invoice *', 'Jatuh tempo', 'Catatan']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Baris Invoice');
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('Simpan Invoice');
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: tombol Edit/Hapus disabled saat memuat + aksi tersedia', () => {
    const { html, text } = renderPage(createElement(InvoiceDetailPage), '/finance/invoices/7');

    expect(text).toContain('Detail Invoice');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
    expect(html).toContain('disabled');
  });
});


describe('H3.1 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter state server, tabel dense, klik baris → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/customerInvoices'");
    expect(page).toContain('fetchCustomerInvoices(client, {');
    expect(page).toContain('INVOICES_LIMIT_MAX');
    expect(page).toContain("queryKey: ['customer-invoices'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/finance/invoices/${String(row.id)}`)");
  });

  it('form: create/update + auto-fill dari order + validasi pure', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createCustomerInvoice');
    expect(page).toContain('updateCustomerInvoice');
    expect(page).toContain('fetchOrder(client, Number(next))');
    expect(page).toContain('invoiceFormFromOrderDetail(orderDetail)');
    expect(page).toContain('validateInvoiceForm(values)');
    expect(page).toContain('invoiceInputFromForm(values)');
    expect(page).toContain("params.get('order')");
    expect(page).toContain('onSubmit={handleSubmit}');
  });

  it('detail: aksi transisi dari `allowed_actions` + hapus DRAFT-only', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('actCustomerInvoice(client, invoiceId ?? 0, action)');
    expect(page).toContain('deleteCustomerInvoice(client, invoiceId ?? 0)');
    expect(page).toContain('invoice?.allowed_actions');
    expect(page).toContain('invoiceDetailItems(invoice)');
    expect(page).toContain("disabled={invoice === undefined || !isDraft}");
  });
});

describe('H3.1 — validasi & helper form (lib)', () => {
  it('form valid → tanpa error & body siap kirim (angka sudah number)', () => {
    const errors = validateInvoiceForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isInvoiceFormValid(errors)).toBe(true);
    expect(invoiceInputFromForm(VALID_FORM)).toEqual({
      order_id: 3,
      invoice_date: '2026-10-12',
      due_date: null,
      notes: '',
      lines: [{ product_id: 34, qty: 5, price_unit: 4000, tax_ids: [19], order_line_id: 5 }],
    });
  });

  it('form awal (EMPTY_INVOICE_FORM) invalid: order, tanggal, dan baris kosong', () => {
    const errors = validateInvoiceForm(EMPTY_INVOICE_FORM);

    expect(errors.order_id).toContain('Order wajib dipilih');
    expect(errors.invoice_date).toContain('wajib diisi');
    expect(errors.lines?.[0]?.product_id).toContain('Produk wajib dipilih');
    expect(isInvoiceFormValid(errors)).toBe(false);
  });

  it('qty 0 / harga negatif / harga bukan angka → error per baris', () => {
    const qtyZero = validateInvoiceForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0]!, qty: '0' }],
    });
    expect(qtyZero.lines?.[0]?.qty).toContain('> 0');

    const negative = validateInvoiceForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0]!, price_unit: '-1' }],
    });
    expect(negative.lines?.[0]?.price_unit).toContain('negatif');

    const notNumber = validateInvoiceForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0]!, price_unit: 'abc' }],
    });
    expect(notNumber.lines?.[0]?.price_unit).toContain('wajib angka');
  });

  it('operasi baris: tambah/hapus/ubah + subtotal & total', () => {
    const added = addInvoiceLine(VALID_FORM);
    expect(added.lines).toHaveLength(2);

    const updated = updateInvoiceLine(added, 1, { product_id: '35', qty: '2', price_unit: '10' });
    expect(updated.lines[1]?.product_id).toBe('35');
    expect(lineSubtotal('2', '10')).toBe('20.00');
    expect(invoiceFormTotal(updated)).toBeCloseTo(20020, 2);

    const removed = removeInvoiceLine(updated, 1);
    expect(removed.lines).toHaveLength(1);
    expect(updateInvoiceLine(removed, 9, { qty: '1' })).toEqual(removed);
  });

  it('invoiceFormFromOrderDetail: baris order → baris invoice (tax & qty ikut)', () => {
    const form = invoiceFormFromOrderDetail({
      customer_id: 10,
      lines: [
        { id: 5, product_id: 34, qty: 5, price_unit: '4000.00', tax_ids: [19] },
        { id: 6, product_id: null, qty: 1, price_unit: '0.00', tax_ids: [] },
      ],
    });

    expect(form.customer_id).toBe('10');
    expect(form.lines).toHaveLength(2);
    expect(form.lines[0]).toEqual({
      id: null,
      order_line_id: 5,
      product_id: '34',
      qty: '5',
      price_unit: '4000.00',
      tax_ids: [19],
    });
    expect(form.lines[1]?.product_id).toBe('');
  });

  it('label/tone state & item detail invoice', () => {
    expect(invoiceStateLabel('SENT')).toBe('Terkirim ke Odoo');
    expect(invoiceStateTone('DRAFT')).toBe('muted');
    expect(invoiceStateTone('CANCELLED')).toBe('coral');
    expect(invoiceStateTone('CONFIRMED')).toBe('blue');

    const items = invoiceDetailItems(DETAIL);
    expect(items).toHaveLength(9);
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'State')?.value).toBe('Draft');
  });
});

