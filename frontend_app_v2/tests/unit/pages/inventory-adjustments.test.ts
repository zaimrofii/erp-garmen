import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { InventoryAdjustmentDetailPage } from '@/pages/inventory/InventoryAdjustmentDetailPage';
import { InventoryAdjustmentFormPage } from '@/pages/inventory/InventoryAdjustmentFormPage';
import { InventoryAdjustmentListPage } from '@/pages/inventory/InventoryAdjustmentListPage';
import {
  adjustmentChipStatus,
  adjustmentCreateInputFromForm,
  adjustmentRowLabel,
  adjustmentStateLabel,
  EMPTY_ADJUSTMENT_FORM,
  isAdjustmentCommittable,
  isAdjustmentFormValid,
  MAX_QTY_DELTA,
  parseQtyDelta,
  qtyLabel,
  signedDelta,
  stockQtyLabel,
  validateAdjustmentForm,
  type AdjustmentFormValues,
} from '@/lib/inventory-adjustment';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { InventoryAdjustmentRow } from '@/types/inventory-adjustment';

/**
 * H2.5 — halaman Inventory Adjustment (`/inventory/adjustments|adjust/:id`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` + `QueryClientProvider`/`MemoryRouter`;
 *   2. SUMBER/pure: route + guard `INVENTORY_ROLES` di `App.tsx`, menu di
 *      `app/nav-config.ts`, dan validasi form di `lib/inventory-adjustment.ts`.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

function renderPage(
  element: React.ReactElement,
  initialPath: string,
  seed?: (client: QueryClient) => void,
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
      createElement(Routes, null, createElement(Route, { path: initialPath, element })),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

/** Isi cache react-query supaya halaman merender cabang DATA (SSR sekali jalan). */
function seedListQueries(client: QueryClient): void {
  client.setQueryData(['inventory-adjustments', '', '', '', '', 0], {
    rows: [ROW],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  });
  client.setQueryData(['master-products', 'inventory-adjust-options'], {
    rows: [
      {
        id: 89,
        code: 'KAIN-COTTON',
        name: 'Kain Cotton',
        category: '',
        uom_id: null,
        uom_code: null,
        sale_price: 0,
        cost_price: 0,
        weight: null,
        image_url: '',
        active: true,
        odoo_id: 89,
        updated_at: null,
      },
    ],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  });
  client.setQueryData(['master-locations', 'inventory-adjust-options'], {
    rows: [
      {
        id: 8,
        code: 'WH/STOK',
        name: 'Stok',
        usage: 'internal',
        parent_id: null,
        parent_name: null,
        warehouse_id: null,
        warehouse_name: null,
        active: true,
        odoo_id: 8,
        children_count: 0,
        complete_name: 'WH/Stok',
      },
    ],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  });
}

/** Isi cache dropdown untuk halaman form (daftar adjustment tak dipanggil). */
function seedFormQueries(client: QueryClient): void {
  seedListQueries(client);
}

const VALID_FORM: AdjustmentFormValues = {
  productId: '89',
  locationId: '8',
  qtyDelta: '-3.5',
  reason: 'Koreksi opname',
};

const ROW: InventoryAdjustmentRow = {
  id: 3,
  code: 'ADJ-2026-0001',
  product_id: 89,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton',
  location_id: 8,
  location_code: 'WH/STOK',
  location_name: 'Stok',
  location_usage: 'internal',
  qty_delta: '5.00',
  qty_before: '60.00',
  qty_after: null,
  reason: 'Hasil opname',
  state: 'DRAFT',
  odoo_move_id: null,
  odoo_reference: '',
  last_error: '',
  created_by: 'sim-h25',
  created_at: null,
  updated_at: null,
};

describe('H2.5 — lib PURE Inventory Adjustment', () => {
  it('form kosong: semua field wajib dilaporkan', () => {
    const errors = validateAdjustmentForm(EMPTY_ADJUSTMENT_FORM);

    expect(errors.productId).toBeDefined();
    expect(errors.locationId).toBeDefined();
    expect(errors.qtyDelta).toBeDefined();
    expect(errors.reason).toBeDefined();
    expect(isAdjustmentFormValid(errors)).toBe(false);
  });

  it('form valid lolos (delta negatif diizinkan)', () => {
    const errors = validateAdjustmentForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isAdjustmentFormValid(errors)).toBe(true);
  });

  it('delta 0 / bukan angka / di atas batas ditolak', () => {
    expect(validateAdjustmentForm({ ...VALID_FORM, qtyDelta: '0' }).qtyDelta).toContain(
      'tidak boleh 0',
    );
    expect(validateAdjustmentForm({ ...VALID_FORM, qtyDelta: 'banyak' }).qtyDelta).toContain(
      'angka',
    );
    expect(
      validateAdjustmentForm({ ...VALID_FORM, qtyDelta: String(MAX_QTY_DELTA + 1) }).qtyDelta,
    ).toContain('maksimal');
  });

  it('alasan wajib & dibatasi panjangnya', () => {
    expect(validateAdjustmentForm({ ...VALID_FORM, reason: '   ' }).reason).toContain('wajib');
    expect(validateAdjustmentForm({ ...VALID_FORM, reason: 'x'.repeat(501) }).reason).toContain(
      'maksimal',
    );
  });

  it('parseQtyDelta menerima koma desimal & menolak teks', () => {
    expect(parseQtyDelta('2,5')).toBe(2.5);
    expect(parseQtyDelta('-3.5')).toBe(-3.5);
    expect(parseQtyDelta('')).toBeNull();
    expect(parseQtyDelta('abc')).toBeNull();
  });

  it('adjustmentCreateInputFromForm memformat 2 desimal + trim alasan', () => {
    expect(adjustmentCreateInputFromForm({ ...VALID_FORM, qtyDelta: '-3.5', reason: ' oke ' })).toEqual(
      {
        product_id: 89,
        location_id: 8,
        qty_delta: '-3.50',
        reason: 'oke',
      },
    );
  });

  it('signedDelta & qtyLabel siap tampil', () => {
    expect(signedDelta('5.00')).toBe('+5.00');
    expect(signedDelta('-2.50')).toBe('-2.50');
    expect(qtyLabel(null)).toBe('—');
    expect(qtyLabel('60.00')).toBe('60.00');
    expect(stockQtyLabel(null)).toContain('tidak terbaca');
    expect(stockQtyLabel('60.00')).toBe('60.00');
  });

  it('label/kompitibilitas state', () => {
    expect(adjustmentStateLabel('DRAFT')).toContain('Draft');
    expect(adjustmentStateLabel('ANEh')).toBe('ANEh');
    expect(isAdjustmentCommittable('DRAFT')).toBe(true);
    expect(isAdjustmentCommittable('SYNCED')).toBe(false);
    expect(adjustmentChipStatus('SYNCED')).toBe('on_track');
    expect(adjustmentChipStatus('FAILED')).toBe('delay');
    expect(adjustmentChipStatus('DRAFT')).toBe('neutral');
  });

  it('adjustmentRowLabel memakai kode/produk/lokasi', () => {
    expect(adjustmentRowLabel(ROW)).toBe('ADJ-2026-0001 — KAIN-COTTON @ WH/STOK');
    expect(
      adjustmentRowLabel({ ...ROW, product_code: null, location_code: null, product_name: null }),
    ).toContain('#89');
  });
});

describe('H2.5 — halaman Inventory Adjustment (render + sumber)', () => {
  it('halaman list merender judul + tombol Buat Adjustment (data di-seed)', () => {
    const { text, html } = renderPage(
      createElement(InventoryAdjustmentListPage),
      '/inventory/adjustments',
      seedListQueries,
    );

    expect(text).toContain('Inventory Adjustment');
    expect(text).toContain('Buat Adjustment');
    expect(text).toContain('ADJ-2026-0001');
    expect(text).toContain('+5.00');
    expect(html).toContain('/inventory/adjust');
  });

  it('halaman form merender field + tombol pratinjau stok & dua tombol simpan', () => {
    const { text } = renderPage(
      createElement(InventoryAdjustmentFormPage),
      '/inventory/adjust',
      seedFormQueries,
    );

    expect(text).toContain('Buat Inventory Adjustment');
    expect(text).toContain('Pratinjau stok Odoo');
    expect(text).toContain('Simpan Draft');
    expect(text).toContain('Kirim ke Odoo');
    expect(text).toContain('Inventory / Manager');
  });

  it('halaman detail menolak id tidak valid', () => {
    const { text } = renderPage(
      createElement(InventoryAdjustmentDetailPage),
      '/inventory/adjustments/abc',
    );

    expect(text).toContain('Id adjustment tidak valid');
  });

  it('route & guard H2.5 terdaftar di App.tsx (INVENTORY_ROLES)', () => {
    expect(APP).toContain('path="/inventory/adjustments"');
    expect(APP).toContain('path="/inventory/adjust"');
    expect(APP).toContain('path="/inventory/adjustments/:id"');
    expect(APP).toContain('InventoryAdjustmentListPage');
    expect(APP).toContain('InventoryAdjustmentFormPage');
    expect(APP).toContain('InventoryAdjustmentDetailPage');
    expect(APP).toContain("const INVENTORY_ROLES: Role[] = ['inventory', 'admin', 'owner'];");
  });

  it('menu Inventory menambah entri Adjustment (nav-config)', () => {
    expect(NAV).toContain("{ label: 'Adjustment', path: '/inventory/adjustments' }");
  });
});
