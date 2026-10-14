import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { CurrenciesPage } from '@/pages/settings/CurrenciesPage';
import {
  CURRENCY_CODE_PATTERN,
  EMPTY_CURRENCY_FORM,
  currencyCreateInputFromForm,
  currencyFormFromRow,
  currencyRateLabel,
  currencySourceLabel,
  currencyUpdateInputFromForm,
  validateCurrencyCreateForm,
  validateCurrencyEditForm,
  type CurrencyFormValues,
} from '@/lib/master-currency';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.2 — halaman `/settings/currencies` (Currency).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings, validasi form
 *      create/edit dan konversi form → payload.
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

describe('H5.2 — route, guard & nav', () => {
  it('App.tsx: /settings/currencies dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/currencies"');
    expect(APP).toContain('<CurrenciesPage />');
    expect(APP).toContain("import('@/pages/settings/CurrenciesPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah topbar "Currencies" di app Settings', () => {
    expect(NAV).toContain("label: 'Currencies', path: '/settings/currencies'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');

    expect(settings?.topbar.some((item) => item.path === '/settings/currencies')).toBe(true);
  });
});

describe('H5.2 — render halaman (react-dom/server)', () => {
  it('CurrenciesPage render judul, kolom, tombol Buat, tanpa tombol Sync', () => {
    const { text } = renderPage(createElement(CurrenciesPage), '/settings/currencies');

    expect(text).toContain('Currencies');
    expect(text).toContain('Mata uang MES');
    expect(text).toContain('Kurs');
    expect(text).toContain('Sumber');
    expect(text).toContain('Buat Mata Uang');
    // MES-only: tidak ada aksi sync ke Odoo
    expect(text).not.toContain('Sync ke Odoo');
  });

  it('CurrenciesPage sumber: CRUD H5.2 (create + set default + hapus window.confirm)', () => {
    const page = read('src/pages/settings/CurrenciesPage.tsx');

    expect(page).toContain('createCurrency');
    expect(page).toContain('updateCurrency');
    expect(page).toContain('deleteCurrency');
    expect(page).toContain('setDefaultCurrency');
    expect(page).toContain('Buat Mata Uang');
    expect(page).toContain('window.confirm');
    expect(page).toContain('STATUS_FILTERS');
  });
});

describe('H5.2 — lib form (PURE)', () => {
  const valid: CurrencyFormValues = {
    code: 'gbp',
    name: 'Pound Sterling',
    symbol: '£',
    rate: '0.000052',
  };

  it('validateCurrencyCreateForm: kode ISO 3 huruf, nama wajib, symbol ≤8, rate ≥0', () => {
    expect(validateCurrencyCreateForm(valid)).toEqual({});
    expect(validateCurrencyCreateForm({ ...valid, code: '' }).code).toContain('wajib');
    expect(validateCurrencyCreateForm({ ...valid, code: 'GB' }).code).toContain('3 huruf');
    expect(validateCurrencyCreateForm({ ...valid, code: 'GB1' }).code).toContain('3 huruf');
    expect(validateCurrencyCreateForm({ ...valid, name: '  ' }).name).toContain('wajib');
    expect(validateCurrencyCreateForm({ ...valid, symbol: '123456789' }).symbol).toContain(
      'maksimal',
    );
    expect(validateCurrencyCreateForm({ ...valid, rate: '-1' }).rate).toContain('negatif');
    expect(validateCurrencyCreateForm({ ...valid, rate: 'abc' }).rate).toContain('angka');
    expect(validateCurrencyCreateForm({ ...valid, rate: '' })).toEqual({});
  });

  it('validateCurrencyEditForm: kode hasil pull `ODOO-12` tidak error saat tidak diubah', () => {
    const pull: CurrencyFormValues = {
      code: 'ODOO-12',
      name: 'Rupiah',
      symbol: 'Rp',
      rate: '',
    };

    expect(validateCurrencyEditForm(pull, 'ODOO-12')).toEqual({});
    expect(validateCurrencyEditForm({ ...pull, code: 'Rp' }, 'ODOO-12').code).toContain(
      '3 huruf',
    );
    expect(validateCurrencyEditForm({ ...pull, code: 'usd' }, 'ODOO-12')).toEqual({});
    expect(validateCurrencyEditForm({ ...pull, name: '' }, 'ODOO-12').name).toContain('wajib');
  });

  it('form→payload + helper tampilan', () => {
    expect(currencyCreateInputFromForm({ ...valid, code: ' gbp ' })).toEqual({
      code: 'GBP',
      name: 'Pound Sterling',
      symbol: '£',
      rate: 0.000052,
    });
    expect(currencyCreateInputFromForm(EMPTY_CURRENCY_FORM)).toEqual({
      code: '',
      name: '',
      symbol: '',
    });

    // `code` hanya dikirim kalau berubah
    expect(currencyUpdateInputFromForm(valid, 'GBP', false)).toEqual({
      name: 'Pound Sterling',
      symbol: '£',
      rate: 0.000052,
      active: false,
    });
    expect(currencyUpdateInputFromForm({ ...valid, code: 'usd' }, 'GBP', true).code).toBe('USD');
    expect(currencyUpdateInputFromForm({ ...valid, rate: '' }, 'GBP', true).rate).toBeNull();

    const row = {
      id: 1,
      code: 'ODOO-12',
      name: 'Rupiah',
      symbol: '',
      rate: null,
      is_default: false,
      is_active: true,
      odoo_id: 12,
    };

    expect(currencyFormFromRow(row)).toEqual({
      code: 'ODOO-12',
      name: 'Rupiah',
      symbol: '',
      rate: '',
    });
    expect(currencySourceLabel(row)).toBe('Odoo');
    expect(currencySourceLabel({ ...row, odoo_id: null })).toBe('MES');
    expect(currencyRateLabel(row)).toBe('—');
    expect(currencyRateLabel({ ...row, rate: 1 })).toBe('1');
    expect(CURRENCY_CODE_PATTERN.test('IDR')).toBe(true);
    expect(CURRENCY_CODE_PATTERN.test('idr')).toBe(false);
  });
});
