import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { ProductPriceHistoryPage } from '@/pages/master/ProductPriceHistoryPage';
import {
  displayOrDash,
  priceFieldLabel,
  priceHistoryItems,
  priceHistorySummary,
  priceHistoryValues,
  priceSourceLabel,
} from '@/lib/master-product';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterProductPriceHistoryRow, MasterProductRow } from '@/types/master-product';

/**
 * H3.5 — halaman riwayat harga (`/master/products/:id/price-history`) + helper PURE.
 *
 * Dua lapis (tanpa jsdom): render SSR (`react-dom/server` + react-query + router) dan
 * pemeriksaan sumber `App.tsx` untuk route/guard.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

const APP = readFileSync(path.join(ROOT, 'src/App.tsx'), 'utf8');

const PRODUCT: MasterProductRow = {
  id: 3,
  code: 'KAIN-COTTON',
  name: 'Kain Cotton',
  category: '',
  uom_id: null,
  uom_code: null,
  sale_price: 50000,
  cost_price: 30000,
  price_updated_at: '2026-10-12T05:00:00+00:00',
  weight: null,
  image_url: '',
  active: true,
  odoo_id: 89,
  created_at: null,
  updated_at: null,
};

const HISTORY: MasterProductPriceHistoryRow = {
  id: 12,
  action: 'master.update_price',
  source: 'price_endpoint',
  fields: ['sale_price'],
  before: { sale_price: '50000.00' },
  after: { sale_price: '61000.00' },
  user: 'admin-h35',
  timestamp: '2026-10-12T05:10:00+00:00',
  request_id: 'req-1',
};

function renderPage(
  element: ReactElement,
  initialPath: string,
  seed?: (client: QueryClient) => void,
  routePath = initialPath,
): { html: string; text: string } {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  seed?.(client);
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: [initialPath] },
      createElement(Routes, null, createElement(Route, { path: routePath, element })),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

/** Route pola (agar `useParams().id` terisi di SSR satu kali jalan). */
const HISTORY_ROUTE = '/master/products/:id/price-history';

describe('H3.5 — helper PURE riwayat harga', () => {
  it('priceSourceLabel menerjemahkan sumber perubahan', () => {
    expect(priceSourceLabel('price_endpoint')).toBe('Endpoint harga');
    expect(priceSourceLabel('product_update')).toBe('Form produk');
    expect(priceSourceLabel('')).toBe('-');
    expect(priceSourceLabel('lain')).toBe('lain');
  });

  it('priceFieldLabel & displayOrDash aman untuk nilai kosong', () => {
    expect(priceFieldLabel('sale_price')).toBe('Harga Jual');
    expect(priceFieldLabel('cost_price')).toBe('Harga Pokok (HPP)');
    expect(priceFieldLabel('aneh')).toBe('aneh');
    expect(displayOrDash(null)).toBe('-');
    expect(displayOrDash('  ')).toBe('-');
    expect(displayOrDash('ok')).toBe('ok');
  });

  it('priceHistoryValues & priceHistorySummary menyusun diff', () => {
    expect(priceHistoryValues(HISTORY, 'sale_price')).toEqual({
      before: '50000.00',
      after: '61000.00',
    });
    expect(priceHistoryValues(HISTORY, 'cost_price')).toEqual({ before: '-', after: '-' });
    expect(priceHistorySummary(HISTORY)).toBe('Harga Jual: 50000.00 → 61000.00');

    const dua: MasterProductPriceHistoryRow = {
      ...HISTORY,
      fields: ['sale_price', 'cost_price'],
      before: { sale_price: '1.00', cost_price: '2.00' },
      after: { sale_price: '3.00', cost_price: '4.00' },
    };
    expect(priceHistorySummary(dua)).toBe(
      'Harga Jual: 1.00 → 3.00 · Harga Pokok (HPP): 2.00 → 4.00',
    );
    expect(priceHistorySummary({ ...HISTORY, fields: [] })).toBe('Perubahan harga');
  });

  it('priceHistoryItems membentuk item UI (label/value)', () => {
    const items = priceHistoryItems(HISTORY);

    expect(items.map((item) => item.label)).toEqual([
      'Perubahan',
      'Sumber',
      'Diubah oleh',
      'Waktu',
      'Aksi audit',
    ]);
    expect(items[0]?.value).toContain('Harga Jual');
    expect(items[1]?.value).toBe('Endpoint harga');
    expect(items[2]?.value).toBe('admin-h35');
  });
});

describe('H3.5 — halaman riwayat harga (render + sumber)', () => {
  it('menampilkan keadaan kosong saat belum ada perubahan', () => {
    const { text } = renderPage(
      createElement(ProductPriceHistoryPage),
      '/master/products/3/price-history',
      (client) => {
        client.setQueryData(['master-product', 3], PRODUCT);
        client.setQueryData(['master-product-price-history', 3, 0], {
          rows: [],
          total_count: 0,
          has_more: false,
          next_cursor: null,
        });
      },
      HISTORY_ROUTE,
    );

    expect(text).toContain('Riwayat Harga');
    expect(text).toContain('Kain Cotton');
    expect(text).toContain('Belum ada perubahan harga');
  });

  it('menampilkan baris riwayat + total saat ada data', () => {
    const { text } = renderPage(
      createElement(ProductPriceHistoryPage),
      '/master/products/3/price-history',
      (client) => {
        client.setQueryData(['master-product', 3], PRODUCT);
        client.setQueryData(['master-product-price-history', 3, 0], {
          rows: [HISTORY],
          total_count: 1,
          has_more: false,
          next_cursor: null,
        });
      },
      HISTORY_ROUTE,
    );

    expect(text).toContain('Harga Jual: 50000.00 → 61000.00');
    expect(text).toContain('Endpoint harga');
    expect(text).toContain('admin-h35');
    expect(text).toMatch(/1\s+dari\s+1/);
    expect(text).not.toContain('Belum ada perubahan harga');
  });

  it('route riwayat harga terdaftar di App.tsx (INVENTORY_ROLES)', () => {
    expect(APP).toContain('path="/master/products/:id/price-history"');
    expect(APP).toContain('MasterProductPriceHistoryPage');
    expect(APP).toContain("const INVENTORY_ROLES: Role[] = ['inventory', 'admin', 'owner'];");
  });

  it('detail produk menautkan ke riwayat harga (kartu harga H3.5)', () => {
    const detail = readFileSync(
      path.join(ROOT, 'src/pages/master/ProductDetailPage.tsx'),
      'utf8',
    );

    expect(detail).toContain('price_updated_at');
    expect(detail).toContain('/price-history');
    expect(detail).toContain('Riwayat Harga');
  });
});
