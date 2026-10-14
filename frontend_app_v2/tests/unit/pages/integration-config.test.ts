import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { IntegrationConfigPage } from '@/pages/settings/IntegrationConfigPage';
import {
  ADAPTER_VALUES,
  CONFIG_FIELD_LABELS,
  EMPTY_INTEGRATION_FORM,
  INTEGRATION_MASK,
  MAX_TOLERANCE_PCT,
  effectiveStatusRows,
  formatConfigValue,
  integrationConfigFormFromRow,
  integrationConfigInputFromForm,
  isIntegrationConfigFormValid,
  isMaskedApiKey,
  toNullableInt,
  validateIntegrationConfigForm,
  waNumbers,
  type IntegrationConfigFormValues,
} from '@/lib/integration-config';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.6 — halaman `/settings/integration` (Integration Config, singleton, Opsi B).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings (landing tetap
 *      `/settings/routing`), validasi 16 field dan konversi form → payload PUT.
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

const VALID: IntegrationConfigFormValues = {
  ...EMPTY_INTEGRATION_FORM,
  odoo_url: 'http://odoo:8069',
  odoo_db: 'garmen_db',
  odoo_user: 'api_bot',
  odoo_api_key: INTEGRATION_MASK,
  odoo_location_wip_id: '11',
  reconciliation_alert_wa_to: '6281, 6282',
};

describe('H5.6 — route, guard & nav', () => {
  it('App.tsx: /settings/integration dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/integration"');
    expect(APP).toContain('<IntegrationConfigPage />');
    expect(APP).toContain("import('@/pages/settings/IntegrationConfigPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah "Integration" di app Settings TANPA mengubah item pertama', () => {
    expect(NAV).toContain("label: 'Integration', path: '/settings/integration'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');

    expect(settings?.topbar.some((item) => item.path === '/settings/integration')).toBe(true);
    // route-fix: landing app Settings tetap item topbar PERTAMA
    expect(settings?.topbar[0]?.path).toBe('/settings/routing');
  });
});

describe('H5.6 — render halaman (react-dom/server)', () => {
  it('IntegrationConfigPage render 5 bagian + tombol aksi', () => {
    const { text } = renderPage(
      createElement(IntegrationConfigPage),
      '/settings/integration',
    );

    expect(text).toContain('Integration Config');
    expect(text).toContain('Odoo (adapter + kredensial)');
    expect(text).toContain('Lokasi Odoo');
    expect(text).toContain('Advanced');
    expect(text).toContain('Rekonsiliasi stok + alert');
    expect(text).toContain('Status konfigurasi aktif (.env)');
    expect(text).toContain('Test Koneksi');
    expect(text).toContain('Simpan Profil');
    // MES-only: tidak ada aksi sync ke Odoo
    expect(text).not.toContain('Sync ke Odoo');
  });

  it('IntegrationConfigPage sumber: GET/PUT/test + API key masked (type=password)', () => {
    const page = read('src/pages/settings/IntegrationConfigPage.tsx');

    expect(page).toContain('fetchIntegrationConfig');
    expect(page).toContain('updateIntegrationConfig');
    expect(page).toContain('testIntegrationConnection');
    expect(page).toContain('type="password"');
    expect(page).toContain('isMaskedApiKey');
    expect(page).toContain('restart_command');
  });
});

describe('H5.6 — lib form (PURE)', () => {
  it('validateIntegrationConfigForm: guard adapter + URL + timeout + id + toleransi + WA', () => {
    expect(validateIntegrationConfigForm(VALID)).toEqual({});
    expect(ADAPTER_VALUES).toEqual(['odoo', 'null']);
    expect(MAX_TOLERANCE_PCT).toBe(1);

    expect(
      validateIntegrationConfigForm({ ...VALID, erp_adapter: 'accurate' }).erp_adapter,
    ).toContain('salah satu');

    // URL tanpa skema ditolak, tetapi hostname internal TANPA TLD tetap VALID
    expect(validateIntegrationConfigForm({ ...VALID, odoo_url: 'odoo:8069' }).odoo_url).toContain(
      'http/https',
    );
    expect(validateIntegrationConfigForm({ ...VALID, odoo_url: 'http://odoo:8069' })).toEqual({});

    // guard: adapter 'odoo' wajib punya db & user
    const guard = validateIntegrationConfigForm({ ...VALID, odoo_db: '', odoo_user: '' });

    expect(guard.odoo_db).toContain('database');
    expect(guard.odoo_user).toContain('user');

    // adapter 'null' bebas kredensial
    expect(
      validateIntegrationConfigForm({ ...EMPTY_INTEGRATION_FORM, erp_adapter: 'null' }),
    ).toEqual({});

    expect(validateIntegrationConfigForm({ ...VALID, odoo_timeout: '0' }).odoo_timeout).toContain(
      'antara',
    );
    expect(
      validateIntegrationConfigForm({ ...VALID, odoo_timeout: 'abc' }).odoo_timeout,
    ).toContain('angka');
    expect(validateIntegrationConfigForm({ ...VALID, odoo_uom_id: '0' }).odoo_uom_id).toContain(
      '≥ 1',
    );
    expect(
      validateIntegrationConfigForm({ ...VALID, reconciliation_tolerance_pct: '1.5' })
        .reconciliation_tolerance_pct,
    ).toContain('antara');
    expect(
      validateIntegrationConfigForm({ ...VALID, reconciliation_tolerance_units: '-1' })
        .reconciliation_tolerance_units,
    ).toContain('negatif');
    expect(
      validateIntegrationConfigForm({ ...VALID, reconciliation_alert_wa_to: 'x'.repeat(33) })
        .reconciliation_alert_wa_to,
    ).toContain('maksimal');
    expect(isIntegrationConfigFormValid(validateIntegrationConfigForm(VALID))).toBe(true);
  });

  it('formFromRow + inputFromForm + mask API key', () => {
    expect(isMaskedApiKey(INTEGRATION_MASK)).toBe(true);
    expect(isMaskedApiKey('rahasia')).toBe(false);
    expect(integrationConfigFormFromRow(null)).toEqual(EMPTY_INTEGRATION_FORM);

    const row = {
      id: 1,
      erp_adapter: 'odoo',
      odoo_url: 'http://odoo:8069',
      odoo_db: 'garmen_db',
      odoo_user: 'api_bot',
      odoo_api_key: INTEGRATION_MASK,
      odoo_timeout: 45.5,
      odoo_location_wip_id: 11,
      odoo_location_production_id: null,
      odoo_location_fg_id: 13,
      odoo_location_scrap_id: null,
      odoo_uom_id: 33,
      odoo_picking_type_internal_id: null,
      odoo_payment_journal_id: 7,
      reconciliation_tolerance_units: 7.5,
      reconciliation_tolerance_pct: 0.02,
      reconciliation_alert_wa_to: ['6281', '6282'],
      is_active: false,
      created_at: '',
      updated_at: '',
    };

    const form = integrationConfigFormFromRow(row);

    expect(form.odoo_timeout).toBe('45.5');
    expect(form.odoo_location_production_id).toBe('');
    expect(form.reconciliation_alert_wa_to).toBe('6281, 6282');
    expect(form.active).toBe(false);

    expect(integrationConfigInputFromForm(form)).toEqual({
      erp_adapter: 'odoo',
      odoo_url: 'http://odoo:8069',
      odoo_db: 'garmen_db',
      odoo_user: 'api_bot',
      odoo_api_key: INTEGRATION_MASK,
      odoo_timeout: 45.5,
      odoo_location_wip_id: 11,
      odoo_location_production_id: null,
      odoo_location_fg_id: 13,
      odoo_location_scrap_id: null,
      odoo_uom_id: 33,
      odoo_picking_type_internal_id: null,
      odoo_payment_journal_id: 7,
      reconciliation_tolerance_units: 7.5,
      reconciliation_tolerance_pct: 0.02,
      reconciliation_alert_wa_to: ['6281', '6282'],
      active: false,
    });

    // nilai baru / kosong pada API key diteruskan apa adanya ('' = hapus)
    expect(
      integrationConfigInputFromForm({ ...form, odoo_api_key: 'kunci-baru' }).odoo_api_key,
    ).toBe('kunci-baru');
    expect(integrationConfigInputFromForm({ ...form, odoo_api_key: '' }).odoo_api_key).toBe('');
  });

  it('helper tampilan: waNumbers, toNullableInt, formatConfigValue, effectiveStatusRows', () => {
    expect(waNumbers('6281, , 6282')).toEqual(['6281', '6282']);
    expect(waNumbers('')).toEqual([]);
    expect(toNullableInt(' 11 ')).toBe(11);
    expect(toNullableInt('')).toBeNull();

    expect(formatConfigValue(null)).toBe('—');
    expect(formatConfigValue('')).toBe('—');
    expect(formatConfigValue([])).toBe('—');
    expect(formatConfigValue([6281, 6282])).toBe('6281, 6282');
    expect(formatConfigValue(33)).toBe('33');
    expect(formatConfigValue(INTEGRATION_MASK)).toBe(INTEGRATION_MASK);

    const effective = {
      erp_adapter: 'odoo',
      odoo_url: 'http://odoo:8069',
      odoo_db: 'garmen_db',
      odoo_user: 'api_bot',
      odoo_api_key: INTEGRATION_MASK,
      odoo_timeout: 30,
      odoo_location_wip_id: 11,
      odoo_location_production_id: 12,
      odoo_location_fg_id: 13,
      odoo_location_scrap_id: 14,
      odoo_uom_id: 33,
      odoo_picking_type_internal_id: null,
      odoo_payment_journal_id: 13,
      reconciliation_tolerance_units: 5,
      reconciliation_tolerance_pct: 0.01,
      reconciliation_alert_wa_to: ['6281'],
    };

    const rows = effectiveStatusRows(effective);

    expect(rows.map((row) => row.field)).toEqual(Object.keys(CONFIG_FIELD_LABELS));
    expect(rows.find((row) => row.field === 'odoo_url')?.value).toBe('http://odoo:8069');
    expect(rows.find((row) => row.field === 'odoo_api_key')?.value).toBe(INTEGRATION_MASK);
    expect(rows.find((row) => row.field === 'odoo_picking_type_internal_id')?.value).toBe('—');
    expect(rows.find((row) => row.field === 'reconciliation_alert_wa_to')?.value).toBe('6281');
  });
});
