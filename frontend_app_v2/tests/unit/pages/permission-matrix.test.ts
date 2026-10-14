import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { PermissionMatrixPage } from '@/pages/settings/PermissionMatrixPage';
import {
  actionLabel,
  defaultRoleId,
  diffUpdates,
  emptyCell,
  readCell,
  readDivergenceCell,
  resourceLabel,
  roleDraft,
  roleOptions,
  roleSummary,
  toggleCell,
} from '@/lib/permission-matrix';
import {
  type PermissionEnvelope,
  type PermissionRole,
} from '@/types/permission-matrix';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.4 — halaman `/settings/permissions` (Permission Matrix, Opsi A′).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` (tanpa data ⇒ banner wajib tetap
 *      tampil, karena halaman merender fallback banner lebih dulu);
 *   2. SUMBER/pure: route + guard di `App.tsx`, nav Settings (landing tetap
 *      `/settings/routing`, Permissions = terakhir), label, draft/diff sel, dan ringkasan.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

/** Konteks feedback palsu — `useFeedback()` di halaman butuh provider (pola H5.6/H5.8). */
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
  const html = htmlOf(tree);

  return { html, text: textOf(html) };
}

const ROLES: PermissionRole[] = [
  { id: 4, code: 'ADMIN', label: 'Administrator', is_active: true },
  { id: 1, code: 'OPERATOR', label: 'Operator', is_active: true },
];

const RESOURCES = ['bundles', 'settings'];
const ACTIONS = ['read', 'create', 'update', 'delete'];

const ENVELOPE: PermissionEnvelope = {
  matrix: {
    '4': { settings: { read: true, create: false, update: false, delete: false } },
    '1': { bundles: { read: true, create: false, update: false, delete: false } },
  },
  effective: {
    '4': { settings: { read: true, create: true, update: true, delete: true } },
    '1': { bundles: { read: true, create: false, update: true, delete: false } },
  },
  diverges: {
    '1': { bundles: { update: { profile: false, effective: true } } },
    '4': { settings: { create: { profile: false, effective: true } } },
  },
  resources: RESOURCES,
  actions: ACTIONS,
  roles: ROLES,
  banner: '⚠️ Perubahan di halaman ini disimpan sebagai PROFIL …',
};

describe('H5.4 — route, guard & nav', () => {
  it('App.tsx: /settings/permissions dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/permissions"');
    expect(APP).toContain('<PermissionMatrixPage />');
    expect(APP).toContain("import('@/pages/settings/PermissionMatrixPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah "Permissions" (TERAKHIR) + landing tetap Routing', () => {
    expect(NAV).toContain("label: 'Permissions', path: '/settings/permissions'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');
    const paths = settings?.topbar.map((item) => item.path) ?? [];

    expect(paths).toContain('/settings/permissions');
    // route-fix: landing app Settings tetap item topbar PERTAMA
    expect(settings?.topbar[0]?.path).toBe('/settings/routing');
    // H5.4 dipasang SETELAH Printer (H5.7) — relatif, tahan perubahan urutan
    expect(paths.indexOf('/settings/permissions')).toBeGreaterThan(
      paths.indexOf('/settings/printers'),
    );
    // F9 (audit produk) tetap ada
    expect(paths).toContain('/settings/audit');
  });
});

describe('H5.4 — render halaman (react-dom/server)', () => {
  it('PermissionMatrixPage render header + banner wajib (profil ≠ enforcement)', () => {
    const { text } = renderPage(
      createElement(PermissionMatrixPage),
      '/settings/permissions',
    );

    expect(text).toContain('Permissions');
    expect(text).toContain('Muat Ulang');
    // banner WAJIB tampil (fallback dipakai sebelum data backend tiba)
    expect(text).toContain('PROFIL');
    expect(text).toContain('Enforcement belum berubah');
    expect(text).toContain('Memuat matrix izin');
  });

  it('PermissionMatrixPage sumber: GET/PUT + diff + tabel + label efektif', () => {
    const page = read('src/pages/settings/PermissionMatrixPage.tsx');

    expect(page).toContain('fetchPermissionMatrix');
    expect(page).toContain('updateRolePermissions');
    expect(page).toContain('diffUpdates');
    expect(page).toContain('toggleCell');
    expect(page).toContain('roleSummary');
    expect(page).toContain('readDivergenceCell');
    expect(page).toContain('PERMISSION_BANNER_FALLBACK');
    expect(page).toContain('TABLE_HEAD');
    expect(page).toContain('Checkbox');
    expect(page).toContain('Simpan Profil');
  });
});

describe('H5.4 — lib matrix (PURE)', () => {
  it('roleOptions / defaultRoleId / label aksi & resource', () => {
    expect(roleOptions(ROLES)).toEqual([
      { value: '4', label: 'ADMIN — Administrator' },
      { value: '1', label: 'OPERATOR — Operator' },
    ]);
    expect(roleOptions([])).toEqual([]);

    expect(defaultRoleId(ROLES)).toBe(4);
    expect(defaultRoleId([])).toBeNull();

    expect(actionLabel('read')).toBe('Lihat');
    expect(actionLabel(' CREATE ')).toBe('Tambah');
    expect(actionLabel('print')).toBe('print');

    expect(resourceLabel('work-orders')).toBe('Work Order');
    expect(resourceLabel('settings')).toBe('Pengaturan');
    expect(resourceLabel('aneh')).toBe('aneh');
  });

  it('emptyCell / roleDraft / readCell / readDivergenceCell / toggleCell', () => {
    const kosong = emptyCell(RESOURCES, ACTIONS);

    expect(Object.keys(kosong)).toEqual(RESOURCES);
    expect(kosong['bundles']['delete']).toBe(false);

    const draft = roleDraft(ENVELOPE.matrix, 4, RESOURCES, ACTIONS);

    expect(draft['settings']['read']).toBe(true);
    expect(draft['settings']['delete']).toBe(false);
    // resource yang belum pernah disimpan tetap ada (false)
    expect(draft['bundles']['read']).toBe(false);

    // role tanpa baris → semua false (tidak error)
    expect(roleDraft({}, 99, RESOURCES, ACTIONS)['bundles']['read']).toBe(false);

    expect(readCell(ENVELOPE.matrix, 4, 'settings', 'read')).toBe(true);
    expect(readCell(ENVELOPE.matrix, 4, 'settings', 'delete')).toBe(false);
    expect(readCell({}, 4, 'settings', 'read')).toBe(false);

    expect(
      readDivergenceCell(ENVELOPE.diverges, 1, 'bundles', 'update'),
    ).toEqual({ profile: false, effective: true });
    expect(readDivergenceCell(ENVELOPE.diverges, 1, 'bundles', 'read')).toBeNull();

    const toggled = toggleCell(draft, 'bundles', 'read', true);

    expect(toggled['bundles']['read']).toBe(true);
    expect(toggled['settings']['read']).toBe(true);
    // immutable: draft lama tidak berubah
    expect(draft['bundles']['read']).toBe(false);
  });

  it('diffUpdates hanya mengirim sel yang berubah', () => {
    const baseline = roleDraft(ENVELOPE.matrix, 4, RESOURCES, ACTIONS);

    expect(diffUpdates(baseline, baseline, RESOURCES, ACTIONS)).toEqual([]);

    const draft = toggleCell(toggleCell(baseline, 'settings', 'delete', true), 'bundles', 'read', true);
    const updates = diffUpdates(baseline, draft, RESOURCES, ACTIONS);

    expect(updates).toEqual([
      { resource: 'bundles', action: 'read', allowed: true },
      { resource: 'settings', action: 'delete', allowed: true },
    ]);

    // kembali ke nilai awal → tidak ada update lagi
    const balik = toggleCell(toggleCell(draft, 'settings', 'delete', false), 'bundles', 'read', false);

    expect(diffUpdates(baseline, balik, RESOURCES, ACTIONS)).toEqual([]);
  });

  it('roleSummary: jumlah sel profil/efektif + beda', () => {
    const summary = roleSummary(ENVELOPE, 4);

    expect(summary.stored).toBe(1); // settings.read
    expect(summary.effective).toBe(4); // settings: read/create/update/delete
    expect(summary.divergent).toBe(1); // fixture: settings.create saja yang beda
    expect(summary.resources).toBe(2);
    expect(summary.divergingResources).toEqual(['settings']);

    // role lain: bundles.update (1 sel berbeda) di resource bundles
    const operator = roleSummary(ENVELOPE, 1);

    expect(operator.stored).toBe(1); // bundles.read
    expect(operator.effective).toBe(2); // bundles: read + update
    expect(operator.divergent).toBe(1);
    expect(operator.divergingResources).toEqual(['bundles']);

    // role tanpa data → semua nol
    const kosong = roleSummary(
      { ...ENVELOPE, matrix: {}, effective: {}, diverges: {} },
      99,
    );

    expect(kosong.stored).toBe(0);
    expect(kosong.effective).toBe(0);
    expect(kosong.divergent).toBe(0);
    expect(kosong.divergingResources).toEqual([]);
  });
});

