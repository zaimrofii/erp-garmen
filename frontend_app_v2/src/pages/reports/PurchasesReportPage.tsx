import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Layers, RefreshCw, TrendingDown, Wallet } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchPurchasesReport,
  PURCHASES_GROUP_BY_VALUES,
  PURCHASES_STATUS_VALUES,
  type PurchasesGroupBy,
  type PurchasesReportRow,
} from '@/api/reports';
import { fetchPartners } from '@/api/masterPartners';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * PurchasesReportPage - route `/reports/purchases` (H4.2, laporan pembelian).
 *
 * Data NYATA `GET /api/v1/reports/purchases/` (`api/reports.ts` -> MODE.reportPurchases=real):
 *
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan), `?vendor_id=`,
 *     `?product_id=`, `?status=`, `?group_by=period|vendor|product`;
 *   * KPI: nilai pembelian (akrual `PurchaseOrder.created_at`), qty, utang bill,
 *     kas keluar (`Payment` OUTBOUND SENT/DONE) - angka apa adanya dari backend;
 *   * tabel memakai `DenseTable` (bukan tabel paralel);
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * Read-only: halaman ini tidak pernah mengirim mutasi (tanpa POST/PUT/DELETE) dan
 * tidak memanggil Odoo. Guard route: `REPORTS_ROLES` (supervisor/admin/owner).
 */

const GROUP_BY_LABEL: Record<PurchasesGroupBy, string> = {
  period: 'Bulan',
  vendor: 'Vendor',
  product: 'Produk',
};

const GROUP_BY_OPTIONS: SelectOption[] = PURCHASES_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

const STATUS_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua status' },
  ...PURCHASES_STATUS_VALUES.map((value) => ({ value, label: value })),
];

/** Semua opsi dropdown keluar dari master MES (tanpa data karangan). */
const ALL_VENDORS: SelectOption = { value: '', label: 'Semua vendor' };
const ALL_PRODUCTS: SelectOption = { value: '', label: 'Semua produk' };

function formatIDR(value: number): string {
  return `Rp${value.toLocaleString('id-ID', { maximumFractionDigits: 0 })}`;
}

function formatQty(value: number): string {
  return value.toLocaleString('id-ID');
}

const COLUMNS: DenseTableColumn<PurchasesReportRow>[] = [
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
    key: 'purchase_count',
    label: 'PO',
    align: 'right',
    render: (row) => formatQty(row.purchase_count),
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

export function PurchasesReportPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  const [vendorId, setVendorId] = useState('');
  const [productId, setProductId] = useState('');
  const [status, setStatus] = useState('');
  const [groupBy, setGroupBy] = useState<PurchasesGroupBy>('period');
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const vendors = useQuery({
    queryKey: ['reports-purchases-vendors'],
    queryFn: () => fetchPartners(client, { limit: 200, is_vendor: true }),
    staleTime: 300_000,
  });

  const products = useQuery({
    queryKey: ['reports-purchases-products'],
    queryFn: () => fetchProducts(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const report = useQuery({
    queryKey: [
      'reports-purchases',
      period,
      vendorId,
      productId,
      status,
      groupBy,
      forceRefresh,
    ],
    queryFn: () =>
      fetchPurchasesReport(client, {
        period: period === '' ? null : period,
        vendorId: vendorId === '' ? null : Number(vendorId),
        productId: productId === '' ? null : Number(productId),
        status: status === '' ? null : status,
        groupBy,
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const vendorOptions: SelectOption[] = [
    ALL_VENDORS,
    ...(vendors.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} - ${row.name}`,
    })),
  ];

  const productOptions: SelectOption[] = [
    ALL_PRODUCTS,
    ...(products.data?.rows ?? []).map((row) => ({
      value: String(row.id),
      label: `${row.code} - ${row.name}`,
    })),
  ];

  const rows = report.data?.rows ?? [];
  const summary = report.data?.summary;
  const queryError = report.error === null || report.error === undefined ? null : report.error;
  const loadError = queryError === null ? null : 'Gagal memuat laporan pembelian (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan Pembelian"
        subtitle="Agregat PO (akrual), utang vendor bill, dan kas keluar - DB MES, read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'Purchases' }]}
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
            label="Vendor"
            options={vendorOptions}
            value={vendorId}
            className="w-56"
            onChange={(event) => {
              setVendorId(event.target.value);
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
            label="Status PO"
            options={STATUS_OPTIONS}
            value={status}
            className="w-40"
            onChange={(event) => {
              setStatus(event.target.value);
            }}
          />
          <Select
            label="Kelompokkan"
            options={GROUP_BY_OPTIONS}
            value={groupBy}
            className="w-40"
            onChange={(event) => {
              setGroupBy(event.target.value as PurchasesGroupBy);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="purchases"
            filters={{
              period: period === '' ? null : period,
              vendorId: vendorId === '' ? null : Number(vendorId),
              productId: productId === '' ? null : Number(productId),
              status: status === '' ? null : status,
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
          label="Nilai Pembelian"
          value={formatIDR(summary?.total_amount ?? 0)}
          trend={`${formatQty(summary?.count_purchases ?? 0)} PO / ${formatQty(
            summary?.count_lines ?? 0,
          )} baris`}
          tone="blue"
          icon={TrendingDown}
        />
        <KpiCard
          label="Total Qty"
          value={`${formatQty(summary?.total_qty ?? 0)} unit`}
          trend={`per ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="muted"
          icon={Layers}
        />
        <KpiCard
          label="Utang (Vendor Bill)"
          value={formatIDR(summary?.billed_amount ?? 0)}
          trend={`${formatQty(summary?.bill_count ?? 0)} bill (sebelum pajak)`}
          tone="coral"
          icon={FileText}
        />
        <KpiCard
          label="Kas Keluar (Payment)"
          value={formatIDR(summary?.paid_amount ?? 0)}
          trend={`${formatQty(summary?.payment_count ?? 0)} payment OUTBOUND SENT/DONE`}
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
          emptyMessage="Tidak ada pembelian pada filter ini."
        />
      </section>

      <p className="text-xs text-muted-foreground">
        {report.data === undefined
          ? 'Memuat rentang laporan...'
          : `Rentang ${report.data.period.from} s/d ${report.data.period.to}`}
        {report.data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
