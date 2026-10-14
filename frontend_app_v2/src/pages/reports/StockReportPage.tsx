import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Layers, RefreshCw, TrendingUp, Wallet } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { ExportButton } from '@/components/molecules/ExportButton';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  fetchStockReport,
  STOCK_GROUP_BY_VALUES,
  type StockGroupBy,
  type StockReportRow,
} from '@/api/reports';
import { fetchLocations } from '@/api/masterLocations';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * StockReportPage - route `/reports/stock` (H4.3, laporan stok snapshot).
 *
 * Data NYATA `GET /api/v1/reports/stock/` (`api/reports.ts` -> MODE.reportStock=real):
 *
 *   * sumber = Odoo `stock.quant` LIVE via jalur I7 (2 RPC), MES tidak menyimpan stok;
 *   * filter server: `?location_id=` (pk MES, usage internal), `?product_id=`, `?search=`,
 *     `?group_by=product|location`, `?only_nonzero=1`;
 *   * KPI: total qty, reserved, available, cakupan produk/lokasi (angka apa adanya backend);
 *   * tabel memakai `DenseTable` (bukan tabel paralel), kolom menyesuaikan `group_by`;
 *   * Muat Ulang memakai escape hatch `?_nocache=1` (bypass cache 300 dtk);
 *   * tombol Export **AKTIF** (H4.8: `ExportButton` -> `POST /api/v1/export/<report>/` = Excel/PDF); halaman read-only (tanpa mutasi).
 *
 * Read-only: halaman ini tidak pernah mengirim mutasi (tanpa POST/PUT/DELETE) dan
 * tidak menulis ke Odoo. Guard route: `REPORTS_ROLES` (supervisor/admin/owner).
 */

const GROUP_BY_LABEL: Record<StockGroupBy, string> = {
  product: 'Produk',
  location: 'Lokasi',
};

const GROUP_BY_OPTIONS: SelectOption[] = STOCK_GROUP_BY_VALUES.map((value) => ({
  value,
  label: GROUP_BY_LABEL[value],
}));

/** Semua opsi dropdown keluar dari master MES (tanpa data karangan). */
const ALL_LOCATIONS: SelectOption = { value: '', label: 'Semua lokasi' };
const ALL_PRODUCTS: SelectOption = { value: '', label: 'Semua produk' };

function formatQty(value: number): string {
  return value.toLocaleString('id-ID', { maximumFractionDigits: 2 });
}

/** Kolom menyesuaikan `group_by` (produk vs lokasi) - reuse `DenseTable`. */
function buildColumns(groupBy: StockGroupBy): DenseTableColumn<StockReportRow>[] {
  const columns: DenseTableColumn<StockReportRow>[] = [
    {
      key: 'label',
      label: groupBy === 'location' ? 'Lokasi' : 'Produk',
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
      key: 'total_qty',
      label: 'Qty',
      align: 'right',
      render: (row) => <span className="font-mono tabular-nums">{formatQty(row.total_qty)}</span>,
    },
    {
      key: 'reserved_qty',
      label: 'Reserved',
      align: 'right',
      render: (row) => (
        <span className="font-mono tabular-nums">{formatQty(row.reserved_qty)}</span>
      ),
    },
    {
      key: 'available_qty',
      label: 'Available',
      align: 'right',
      render: (row) => (
        <span className="font-mono tabular-nums">{formatQty(row.available_qty)}</span>
      ),
    },
  ];

  if (groupBy === 'location') {
    columns.push({
      key: 'products_count',
      label: 'Produk',
      align: 'right',
      render: (row) => formatQty(row.products_count ?? 0),
    });
    return columns;
  }

  columns.push({
    key: 'uom_code',
    label: 'UoM',
    render: (row) => row.uom_code ?? '',
  });
  columns.push({
    key: 'locations_count',
    label: 'Lokasi',
    align: 'right',
    render: (row) => formatQty(row.locations_count ?? 0),
  });
  return columns;
}

export function StockReportPage() {
  const client = useApiClient();

  const [locationId, setLocationId] = useState('');
  const [productId, setProductId] = useState('');
  const [search, setSearch] = useState('');
  const [groupBy, setGroupBy] = useState<StockGroupBy>('product');
  const [onlyNonzero, setOnlyNonzero] = useState(false);
  /** Naik +1 setiap Muat Ulang -> `?_nocache=1` dipakai sekali (force refresh). */
  const [forceRefresh, setForceRefresh] = useState(0);

  const locations = useQuery({
    queryKey: ['reports-stock-locations'],
    queryFn: () => fetchLocations(client, { limit: 200, usage: 'internal' }),
    staleTime: 300_000,
  });

  const products = useQuery({
    queryKey: ['reports-stock-products'],
    queryFn: () => fetchProducts(client, { limit: 200, active: true }),
    staleTime: 300_000,
  });

  const report = useQuery({
    queryKey: [
      'reports-stock',
      locationId,
      productId,
      search,
      groupBy,
      onlyNonzero,
      forceRefresh,
    ],
    queryFn: () =>
      fetchStockReport(client, {
        locationId: locationId === '' ? null : Number(locationId),
        productId: productId === '' ? null : Number(productId),
        search: search === '' ? null : search,
        groupBy,
        onlyNonzero,
        nocache: forceRefresh > 0,
      }),
    staleTime: 60_000,
  });

  const locationOptions: SelectOption[] = [
    ALL_LOCATIONS,
    ...(locations.data?.rows ?? []).map((row) => ({
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
  const loadError = queryError === null ? null : 'Gagal memuat laporan stok (perlu login?).';


  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Laporan Stok"
        subtitle="Snapshot stok Odoo (stock.quant) - on-demand, DB MES read-only"
        breadcrumb={[{ label: 'Reports' }, { label: 'Stock' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
        <div className="flex flex-wrap items-end gap-3">
          <Select
            label="Lokasi (internal)"
            options={locationOptions}
            value={locationId}
            className="w-56"
            onChange={(event) => {
              setLocationId(event.target.value);
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
          <Input
            label="Cari produk"
            value={search}
            className="w-56"
            placeholder="kode / nama"
            onChange={(event) => {
              setSearch(event.target.value);
            }}
          />
          <Select
            label="Kelompokkan"
            options={GROUP_BY_OPTIONS}
            value={groupBy}
            className="w-40"
            onChange={(event) => {
              setGroupBy(event.target.value as StockGroupBy);
            }}
          />
          <Checkbox
            label="Sembunyikan qty 0"
            checked={onlyNonzero}
            onCheckedChange={setOnlyNonzero}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ExportButton
            report="stock"
            filters={{
              locationId: locationId === '' ? null : Number(locationId),
              productId: productId === '' ? null : Number(productId),
              search: search === '' ? null : search,
              groupBy,
              onlyNonzero,
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
          label="Total Qty"
          value={formatQty(summary?.total_qty ?? 0)}
          trend={`${formatQty(summary?.quant_count ?? 0)} baris stock.quant`}
          tone="blue"
          icon={Layers}
        />
        <KpiCard
          label="Reserved"
          value={formatQty(summary?.reserved_qty ?? 0)}
          trend="tertahan untuk delivery/produksi"
          tone="muted"
          icon={FileText}
        />
        <KpiCard
          label="Available"
          value={formatQty(summary?.available_qty ?? 0)}
          trend="qty dikurangi reserved (dihitung backend)"
          tone="coral"
          icon={Wallet}
        />
        <KpiCard
          label="Cakupan"
          value={`${formatQty(summary?.product_count ?? 0)} produk`}
          trend={`${formatQty(summary?.location_count ?? 0)} lokasi - ${GROUP_BY_LABEL[report.data?.group_by ?? groupBy]}`}
          tone="blue"
          icon={TrendingUp}
        />
      </section>

      {(summary?.unmapped_product_count ?? 0) > 0 ? (
        <p className="text-xs text-muted-foreground">
          {`Perhatian: ${formatQty(summary?.unmapped_product_count ?? 0)} produk Odoo belum ter-map ke master MES (${formatQty(summary?.unmapped_qty ?? 0)} qty) - tidak masuk baris di bawah.`}
        </p>
      ) : null}

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={buildColumns(report.data?.group_by ?? groupBy)}
          rows={rows}
          loading={report.isLoading}
          error={loadError}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada stok pada filter ini."
        />
      </section>

      <p className="text-xs text-muted-foreground">
        {report.data === undefined
          ? 'Memuat snapshot stok...'
          : `Sumber ${report.data.source} - dibuat ${report.data.generated_at}`}
        {report.data?.cached === true ? ' - dari cache backend (5 menit)' : ''}
      </p>
    </div>
  );
}
