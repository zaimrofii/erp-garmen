import { describe, expect, it } from 'vitest';
import { ReadinessTable } from '@/components/molecules/ReadinessTable';
import { readOrderReadiness, type OrderReadinessLine } from '@/api/readiness';
import { readinessLabel, readinessTone } from '@/lib/state-display';
import { htmlOf, textOf } from '../../helpers/react-tree';

/** F8/8.3+8.5 — tabel readiness (reuse `DenseTable`), status & tone. */

const LINES: OrderReadinessLine[] = [
  {
    order_line_id: 1,
    product_code: 'TS-DEMO-001',
    required_qty: 20,
    received_qty: 15,
    shortage_qty: 5,
    status: 'PARTIAL',
    expected_date: '2026-10-15',
    last_computed_at: '2026-10-08T02:00:00Z',
    vendor_bill_status: 'DRAFT',
    vendor_bill_ids: [8],
    vendor_bill_amount: 1500000,
  },
  {
    order_line_id: 2,
    product_code: 'TS-DEMO-002',
    required_qty: 10,
    received_qty: 10,
    shortage_qty: 0,
    status: 'READY',
    expected_date: null,
    last_computed_at: '2026-10-08T02:00:00Z',
    vendor_bill_status: 'POSTED',
    vendor_bill_ids: [9, 10],
    vendor_bill_amount: 900000,
  },
  {
    order_line_id: 3,
    product_code: null,
    required_qty: null,
    received_qty: null,
    shortage_qty: null,
    status: 'WAITING',
    expected_date: null,
    last_computed_at: null,
    vendor_bill_status: null,
    vendor_bill_ids: null,
    vendor_bill_amount: null,
  },
  {
    order_line_id: 4,
    product_code: 'TS-DEMO-004',
    required_qty: 5,
    received_qty: null,
    shortage_qty: null,
    status: null,
    expected_date: null,
    last_computed_at: null,
    vendor_bill_status: null,
    vendor_bill_ids: null,
    vendor_bill_amount: null,
  },
];

function rowCount(html: string): number {
  return [...html.matchAll(/<tr/g)].length;
}

describe('F8 — tone & label status (§5.4)', () => {
  it('READY/PARTIAL/WAITING → tone token, nilai asing → default', () => {
    expect(readinessTone('READY')).toBe('blue');
    expect(readinessTone('PARTIAL')).toBe('coral');
    expect(readinessTone('WAITING')).toBe('muted');
    expect(readinessTone(null)).toBe('default');
    expect(readinessTone('ANEHDONG')).toBe('default');
  });

  it('label siap-tampil', () => {
    expect(readinessLabel('READY')).toBe('Siap');
    expect(readinessLabel('PARTIAL')).toBe('Sebagian');
    expect(readinessLabel('WAITING')).toBe('Menunggu PO');
    expect(readinessLabel(null)).toBe('Belum dihitung');
  });
});

describe('F8 — ReadinessTable', () => {
  const tree = ReadinessTable({ lines: LINES });
  const html = htmlOf(tree);

  it('kolom lengkap sesuai §5.4 (+ vendor bill)', () => {
    const text = textOf(tree);

    for (const header of [
      'Produk',
      'Dipesan',
      'Diterima',
      'Kurang',
      'Status',
      'ETA',
      'Status Bill',
      'Bill',
      'Nilai Bill',
      'Dihitung',
    ]) {
      expect(text, header).toContain(header);
    }
  });

  it('satu baris per OrderLine (header + 4 baris)', () => {
    expect(rowCount(html)).toBe(LINES.length + 1);
  });

  it('nilai baris tampil apa adanya & null → "-"', () => {
    const text = textOf(tree);

    expect(text).toContain('TS-DEMO-001');
    expect(text).toContain('1500000');
    expect(text).toContain('2026-10-15');
    expect(text).toContain('DRAFT');
    expect(text).toContain('9, 10');
  });

  it('3 status dirender dengan tone Badge (token OKLCH, tanpa warna hex/rgb)', () => {
    expect(textOf(tree)).toContain('Sebagian');
    expect(textOf(tree)).toContain('Siap');
    expect(textOf(tree)).toContain('Menunggu PO');

    expect(html).toContain('text-accent-coral'); // PARTIAL
    expect(html).toContain('text-accent-blue'); // READY
    expect(html).toContain('bg-muted'); // WAITING
    expect(html).toContain('text-primary'); // null → default tone

    expect(html).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(html).not.toMatch(/rgba?\(/i);
  });

  it('baris tanpa order_line_id dibuang sebelum dirender', () => {
    const parsed = readOrderReadiness({
      order_id: 1,
      lines: [LINES[0], 'rusak', { product_code: 'X' }, LINES[1]],
    });

    expect(parsed?.lines).toHaveLength(2);
    expect(rowCount(htmlOf(ReadinessTable({ lines: parsed?.lines ?? [] })))).toBe(3);
  });

  it('state kosong & loading', () => {
    expect(textOf(ReadinessTable({ lines: [] }))).toContain('Belum ada OrderLine');
    expect(htmlOf(ReadinessTable({ lines: [], loading: true }))).toContain('aria-busy="true"');
  });

  it('error + onRetry dirender DenseTable (satu sumber tabel)', () => {
    const errored = ReadinessTable({ lines: [], error: 'Gagal memuat readiness', onRetry: () => {} });

    expect(textOf(errored)).toContain('Gagal memuat readiness');
    expect(textOf(errored)).toContain('Coba Lagi');
  });
});
