import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { WAConfigPage } from '@/pages/settings/WAConfigPage';
import {
  BACKEND_VALUES,
  CONFIG_FIELD_LABELS,
  EMPTY_WA_FORM,
  WA_MASK,
  effectiveStatusRows,
  formatConfigValue,
  isMaskedApiKey,
  isWAConfigFormValid,
  validateWAConfigForm,
  waConfigFormFromRow,
  waConfigInputFromForm,
  type WAConfigFormValues,
} from '@/lib/wa-config';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.8 — halaman `/settings/wa` (WA Gateway Config, singleton, Opsi B).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings (landing tetap
 *      `/settings/routing`), validasi 3 field dan konversi form → payload PUT.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

/** Konteks feedback palsu — `useFeedback()` di halaman butuh provider. */
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

const VALID: WAConfigFormValues = {
  ...EMPTY_WA_FORM,
  wa_backend: 'real',
  wa_api_url: 'http://wa-gateway:8080',
  wa_api_key: WA_MASK,
};

describe('H5.8 — route, guard & nav', () => {
  it('App.tsx: /settings/wa dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/wa"');
    expect(APP).toContain('<WAConfigPage />');
    expect(APP).toContain("import('@/pages/settings/WAConfigPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah "WA Gateway" di app Settings TANPA mengubah item pertama', () => {
    expect(NAV).toContain("label: 'WA Gateway', path: '/settings/wa'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');

    expect(settings?.topbar.some((item) => item.path === '/settings/wa')).toBe(true);
    // route-fix: landing app Settings tetap item topbar PERTAMA
    expect(settings?.topbar[0]?.path).toBe('/settings/routing');
  });
});

describe('H5.8 — render halaman (react-dom/server)', () => {
  it('WAConfigPage render bagian gateway + status + tombol aksi', () => {
    const { text } = renderPage(createElement(WAConfigPage), '/settings/wa');

    expect(text).toContain('WA Gateway');
    expect(text).toContain('WA Gateway (backend + kredensial)');
    expect(text).toContain('Status gateway aktif (.env)');
    expect(text).toContain('Test Koneksi');
    expect(text).toContain('Simpan Profil');
    // MES-only: tidak ada aksi sync ke vendor WA
    expect(text).not.toContain('Sync ke Vendor');
  });

  it('WAConfigPage sumber: GET/PUT/test + API key masked (type=password)', () => {
    const page = read('src/pages/settings/WAConfigPage.tsx');

    expect(page).toContain('fetchWAConfig');
    expect(page).toContain('updateWAConfig');
    expect(page).toContain('testWAConnection');
    expect(page).toContain('type="password"');
    expect(page).toContain('isMaskedApiKey');
    expect(page).toContain('restart_command');
  });
});

describe('H5.8 — lib form (PURE)', () => {
  it('validateWAConfigForm: guard backend real/api + URL + panjang', () => {
    expect(validateWAConfigForm(VALID)).toEqual({});
    expect(BACKEND_VALUES).toEqual(['mock', 'real', 'api']);

    expect(validateWAConfigForm({ ...VALID, wa_backend: 'cloud-api' }).wa_backend).toContain(
      'salah satu',
    );

    // URL tanpa skema ditolak, tetapi hostname internal TANPA TLD tetap VALID
    expect(validateWAConfigForm({ ...VALID, wa_api_url: 'wa-gateway:8080' }).wa_api_url).toContain(
      'http/https',
    );
    expect(validateWAConfigForm({ ...VALID, wa_api_url: 'http://wa-gateway:8080' })).toEqual({});

    // guard: backend real/api wajib punya URL + API key
    const guard = validateWAConfigForm({ ...VALID, wa_api_url: '', wa_api_key: '' });

    expect(guard.wa_api_url).toContain('membutuhkan');
    expect(guard.wa_api_key).toContain('membutuhkan');

    // 'mock' bebas kredensial
    expect(validateWAConfigForm({ ...EMPTY_WA_FORM, wa_backend: 'mock' })).toEqual({});
    expect(isWAConfigFormValid(validateWAConfigForm(EMPTY_WA_FORM))).toBe(true);
  });

  it('formFromRow + inputFromForm + mask API key', () => {
    expect(isMaskedApiKey(WA_MASK)).toBe(true);
    expect(isMaskedApiKey('rahasia')).toBe(false);
    expect(waConfigFormFromRow(null)).toEqual(EMPTY_WA_FORM);

    const row = {
      id: 1,
      wa_backend: 'real',
      wa_api_url: 'http://wa-gateway:8080',
      wa_api_key: WA_MASK,
      is_active: false,
      created_at: '',
      updated_at: '',
    };

    const form = waConfigFormFromRow(row);

    expect(form.wa_backend).toBe('real');
    expect(form.wa_api_url).toBe('http://wa-gateway:8080');
    expect(form.active).toBe(false);

    expect(waConfigInputFromForm(form)).toEqual({
      wa_backend: 'real',
      wa_api_url: 'http://wa-gateway:8080',
      wa_api_key: WA_MASK,
      active: false,
    });

    // nilai baru / kosong pada API key diteruskan apa adanya ('' = hapus)
    expect(waConfigInputFromForm({ ...form, wa_api_key: 'kunci-baru' }).wa_api_key).toBe(
      'kunci-baru',
    );
    expect(waConfigInputFromForm({ ...form, wa_api_key: '' }).wa_api_key).toBe('');

    // backend 'MOCK ' dinormalisasi lower/trim
    expect(waConfigInputFromForm({ ...form, wa_backend: ' MOCK ' }).wa_backend).toBe('mock');
  });

  it('helper tampilan: formatConfigValue + effectiveStatusRows', () => {
    expect(formatConfigValue(null)).toBe('—');
    expect(formatConfigValue('')).toBe('—');
    expect(formatConfigValue('real')).toBe('real');
    expect(formatConfigValue(WA_MASK)).toBe(WA_MASK);

    const effective = {
      wa_backend: 'mock',
      wa_api_url: '',
      wa_api_key: WA_MASK,
    };

    const rows = effectiveStatusRows(effective);

    expect(rows.map((row) => row.field)).toEqual(Object.keys(CONFIG_FIELD_LABELS));
    expect(rows.find((row) => row.field === 'wa_backend')?.value).toBe('mock');
    expect(rows.find((row) => row.field === 'wa_api_url')?.value).toBe('—');
    expect(rows.find((row) => row.field === 'wa_api_key')?.value).toBe(WA_MASK);
  });
});

