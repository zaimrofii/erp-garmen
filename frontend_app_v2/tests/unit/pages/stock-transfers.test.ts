import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { StockTransferDetailPage } from '@/pages/inventory/StockTransferDetailPage';
import { StockTransferFormPage } from '@/pages/inventory/StockTransferFormPage';
import { StockTransferListPage } from '@/pages/inventory/StockTransferListPage';
import {
  EMPTY_TRANSFER_FORM,
  isTransferCommittable,
  isTransferFormValid,
  MAX_TRANSFER_QTY,
  parseTransferQty,
  transferChipStatus,
  transferCreateInputFromForm,
  transferQtyLabel,
  transferRouteLabel,
  transferStateLabel,
  validateTransferForm,
  type TransferFormValues,
} from '@/lib/stock-transfer';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { StockTransferRow } from '@/types/stock-transfer';

/**
 * H2.6 — halaman Stock Transfer (`/inventory/transfer|transfers/:id`).
 *
 * Dua lapis (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` + `QueryClientProvider`/`MemoryRouter`;
 *   2. SUMBER/pure: route + guard `INVENTORY_ROLES` di `App.tsx`, menu di
 *      `app/nav-config.ts`, dan validasi form (termasuk `from != to`) di `lib/stock-transfer.ts`.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

function renderPage(
  element: ReactElement,
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

const VALID_FORM: TransferFormValues = {
  productId: '89',
  fromLocationId: '8',
  toLocationId: '50',
  qty: '5',
  reason: 'Pindah lini',
};

const ROW: StockTransferRow = {
  id: 4,
  code: 'TRF-2026-0001',
  product_id: 89,
  product_code: 'KAIN-COTTON',
  product_name: 'Kain Cotton',
  from_location_id: 8,
  from_location_code: 'WH/STOK',
  from_location_name: 'Stok',
  to_location_id: 50,
  to_location_code: 'WH/PROD',
  to_location_name: 'Produksi',
  qty: '5.00',
  qty_before: '60.00',
  reason: 'Pindah lini',
  state: 'DRAFT',
  odoo_picking_id: null,
  odoo_picking_name: '',
  last_error: '',
  created_by: 'sim-h26',
  created_at: null,
  updated_at: null,
};

/** Isi cache react-query supaya halaman merender cabang DATA (SSR sekali jalan). */
function seedQueries(client: QueryClient): void {
  client.setQueryData(['stock-transfers', '', '', '', '', '', 0], {
    rows: [ROW],
    total_count: 1,
    has_more: false,
    next_cursor: null,
  });
  client.setQueryData(['master-products', 'stock-transfer-options'], {
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
  client.setQueryData(['master-products', 'stock-transfer-form'], {
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
  for (const key of ['stock-transfer-options', 'stock-transfer-form']) {
    client.setQueryData(['master-locations', key], {
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
        {
          id: 50,
          code: 'WH/PROD',
          name: 'Produksi',
          usage: 'internal',
          parent_id: null,
          parent_name: null,
          warehouse_id: null,
          warehouse_name: null,
          active: true,
          odoo_id: 50,
          children_count: 0,
          complete_name: 'WH/Production',
        },
      ],
      total_count: 2,
      has_more: false,
      next_cursor: null,
    });
  }
}

describe('H2.6 — lib PURE Stock Transfer', () => {
  it('form kosong: semua field wajib dilaporkan', () => {
    const errors = validateTransferForm(EMPTY_TRANSFER_FORM);

    expect(errors.productId).toBeDefined();
    expect(errors.fromLocationId).toBeDefined();
    expect(errors.toLocationId).toBeDefined();
    expect(errors.qty).toBeDefined();
    expect(isTransferFormValid(errors)).toBe(false);
  });

  it('form valid lolos', () => {
    const errors = validateTransferForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isTransferFormValid(errors)).toBe(true);
  });

  it('lokasi asal == tujuan ditolak (client-side, selaras backend)', () => {
    const errors = validateTransferForm({ ...VALID_FORM, toLocationId: '8' });

    expect(errors.toLocationId).toContain('BEDA');
    expect(isTransferFormValid(errors)).toBe(false);
  });

  it('qty 0 / bukan angka / di atas batas ditolak', () => {
    expect(validateTransferForm({ ...VALID_FORM, qty: '0' }).qty).toContain('lebih besar dari 0');
    expect(validateTransferForm({ ...VALID_FORM, qty: '-' }).qty).toContain('angka');
    expect(validateTransferForm({ ...VALID_FORM, qty: String(MAX_TRANSFER_QTY + 1) }).qty).toContain(
      'maksimal',
    );
  });

  it('catatan opsional tapi dibatasi panjangnya', () => {
    expect(validateTransferForm({ ...VALID_FORM, reason: '' }).reason).toBeUndefined();
    expect(validateTransferForm({ ...VALID_FORM, reason: 'x'.repeat(501) }).reason).toContain(
      'maksimal',
    );
  });

  it('parseTransferQty menerima koma desimal & menolak teks', () => {
    expect(parseTransferQty('2,5')).toBe(2.5);
    expect(parseTransferQty('12')).toBe(12);
    expect(parseTransferQty('')).toBeNull();
    expect(parseTransferQty('abc')).toBeNull();
  });

  it('transferCreateInputFromForm memformat 2 desimal + trim catatan', () => {
    expect(
      transferCreateInputFromForm({ ...VALID_FORM, qty: '5', reason: ' oke ' }),
    ).toEqual({
      product_id: 89,
      from_location_id: 8,
      to_location_id: 50,
      qty: '5.00',
      reason: 'oke',
    });
  });

  it('label & status siap tampil', () => {
    expect(transferStateLabel('DRAFT')).toContain('Draft');
    expect(transferStateLabel('ANEh')).toBe('ANEh');
    expect(isTransferCommittable('DRAFT')).toBe(true);
    expect(isTransferCommittable('SYNCED')).toBe(false);
    expect(transferChipStatus('SYNCED')).toBe('on_track');
    expect(transferChipStatus('FAILED')).toBe('delay');
    expect(transferChipStatus('COMMITTED')).toBe('neutral');
    expect(transferQtyLabel(null)).toBe('—');
    expect(transferQtyLabel('5.00')).toBe('5.00');
  });

  it('transferRouteLabel memakai kode lokasi', () => {
    expect(transferRouteLabel(ROW)).toBe('WH/STOK → WH/PROD');
    // Fallback berlapis: kode → nama → `#id`.
    expect(
      transferRouteLabel({ ...ROW, from_location_code: null, to_location_code: null }),
    ).toBe('Stok → Produksi');
    expect(
      transferRouteLabel({
        ...ROW,
        from_location_code: null,
        from_location_name: null,
        to_location_code: null,
        to_location_name: null,
      }),
    ).toContain('#8');
  });
});

describe('H2.6 — halaman Stock Transfer (render + sumber)', () => {
  it('halaman list merender judul + tombol Buat Transfer (data di-seed)', () => {
    const { text, html } = renderPage(
      createElement(StockTransferListPage),
      '/inventory/transfers',
      seedQueries,
    );

    expect(text).toContain('Stock Transfer');
    expect(text).toContain('Buat Transfer');
    expect(text).toContain('TRF-2026-0001');
    expect(text).toContain('WH/STOK → WH/PROD');
    expect(html).toContain('/inventory/transfer');
  });

  it('halaman form merender field rute + tombol pratinjau & dua tombol simpan', () => {
    const { text } = renderPage(
      createElement(StockTransferFormPage),
      '/inventory/transfer',
      seedQueries,
    );

    expect(text).toContain('Buat Stock Transfer');
    expect(text).toContain('Pratinjau stok Odoo (asal)');
    expect(text).toContain('Simpan Draft');
    expect(text).toContain('Kirim ke Odoo');
    expect(text).toContain('Lokasi tujuan');
  });

  it('halaman detail menolak id tidak valid', () => {
    const { text } = renderPage(
      createElement(StockTransferDetailPage),
      '/inventory/transfers/abc',
    );

    expect(text).toContain('Id transfer tidak valid');
  });

  it('route & guard H2.6 terdaftar di App.tsx (INVENTORY_ROLES)', () => {
    expect(APP).toContain('path="/inventory/transfers"');
    expect(APP).toContain('path="/inventory/transfer"');
    expect(APP).toContain('path="/inventory/transfers/:id"');
    expect(APP).toContain('StockTransferListPage');
    expect(APP).toContain('StockTransferFormPage');
    expect(APP).toContain('StockTransferDetailPage');
    expect(APP).toContain("const INVENTORY_ROLES: Role[] = ['inventory', 'admin', 'owner'];");
  });

  it('menu Inventory menambah entri Transfer (nav-config)', () => {
    expect(NAV).toContain("{ label: 'Transfer', path: '/inventory/transfers' }");
  });
});

