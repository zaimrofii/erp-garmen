import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { ProductDetailPage } from '@/pages/master/ProductDetailPage';
import { ProductFormPage } from '@/pages/master/ProductFormPage';
import { ProductsPage } from '@/pages/master/ProductsPage';
import {
  activeParamForStatus,
  displayOrDash,
  EMPTY_PRODUCT_FORM,
  formatPrice,
  isProductFormValid,
  productDetailItems,
  productFormFromRow,
  productInputFromForm,
  validateProductForm,
  type ProductFormValues,
} from '@/lib/master-product';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterProductRow } from '@/types/master-product';

/** Nilai form yang SAH dipakai beberapa test "submit". */
const VALID_FORM: ProductFormValues = {
  code: 'TS-900',
  name: 'Kaos Uji',
  category: 'Atasan',
  uom: '3',
  sale_price: '15000.5',
  cost_price: '9000',
  weight: '0.25',
  image_url: 'https://cdn.klien.com/kaos.png',
  active: true,
};

const ROW: MasterProductRow = {
  id: 7,
  code: 'TS-900',
  name: 'Kaos Uji',
  category: 'Atasan',
  uom_id: 3,
  uom_code: 'PCS',
  sale_price: 15000.5,
  cost_price: 9000,
  weight: 0.25,
  image_url: 'https://cdn.klien.com/kaos.png',
  active: true,
  odoo_id: null,
  created_at: '2026-10-10T10:00:00+07:00',
  updated_at: '2026-10-10T10:00:00+07:00',
};

/**
 * H1.1 — halaman master produk (`/master/products*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (komponen fungsi & hooks ikut jalan,
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + konteks runtime palsu);
 *      pohon dibangun dengan `createElement` supaya file tetap `.ts` (tanpa JSX);
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, dan validasi form
 *      (`lib/master-product.ts`) — termasuk kasus "submit code kosong".
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/master/ProductsPage.tsx';
const FORM_PAGE = 'src/pages/master/ProductFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/ProductDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function inProviders(element: ReactElement, initialPath: string): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  return createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: [initialPath] },
      createElement(
        FeedbackRuntimeContext.Provider,
        { value: FEEDBACK },
        createElement(
          Routes,
          null,
          createElement(Route, { path: initialPath, element }),
        ),
      ),
    ),
  );
}

function renderPage(element: ReactElement, initialPath: string): { html: string; text: string } {
  const tree = inProviders(element, initialPath);

  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('H1.1 — route & guard (App.tsx)', () => {
  it('4 route master produk terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/products',
      '/master/products/new',
      '/master/products/:id',
      '/master/products/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterProductsPage />');
    expect(APP).toContain('<MasterProductFormPage />');
    expect(APP).toContain('<MasterProductDetailPage />');
    expect(APP).toMatch(/path="\/master\/products"[\s\S]{0,200}INVENTORY_ROLES/);
  });

  it('path `/master/products*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ prefix: '/master/products', appId: 'inventory' }",
    );
  });

  it('menu Inventory punya item Master Products (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Products');

    expect(item?.path).toBe('/master/products');
    // Tanpa `children` ⇒ TopBar merender LINK (sesuai F16).
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.1 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom dense table, filter, dan CTA Produk Baru', () => {
    const { html, text } = renderPage(createElement(ProductsPage), '/master/products');

    expect(text).toContain('Master Products');
    expect(text).toContain('Produk Baru');
    for (const label of ['Kode', 'Nama', 'Kategori', 'UoM', 'Harga Jual', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Nonaktif');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): field wajib, checkbox aktif, tombol submit', () => {
    const { html, text } = renderPage(
      createElement(ProductFormPage),
      '/master/products/new',
    );

    expect(text).toContain('Produk Baru');
    for (const label of ['Kode *', 'Nama *', 'Kategori', 'UoM', 'Harga Jual']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Produk aktif');
    expect(text).toContain('Simpan Produk');
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html } = renderPage(createElement(ProductDetailPage), '/master/products/7');

    expect(html).toContain('Detail Produk');
    expect(html).toContain('>Edit<');
    expect(html).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

describe('H1.1 — sumber halaman (wiring API & placeholder)', () => {
  it('list: memakai adapter real, filter server, dan tabel dense (tanpa <table> baru)', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterProducts'");
    expect(page).toContain('fetchProducts(client, {');
    expect(page).toContain('PRODUCTS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-products'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("'/master/products/new'");
  });

  it('form: create & update lewat adapter + validasi pure + submit handler', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createProduct(client, input)');
    expect(page).toContain('updateProduct(client, productId, input)');
    // H1.2 — validasi memakai daftar UoM aktif sebagai opsi kedua (`uomIds`).
    expect(page).toMatch(/validateProductForm\(\s*values,/);
    expect(page).toContain('{ uomIds: uomRows.map((row) => row.id) }');
    expect(page).toContain('productInputFromForm(values)');
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).toContain('save.mutate()');
    // tanpa `fetch()` langsung di komponen (§12.1); `refetch()` react-query tetap boleh.
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only (tanpa mutasi) + Sync placeholder disabled ber-tooltip H2', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchProduct(client, productId ?? 0)');
    expect(page).toContain('disabled');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/products/${String(productId)}/edit');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteProduct');
  });
});

describe('H1.1 — submit form: valid & code kosong', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateProductForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isProductFormValid(errors)).toBe(true);
    expect(productInputFromForm(VALID_FORM)).toEqual({
      code: 'TS-900',
      name: 'Kaos Uji',
      category: 'Atasan',
      uom_id: 3,
      sale_price: 15000.5,
      cost_price: 9000,
      weight: 0.25,
      image_url: 'https://cdn.klien.com/kaos.png',
      active: true,
    });
  });

  it('form code KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validateProductForm({ ...VALID_FORM, code: '   ' });

    expect(errors.code).toBe('Kode produk wajib diisi.');
    expect(isProductFormValid(errors)).toBe(false);
  });

  it('form awal (EMPTY_PRODUCT_FORM) tidak valid: code & name kosong', () => {
    expect(Object.keys(validateProductForm(EMPTY_PRODUCT_FORM)).sort()).toEqual([
      'code',
      'name',
    ]);
  });

  it('validasi lain: UoM non-angka, harga negatif, berat bukan angka, URL salah', () => {
    const errors = validateProductForm({
      ...VALID_FORM,
      uom: 'PCS',
      sale_price: '-1',
      cost_price: 'abc',
      weight: 'berat',
      image_url: 'cdn/kaos.png',
    });

    expect(Object.keys(errors).sort()).toEqual([
      'cost_price',
      'image_url',
      'sale_price',
      'uom',
      'weight',
    ]);
    // `weight` kosong = opsional → tidak ada error.
    expect(validateProductForm({ ...VALID_FORM, weight: '' }).weight).toBeUndefined();
  });

  it('edit: productFormFromRow ↔ productInputFromForm konsisten', () => {
    expect(productFormFromRow(ROW)).toEqual(VALID_FORM);
    expect(productInputFromForm(productFormFromRow(ROW)).code).toBe('TS-900');
  });
});

describe('H1.1 — helper tampilan (lib)', () => {
  it('formatPrice memakai format Indonesia', () => {
    expect(formatPrice(15000.5)).toBe('15.000,50');
    expect(formatPrice(0)).toBe('0,00');
  });

  it("displayOrDash: null/''/spasi → '-'", () => {
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash('   ')).toBe('-');
    expect(displayOrDash('PCS')).toBe('PCS');
  });

  it('activeParamForStatus: "all" → null (param active tidak dikirim)', () => {
    expect(activeParamForStatus('all')).toBeNull();
    expect(activeParamForStatus('active')).toBe(true);
    expect(activeParamForStatus('inactive')).toBe(false);
  });

  it('productDetailItems: odoo_id null → "belum dikirim"', () => {
    const items = productDetailItems(ROW);

    expect(items).toHaveLength(11);
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'Harga Jual')?.value).toBe('15.000,50');
    expect(productDetailItems({ ...ROW, odoo_id: 101 })[8]?.value).toBe('101');
  });
});

describe('H1.2 — bonus tutup backlog H1.1: dropdown UoM di form produk', () => {
  it('form produk memakai <Select> berisi UoM aktif dari fetchUoms(...)', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain("import { fetchUoms, UOMS_LIMIT_MAX } from '@/api/masterUoms';");
    expect(page).toContain('fetchUoms(client, { active: true, limit: UOMS_LIMIT_MAX })');
    expect(page).toContain("queryKey: ['master-uom-options']");
    expect(page).toContain('uomOptionLabel');
    expect(page).toContain('<Select');
    // input teks ID UoM (H1.1) sudah tidak ada.
    expect(page).not.toContain('label="UoM (ID)"');
    expect(page).not.toContain('dropdown menyusul di H1.2');
  });

  it('pilihan UoM terkirim sebagai `uom_id` + divalidasi terhadap daftar opsi', () => {
    expect(productInputFromForm({ ...VALID_FORM, uom: '7' }).uom_id).toBe(7);
    expect(productInputFromForm({ ...VALID_FORM, uom: '' }).uom_id).toBeNull();

    // Daftar opsi tersedia (query sudah termuat): id di luar daftar ditolak di klien.
    expect(validateProductForm({ ...VALID_FORM, uom: '7' }, { uomIds: [3, 7] })).toEqual({});
    expect(validateProductForm({ ...VALID_FORM, uom: '9' }, { uomIds: [3, 7] }).uom).toContain(
      'tidak ada di daftar',
    );

    // Daftar belum termuat → hanya cek bentuk (angka), backend tetap validasi.
    expect(validateProductForm({ ...VALID_FORM, uom: '9' }).uom).toBeUndefined();
    expect(validateProductForm({ ...VALID_FORM, uom: 'PCS' }).uom).toContain('dropdown');
  });
});


