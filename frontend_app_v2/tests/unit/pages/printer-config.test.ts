import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { PrinterConfigPage } from '@/pages/settings/PrinterConfigPage';
import type { PrinterConfigRow } from '@/types/printer-config';
import {
  BACKEND_OPTIONS,
  CONFIG_FIELD_LABELS,
  EMPTY_PRINTER_FORM,
  effectiveStatusRows,
  formatConfigValue,
  isKnownBackend,
  isPrinterConfigFormValid,
  printerConfigFormFromRow,
  printerConfigInputFromForm,
  toNullablePort,
  validatePrinterConfigForm,
  visibleFieldGroups,
  type PrinterConfigFormValues,
} from '@/lib/printer-config';
import { PRINTER_PORT_MAX, PRINTER_PORT_MIN } from '@/types/printer-config';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.7 — halaman `/settings/printers` (Printer Config, singleton, Opsi B).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings (landing tetap
 *      `/settings/routing`, Printer = terakhir), field kondisional per backend,
 *      validasi form, dan konversi form → payload PUT.
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

const VALID_NETWORK: PrinterConfigFormValues = {
  ...EMPTY_PRINTER_FORM,
  printer_backend: 'network',
  printer_network_host: '192.168.1.50',
  printer_network_port: '9100',
};

const ROW: PrinterConfigRow = {
  id: 3,
  printer_backend: 'network',
  printer_usb_vendor_id: '',
  printer_usb_product_id: '',
  printer_network_host: '192.168.1.50',
  printer_network_port: 9100,
  printer_mock_dir: '',
  is_active: true,
  created_at: '',
  updated_at: '',
};

describe('H5.7 — route, guard & nav', () => {
  it('App.tsx: /settings/printers dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/printers"');
    expect(APP).toContain('<PrinterConfigPage />');
    expect(APP).toContain("import('@/pages/settings/PrinterConfigPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah "Printer" sebagai item TERAKHIR + landing tetap Routing', () => {
    expect(NAV).toContain("label: 'Printer', path: '/settings/printers'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');
    const paths = settings?.topbar.map((item) => item.path) ?? [];

    expect(paths).toContain('/settings/printers');
    // route-fix: landing app Settings tetap item topbar PERTAMA
    expect(settings?.topbar[0]?.path).toBe('/settings/routing');
    // H5.7 dipasang SETELAH Audit Log (H5.5) — relatif, tahan modul berikutnya
    expect(paths.indexOf('/settings/printers')).toBeGreaterThan(
      paths.indexOf('/settings/audit-log'),
    );
    // F9 (audit produk) tetap ada
    expect(paths).toContain('/settings/audit');
  });
});

describe('H5.7 — render halaman (react-dom/server)', () => {
  it('PrinterConfigPage render bagian backend + mock (default) + status', () => {
    const { text } = renderPage(createElement(PrinterConfigPage), '/settings/printers');

    expect(text).toContain('Printer');
    expect(text).toContain('Printer (backend + kredensial)');
    // default backend = mock → blok Mock tampil, blok USB/Network TIDAK
    expect(text).toContain('Mock (opsional untuk backend mock)');
    expect(text).not.toContain('USB (wajib untuk backend usb)');
    expect(text).not.toContain('Network (wajib untuk backend network)');
    expect(text).toContain('Status printer aktif (.env)');
    expect(text).toContain('Test Koneksi');
    expect(text).toContain('Simpan Profil');
  });

  it('PrinterConfigPage sumber: GET/PUT/test + field kondisional per backend', () => {
    const page = read('src/pages/settings/PrinterConfigPage.tsx');

    expect(page).toContain('fetchPrinterConfig');
    expect(page).toContain('updatePrinterConfig');
    expect(page).toContain('testPrinterConnection');
    expect(page).toContain('visibleFieldGroups');
    expect(page).toContain('groups.usb');
    expect(page).toContain('groups.network');
    expect(page).toContain('groups.mock');
    expect(page).toContain('restart_command');
  });
});

describe('H5.7 — lib form (PURE)', () => {
  it('visibleFieldGroups + isKnownBackend', () => {
    expect(visibleFieldGroups('usb')).toEqual({ usb: true, network: false, mock: false });
    expect(visibleFieldGroups('network')).toEqual({
      usb: false,
      network: true,
      mock: false,
    });
    expect(visibleFieldGroups('mock')).toEqual({ usb: false, network: false, mock: true });
    // backend kosong = tampilkan blok mock (default aman)
    expect(visibleFieldGroups('')).toEqual({ usb: false, network: false, mock: true });

    expect(isKnownBackend('MOCK')).toBe(true);
    expect(isKnownBackend(' network ')).toBe(true);
    expect(isKnownBackend('bluetooth')).toBe(false);
    expect(BACKEND_OPTIONS.map((option) => option.value)).toEqual(['mock', 'usb', 'network']);
  });

  it('validatePrinterConfigForm: guard usb/network + port + panjang teks', () => {
    expect(validatePrinterConfigForm(VALID_NETWORK)).toEqual({});
    expect(validatePrinterConfigForm(EMPTY_PRINTER_FORM)).toEqual({});
    expect(isPrinterConfigFormValid(validatePrinterConfigForm(EMPTY_PRINTER_FORM))).toBe(true);

    // backend tak dikenal
    expect(
      validatePrinterConfigForm({ ...VALID_NETWORK, printer_backend: 'bluetooth' })
        .printer_backend,
    ).toContain('salah satu');

    // guard usb: vendor + product wajib
    const usb = validatePrinterConfigForm({ ...EMPTY_PRINTER_FORM, printer_backend: 'usb' });

    expect(usb.printer_usb_vendor_id).toContain('membutuhkan');
    expect(usb.printer_usb_product_id).toContain('membutuhkan');

    expect(
      validatePrinterConfigForm({
        ...EMPTY_PRINTER_FORM,
        printer_backend: 'usb',
        printer_usb_vendor_id: '0x04b8',
        printer_usb_product_id: '0x0202',
      }),
    ).toEqual({});

    // guard network: host + port wajib
    const network = validatePrinterConfigForm({
      ...EMPTY_PRINTER_FORM,
      printer_backend: 'network',
    });

    expect(network.printer_network_host).toContain('membutuhkan');
    expect(network.printer_network_port).toContain('membutuhkan');

    // port di luar rentang / bukan angka
    expect(
      validatePrinterConfigForm({ ...VALID_NETWORK, printer_network_port: '0' })
        .printer_network_port,
    ).toContain(`antara ${String(PRINTER_PORT_MIN)}`);
    expect(
      validatePrinterConfigForm({ ...VALID_NETWORK, printer_network_port: '65536' })
        .printer_network_port,
    ).toContain(`antara ${String(PRINTER_PORT_MIN)}`);
    expect(
      validatePrinterConfigForm({ ...VALID_NETWORK, printer_network_port: 'abc' })
        .printer_network_port,
    ).toContain('angka bulat');
    expect(PRINTER_PORT_MAX).toBe(65535);

    // panjang teks
    expect(
      validatePrinterConfigForm({
        ...VALID_NETWORK,
        printer_network_host: 'x'.repeat(201),
      }).printer_network_host,
    ).toContain('maksimal');
    expect(
      validatePrinterConfigForm({
        ...EMPTY_PRINTER_FORM,
        printer_usb_vendor_id: 'x'.repeat(33),
      }).printer_usb_vendor_id,
    ).toContain('maksimal');
  });

  it('formFromRow + inputFromForm + toNullablePort + tanpa mask', () => {
    expect(printerConfigFormFromRow(null)).toEqual(EMPTY_PRINTER_FORM);

    const form = printerConfigFormFromRow(ROW);

    expect(form.printer_backend).toBe('network');
    expect(form.printer_network_host).toBe('192.168.1.50');
    expect(form.printer_network_port).toBe('9100');
    expect(form.active).toBe(true);

    expect(printerConfigInputFromForm(form)).toEqual({
      printer_backend: 'network',
      printer_usb_vendor_id: '',
      printer_usb_product_id: '',
      printer_network_host: '192.168.1.50',
      printer_network_port: 9100,
      printer_mock_dir: '',
      active: true,
    });

    // port kosong → null (hapus), dan nilai tetap apa adanya (tanpa mask)
    expect(
      printerConfigInputFromForm({ ...form, printer_network_port: '' }).printer_network_port,
    ).toBeNull();
    expect(
      printerConfigInputFromForm({ ...form, printer_usb_vendor_id: ' 0x04b8 ' })
        .printer_usb_vendor_id,
    ).toBe('0x04b8');

    expect(toNullablePort('9100')).toBe(9100);
    expect(toNullablePort(' 9100 ')).toBe(9100);
    expect(toNullablePort('')).toBeNull();
    expect(toNullablePort('abc')).toBeNull();
  });

  it('helper tampilan: formatConfigValue + effectiveStatusRows', () => {
    expect(formatConfigValue(null)).toBe('—');
    expect(formatConfigValue('')).toBe('—');
    expect(formatConfigValue('network')).toBe('network');
    expect(formatConfigValue(9100)).toBe('9100');

    const effective = {
      printer_backend: 'mock',
      printer_usb_vendor_id: '',
      printer_usb_product_id: '',
      printer_network_host: '',
      printer_network_port: null,
      printer_mock_dir: '/tmp/print_mock',
    };

    const rows = effectiveStatusRows(effective);

    expect(rows.map((row) => row.field)).toEqual(Object.keys(CONFIG_FIELD_LABELS));
    expect(rows.find((row) => row.field === 'printer_backend')?.value).toBe('mock');
    expect(rows.find((row) => row.field === 'printer_network_port')?.value).toBe('—');
    expect(rows.find((row) => row.field === 'printer_mock_dir')?.value).toBe('/tmp/print_mock');
  });
});


