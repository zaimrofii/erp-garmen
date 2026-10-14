import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { ExportButton } from '@/components/molecules/ExportButton';
import { textOf, attrOf, htmlOf } from '../../helpers/react-tree';

/**
 * H4.8 - `ExportButton` (tombol unduh laporan Excel/PDF).
 *
 * Rendering memakai `react-dom/server` (TANPA DOM) lewat `createElement` (file tes
 * `.ts`). Alur unduh TIDAK diuji lewat DOM (jsdom tidak ada): jalur API diuji di
 * `tests/unit/api/export.test.ts`, jalur blob di `tests/unit/lib/download.test.ts`,
 * sedangkan wiring komponen + 7 halaman dipaku dengan pemindaian sumber.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const SOURCE = read('src/components/molecules/ExportButton.tsx');

const PAGES: Array<[string, string]> = [
  ['src/pages/reports/SalesReportPage.tsx', 'sales'],
  ['src/pages/reports/PurchasesReportPage.tsx', 'purchases'],
  ['src/pages/reports/StockReportPage.tsx', 'stock'],
  ['src/pages/reports/CogsReportPage.tsx', 'cogs'],
  ['src/pages/reports/PnlReportPage.tsx', 'pnl'],
  ['src/pages/reports/ProductionReportPage.tsx', 'production'],
  ['src/pages/dashboard/ExecutiveDashboardPage.tsx', 'executive'],
];

describe('H4.8 - ExportButton (render)', () => {
  it('merender satu tombol Export + aria-label laporan (modal tertutup)', () => {
    const tree = createElement(ExportButton, { report: 'sales' });
    const html = htmlOf(tree);

    expect(textOf(tree)).toContain('Export');
    expect(attrOf(tree, 'aria-label')).toBe('Export Laporan Penjualan');
    expect(html.match(/<button/g)?.length).toBe(1);
    expect(html).not.toContain('role="dialog"');
  });

  it('label + ukuran bisa diganti; opsi format dari kontrak backend (tanpa kelas baru)', () => {
    const tree = createElement(ExportButton, {
      report: 'executive',
      label: 'Unduh',
      size: 'md',
    });

    expect(textOf(tree)).toContain('Unduh');
    expect(attrOf(tree, 'aria-label')).toBe('Export Dashboard Eksekutif');
    // Opsi dropdown dibangun dari kontrak `@/api/export` (bukan daftar hardcode).
    expect(SOURCE).toContain('const FORMAT_OPTIONS: SelectOption[] = EXPORT_FORMAT_VALUES.map(');
    expect(SOURCE).toContain('label: EXPORT_FORMAT_LABELS[value]');
    expect(SOURCE).toContain('options={FORMAT_OPTIONS}');
  });
});

describe('H4.8 - ExportButton (wiring)', () => {
  it('mengirim export lewat adapter + menyimpan berkas via downloadBlob', () => {
    expect(SOURCE).toContain("from '@/api/export'");
    expect(SOURCE).toContain('  exportReport,');
    expect(SOURCE).toContain('EXPORT_FORMAT_DEFAULT');
    expect(SOURCE).toContain('const file = await exportReport(client, report, format, filters);');
    expect(SOURCE).toContain('downloadBlob(file.blob, file.filename);');
    expect(SOURCE).toContain("from '@/lib/download'");
  });

  it('modal pilih format + state busy/error (tanpa retry otomatis)', () => {
    expect(SOURCE).toContain("from '@/components/atoms/Modal'");
    expect(SOURCE).toContain('<Modal');
    expect(SOURCE).toContain('open={open}');
    expect(SOURCE).toContain("from '@/components/atoms/Select'");
    expect(SOURCE).toContain("useState<ExportFormat>(EXPORT_FORMAT_DEFAULT)");
    expect(SOURCE).toContain('setError(caught instanceof Error ? caught.message');
    expect(SOURCE).toContain('role="alert"');
    expect(SOURCE).toContain('loading={busy}');
  });

  it('TIDAK memanggil fetch langsung (satu pintu HTTP = ApiClient.requestBlob)', () => {
    expect(SOURCE).not.toContain('fetch(');
    expect(SOURCE).not.toContain("method: 'POST'");
  });
});

describe('H4.8 - 7 halaman memakai ExportButton (export aktif)', () => {
  it.each(PAGES)('%s → report="%s" + filter halaman + read-only', (relative, report) => {
    const page = read(relative);

    expect(page).toContain("from '@/components/molecules/ExportButton'");
    expect(page).toContain('<ExportButton');
    expect(page).toContain(`report="${report}"`);
    expect(page).toContain('filters={{');
    expect(page).toContain('H4.8');
    expect(page).not.toContain('client.post');
    expect(page).not.toContain('client.request');
    expect(page).not.toContain('<Tooltip content="Export');
    expect(page).not.toContain('menyusul di H4.8');
  });
});
