import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * F8 — halaman kesiapan material (`/production/readiness/:orderId`).
 *
 * Rendering penuh butuh Router + QueryClient + provider runtime (di luar gaya tes tanpa
 * DOM), jadi tes ini memaku wiring sumber + memastikan **`:orderId`** (id ORDER, §5.4),
 * reuse `DenseTable`, dan tidak ada link navigasi baru (anti scope-creep).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const PAGE = 'src/pages/production/MaterialReadinessPage.tsx';
const TABLE = 'src/components/molecules/ReadinessTable.tsx';

describe('F8/8.4 — route', () => {
  const app = read('src/App.tsx');

  it('route /production/readiness/:orderId (BUKAN :orderLineId) + guard role', () => {
    expect(app).toContain('path="/production/readiness/:orderId"');
    expect(app).toContain('<MaterialReadinessPage />');
    expect(app).toContain('MaterialReadinessPage');
    expect(app).not.toContain('orderLineId');
  });
});

describe('F8/8.1-8.2 — halaman', () => {
  const page = read(PAGE);

  it('orderId dari URL → GET readiness', () => {
    expect(page).toContain('useParams<{ orderId: string }>');
    expect(page).toContain('getOrderReadiness(apiClient, key)');
    expect(page).toContain("queryKey: ['order-readiness', key]");
  });

  it('tombol Recompute → postRecomputeReadiness + refetch query', () => {
    expect(page).toContain('postRecomputeReadiness(apiClient, key)');
    expect(page).toContain("invalidateQueries({ queryKey: ['order-readiness', key] })");
    expect(page).toContain('Recompute');
  });

  it('feedback + toast (pola F6/F7)', () => {
    expect(page).toContain("trigger('success')");
    expect(page).toContain("trigger('error')");
    expect(page).toContain('<Toast');
  });

  it('memakai ReadinessTable (bukan tabel sendiri)', () => {
    expect(page).toContain('<ReadinessTable');
  });
});

describe('F8/8.3 — tabel memakai ulang DenseTable', () => {
  const table = read(TABLE);

  it('import DenseTable & tidak membuat <table> paralel', () => {
    expect(table).toContain("from '@/components/molecules/DenseTable'");
    expect(table).not.toContain('<table');
    expect(table).not.toContain('<thead');
  });

  it('status memakai Badge + helper tone (tanpa warna hardcode)', () => {
    expect(table).toContain("from '@/components/atoms/Badge'");
    expect(table).toContain('readinessTone(row.status)');
    expect(table).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it('baris di-key id = order_line_id', () => {
    expect(table).toContain('id: line.order_line_id');
  });
});

describe('F8/8.6 — tanpa scope-creep navigasi', () => {
  it('tidak menambah link/menu readiness di nav-config', () => {
    expect(read('src/app/nav-config.ts')).not.toContain('readiness');
    expect(read('src/app/menu-config.ts')).not.toContain('readiness');
  });
});
