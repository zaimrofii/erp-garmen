import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F15 — halaman antrean invoice (`/finance/invoices`, revive F10).
 *
 * Tes berbasis sumber (render penuh butuh Router + QueryClient): memaku route + guard,
 * adapter, reuse `DenseTable`, filter `state` yang divalidasi, guard `limit`, filter
 * status backend, dan feedback Toast/trigger.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/finance/InvoiceQueuePage.tsx';

describe('F15/B.6 — route finance', () => {
  const app = read('src/App.tsx');

  it('route /finance/invoices + guard FINANCE_ROLES (owner + admin)', () => {
    expect(app).toContain('path="/finance/invoices"');
    expect(app).toContain('<InvoiceQueuePage />');
    expect(app).toMatch(/path="\/finance\/invoices"[\s\S]{0,180}FINANCE_ROLES/);
    expect(app).toContain("const FINANCE_ROLES: Role[] = ['admin', 'owner'];");
  });
});

describe('F15/B.4 — halaman', () => {
  const page = read(PAGE);

  it('memuat GET /finance/invoices/ lewat adapter (bukan real/ langsung)', () => {
    expect(page).toContain("from '@/api/invoice'");
    expect(page).toContain('getInvoices(apiClient, { state: status, limit })');
    expect(page).toContain("queryKey: ['invoice-queue', status, limit]");
    expect(page).not.toContain("from '@/api/real/invoice'");
  });

  it('DenseTable + kolom field NYATA backend (order/status/erp/attempts/error/waktu)', () => {
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');

    for (const key of ['order_no', 'invoice_status', 'erp_id', 'attempts', 'last_error', 'sent_at', 'created_at']) {
      expect(page, key).toContain(`key: '${key}'`);
    }
  });

  it('status memakai Badge + helper tone (OKLCH, tanpa hex)', () => {
    expect(page).toContain('syncStatusTone(row.invoice_status)');
    expect(page).toContain('syncStatusLabel(row.invoice_status)');
    expect(page).toContain("from '@/lib/state-display'");
    expect(page).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('filter status sync (state) + guard limit 1..200', () => {
    expect(page).toContain('INVOICE_STATUSES');
    expect(page).toContain("label=\"Status sync\"");
    expect(page).toContain('parseIntParam(limitInput, 1, INVOICE_LIMIT_MAX)');
    expect(page).toContain('Baris per halaman');
  });

  it('feedback trigger + Toast + retry (pola F8/F9)', () => {
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
    expect(page).toContain('onRetry={() => {');
    expect(page).toContain('Gagal memuat antrean invoice (perlu login?).');
  });
});

describe('F15/B.7 — nav Finance nyata', () => {
  const nav = read('src/app/nav-config.ts');
  const menu = read('src/app/menu-config.ts');

  it('NAV_APPS punya app finance dengan item Invoices', () => {
    expect(nav).toContain("id: 'finance'");
    expect(nav).toContain("{ label: 'Invoices', path: '/finance/invoices' }");
  });

  it('menu-config: Finance & Sales TIDAK lagi placeholder (Master tetap)', () => {
    expect(menu).not.toContain("id: 'finance'");
    expect(menu).not.toContain("id: 'sales'");
    expect(menu).toContain("id: 'master'");
    expect(menu).toContain('NAV_APPS');
  });

  it('ROLE_APPS: finance hanya untuk admin & owner', () => {
    const role = read('src/app/useRole.ts');

    expect(role).toContain('"finance"');
    expect(role).not.toMatch(/operator: \[[^\]]*finance/);
    expect(role).not.toMatch(/supervisor: \[[^\]]*finance/);
    expect(role).not.toMatch(/inventory: \[[^\]]*finance/);
    expect(role).not.toMatch(/purchasing: \[[^\]]*finance/);
  });
});
