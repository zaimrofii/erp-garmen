import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import {
  FeedbackRuntimeContext,
  OfflineRuntimeContext,
  type FeedbackRuntime,
  type OfflineRuntime,
} from '@/app/app-runtime';
import { ProductDetailPage } from '@/pages/master/ProductDetailPage';
import { PartnerDetailPage } from '@/pages/master/PartnerDetailPage';
import { ProductsPage } from '@/pages/master/ProductsPage';
import { BundleDetailPage } from '@/pages/bundles/BundleDetailPage';
import { ShopFloorPage } from '@/pages/production/ShopFloorPage';
import { QCPage } from '@/pages/production/QCPage';
import { OrderDetailPage } from '@/pages/sales/OrderDetailPage';
import { OrdersPage } from '@/pages/sales/OrdersPage';
import { PurchaseOrderDetailPage } from '@/pages/purchase/PurchaseOrderDetailPage';
import { SalesReportPage } from '@/pages/reports/SalesReportPage';
import { ProductionReportPage } from '@/pages/reports/ProductionReportPage';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * Sprint E.4 — pasang FloatingAIAssistant di 11 halaman prioritas.
 *
 * Render nyata (react-dom/server) memastikan ikon benar-benar muncul; konteks
 * (page_type/resource/filters/snapshot) diverifikasi dari SUMBER halaman karena
 * data detail baru ada setelah fetch (tidak berjalan di SSR tanpa efek).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const read = (relative: string): string =>
  readFileSync(path.join(ROOT, relative), 'utf8');

const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};
const OFFLINE: OfflineRuntime = {
  queue: {} as OfflineRuntime['queue'],
  isOnline: true,
  pendingCount: 0,
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
        createElement(
          OfflineRuntimeContext.Provider,
          { value: OFFLINE },
          createElement(Routes, null, createElement(Route, { path: routePath, element })),
        ),
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

function expectIcon(
  element: ReactElement,
  initialPath: string,
  routePath?: string,
): void {
  const { html, text } = renderPage(element, initialPath, routePath);

  expect(html).toContain('fixed bottom-6 right-6');
  expect(html).toContain('aria-label="Buka Asisten AI"');
  expect(html).toContain('aria-expanded="false"');
  expect(text).not.toContain('role="dialog"');
}

describe('Sprint E.4 — ikon floating di halaman prioritas', () => {
  it('ProductDetailPage + snapshot field produk', () => {
    expectIcon(
      createElement(ProductDetailPage),
      '/master/products/7',
      '/master/products/:id',
    );

    const source = read('src/pages/master/ProductDetailPage.tsx');
    expect(source).toContain('FloatingAIAssistant context={aiContext}');
    expect(source).toContain('"product"');
    expect(source).toContain('sale_price: product.sale_price');
    expect(source).toContain('{ id }');
  });

  it('PartnerDetailPage + snapshot partner', () => {
    expectIcon(
      createElement(PartnerDetailPage),
      '/master/partners/7',
      '/master/partners/:id',
    );

    const source = read('src/pages/master/PartnerDetailPage.tsx');
    expect(source).toContain('"partner"');
    expect(source).toContain('is_vendor: partner.is_vendor');
    expect(source).toContain('city: partner.city');
  });

  it('BundleDetailPage + snapshot bundle', () => {
    expectIcon(createElement(BundleDetailPage), '/bundles/7', '/bundles/:id');

    const source = read('src/pages/bundles/BundleDetailPage.tsx');
    expect(source).toContain('"bundle"');
    expect(source).toContain('size: bundle.size');
  });

  it('ShopFloorPage + qty_done', () => {
    expectIcon(
      createElement(ShopFloorPage),
      '/production/shop-floor/7',
      '/production/shop-floor/:id',
    );

    const source = read('src/pages/production/ShopFloorPage.tsx');
    expect(source).toContain('qty_done: bundle.qty_done');
  });

  it('QCPage + snapshot bundle', () => {
    expectIcon(createElement(QCPage), '/production/qc/7', '/production/qc/:id');

    const source = read('src/pages/production/QCPage.tsx');
    expect(source).toContain("'bundle'");
    expect(source).toContain('FloatingAIAssistant context={aiContext}');
  });

  it('OrderDetailPage + customer & total', () => {
    expectIcon(
      createElement(OrderDetailPage),
      '/sales/orders/7',
      '/sales/orders/:id',
    );

    const source = read('src/pages/sales/OrderDetailPage.tsx');
    expect(source).toContain('customer_name: order.customer_name');
    expect(source).toContain('total: order.amount_total');
  });

  it('PurchaseOrderDetailPage + vendor & total', () => {
    expectIcon(
      createElement(PurchaseOrderDetailPage),
      '/purchase/orders/7',
      '/purchase/orders/:id',
    );

    const source = read('src/pages/purchase/PurchaseOrderDetailPage.tsx');
    expect(source).toContain('vendor_name: po.vendor_name');
    expect(source).toContain("'purchase_order'");
  });

  it('ProductsPage (list) + filters', () => {
    expectIcon(createElement(ProductsPage), '/master/products');

    const source = read('src/pages/master/ProductsPage.tsx');
    expect(source).toContain('"list", "product"');
    expect(source).toContain('active: status');
  });

  it('OrdersPage (list) + filters', () => {
    expectIcon(createElement(OrdersPage), '/sales/orders');

    const source = read('src/pages/sales/OrdersPage.tsx');
    expect(source).toContain("'list', 'order'");
    expect(source).toMatch(/search,\s*state,/);
  });

  it('SalesReportPage (report) + filters.period', () => {
    expectIcon(createElement(SalesReportPage), '/reports/sales');

    const source = read('src/pages/reports/SalesReportPage.tsx');
    expect(source).toContain("'report', 'report'");
    expect(source).toMatch(/period,\s*customer_id/);
    expect(source).toContain('group_by: groupBy');
  });

  it('ProductionReportPage (report) + work center/line', () => {
    expectIcon(createElement(ProductionReportPage), '/reports/production');

    const source = read('src/pages/reports/ProductionReportPage.tsx');
    expect(source).toContain('work_center_id: workCenterId');
    expect(source).toContain('line_id: lineId');
  });

  it('semua halaman detail mengirim resource_id sebagai string (helper)', () => {
    for (const relative of [
      'src/pages/master/ProductDetailPage.tsx',
      'src/pages/master/PartnerDetailPage.tsx',
      'src/pages/bundles/BundleDetailPage.tsx',
      'src/pages/production/ShopFloorPage.tsx',
      'src/pages/production/QCPage.tsx',
      'src/pages/sales/OrderDetailPage.tsx',
      'src/pages/purchase/PurchaseOrderDetailPage.tsx',
    ]) {
      const source = read(relative);

      expect(source, relative).toContain('FloatingAIAssistant');
      expect(source, relative).toContain('{ id }');
      expect(source, relative).toContain('buildChatContext');
    }
  });
});

