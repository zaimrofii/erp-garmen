import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { TaxDetailPage } from '@/pages/master/TaxDetailPage';
import { TaxFormPage } from '@/pages/master/TaxFormPage';
import { TaxesPage } from '@/pages/master/TaxesPage';
import {
  EMPTY_TAX_FORM,
  isTaxAmountType,
  isTaxFormValid,
  isTaxUse,
  taxAmountLabel,
  taxDetailItems,
  taxFormFromRow,
  taxInputFromForm,
  taxOptionLabel,
  taxUseLabel,
  validateTaxForm,
  type TaxFormValues,
} from '@/lib/master-tax';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterTaxRow } from '@/types/master-tax';

/**
 * H3.6 — halaman master Tax (`/master/taxes*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun dengan `createElement`
 *      supaya file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter`
 *      + konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, dan validasi form
 *      (`lib/master-tax.ts`) — termasuk "submit nama kosong" & "amount negatif".
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/master/TaxesPage.tsx';
const FORM_PAGE = 'src/pages/master/TaxFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/TaxDetailPage.tsx';

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

/** Nilai form pajak yang SAH dipakai beberapa test "submit". */
const VALID_FORM: TaxFormValues = {
  code: 'PPN11-SALE',
  name: 'PPN 11%',
  amount: '11',
  amount_type: 'percent',
  type_tax_use: 'sale',
  price_include: false,
  is_default: true,
  active: true,
};

const ROW: MasterTaxRow = {
  id: 12,
  code: 'PPN11-SALE',
  name: 'PPN 11%',
  amount: 11,
  amount_type: 'percent',
  type_tax_use: 'sale',
  price_include: false,
  is_default: true,
  active: true,
  odoo_id: null,
};

describe('H3.6 — route & guard (App.tsx)', () => {
  it('4 route master pajak terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/taxes',
      '/master/taxes/new',
      '/master/taxes/:id',
      '/master/taxes/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterTaxesPage />');
    expect(APP).toContain('<MasterTaxFormPage />');
    expect(APP).toContain('<MasterTaxDetailPage />');
    expect(APP).toMatch(/path="\/master\/taxes"[\s\S]{0,200}INVENTORY_ROLES/);
  });

  it('path `/master/taxes*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ prefix: '/master/taxes', appId: 'inventory' }",
    );
  });

  it('menu Inventory punya item Master Pajak (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Pajak');

    expect(item?.path).toBe('/master/taxes');
    expect(item?.children).toBeUndefined();
  });
});

describe('H3.6 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter jenis, dan CTA Pajak Baru', () => {
    const { html, text } = renderPage(createElement(TaxesPage), '/master/taxes');

    expect(text).toContain('Master Pajak');
    expect(text).toContain('Pajak Baru');
    for (const label of ['Kode', 'Nama', 'Tarif', 'Jenis', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Penjualan');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): field wajib + checkbox default & tombol submit', () => {
    const { html, text } = renderPage(createElement(TaxFormPage), '/master/taxes/new');

    expect(text).toContain('Pajak Baru');
    for (const label of ['Nama *', 'Kode', 'Tarif *', 'Tipe nilai', 'Jenis pajak']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Jadikan pajak default MES');
    expect(text).toContain('Simpan Pajak');
    // dropdown tipe nilai = selection Odoo (percent|fixed)
    expect(text).toContain('Persen (%)');
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: tombol Edit + aksi Jadikan Default', () => {
    const { html, text } = renderPage(createElement(TaxDetailPage), '/master/taxes/12');

    expect(text).toContain('Detail Pajak');
    expect(text).toContain('Edit');
    expect(text).toContain('Jadikan Default');
    expect(html).toContain('disabled');
  });
});


describe('H3.6 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter jenis server, tabel dense, klik baris → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterTaxes'");
    expect(page).toContain('fetchTaxes(client, {');
    expect(page).toContain('TAXES_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-taxes'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/taxes/${String(row.id)}`)");
  });

  it('form: create & update lewat adapter + validasi pure + submit handler', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createTax');
    expect(page).toContain('updateTax');
    expect(page).toContain('validateTaxForm(values)');
    expect(page).toContain('taxInputFromForm(values)');
    expect(page).toContain("from '@/components/atoms/Checkbox'");
    expect(page).toContain("from '@/components/atoms/Select'");
    expect(page).toContain('onSubmit={handleSubmit}');
  });

  it('detail: read-only + aksi `set-default` (is_default = keputusan MES)', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('setDefaultTax(client, taxId ?? 0)');
    expect(page).toContain('taxDetailItems(tax)');
    expect(page).toContain('/master/taxes/${String(taxId)}/edit');
    expect(page).toContain('disabled={tax === undefined || tax.is_default || !tax.active}');
    expect(page).not.toContain('deleteTax');
  });
});

describe('H3.6 — submit form: valid & field wajib', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateTaxForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isTaxFormValid(errors)).toBe(true);
    expect(taxInputFromForm(VALID_FORM)).toEqual({
      code: 'PPN11-SALE',
      name: 'PPN 11%',
      amount: 11,
      amount_type: 'percent',
      type_tax_use: 'sale',
      price_include: false,
      is_default: true,
      active: true,
    });
  });

  it('form nama KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validateTaxForm({ ...VALID_FORM, name: '   ' });

    expect(errors.name).toBe('Nama pajak wajib diisi.');
    expect(isTaxFormValid(errors)).toBe(false);
  });

  it('form awal (EMPTY_TAX_FORM) hanya nama yang kurang (tarif default 11%, 0 diizinkan)', () => {
    expect(Object.keys(validateTaxForm(EMPTY_TAX_FORM))).toEqual(['name']);
    expect(validateTaxForm({ ...EMPTY_TAX_FORM, name: 'PPN 0%', amount: '0' })).toEqual({});
  });

  it('amount negatif / bukan angka → error (0 tetap diizinkan)', () => {
    const negative = validateTaxForm({ ...VALID_FORM, amount: '-1' });
    expect(negative.amount).toContain('tidak boleh negatif');

    const notNumber = validateTaxForm({ ...VALID_FORM, amount: 'sebelas' });
    expect(notNumber.amount).toContain('Isi angka');

    expect(validateTaxForm({ ...VALID_FORM, amount: '0' })).toEqual({});
  });

  it('edit: taxFormFromRow ↔ taxInputFromForm konsisten', () => {
    expect(taxFormFromRow(ROW)).toEqual(VALID_FORM);
    expect(taxInputFromForm(taxFormFromRow(ROW))).toEqual(taxInputFromForm(VALID_FORM));
    // Odoo ID tidak ikut dikirim di body (kunci sync, bukan field tulis).
    expect('odoo_id' in taxInputFromForm(VALID_FORM)).toBe(false);
  });
});

describe('H3.6 — bonus: dropdown pajak di form SO/PO (tutup gap H2.1/H2.2)', () => {
  it('form SO: memuat pajak penjualan + opsi per baris → `tax_ids: [id]`', () => {
    const page = read('src/pages/sales/OrderFormPage.tsx');

    expect(page).toContain("from '@/api/masterTaxes'");
    expect(page).toContain('fetchTaxes(client, { type_tax_use: \'sale\', active: true, limit: TAXES_LIMIT_MAX })');
    expect(page).toContain('taxOptionLabel');
    expect(page).toContain('tax_ids: next === \'\' ? [] : [Number(next)]');
  });

  it('form PO: memuat pajak pembelian + opsi per baris → `tax_ids: [id]`', () => {
    const page = read('src/pages/purchase/PurchaseOrderFormPage.tsx');

    expect(page).toContain("from '@/api/masterTaxes'");
    expect(page).toContain(
      'fetchTaxes(client, { type_tax_use: \'purchase\', active: true, limit: TAXES_LIMIT_MAX })',
    );
    expect(page).toContain('taxOptionLabel');
    expect(page).toContain('tax_ids: next === \'\' ? [] : [Number(next)]');
  });
});

describe('H3.6 — helper tampilan (lib)', () => {
  it('isTaxUse/isTaxAmountType hanya menerima nilai selection Odoo', () => {
    expect(isTaxUse('sale')).toBe(true);
    expect(isTaxUse('purchase')).toBe(true);
    expect(isTaxUse('none')).toBe(true);
    expect(isTaxUse('both')).toBe(false);

    expect(isTaxAmountType('percent')).toBe(true);
    expect(isTaxAmountType('fixed')).toBe(true);
    expect(isTaxAmountType('division')).toBe(false);
  });

  it('taxAmountLabel & taxUseLabel: persen vs nominal tetap', () => {
    expect(taxAmountLabel({ amount: 11, amount_type: 'percent' })).toBe('11%');
    expect(taxAmountLabel({ amount: 5000, amount_type: 'fixed' })).toBe('Rp 5000');
    expect(taxUseLabel('purchase')).toBe('Pembelian (purchase)');
  });

  it('taxOptionLabel: KODE - nama (fallback kalau salah satu kosong)', () => {
    expect(taxOptionLabel(ROW)).toBe('PPN11-SALE - PPN 11%');
    expect(taxOptionLabel({ ...ROW, code: '' })).toBe('PPN 11%');
    expect(taxOptionLabel({ ...ROW, name: ' ' })).toBe('PPN11-SALE');
  });

  it('taxDetailItems: 8 baris + odoo_id null → "belum dikirim"', () => {
    const items = taxDetailItems(ROW);

    expect(items).toHaveLength(8);
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Pajak default MES')?.value).toBe('Ya');
    expect(items.find((item) => item.label === 'Tarif')?.value).toBe('11%');
    expect(taxDetailItems({ ...ROW, odoo_id: 19 })[7]?.value).toBe('19');
  });
});

