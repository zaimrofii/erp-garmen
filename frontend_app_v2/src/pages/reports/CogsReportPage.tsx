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
  fetchCogsReport,
  COGS_GROUP_BY_VALUES,
  COGS_ORDER_TYPES,
  type CogsGroupBy,
  type CogsReportRow,
} from '@/api/reports';
import { fetchPartners } from '@/api/masterPartners';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * CogsReportPage - route `/reports/cogs` (H4.4, laporan HPP/laba kotor).
 *
 * Data NYATA `GET /api/v1/reports/cogs/` (`api/reports.ts` -> MODE.reportCogs=real):
 *
 *   * filter server: `?period=YYYY-MM` (default bulan berjalan), `?customer_id=`,
 *     `?product_id=`, `?order_type=`, `?group_by=period|customer|product`;
 *   * HPP **simplified** (`qty x Product.cost_price`); tenaga kerja + overhead =
 *     sprint terpisah. Angka apa adanya dari backend (tidak dihitung ulang di UI);
 *   * KPI: omzet, HPP, laba kotor, margin % + peringatan `rows_with_missing_cost`
 *     (COGS **tidak difabrikasi** - `cost_price = 0` / produk belum tersinkron);
 *   * tabel memakai `DenseTable` (bukan tabel paralel);
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * Read-only: halaman ini tidak pernah mengirim mutasi (tanpa POST/PUT/DELETE) dan
 * tidak menyentuh master harga (`Product.cost_price`/H3.5). Guard route: `REPORTS_ROLES`.
 */

const GROUP_BY_LABEL: Record<CogsGroupBy, string> = {
  period: 'Bulan',
  customer: 'Customer',
  product: 'Produk',
};

const GROUP_BY_OPTIONS: SelectOption[] = COGS_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

const ORDER_TYPE_OPTIONS: SelectOption[] = [
  { value: '', label: 'Semua tipe' },
  ...COGS_ORDER_TYPES.map((value) => ({ value, label: value })),
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

function formatPct(value: number): string {
  return `${value.toLocaleString('id-ID', { maximumFractionDigits: 2 })}%`;
}

const COLUMNS: DenseTableColumn<CogsReportRow>[] = [
  {
    key: 'label',
    label: 'Grup',
    render: (row) => (
      <span>
        <span className="font-medium text-foreground">{row.label}</span>
        {row.key === '' ? null : (
          <span className="ml-2 font-mono text-xs text-muted-foreground">{row.key}</span>
        )}
        {row.has_missing_cost ? (
          <span className="ml-2 text-xs text-muted-foreground">
            {row.missing_cost_reason === 'no_product' ? '(produk belum sinkron)' : '(HPP belum diisi)'}
          </span>
        ) : null}
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
    key: 'sales_amount',
    label: 'Omzet (IDR)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.sales_amount)}</span>,
  },
  {
    key: 'cogs_amount',
    label: 'HPP (IDR)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.cogs_amount)}</span>,
  },
  {
    key: 'gross_profit',
    label: 'Laba Kotor (IDR)',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatIDR(row.gross_profit)}</span>,
  },
  {
    key: 'gross_margin_pct',
    label: 'Margin',
    align: 'right',
    render: (row) => <span className="font-mono tabular-nums">{formatPct(row.gross_margin_pct)}</span>,
  },
];

export function CogsReportPage() {
  const client = useApiClient();

  const [period, setPeriod] = useState('');
  const [customerId, setCustomerId] = useState('');
  const [productId, setProductId] = useState('');
  const [orderType, setOrderType] = useState('');
  const [groupBy, setGroupBy] = useState<CogsGroupBy>('period');
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const customers = useQuery({
    queryKey: ['reports-cogs-customers'],
    queryFn: () => fetchPartners(client, { limit: 200, is_customer: true }),
    staleTime: 300_000,
  });

  const products = useQuery({
    queryKey: ['reports-cogs-products'],
    queryFn: () => fetchProducts(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const report = useQuery({
    queryKey: [
      'reports-cogs',
      period,
      customerId,
      productId,
      orderType,
      groupBy,
      forceRefresh,
    ],
    queryFn: () =>
      fetchCogsReport(client, {
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
  const loadError = queryError === null ? null : 'Gagal memuat laporan HPP (perlu login?).';


  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan HPP (COGS)"
        subtitle="Omzet, HPP simplified (qty x cost_price), laba kotor, margin % - DB MES, read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'HPP (COGS)' }]}
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
              setGroupBy(event.target.value as CogsGroupBy);
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="cogs"
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
          label="Omzet"
          value={formatIDR(summary?.total_sales ?? 0)}
          trend={`${formatQty(summary?.order_count ?? 0)} order / ${formatQty(
            summary?.line_count ?? 0,
          )} baris`}
          tone="blue"
          icon={TrendingUp}
        />
        <KpiCard
          label="HPP (Simplified)"
          value={formatIDR(summary?.total_cogs ?? 0)}
          trend="qty x cost_price (tanpa tenaga kerja/overhead)"
          tone="muted"
          icon={FileText}
        />
        <KpiCard
          label="Laba Kotor"
          value={formatIDR(summary?.total_gross_profit ?? 0)}
          trend={`${formatQty(summary?.qty_total ?? 0)} unit terjual`}
          tone="coral"
          icon={Wallet}
        />
        <KpiCard
          label="Margin Kotor"
          value={formatPct(summary?.gross_margin_pct ?? 0)}
          trend={`per ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="blue"
          icon={Layers}
        />
      </section>

      {(summary?.rows_with_missing_cost ?? 0) > 0 ? (
        <p className="text-xs text-muted-foreground">
          {`Perhatian: ${formatQty(summary?.rows_with_missing_cost ?? 0)} baris order belum punya HPP (produk belum tersinkron atau cost_price masih 0) - COGS-nya dihitung 0 dan tidak dikarang. Lengkapi lewat master produk.`}
        </p>
      ) : null}

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
          ? 'Memuat rentang laporan...'
          : `Rentang ${report.data.period.from} s/d ${report.data.period.to} - mata uang ${report.data.summary.currency}`}
        {report.data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
