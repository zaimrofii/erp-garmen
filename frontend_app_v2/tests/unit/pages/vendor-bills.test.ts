import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { VendorBillDetailPage } from '@/pages/finance/VendorBillDetailPage';
import { VendorBillFormPage } from '@/pages/finance/VendorBillFormPage';
import { VendorBillsPage } from '@/pages/finance/VendorBillsPage';
import {
  addBillLine,
  billDetailItems,
  billFormFromPurchaseOrderDetail,
  billFormTotal,
  billInputFromForm,
  billStateLabel,
  billStateTone,
  EMPTY_BILL_FORM,
  isBillFormValid,
  lineSubtotal,
  removeBillLine,
  updateBillLine,
  validateBillForm,
  type BillFormValues,
} from '@/lib/vendor-bill';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { VendorBillDetail } from '@/types/vendor-bill';

/**
 * H3.2 — halaman Vendor Bill (`/finance/vendor-bills*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun `createElement`), dibungkus
 *      `QueryClientProvider` + `MemoryRouter` + konteks feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, wiring API, validasi &
 *      helper form (`lib/vendor-bill.ts`), plus bonus tombol "Buat Bill" di detail PO H2.2.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/finance/VendorBillsPage.tsx';
const FORM_PAGE = 'src/pages/finance/VendorBillFormPage.tsx';
const DETAIL_PAGE = 'src/pages/finance/VendorBillDetailPage.tsx';
const PO_DETAIL = 'src/pages/purchase/PurchaseOrderDetailPage.tsx';

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

/** Nilai form bill yang SAH dipakai beberapa test "submit". */
const VALID_FORM: BillFormValues = {
  purchase_order_id: '5',
  vendor_id: '14',
  ref: 'INV-VENDOR-001',
  invoice_date: '2026-10-13',
  due_date: '',
  notes: '',
  lines: [
    { id: null, po_line_id: 9, product_id: '34', qty: '10', price_unit: '1500.00', tax_ids: [20] },
  ],
};

const DETAIL: VendorBillDetail = {
  id: 22,
  code: 'VB-2026-0001',
  purchase_order_id: 5,
  purchase_order_no: 'PO-2026-9001',
  vendor_id: 14,
  vendor_name: 'PT Vendor Bill',
  vendor_code: 'SUP-VB',
  ref: 'INV-VENDOR-001',
  invoice_date: '2026-10-13',
  due_date: null,
  state: 'DRAFT',
  notes: '',
  lines_count: 1,
  amount_total: '15000.00',
  odoo_id: null,
  created_at: null,
  updated_at: null,
  lines: [
    {
      id: 31,
      po_line_id: 9,
      product_id: 34,
      product_code: 'BENANG-VB',
      product_name: 'Benang Vendor',
      qty: '10.00',
      price_unit: '1500.00',
      subtotal: '15000.00',
      tax_ids: [20],
      tax_odoo_ids: [20],
      line_total: '15000.00',
      created_at: null,
      updated_at: null,
    },
  ],
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

describe('H3.2 — route & guard (App.tsx)', () => {
  it('route CRUD terdaftar dengan guard FINANCE_ROLES tanpa mengubah H3.1/F15', () => {
    for (const routePath of [
      '/finance/vendor-bills',
      '/finance/vendor-bills/new',
      '/finance/vendor-bills/:id',
      '/finance/vendor-bills/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<VendorBillsPage />');
    expect(APP).toContain('<VendorBillFormPage />');
    expect(APP).toContain('<VendorBillDetailPage />');
    expect(APP).toMatch(/path="\/finance\/vendor-bills"[\s\S]{0,200}FINANCE_ROLES/);

    // H3.1 (customer invoice) + F15 (antrean invoice) tetap ada & tidak diubah.
    expect(APP).toContain('<CustomerInvoicesPage />');
    expect(APP).toContain('<InvoiceQueuePage />');
  });

  it('menu Finance punya item Vendor Bills di samping Invoices & Customer Invoices', () => {
    const finance = NAV_APPS.find((app) => app.id === 'finance');
    const labels = (finance?.topbar ?? []).map((menu) => menu.label);

    expect(labels).toContain('Invoices');
    expect(labels).toContain('Customer Invoices');
    expect(labels).toContain('Vendor Bills');
    expect(finance?.topbar.find((menu) => menu.label === 'Vendor Bills')?.path).toBe(
      '/finance/vendor-bills',
    );
  });

  it('detail PO (H2.2) punya tombol "Buat Bill" → form dengan `?po=`', () => {
    const page = read(PO_DETAIL);

    expect(page).toContain('Buat Bill');
    expect(page).toContain('navigate(`/finance/vendor-bills/new?po=${String(poId)}`)');
  });
});

describe('H3.2 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter state, dan CTA Bill Baru', () => {
    const { html, text } = renderPage(createElement(VendorBillsPage), '/finance/vendor-bills');

    expect(text).toContain('Vendor Bill');
    expect(text).toContain('Bill Baru');
    for (const label of ['Kode', 'PO', 'Vendor', 'Ref vendor', 'Tanggal', 'Total', 'State']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Odoo ID');
    expect(text).toContain('Semua');
    expect(text).toContain('Draft');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): field header + kolom baris + tombol submit', () => {
    const { html, text } = renderPage(createElement(VendorBillFormPage), '/finance/vendor-bills/new');

    expect(text).toContain('Vendor Bill Baru');
    for (const label of [
      'Purchase Order',
      'Vendor *',
      'No. bill vendor (ref)',
      'Tanggal bill *',
      'Jatuh tempo',
      'Catatan',
    ]) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Baris Bill');
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('Simpan Bill');
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: judul, tombol Kembali/Edit/Hapus (disabled saat memuat)', () => {
    const { html, text } = renderPage(
      createElement(VendorBillDetailPage),
      '/finance/vendor-bills/22',
    );

    expect(text).toContain('Detail Vendor Bill');
    expect(text).toContain('Kembali');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
    expect(html).toContain('disabled');
  });
});

describe('H3.2 — wiring API di halaman (sumber)', () => {
  it('list memakai adapter vendorBills + DenseTable (bukan <table> mentah)', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain('fetchVendorBills');
    expect(page).toContain('DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain('navigate(`/finance/vendor-bills/${String(row.id)}`)');
  });

  it('form memakai create/update + auto-fill PO (`?po=`) & fetch PurchaseOrderMes', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createVendorBill');
    expect(page).toContain('updateVendorBill');
    expect(page).toContain('fetchPurchaseOrderMes');
    expect(page).toContain('billFormFromPurchaseOrderDetail');
    expect(page).toContain("params.get('po')");
  });

  it('detail memakai aksi (`confirm`/`done`/`cancel`) + hapus + allowed_actions', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('actVendorBill');
    expect(page).toContain('deleteVendorBill');
    expect(page).toContain('allowed_actions');
    expect(page).toContain('BILL_STATE_TO_ACTION');
  });
});

describe('H3.2 — validasi & helper PURE (lib/vendor-bill)', () => {
  it('form valid → body API (trim + `po`/`due_date` kosong → null)', () => {
    const input = billInputFromForm(VALID_FORM);

    expect(input).toEqual({
      vendor_id: 14,
      purchase_order_id: 5,
      ref: 'INV-VENDOR-001',
      invoice_date: '2026-10-13',
      due_date: null,
      notes: '',
      lines: [
        { product_id: 34, qty: 10, price_unit: 1500, tax_ids: [20], po_line_id: 9 },
      ],
    });

    const tanpaPo = billInputFromForm({
      ...VALID_FORM,
      purchase_order_id: '',
      lines: [{ ...VALID_FORM.lines[0], po_line_id: null }],
    });
    expect(tanpaPo.purchase_order_id).toBeNull();
    expect(tanpaPo.lines?.[0].po_line_id).toBeNull();
  });

  it('EMPTY_BILL_FORM invalid; vendor & tanggal wajib; ref > 64 char ditolak', () => {
    expect(isBillFormValid(validateBillForm(EMPTY_BILL_FORM))).toBe(false);
    expect(validateBillForm(EMPTY_BILL_FORM).vendor_id).toContain('Vendor');
    expect(validateBillForm(EMPTY_BILL_FORM).invoice_date).toContain('Tanggal');

    expect(validateBillForm(VALID_FORM).ref).toBeUndefined();
    expect(validateBillForm({ ...VALID_FORM, ref: 'X'.repeat(65) }).ref).toContain('64');
    expect(isBillFormValid(validateBillForm(VALID_FORM))).toBe(true);
  });

  it('baris: qty 0 / harga negatif / produk kosong → error per indeks', () => {
    const qtyZero = validateBillForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0], qty: '0' }],
    });
    expect(qtyZero.lines?.[0].qty).toContain('> 0');

    const negative = validateBillForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0], price_unit: '-1' }],
    });
    expect(negative.lines?.[0].price_unit).toContain('negatif');

    const noProduct = validateBillForm({
      ...VALID_FORM,
      lines: [{ ...VALID_FORM.lines[0], product_id: '' }],
    });
    expect(noProduct.lines?.[0].product_id).toContain('Produk');

    // Harga 0 (tagihan menyusul) DIIZINKAN — beda dari customer invoice H3.1.
    expect(
      isBillFormValid(
        validateBillForm({ ...VALID_FORM, lines: [{ ...VALID_FORM.lines[0], price_unit: '0' }] }),
      ),
    ).toBe(true);
  });

  it('add/remove/update baris + subtotal & total', () => {
    const added = addBillLine(VALID_FORM);
    expect(added.lines).toHaveLength(2);
    expect(added.lines[1].product_id).toBe('');

    const updated = updateBillLine(VALID_FORM, 0, { qty: '3' });
    expect(updated.lines[0].qty).toBe('3');
    expect(updateBillLine(VALID_FORM, 9, { qty: '3' }).lines[0].qty).toBe('10');

    const removed = removeBillLine(added, 1);
    expect(removed.lines).toHaveLength(1);
    expect(removeBillLine(VALID_FORM, 9).lines).toHaveLength(1);

    expect(lineSubtotal('10', '1500.00')).toBe('15000.00');
    expect(lineSubtotal('', '')).toBe('0.00');
    expect(billFormTotal(VALID_FORM)).toBe(15000);
  });

  it('billFormFromPurchaseOrderDetail: auto-fill vendor + baris dari PO Line', () => {
    const filled = billFormFromPurchaseOrderDetail({
      vendor_id: 14,
      lines: [
        { id: 9, product_id: 34, qty: '10.00', price_unit: '1500.00', tax_ids: [20] },
        { id: 10, product_id: null, qty: '2.00', price_unit: '0.00', tax_ids: [] },
      ],
    });

    expect(filled.vendor_id).toBe('14');
    expect(filled.lines).toHaveLength(2);
    expect(filled.lines[0]).toEqual({
      id: null,
      po_line_id: 9,
      product_id: '34',
      qty: '10.00',
      price_unit: '1500.00',
      tax_ids: [20],
    });
    expect(filled.lines[1].product_id).toBe('');

    const empty = billFormFromPurchaseOrderDetail({ vendor_id: null, lines: [] });
    expect(empty.vendor_id).toBe('');
    expect(empty.lines).toHaveLength(1);
  });

  it('label/tone & field detail bill', () => {
    expect(billStateLabel('SENT')).toBe('Terkirim ke Odoo');
    expect(billStateTone('CANCELLED')).toBe('coral');
    expect(billStateTone('DRAFT')).toBe('muted');
    expect(billStateTone('CONFIRMED')).toBe('blue');

    const items = billDetailItems(DETAIL);
    expect(items.map((item) => item.label)).toContain('No. bill vendor (ref)');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Purchase Order')?.value).toBe('PO-2026-9001');
  });
});


