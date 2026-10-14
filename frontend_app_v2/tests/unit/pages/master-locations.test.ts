import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS, legacyAppIdForPath } from '@/app/nav-config';
import { LocationDetailPage } from '@/pages/master/LocationDetailPage';
import { LocationFormPage } from '@/pages/master/LocationFormPage';
import { LocationsPage } from '@/pages/master/LocationsPage';
import {
  EMPTY_LOCATION_FORM,
  isLocationFormValid,
  isLocationUsage,
  LOCATION_USAGE_OPTIONS,
  locationDetailItems,
  locationFormFromRow,
  locationInputFromForm,
  locationOptionLabel,
  MAX_CODE_LENGTH,
  selectableParentOptions,
  toNullableId,
  validateLocationForm,
  type LocationFormValues,
} from '@/lib/master-location';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { MasterLocationRow } from '@/types/master-location';

/**
 * H1.4 — halaman master lokasi (`/master/locations*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (pohon dibangun `createElement` agar
 *      file tetap `.ts`), dibungkus `QueryClientProvider` + `MemoryRouter` +
 *      konteks runtime palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, validasi form
 *      (`lib/master-location.ts`), dropdown `usage` 7 nilai Odoo, dan opsi induk.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');
const LIST_PAGE = 'src/pages/master/LocationsPage.tsx';
const FORM_PAGE = 'src/pages/master/LocationFormPage.tsx';
const DETAIL_PAGE = 'src/pages/master/LocationDetailPage.tsx';

/** Konteks feedback palsu — `useFeedback()` di halaman form butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
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
        createElement(Routes, null, createElement(Route, { path: routePath, element })),
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

const VALID_FORM: LocationFormValues = {
  code: 'WH/STOCK',
  name: 'Stok',
  usage: 'internal',
  parent_id: '3',
  warehouse_id: '1',
  active: true,
};

const ROW: MasterLocationRow = {
  id: 12,
  code: 'WH/STOCK',
  name: 'Stok',
  usage: 'internal',
  parent_id: 3,
  parent_name: 'Gudang Utama',
  warehouse_id: 1,
  warehouse_name: 'Gudang Utama',
  active: true,
  odoo_id: null,
  children_count: 2,
  complete_name: 'Gudang Utama/Stok',
};

describe('H1.4 — route & guard (App.tsx)', () => {
  it('4 route master lokasi terdaftar dengan guard INVENTORY_ROLES', () => {
    for (const routePath of [
      '/master/locations',
      '/master/locations/new',
      '/master/locations/:id',
      '/master/locations/:id/edit',
    ]) {
      expect(APP, routePath).toContain(`path="${routePath}"`);
    }

    expect(APP).toContain('<MasterLocationsPage />');
    expect(APP).toContain('<MasterLocationFormPage />');
    expect(APP).toContain('<MasterLocationDetailPage />');
    expect(APP).toMatch(/path="\/master\/locations"[\s\S]{0,220}INVENTORY_ROLES/);
  });

  it('path `/master/locations*` dipetakan ke app inventory (nav-config alias)', () => {
    expect(NAV).toContain("{ prefix: '/master/locations', appId: 'inventory' }");
    expect(legacyAppIdForPath('/master/locations')).toBe('inventory');
    expect(legacyAppIdForPath('/master/locations/12/edit')).toBe('inventory');
  });

  it('menu Inventory punya item Master Lokasi (link biasa, bukan dropdown)', () => {
    const inventory = NAV_APPS.find((app) => app.id === 'inventory');
    const item = inventory?.topbar.find((menu) => menu.label === 'Master Lokasi');

    expect(item?.path).toBe('/master/locations');
    expect(item?.children).toBeUndefined();
  });
});

describe('H1.4 — render halaman (react-dom/server)', () => {
  it('halaman list: judul, kolom (incl. Induk/Gudang/Anak), filter status+jenis, CTA', () => {
    const { html, text } = renderPage(createElement(LocationsPage), '/master/locations');

    expect(text).toContain('Master Lokasi');
    expect(text).toContain('Lokasi Baru');
    for (const label of ['Kode', 'Nama', 'Jenis', 'Induk', 'Gudang', 'Anak', 'Status', 'Odoo ID']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Semua');
    expect(text).toContain('Nonaktif');
    expect(text).toContain('Semua jenis');
    expect(text).toContain('Export CSV');
    expect(html).toContain('aria-busy');
  });

  it('halaman form (baru): 6 field + dropdown jenis 7 opsi + submit', () => {
    const { html, text } = renderPage(createElement(LocationFormPage), '/master/locations/new');

    expect(text).toContain('Lokasi Baru');
    for (const label of ['Kode *', 'Nama *', 'Jenis', 'Induk', 'Gudang']) {
      expect(text, label).toContain(label);
    }
    expect(text).toContain('Lokasi aktif');
    expect(text).toContain('Simpan Lokasi');
    // opsi dropdown = selection Odoo (probe fields_get), termasuk label Indonesia
    expect(text).toContain('Internal (stok nyata)');
    expect(text).toContain('Vendor (sumber barang masuk)');
    // label induk/gudang kosong = `null` di backend
    expect(text).toContain('Tanpa induk (lokasi akar)');
    expect(text).toContain('Tanpa gudang (lokasi global)');
    expect(html).toContain('type="submit"');
  });

  it('halaman form (edit): mode edit + breadcrumb Edit', () => {
    const { text } = renderPage(
      createElement(LocationFormPage),
      '/master/locations/12/edit',
      '/master/locations/:id/edit',
    );

    expect(text).toContain('Edit Lokasi');
    expect(text).toContain('Simpan Perubahan');
  });

  it('halaman detail: tombol Edit ada, tombol Sync DISABLED + tooltip H2', () => {
    const { html, text } = renderPage(createElement(LocationDetailPage), '/master/locations/12');

    expect(text).toContain('Detail Lokasi');
    expect(text).toContain('Edit');
    expect(text).toContain('Sync ke Odoo');
    expect(html).toContain('disabled');
    expect(html).toContain('Sync manual tersedia di H2');
  });
});

describe('H1.4 — sumber halaman (wiring API)', () => {
  it('list: adapter real, filter server (search/active/usage), tabel dense, klik → detail', () => {
    const page = read(LIST_PAGE);

    expect(page).toContain("from '@/api/masterLocations'");
    expect(page).toContain('fetchLocations(client, {');
    expect(page).toContain('LOCATIONS_LIMIT_MAX');
    expect(page).toContain("queryKey: ['master-locations'");
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).not.toContain('<table');
    expect(page).toContain("navigate(`/master/locations/${String(row.id)}`)");
  });

  it('form: create & update lewat adapter + validasi pure + dropdown induk/gudang', () => {
    const page = read(FORM_PAGE);

    expect(page).toContain('createLocation(client, input)');
    expect(page).toContain('updateLocation(client, locationId, input)');
    expect(page).toContain('validateLocationForm(values)');
    expect(page).toContain('locationInputFromForm(values)');
    expect(page).toContain('LOCATION_USAGE_OPTIONS');
    expect(page).toContain('selectableParentOptions(rows, locationId)');
    expect(page).toContain('fetchWarehouses(client, {');
    expect(page).toContain('onSubmit={handleSubmit}');
    expect(page).not.toMatch(/\bfetch\(/);
  });

  it('detail: read-only + Sync placeholder H2 + anak dimuat lewat filter parent_id', () => {
    const page = read(DETAIL_PAGE);

    expect(page).toContain('fetchLocation(client, locationId ?? 0)');
    expect(page).toContain('fetchLocations(client, { parent_id: locationId');
    expect(page).toContain('Tooltip content="Sync manual tersedia di H2');
    expect(page).toContain('/master/locations/${String(locationId)}/edit');
    expect(page).not.toContain('useMutation');
    expect(page).not.toContain('deleteLocation');
  });
});

describe('H1.4 — submit form: valid & wajib', () => {
  it('form valid → tanpa error (siap dikirim ke POST/PUT)', () => {
    const errors = validateLocationForm(VALID_FORM);

    expect(errors).toEqual({});
    expect(isLocationFormValid(errors)).toBe(true);
    expect(locationInputFromForm(VALID_FORM)).toEqual({
      code: 'WH/STOCK',
      name: 'Stok',
      usage: 'internal',
      parent_id: 3,
      warehouse_id: 1,
      active: true,
    });
  });

  it('form code KOSONG → error "wajib diisi" & TIDAK valid (tidak dikirim)', () => {
    const errors = validateLocationForm({ ...VALID_FORM, code: '   ' });

    expect(errors.code).toBe('Kode lokasi wajib diisi.');
    expect(isLocationFormValid(errors)).toBe(false);
  });

  it('validasi: nama kosong, code terlalu panjang, id induk/gudang ngawur', () => {
    expect(validateLocationForm({ ...VALID_FORM, name: ' ' }).name).toBe('Nama lokasi wajib diisi.');
    expect(validateLocationForm({ ...VALID_FORM, code: 'X'.repeat(MAX_CODE_LENGTH + 1) }).code).toBe(
      `Kode maksimal ${String(MAX_CODE_LENGTH)} karakter.`,
    );
    expect(validateLocationForm({ ...VALID_FORM, parent_id: 'abc' }).parent_id).toBe(
      'Induk tidak valid.',
    );
    expect(validateLocationForm({ ...VALID_FORM, warehouse_id: '0' }).warehouse_id).toBe(
      'Gudang tidak valid.',
    );
    expect(
      validateLocationForm({ ...VALID_FORM, usage: 'melayang' as LocationFormValues['usage'] })
        .usage,
    ).toBe('Jenis lokasi tidak dikenal.');
  });

  it('form awal (EMPTY_LOCATION_FORM) tidak valid: code & name kosong', () => {
    expect(Object.keys(validateLocationForm(EMPTY_LOCATION_FORM)).sort()).toEqual(['code', 'name']);
  });

  it('edit: locationFormFromRow ↔ locationInputFromForm konsisten (null = akar/gudang kosong)', () => {
    expect(locationFormFromRow(ROW)).toEqual(VALID_FORM);
    expect(locationInputFromForm(locationFormFromRow(ROW))).toEqual(
      locationInputFromForm(VALID_FORM),
    );

    const root = locationFormFromRow({ ...ROW, parent_id: null, warehouse_id: null });
    expect(root.parent_id).toBe('');
    expect(locationInputFromForm(root)).toEqual({
      code: 'WH/STOCK',
      name: 'Stok',
      usage: 'internal',
      parent_id: null,
      warehouse_id: null,
      active: true,
    });
    expect('odoo_id' in locationInputFromForm(VALID_FORM)).toBe(false);
  });

  it('toNullableId: hanya id bulat positif, selain itu `null`', () => {
    expect(toNullableId('12')).toBe(12);
    expect(toNullableId('')).toBeNull();
    expect(toNullableId('   ')).toBeNull();
    expect(toNullableId('0')).toBeNull();
    expect(toNullableId('-3')).toBeNull();
    expect(toNullableId('1.5')).toBeNull();
    expect(toNullableId('abc')).toBeNull();
  });
});

describe('H1.4 — helper tampilan (lib)', () => {
  it('type guard dropdown hanya menerima 7 nilai selection Odoo', () => {
    expect(LOCATION_USAGE_OPTIONS.map((option) => option.value)).toEqual([
      'view',
      'internal',
      'supplier',
      'customer',
      'inventory',
      'production',
      'transit',
    ]);

    expect(isLocationUsage('internal')).toBe(true);
    expect(isLocationUsage('transit')).toBe(true);
    expect(isLocationUsage('melayang')).toBe(false);
  });

  it('selectableParentOptions: buang diri sendiri & lokasi nonaktif', () => {
    const rows = [
      ROW,
      { ...ROW, id: 3, code: 'WH', name: 'Gudang Utama' },
      { ...ROW, id: 9, code: 'WH/OLD', name: 'Lama', active: false },
    ];

    expect(selectableParentOptions(rows, ROW.id).map((row) => row.id)).toEqual([3]);
    expect(selectableParentOptions(rows, null).map((row) => row.id)).toEqual([12, 3]);
  });

  it('locationOptionLabel: KODE - nama (fallback kalau salah satu kosong)', () => {
    expect(locationOptionLabel(ROW)).toBe('WH/STOCK - Stok');
    expect(locationOptionLabel({ ...ROW, code: '' })).toBe('Stok');
    expect(locationOptionLabel({ ...ROW, name: ' ' })).toBe('WH/STOCK');
  });

  it('locationDetailItems: label manusiawi + complete_name + odoo_id null → "belum dikirim"', () => {
    const items = locationDetailItems(ROW);

    expect(items.find((item) => item.label === 'Jenis')?.value).toBe('Internal (stok nyata)');
    expect(items.find((item) => item.label === 'Nama Lengkap')?.value).toBe('Gudang Utama/Stok');
    expect(items.find((item) => item.label === 'Induk')?.value).toBe('Gudang Utama');
    expect(items.find((item) => item.label === 'Anak Langsung')?.value).toBe('2');
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(
      locationDetailItems({ ...ROW, odoo_id: 43 }).find((item) => item.label === 'Odoo ID')?.value,
    ).toBe('43');
  });

  it('locationDetailItems: relasi kosong ditampilkan "-" (bukan "null")', () => {
    const items = locationDetailItems({
      ...ROW,
      parent_name: null,
      warehouse_name: null,
      complete_name: '',
    });

    expect(items.find((item) => item.label === 'Induk')?.value).toBe('-');
    expect(items.find((item) => item.label === 'Gudang')?.value).toBe('-');
    expect(items.find((item) => item.label === 'Nama Lengkap')?.value).toBe('-');
  });
});

