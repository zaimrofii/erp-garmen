import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { CompanyPage } from '@/pages/settings/CompanyPage';
import {
  DEFAULT_COMPANY_TIMEZONE,
  EMPTY_COMPANY_FORM,
  companyFormFromRow,
  companyInputFromForm,
  isCompanyFormValid,
  isHttpUrl,
  validateCompanyForm,
  type CompanyFormValues,
} from '@/lib/company';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.1 — halaman `/settings/company` (Company Profile, singleton).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings, validasi form dan
 *      konversi form → payload PUT.
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

const VALID: CompanyFormValues = {
  ...EMPTY_COMPANY_FORM,
  name: 'PT Garmen Jaya',
  city: 'Bandung',
  country: 'id',
  email: 'admin@garmen.test',
  npwp: '01.234.567.8-901.000',
  website: 'https://garmen.test',
  logo_url: 'https://garmen.test/logo.png',
};

describe('H5.1 — route, guard & nav', () => {
  it('App.tsx: /settings/company dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/company"');
    expect(APP).toContain('<CompanyPage />');
    expect(APP).toContain("import('@/pages/settings/CompanyPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah topbar "Company" di app Settings', () => {
    expect(NAV).toContain("label: 'Company', path: '/settings/company'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');

    expect(settings?.topbar.some((item) => item.path === '/settings/company')).toBe(true);
  });
});

describe('H5.1 — render halaman (react-dom/server)', () => {
  it('CompanyPage render judul, field wajib, dropdown mata uang, tombol Simpan', () => {
    const { text } = renderPage(createElement(CompanyPage), '/settings/company');

    expect(text).toContain('Company Profile');
    expect(text).toContain('Identitas perusahaan MES');
    expect(text).toContain('Nama perusahaan');
    expect(text).toContain('Mata uang default');
    expect(text).toContain('Zona waktu');
    expect(text).toContain('Simpan Profil');
    // MES-only: tidak ada aksi sync ke Odoo
    expect(text).not.toContain('Sync ke Odoo');
  });

  it('CompanyPage sumber: GET + PUT + muat ulang (singleton, tanpa POST/DELETE)', () => {
    const page = read('src/pages/settings/CompanyPage.tsx');

    expect(page).toContain('fetchCompany');
    expect(page).toContain('updateCompany');
    expect(page).toContain('Muat Ulang');
    expect(page).toContain('Simpan Profil');
    expect(page).toContain('fetchCurrencies');
    expect(page).not.toContain('deleteCompany');
  });
});

describe('H5.1 — lib form (PURE)', () => {
  it('validateCompanyForm: nama wajib, ISO negara, email, NPWP 15/16 digit, URL', () => {
    expect(validateCompanyForm(VALID)).toEqual({});
    expect(validateCompanyForm({ ...VALID, name: '  ' }).name).toContain('wajib');
    expect(validateCompanyForm({ ...VALID, country: 'IDN' }).country).toContain('2 huruf');
    expect(validateCompanyForm({ ...VALID, country: '' }).country).toBeUndefined();
    expect(validateCompanyForm({ ...VALID, email: 'bukan-email' }).email).toContain('tidak valid');
    expect(validateCompanyForm({ ...VALID, npwp: '12345' }).npwp).toContain('15 atau 16 digit');
    expect(validateCompanyForm({ ...VALID, npwp: '' }).npwp).toBeUndefined();
    expect(validateCompanyForm({ ...VALID, website: 'garmen' }).website).toContain('http');
    expect(validateCompanyForm({ ...VALID, logo_url: 'garmen' }).logo_url).toContain('http');
    expect(validateCompanyForm({ ...VALID, timezone: 'x'.repeat(65) }).timezone).toContain(
      'maksimal',
    );
    expect(isCompanyFormValid(validateCompanyForm(VALID))).toBe(true);
    expect(isCompanyFormValid(validateCompanyForm({ ...VALID, name: '' }))).toBe(false);
  });

  it('companyFormFromRow + companyInputFromForm (NPWP digit-only, currency null)', () => {
    expect(companyFormFromRow(null)).toEqual(EMPTY_COMPANY_FORM);

    const row = {
      id: 1,
      name: 'PT A',
      legal_name: 'PT A Sejahtera',
      address: 'Jl. 1',
      city: 'Solo',
      country: 'ID',
      phone: '022',
      email: 'a@b.test',
      npwp: '012345678901000',
      website: 'https://a.test',
      logo_url: '',
      currency_id: 4,
      currency: { id: 4, code: 'IDR', name: 'Rupiah', symbol: 'Rp' },
      timezone: 'Asia/Jakarta',
      is_active: false,
      created_at: '2026-10-14T03:00:00+00:00',
      updated_at: '2026-10-14T04:00:00+00:00',
    };

    expect(companyFormFromRow(row)).toEqual({
      ...EMPTY_COMPANY_FORM,
      name: 'PT A',
      legal_name: 'PT A Sejahtera',
      address: 'Jl. 1',
      city: 'Solo',
      country: 'ID',
      phone: '022',
      email: 'a@b.test',
      npwp: '012345678901000',
      website: 'https://a.test',
      currencyId: '4',
      active: false,
    });

    expect(companyInputFromForm(VALID)).toEqual({
      name: 'PT Garmen Jaya',
      legal_name: '',
      address: '',
      city: 'Bandung',
      country: 'ID',
      phone: '',
      email: 'admin@garmen.test',
      npwp: '012345678901000',
      website: 'https://garmen.test',
      logo_url: 'https://garmen.test/logo.png',
      currency_id: null,
      timezone: DEFAULT_COMPANY_TIMEZONE,
      active: true,
    });

    expect(companyInputFromForm({ ...VALID, currencyId: '4' }).currency_id).toBe(4);
    expect(isHttpUrl('https://a.test')).toBe(true);
    expect(isHttpUrl('ftp://a.test')).toBe(false);
    expect(isHttpUrl('a.test')).toBe(false);
  });
});
