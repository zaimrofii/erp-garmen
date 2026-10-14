import { useQuery } from '@tanstack/react-query';
import { ShoppingCart, Wallet } from 'lucide-react';
import { BarChart, BarChartCard } from '@/components/molecules/BarChart';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchPurchaseReporting, type TopVendor } from '@/api/purchase';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * PurchaseReportingPage - route `/purchase/reporting` (F2C.2).
 * Data NYATA `GET /api/v1/purchase/reporting/` (B11 + G5b).
 */

function formatRupiah(value: number): string {
  return `Rp ${value.toLocaleString('id-ID')}`;
}

const COLUMNS: DenseTableColumn<TopVendor>[] = [
  {
    key: 'vendor_code',
    label: 'Kode',
    render: (row) => (
      <span className="font-mono tabular-nums">{row.vendor_code ?? '—'}</span>
    ),
  },
  {
    key: 'vendor_name',
    label: 'Vendor',
    render: (row) => row.vendor_name ?? row.partner_name ?? '—',
  },
  { key: 'po_count', label: 'Total PO', align: 'right' },
  {
    key: 'amount_total',
    label: 'Total Nilai',
    align: 'right',
    render: (row) => formatRupiah(row.amount_total),
  },
];

export function PurchaseReportingPage() {
  const client = useApiClient();

  const report = useQuery({
    queryKey: ['purchase-reporting'],
    queryFn: () => fetchPurchaseReporting(client),
    staleTime: 30_000,
  });

  const data = report.data;
  const series = (data?.monthly_series ?? []).map((point) => ({
    label: point.month,
    value: point.amount_total,
  }));

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Purchase Reporting"
        subtitle="Nilai pembelian bulanan + top vendor"
        breadcrumb={[{ label: 'Purchase' }, { label: 'Reporting' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <KpiCard
          label="Total PO"
          value={String(data?.total_po ?? 0)}
          trend={`${data?.top_vendors.length ?? 0} top vendor`}
          tone="blue"
          icon={ShoppingCart}
        />
        <KpiCard
          label="Total Nilai PO"
          value={formatRupiah(data?.total_amount ?? 0)}
          trend={`${data?.vendor_bills.total ?? 0} vendor bill`}
          tone="muted"
          icon={Wallet}
        />
      </section>

      <BarChartCard title="Nilai Pembelian 6 Bulan" hint="rupiah per bulan">
        <BarChart
          data={series}
          valueFormatter={(value) => `Rp ${value.toLocaleString('id-ID')}`}
          emptyMessage="Belum ada data bulanan."
        />
      </BarChartCard>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={data?.top_vendors ?? []}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat laporan pembelian.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Belum ada data vendor."
        />
      </section>
    </div>
  );
}
