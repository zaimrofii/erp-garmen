import { Badge } from '@/components/atoms/Badge';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { readinessLabel, readinessTone } from '@/lib/state-display';
import type { OrderReadinessLine } from '@/api/readiness';

/**
 * ReadinessTable - tabel kesiapan material satu Order (kontrak §5.4, F8).
 *
 * MEMAKAI ULANG `DenseTable` (Fase 20) - tidak ada tabel paralel: header/sel/empty/error
 * state tetap satu sumber. Baris di-`key` dengan `id = order_line_id`
 * (`DenseTable` butuh `{id}`; `readReadinessLine` sudah membuang baris tanpa id).
 *
 * Status WAITING/PARTIAL/READY dirender `Badge` (atom) dengan tone token OKLCH
 * lewat `readinessTone` - TIDAK ada warna hardcode di sini.
 */

interface ReadinessRow extends OrderReadinessLine {
  id: number;
}

interface ReadinessTableProps {
  lines: readonly OrderReadinessLine[];
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
  className?: string;
}

function toRows(lines: readonly OrderReadinessLine[]): ReadinessRow[] {
  return lines.map((line) => ({ ...line, id: line.order_line_id }));
}

function numberOf(value: number | null): string {
  return value === null ? '-' : String(value);
}

export function ReadinessTable({
  lines,
  loading = false,
  error = null,
  onRetry,
  className,
}: ReadinessTableProps) {
  const columns: DenseTableColumn<ReadinessRow>[] = [
    {
      key: 'product_code',
      label: 'Produk',
      render: (row) => <span className="font-mono text-xs">{row.product_code ?? '-'}</span>,
    },
    {
      key: 'required_qty',
      label: 'Dipesan',
      align: 'right',
      render: (row) => numberOf(row.required_qty),
    },
    {
      key: 'received_qty',
      label: 'Diterima',
      align: 'right',
      render: (row) => numberOf(row.received_qty),
    },
    {
      key: 'shortage_qty',
      label: 'Kurang',
      align: 'right',
      render: (row) => numberOf(row.shortage_qty),
    },
    {
      key: 'status',
      label: 'Status',
      render: (row) => (
        <Badge tone={readinessTone(row.status)}>{readinessLabel(row.status)}</Badge>
      ),
    },
    {
      key: 'expected_date',
      label: 'ETA',
      render: (row) => row.expected_date ?? '-',
    },
    {
      key: 'vendor_bill_status',
      label: 'Status Bill',
      render: (row) => row.vendor_bill_status ?? '-',
    },
    {
      key: 'vendor_bill_ids',
      label: 'Bill',
      align: 'right',
      render: (row) => (row.vendor_bill_ids === null ? '-' : row.vendor_bill_ids.join(', ')),
    },
    {
      key: 'vendor_bill_amount',
      label: 'Nilai Bill',
      align: 'right',
      render: (row) => numberOf(row.vendor_bill_amount),
    },
    {
      key: 'last_computed_at',
      label: 'Dihitung',
      render: (row) => row.last_computed_at ?? '-',
    },
  ];

  return (
    <DenseTable
      columns={columns}
      rows={toRows(lines)}
      loading={loading}
      error={error}
      {...(onRetry === undefined ? {} : { onRetry })}
      emptyMessage="Belum ada OrderLine pada order ini."
      {...(className === undefined ? {} : { className })}
    />
  );
}
