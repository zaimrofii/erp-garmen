import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Layers, RefreshCw, TrendingUp, Wallet } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchSalesReport,
  SALES_GROUP_BY_VALUES,
  SALES_ORDER_TYPES,
  type SalesGroupBy,
  type SalesReportRow,
} from '@/api/reports';
import { fetchPartners } from '@/api/masterPartners';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * SalesReportPage - route `/reports/sales` (H4.1, laporan penjualan).
 *
 * Data NYATA `GET /api/v1/reports/sales/` (`api/reports.ts` → MODE.reportSales='real'):
 *
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan), `?customer_id=`,
 *     `?product_id=`, `?order_type=`, `?group_by=period|customer|product`;
 *   * KPI: nilai penjualan (akrual `Order.created_at`), qty, piutang invoice,
 *     kas masuk (`Payment` INBOUND SENT/DONE) - angka apa adanya dari backend;
 *   * tabel memakai `DenseTable` (bukan tabel paralel);
 *   * "Muat Ulang" memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * Read-only: halaman ini tidak pernah mengirim mutasi (tanpa POST/PUT/DELETE) dan
 * tidak memanggil Odoo. Guard route: `REPORTS_ROLES` (supervisor/admin/owner).
 */

const GROUP_BY_LABEL: Record<SalesGroupBy, string> = {
  period: 'Bulan',
  customer: 'Customer',
  product: 'Produk',
};

const GROUP_BY_OPTIONS: SelectOption[] = SALES_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

const ORDER_TYPE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua tipe' },
  ...SALES_ORDER_TYPES.map((value) => ({ value, label: value })),
];

/** Semua opsi dropdown keluar dari master MES (tanpa data karangan). */
const ALL_CUSTOMERS: SelectOption = { value: '', label: 'Semua customer' };
const ALL_PRODUCTS: SelectOption = { value: '', label: 'Semua produk' };

function formatIDR(value: number): string {
  return `Rp${value.toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function formatQty(value: number): string {
  return value.toLocaleString('id-ID');
}

const COLUMNS: DenseTableColumn<SalesReportRow>[] = [
  {
    key: 'label',
    label: 'Grup',
    render: (row) => (
      <span>
        <span className="font-medium text-foreground">{row.label}</span>
        {row.key === '' ? null : (
          <span className="ml-2 font-mono text-xs text-muted-foreground">{row.key}</span>
        )}
      </span>
    ),
  },
  {
    key: 'order_count',
    label: 'Order',
    align: 'right',
    render: (row) => formatQty(row.order_count),
  },
  {
    key: 'line_count',
    label: 'Baris',
    align: 'right',
    render: (row) => formatQty(row.line_count),
  },
  {
    key: 'total_qty',
    label: 'Qty',
    align: 'right',
    render: (row) => formatQty(row.total_qty),
  },
  {
    key: 'total_amount',
    label: 'Nilai (IDR)',
    align: 'right',
    render: (row) => (
      <span className="font-mono tabular-nums">{formatIDR(row.total_amount)}</span>
    ),
  },
];

export function SalesReportPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [productId, setProductId] = useState('');
  const [orderType, setOrderType] = useState('');
  const [groupBy, setGroupBy] = useState<SalesGroupBy>('period');
  /** Naik +1 setiap "Muat Ulang" → `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const customers = useQuery({
    queryKey: ['reports-sales-customers'],
    queryFn: () => fetchPartners(client, { limit: 200, is_customer: true }),
    staleTime: 300_000,
  });

  const products = useQuery({
    queryKey: ['reports-sales-products'],
    queryFn: () => fetchProducts(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const report = useQuery({
    queryKey: [
      'reports-sales',
      period,
      customerId,
      productId,
      orderType,
      groupBy,
      forceRefresh,
    ],
    queryFn: () =>
      fetchSalesReport(client, {
        period: period === '' ? null : period,
        customerId: customerId === '' ? null : Number(customerId),
        productId: productId === '' ? null : Number(productId),
        orderType: orderType === '' ? null : orderType,
        groupBy,
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const customerOptions: SelectOption[] = [
    ALL_CUSTOMERS,
    ...(customers.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} — ${row.name}`,
    })),
  ];

  const productOptions: SelectOption[] = [
    ALL_PRODUCTS,
    ...(products.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} — ${row.name}`,
    })),
  ];

  const rows = report.data?.rows ?? [];
  const summary = report.data?.summary;
  const queryError = report.error === null || report.error === undefined ? null : report.error;
  const loadError = queryError === null ? null : 'Gagal memuat laporan penjualan (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan Penjualan"
        subtitle="Agregat order (akrual), piutang invoice, dan kas masuk — DB MES, read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'Sales' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Input
            type="month"
            label="Periode (bulan berjalan default)"
            value={period}
            className="w-40"
            onChange={(event) => {
              setPeriod(event.target.value);
            }}
          />
          <Select
            label="Customer"
            options={customerOptions}
            value={customerId}
            className="w-56"
            onChange={(event) => {
              setCustomerId(event.target.value);
            }}
          />
          <Select
            label="Produk"
            options={productOptions}
            value={productId}
            className="w-56"
            onChange={(event) => {
              setProductId(event.target.value);
            }}
          />
          <Select
            label="Tipe order"
            options={ORDER_TYPE_OPTIONS}
            value={orderType}
            className="w-40"
            onChange={(event) => {
              setOrderType(event.target.value);
            }}
          />
          <Select
            label="Kelompokkan"
            options={GROUP_BY_OPTIONS}
            value={groupBy}
            className="w-40"
            onChange={(event) => {
              setGroupBy(event.target.value as SalesGroupBy);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="sales"
            filters={{
              period: period === '' ? null : period,
              customerId: customerId === '' ? null : Number(customerId),
              productId: productId === '' ? null : Number(productId),
              orderType: orderType === '' ? null : orderType,
              groupBy,
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={report.isFetching}
            onClick={() => {
              setForceRefresh((value) => value + 1);
            }}
          >
            Muat Ulang
          </Button>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Nilai Penjualan"
          value={formatIDR(summary?.total_amount ?? 0)}
          trend={`${formatQty(summary?.count_orders ?? 0)} order / ${formatQty(
            summary?.count_lines ?? 0,
          )} baris`}
          tone="blue"
          icon={TrendingUp}
        />
        <KpiCard
          label="Total Qty"
          value={`${formatQty(summary?.total_qty ?? 0)} pcs`}
          trend={`per ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="muted"
          icon={Layers}
        />
        <KpiCard
          label="Piutang (Invoice)"
          value={formatIDR(summary?.invoiced_amount ?? 0)}
          trend={`${formatQty(summary?.invoice_count ?? 0)} invoice (sebelum pajak)`}
          tone="coral"
          icon={FileText}
        />
        <KpiCard
          label="Kas Masuk (Payment)"
          value={formatIDR(summary?.paid_amount ?? 0)}
          trend={`${formatQty(summary?.payment_count ?? 0)} payment INBOUND SENT/DONE`}
          tone="blue"
          icon={Wallet}
        />
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={rows}
          loading={report.isLoading}
          error={loadError}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada penjualan pada filter ini."
        />
      </section>

      <p className="text-xs text-muted-foreground">
        {report.data === undefined
          ? 'Memuat rentang laporan…'
          : `Rentang ${report.data.period.from} s/d ${report.data.period.to}`}
        {report.data?.cached === true ? ' — dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
