import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F9/9.2 + 9.3 + 9.4 — halaman audit produk (`/settings/audit`).
 *
 * Tes berbasis sumber: memaku bahwa halaman menampilkan DUA potret §6.1 (`products` +
 * `used_in_open_bundles`), memakai `DenseTable`, dan route/nav-nya terpasang di guard admin.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/settings/ProductAuditPage.tsx';

describe('F9/9.3 — route', () => {
  const app = read('src/App.tsx');

  it('route /settings/audit + guard SETTINGS (admin)', () => {
    expect(app).toContain('path="/settings/audit"');
    expect(app).toContain('<ProductAuditPage />');
    expect(app).toMatch(/path="\/settings\/audit"[\s\S]{0,160}SETTINGS_ROLES/);
  });
});

describe('F9/9.2 — halaman', () => {
  const page = read(PAGE);

  it('memuat GET /audit/products-missing-odoo-id/ lewat adapter', () => {
    expect(page).toContain('getProductAudit(apiClient)');
    expect(page).toContain("from '@/api/audit'");
    expect(page).toContain("queryKey: ['product-audit']");
  });

  it('menampilkan `products` (missing) DAN `used_in_open_bundles` + count', () => {
    expect(page).toContain('data?.products');
    expect(page).toContain('data?.used_in_open_bundles');
    expect(page).toContain('urgent?.count ?? 0');
    expect(page).toContain('dipakai bundle terbuka');
    expect(page).toContain('tanpa odoo_id di master MES');
  });

  it('dua tabel memakai DenseTable yang sama (tanpa tabel baru)', () => {
    expect(read('src/components/molecules/DenseTable.tsx')).toContain('DenseTable');
    expect(page).toContain("from '@/components/molecules/DenseTable'");
    expect(page).toContain('<DenseTable');
    expect(page).not.toContain('<table');
    expect(page).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('read-only: tidak ada POST/PUT/DELETE (halaman audit tidak mengubah produk)', () => {
    expect(page).not.toContain('apiClient.post');
    expect(page).not.toContain('useMutation');
  });

  it('feedback + toast + error handling (pola F8)', () => {
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
    expect(page).toContain('Gagal memuat audit produk (perlu login?).');
  });
});

describe('F9/9.4 — nav item', () => {
  it('Settings punya item Audit dengan path yang benar', () => {
    expect(read('src/app/nav-config.ts')).toContain("{ label: 'Audit', path: '/settings/audit' }");
  });
});
