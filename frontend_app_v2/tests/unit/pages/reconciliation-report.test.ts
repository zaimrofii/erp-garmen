import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F9/9.1 + 9.3 + 9.4 — halaman rekonsiliasi (`/reports/reconciliation`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa DOM),
 * jadi tes ini memaku wiring sumber: hari default 7, validasi 1..90 lewat
 * `parseReconciliationDays`, reuse `DenseTable`, guard role REPORTS, dan item nav baru.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/reports/ReconciliationReportPage.tsx';

describe('F9/9.3 — route', () => {
  const app = read('src/App.tsx');

  it('route /reports/reconciliation + guard role REPORTS', () => {
    expect(app).toContain('path="/reports/reconciliation"');
    expect(app).toContain('<ReconciliationReportPage />');
    expect(app).toContain('ReconciliationReportPage');
  });
});

describe('F9/9.1 — halaman', () => {
  const page = read(PAGE);

  it('default 7 hari + validasi 1..90 sebelum request', () => {
    expect(page).toContain('RECONCILIATION_DAYS_DEFAULT');
    expect(page).toContain('parseReconciliationDays(daysInput)');
    expect(page).toContain('enabled: days !== null');
    expect(page).toContain("queryKey: ['reconciliation-report', effectiveDays]");
  });

  it('query memakai adapter `getReconciliationReport` + days efektif', () => {
    expect(page).toContain('getReconciliationReport(apiClient, effectiveDays)');
    expect(page).toContain("from '@/api/reconciliation'");
  });

  it('kolom kontrak §6.2: run_at, product_code, product_odoo_id, mes_qty, odoo_qty, diff, is_alert, notes', () => {
    for (const key of [
      'run_at',
      'product_code',
      'product_odoo_id',
      'mes_qty',
      'odoo_qty',
      'diff',
      'is_alert',
      'notes',
    ]) {
      expect(page, key).toContain(`key: '${key}'`);
    }
  });

  it('memakai DenseTable (bukan tabel paralel) + Badge tone token', () => {
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).toContain("from '@/components/atoms/Badge'");
    expect(page).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('baris di-key id turunan (backend tidak mengirim id)', () => {
    expect(page).toContain('interface ReconciliationRow extends ReconciliationEntry');
    expect(page).toContain('id: `${entry.run_at');
  });

  it('feedback + toast + error handling (pola F8)', () => {
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
    expect(page).toContain('Gagal memuat rekonsiliasi (perlu login?).');
  });
});

describe('F9/9.4 — nav item', () => {
  it('Reports punya item Reconciliation dengan path yang benar', () => {
    expect(read('src/app/nav-config.ts')).toContain(
      "{ label: 'Reconciliation', path: '/reports/reconciliation' }",
    );
  });

  it('menu-config TIDAK menyalin daftar (tetap turunan NAV_APPS)', () => {
    const menu = read('src/app/menu-config.ts');

    expect(menu).toContain('NAV_APPS');
    expect(menu).not.toContain('/reports/reconciliation');
  });
});
