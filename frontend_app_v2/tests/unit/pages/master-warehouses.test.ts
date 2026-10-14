import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { WarehouseDetailPage } from '@/pages/master/WarehouseDetailPage';
import { WarehouseFormPage } from '@/pages/master/WarehouseFormPage';
import { WarehousesPage } from '@/pages/master/WarehousesPage';
import {
  DELIVERY_STEP_OPTIONS,
  EMPTY_WAREHOUSE_FORM,
  isDeliverySteps,
  isReceptionSteps,
  isWarehouseFormValid,
  ODOO_CODE_MAX_LENGTH,
  RECEPTION_STEP_OPTIONS,
  validateWarehouseForm,
  warehouseDetailItems,
  warehouseFormFromRow,
  warehouseInputFromForm,
  warehouseOptionLabel,
  type WarehouseFormValues,
} from '@/lib/master-warehouse';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterWarehouseRow } from '@/types/master-warehouse';

/**
 * H1.3 — halaman master gudang (`/master/warehouses*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon dibangun `createElement` agar
 *      file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter` +
 *      konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form
 *      (`lib/master-warehouse.ts`) termasuk "submit code kosong", dan dropdown steps.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/master/WarehousesPage.tsx';
const FORM_PAGE = 'src/pages/master/WarehouseFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/WarehouseDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
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

const VALID_FORM: WarehouseFormValues = {
  code: 'WH',
  name: 'Gudang Utama',
  reception_steps: 'one_step',
  delivery_steps: 'ship_only',
  active: true,
};

const ROW: MasterWarehouseRow = {
  id: 3,
  code: 'WH',
  name: 'Gudang Utama',
  reception_steps: 'one_step',
  delivery_steps: 'ship_only',
  active: true,
  odoo_id: null,
};

describe('H1.3 — route & guard (App.tsx)', () => {
  it('4 route master gudang terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/warehouses',
      '/master/warehouses/new',
      '/master/warehouses/:id',
      '/master/warehouses/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterWarehousesPage />');
    expect(APP).toContain('<MasterWarehouseFormPage />');
    expect(APP).toContain('<MasterWarehouseDetailPage />');
    expect(APP).toMatch(/path="\/master\/warehouses"[\s\S]{0,220}INVENTORY_ROLES/);
  });

  it('path `/master/warehouses*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ prefix: '/master/warehouses', appId: 'inventory' }",
    );
  });

  it('menu Inventory punya item Master Gudang (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Gudang');

    expect(item?.path).toBe('/master/warehouses');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.3 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom, filter status, dan CTA Gudang Baru', () => {
    const { html, text } = renderPage(createElement(WarehousesPage), '/master/warehouses');

    expect(text).toContain('Master Gudang');
    expect(text).toContain('Gudang Baru');
    for (const label of ['Kode', 'Nama', 'Penerimaan', 'Pengiriman', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Nonaktif');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): 5 field + 2 dropdown langkah + tombol submit', () => {
    const { html, text } = renderPage(
      createElement(WarehouseFormPage),
      '/master/warehouses/new',
    );

    expect(text).toContain('Gudang Baru');
    for (const label of ['Kode *', 'Nama *', 'Penerimaan', 'Pengiriman']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Gudang aktif');
    expect(text).toContain('Simpan Gudang');
    // opsi dropdown = selection Odoo (probe fields_get)
    expect(text).toContain('Terima langsung ke stok (1 langkah)');
    expect(text).toContain('Kirim langsung (1 langkah)');
    expect(text).toContain(String(ODOO_CODE_MAX_LENGTH));
    expect(html).toContain('type="submit"');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html } = renderPage(createElement(WarehouseDetailPage), '/master/warehouses/3');

    expect(html).toContain('Detail Gudang');
    expect(html).toContain('Edit');
    expect(html).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

describe('H1.3 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server, tabel dense, klik baris → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterWarehouses'");
    expect(page).toContain('fetchWarehouses(client, {');
    expect(page).toContain('WAREHOUSES_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-warehouses'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/warehouses/${String(row.id)}`)");
  });

  it('form: create & update lewat adapter + validasi pure + 2 dropdown', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createWarehouse(client, input)');
    expect(page).toContain('updateWarehouse(client, warehouseId, input)');
    expect(page).toContain('validateWarehouseForm(values)');
    expect(page).toContain('warehouseInputFromForm(values)');
    expect(page).toContain('RECEPTION_STEP_OPTIONS');
    expect(page).toContain('DELIVERY_STEP_OPTIONS');
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + Sync placeholder disabled ber-tooltip H2', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchWarehouse(client, warehouseId ?? 0)');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/warehouses/${String(warehouseId)}/edit');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteWarehouse');
  });
});

describe('H1.3 — submit form: valid & wajib', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateWarehouseForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isWarehouseFormValid(errors)).toBe(true);
    expect(warehouseInputFromForm(VALID_FORM)).toEqual({
      code: 'WH',
      name: 'Gudang Utama',
      reception_steps: 'one_step',
      delivery_steps: 'ship_only',
      active: true,
    });
  });

  it('form code KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validateWarehouseForm({ ...VALID_FORM, code: '   ' });

    expect(errors.code).toBe('Kode gudang wajib diisi.');
    expect(isWarehouseFormValid(errors)).toBe(false);
  });

  it('form awal (EMPTY_WAREHOUSE_FORM) tidak valid: code & name kosong', () => {
    expect(Object.keys(validateWarehouseForm(EMPTY_WAREHOUSE_FORM)).sort()).toEqual([
      'code',
      'name',
    ]);
  });

  it('edit: warehouseFormFromRow ↔ warehouseInputFromForm konsisten', () => {
    expect(warehouseFormFromRow(ROW)).toEqual(VALID_FORM);
    expect(warehouseInputFromForm(warehouseFormFromRow(ROW))).toEqual(
      warehouseInputFromForm(VALID_FORM),
    );
    expect('odoo_id' in warehouseInputFromForm(VALID_FORM)).toBe(false);
  });
});

describe('H1.3 — helper tampilan (lib)', () => {
  it('type guard dropdown hanya menerima nilai selection Odoo', () => {
    expect(isReceptionSteps('one_step')).toBe(true);
    expect(isReceptionSteps('two_steps')).toBe(true);
    expect(isReceptionSteps('four_steps')).toBe(false);

    expect(isDeliverySteps('ship_only')).toBe(true);
    expect(isDeliverySteps('pick_pack_ship')).toBe(true);
    expect(isDeliverySteps('kirim_langsung')).toBe(false);
  });

  it('opsi dropdown = 3 langkah untuk masing-masing alur Odoo', () => {
    expect(RECEPTION_STEP_OPTIONS.map((option) => option.value)).toEqual([
      'one_step',
      'two_steps',
      'three_steps',
    ]);
    expect(DELIVERY_STEP_OPTIONS.map((option) => option.value)).toEqual([
      'ship_only',
      'pick_ship',
      'pick_pack_ship',
    ]);
  });

  it('warehouseOptionLabel: KODE - nama (fallback kalau salah satu kosong)', () => {
    expect(warehouseOptionLabel(ROW)).toBe('WH - Gudang Utama');
    expect(warehouseOptionLabel({ ...ROW, code: '' })).toBe('Gudang Utama');
    expect(warehouseOptionLabel({ ...ROW, name: ' ' })).toBe('WH');
  });

  it('warehouseDetailItems: label langkah manusiawi + odoo_id null → "belum dikirim"', () => {
    const items = warehouseDetailItems(ROW);

    expect(items.find((item) => item.label === 'Penerimaan')?.value).toBe(
      'Terima langsung ke stok (1 langkah)',
    );
    expect(items.find((item) => item.label === 'Pengiriman')?.value).toBe(
      'Kirim langsung (1 langkah)',
    );
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(
      warehouseDetailItems({ ...ROW, odoo_id: 7 }).find((item) => item.label === 'Odoo ID')?.value,
    ).toBe('7');
  });
});

