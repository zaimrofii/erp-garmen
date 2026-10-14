import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { PaymentDetailPage } from '@/pages/finance/PaymentDetailPage';
import { PaymentFormPage } from '@/pages/finance/PaymentFormPage';
import { PaymentsPage } from '@/pages/finance/PaymentsPage';
import {
  activePaymentsTotal,
  billOptionLabel,
  EMPTY_PAYMENT_FORM,
  invoiceOptionLabel,
  isPaymentFormValid,
  paymentDetailItems,
  paymentFormFromDetail,
  paymentInputFromForm,
  paymentStateLabel,
  paymentStateTone,
  paymentTypeLabel,
  remainingForSource,
  suggestedAmount,
  switchPaymentType,
  validatePaymentForm,
  type PaymentFormValues,
} from '@/lib/payment';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { PaymentDetail, PaymentRow } from '@/types/payment';

/**
 * H3.3 — halaman Payment (`/finance/payments*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun `createElement`), dibungkus
 *      `QueryClientProvider` + `MemoryRouter` + konteks feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, wiring API, validasi &
 *      helper form (`lib/payment.ts`), plus bonus tombol "Bayar" di detail invoice
 *      (H3.1) dan detail bill (H3.2).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/finance/PaymentsPage.tsx';
const FORM_PAGE = 'src/pages/finance/PaymentFormPage.tsx';
const DETAIL_PAGE = 'src/pages/finance/PaymentDetailPage.tsx';
const INVOICE_DETAIL = 'src/pages/finance/InvoiceDetailPage.tsx';
const BILL_DETAIL = 'src/pages/finance/VendorBillDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form/detail butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(element: ReactElement, initialPath: string): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  //: React Router mencocokkan `pathname` saja ⇒ `path` route tanpa query string.
  const routePath = initialPath.split('?')[0] ?? initialPath;
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

/** Nilai form payment yang SAH dipakai beberapa test "submit". */
const VALID_FORM: PaymentFormValues = {
  payment_type: 'INBOUND',
  customer_invoice_id: '7',
  vendor_bill_id: '',
  amount: '20000.00',
  currency: 'IDR',
  payment_date: '2026-10-13',
  payment_method: 'bank',
  reference: 'TRF-001',
  memo: '',
};

const ROW: PaymentRow = {
  id: 22,
  code: 'PAY-2026-0001',
  payment_type: 'INBOUND',
  partner_id: 10,
  partner_name: 'PT Buyer Payment',
  partner_code: 'CUST-PAY',
  customer_invoice_id: 7,
  customer_invoice_code: 'INV-2026-0001',
  vendor_bill_id: null,
  vendor_bill_code: null,
  source_type: 'CUSTOMER_INVOICE',
  source_label: 'Customer Invoice INV-2026-0001',
  amount: '20000.00',
  currency: 'IDR',
  payment_date: '2026-10-13',
  payment_method: 'manual',
  reference: 'TRF-001',
  memo: '',
  state: 'DRAFT',
  odoo_id: null,
  created_at: null,
  updated_at: null,
};

const DETAIL: PaymentDetail = {
  ...ROW,
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
  source_amount_total: '20000.00',
  source_remaining_amount: '0.00',
};

describe('H3.3 — route & guard (App.tsx)', () => {
  it('route CRUD terdaftar dengan guard FINANCE_ROLES tanpa mengubah H3.1/H3.2/F15', () => {
    for (const routePath of [
      '/finance/payments',
      '/finance/payments/new',
      '/finance/payments/:id',
      '/finance/payments/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<PaymentsPage />');
    expect(APP).toContain('<PaymentFormPage />');
    expect(APP).toContain('<PaymentDetailPage />');
    expect(APP).toMatch(/path="\/finance\/payments"[\s\S]{0,220}FINANCE_ROLES/);

    //: H3.1 + H3.2 + F15 tetap ada & tidak diubah.
    expect(APP).toContain('<CustomerInvoicesPage />');
    expect(APP).toContain('<VendorBillsPage />');
    expect(APP).toContain('<InvoiceQueuePage />');
  });

  it('menu Finance punya item Payments di samping Invoices/Customer Invoices/Vendor Bills', () => {
    const finance = NAV_APPS.find((app) => app.id === 'finance');
    const labels = (finance?.topbar ?? []).map((menu) => menu.label);

    expect(labels).toContain('Invoices');
    expect(labels).toContain('Customer Invoices');
    expect(labels).toContain('Vendor Bills');
    expect(labels).toContain('Payments');
    expect(finance?.topbar.find((menu) => menu.label === 'Payments')?.path).toBe(
      '/finance/payments',
    );
  });

  it('bonus tombol "Bayar" di detail invoice (H3.1) & detail bill (H3.2)', () => {
    const invoice = read(INVOICE_DETAIL);
    expect(invoice).toContain('Bayar');
    expect(invoice).toContain('navigate(`/finance/payments/new?invoice=${String(invoiceId)}`)');

    const bill = read(BILL_DETAIL);
    expect(bill).toContain('Bayar');
    expect(bill).toContain('navigate(`/finance/payments/new?bill=${String(billId)}`)');
  });
});

describe('H3.3 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter, dan CTA Payment Baru', () => {
    const { html, text } = renderPage(createElement(PaymentsPage), '/finance/payments');

    expect(text).toContain('Payment');
    expect(text).toContain('Payment Baru');
    for (const label of ['Kode', 'Arah', 'Dokumen sumber', 'Partner', 'Jumlah', 'Tanggal', 'State']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Odoo ID');
    expect(text).toContain('Semua');
    expect(text).toContain('Draft');
    expect(text).toContain('Semua arah');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): pilihan arah, field, dan tombol submit', () => {
    const { html, text } = renderPage(createElement(PaymentFormPage), '/finance/payments/new');

    expect(text).toContain('Payment Baru');
    expect(text).toContain('Arah Pembayaran');
    expect(text).toContain('Pembayaran Masuk');
    expect(text).toContain('Pembayaran Keluar');
    for (const label of [
      'Customer Invoice *',
      'Jumlah bayar *',
      'Tanggal bayar *',
      'Cara bayar',
      'Referensi bank',
      'Catatan',
    ]) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Simpan Payment');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (prefill `?bill=`) → pilihan arah OUTBOUND & sumber vendor bill', () => {
    const { text } = renderPage(
      createElement(PaymentFormPage),
      '/finance/payments/new?bill=9',
    );

    expect(text).toContain('Pembayaran Keluar');
    expect(text).toContain('Vendor Bill *');
  });

  it('halaman detail: judul, tombol Kembali/Lihat Dokumen/Edit/Hapus', () => {
    const { html, text } = renderPage(
      createElement(PaymentDetailPage),
      '/finance/payments/22',
    );

    expect(text).toContain('Detail Payment');
    expect(text).toContain('Kembali');
    expect(text).toContain('Lihat Dokumen');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
    expect(html).toContain('disabled');
  });
});

describe('H3.3 — wiring API di halaman (sumber)', () => {
  it('list memakai adapter payments + DenseTable (bukan <table> mentah)', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain('fetchPayments');
    expect(page).toContain('DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain('navigate(`/finance/payments/${String(row.id)}`)');
    expect(page).toContain('PAYMENT_TYPE_FILTERS');
  });

  it('form memakai create/update + sumber H3.1/H3.2 + sisa dokumen', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createPayment');
    expect(page).toContain('updatePayment');
    expect(page).toContain('fetchCustomerInvoice');
    expect(page).toContain('fetchVendorBill');
    expect(page).toContain('suggestedAmount');
    expect(page).toContain("params.get('invoice')");
    expect(page).toContain("params.get('bill')");
  });

  it('detail memakai aksi + hapus + allowed_actions + tautan dokumen sumber', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('actPayment');
    expect(page).toContain('deletePayment');
    expect(page).toContain('allowed_actions');
    expect(page).toContain('PAYMENT_STATE_TO_ACTION');
    expect(page).toContain('Lihat Dokumen');
  });
});

describe('H3.3 — validasi & helper PURE (lib/payment)', () => {
  it('form valid → body API (sumber sesuai tipe; teks di-trim)', () => {
    expect(paymentInputFromForm(VALID_FORM)).toEqual({
      payment_type: 'INBOUND',
      customer_invoice_id: 7,
      vendor_bill_id: null,
      amount: 20000,
      currency: 'IDR',
      payment_date: '2026-10-13',
      payment_method: 'bank',
      reference: 'TRF-001',
      memo: '',
    });

    const outbound = paymentInputFromForm({
      ...VALID_FORM,
      payment_type: 'OUTBOUND',
      customer_invoice_id: '7',
      vendor_bill_id: '9',
    });
    expect(outbound.vendor_bill_id).toBe(9);
    expect(outbound.customer_invoice_id).toBeNull();
  });

  it('EMPTY_PAYMENT_FORM invalid; sumber & jumlah & tanggal wajib', () => {
    const emptyErrors = validatePaymentForm(EMPTY_PAYMENT_FORM);
    expect(isPaymentFormValid(emptyErrors)).toBe(false);
    expect(emptyErrors.source).toContain('customer invoice');
    expect(emptyErrors.amount).toContain('wajib');
    expect(emptyErrors.payment_date).toContain('wajib');

    expect(isPaymentFormValid(validatePaymentForm(VALID_FORM))).toBe(true);
  });

  it('jumlah: kosong / 0 / negatif / bukan angka → error', () => {
    for (const amount of ['', '0', '-5', 'abc']) {
      const errors = validatePaymentForm({ ...VALID_FORM, amount });
      expect(errors.amount, amount).toBeDefined();
    }

    expect(validatePaymentForm({ ...VALID_FORM, amount: '0.01' }).amount).toBeUndefined();
  });

  it('OUTBOUND wajib vendor bill; referensi > 64 char ditolak', () => {
    const noBill = validatePaymentForm({
      ...VALID_FORM,
      payment_type: 'OUTBOUND',
      customer_invoice_id: '7',
      vendor_bill_id: '',
    });
    expect(noBill.source).toContain('vendor bill');

    expect(validatePaymentForm({ ...VALID_FORM, reference: 'X'.repeat(65) }).reference).toContain(
      '64',
    );
  });

  it('switchPaymentType mengosongkan sumber lawan', () => {
    const outbound = switchPaymentType(VALID_FORM, 'OUTBOUND');
    expect(outbound.payment_type).toBe('OUTBOUND');
    expect(outbound.customer_invoice_id).toBe('');

    const inbound = switchPaymentType(
      { ...VALID_FORM, payment_type: 'OUTBOUND', vendor_bill_id: '9', customer_invoice_id: '' },
      'INBOUND',
    );
    expect(inbound.vendor_bill_id).toBe('');
  });

  it('sisa dokumen: Σ payment aktif + saran jumlah', () => {
    const rows: PaymentRow[] = [
      ROW,
      { ...ROW, id: 23, amount: '5000.00', state: 'CANCELLED' },
      { ...ROW, id: 24, amount: '15000.00', state: 'SENT' },
    ];

    //: CANCELLED diabaikan ⇒ 20.000 + 15.000.
    expect(activePaymentsTotal(rows)).toBe(35000);
    expect(remainingForSource('50000.00', rows)).toBe(15000);
    expect(suggestedAmount('50000.00', rows)).toBe('15000.00');
    expect(remainingForSource('35000.00', rows)).toBe(0);
    expect(suggestedAmount('35000.00', rows)).toBe('');
  });

  it('paymentFormFromDetail + label opsi dropdown', () => {
    const form = paymentFormFromDetail(DETAIL);
    expect(form.payment_type).toBe('INBOUND');
    expect(form.customer_invoice_id).toBe('7');
    expect(form.vendor_bill_id).toBe('');
    expect(form.amount).toBe('20000.00');
    expect(form.payment_date).toBe('2026-10-13');

    expect(invoiceOptionLabel({ code: 'INV-1', customer_name: 'PT Buyer' })).toBe(
      'INV-1 — PT Buyer',
    );
    expect(billOptionLabel({ code: 'VB-1', vendor_name: null })).toBe('VB-1 — -');
  });

  it('label/tone & field detail payment', () => {
    expect(paymentTypeLabel('OUTBOUND')).toBe('Keluar (vendor)');
    expect(paymentStateLabel('SENT')).toBe('Terkirim ke Odoo');
    expect(paymentStateTone('CANCELLED')).toBe('coral');
    expect(paymentStateTone('DRAFT')).toBe('muted');
    expect(paymentStateTone('CONFIRMED')).toBe('blue');

    const items = paymentDetailItems(ROW);
    expect(items.map((item) => item.label)).toContain('Dokumen sumber');
    expect(items.find((item) => item.label === 'Jumlah')?.value).toBe('20000.00 IDR');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
  });
});


