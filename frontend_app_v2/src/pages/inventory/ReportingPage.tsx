import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertOctagon, Boxes, Package } from 'lucide-react';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { KpiCard } from '@/components/molecules/KpiCard';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import {
  fetchLocationStock,
  type LocationStockReport,
  type LocationStockRow,
} from '@/api/inventory';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * InventoryReportingPage - route `/inventory/reporting` (inventory/admin/owner).
 *
 * REAL sejak F5.4.CLOSE (backend B30, `GET /inventory/reporting/`): laporan =
 * **agregat stok per lokasi MES** (`rows[]` = `location_code`, `location_name`,
 * `product_count`, `total_qty`, `last_updated`; amplop `total_locations` +
 * `generated_at`) — BUKAN riwayat mutasi stok (endpoint mutasi tidak ada di kontrak
 * v4.3). Filter periode dibuang karena backend hanya menerima `?location_code=`.
 *
 * Fail-safe backend: env `ODOO_LOCATION_*` kosong → 4 baris tetap muncul dengan
 * `total_qty=0`/`last_updated=null` (ditampilkan "-"), jadi halaman tidak error.
 */

const EMPTY_ROWS: LocationStockRow[] = [];

const CSV_COLUMNS: CsvColumn<LocationStockRow>[] = [
  { key: 'location_code', label: 'location_code' },
  { key: 'location_name', label: 'location_name' },
  { key: 'product_count', label: 'product_count' },
  { key: 'total_qty', label: 'total_qty' },
  { key: 'last_updated', label: 'last_updated' },
];

const COLUMNS: DenseTableColumn<LocationStockRow>[] = [
  {
    key: 'location_code',
    label: 'Kode Lokasi',
    render: (row) => <span className="font-mono tabular-nums">{row.location_code}</span>,
  },
  { key: 'location_name', label: 'Nama Lokasi' },
  {
    key: 'product_count',
    label: 'Produk',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.product_count}</span>,
  },
  {
    key: 'total_qty',
    label: 'Qty',
    align: 'right',
    render: (row) => <span className="font-medium tabular-nums">{row.total_qty}</span>,
  },
  {
    key: 'last_updated',
    label: 'Terakhir Diperbarui',
    render: (row) =>
      row.last_updated === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        new Date(row.last_updated).toLocaleString('id-ID')
      ),
  },
];

export function InventoryReportingPage() {
  const client = useApiClient();
  const [search, setSearch] = useState('');

  const report = useQuery({
    queryKey: ['inventory-reporting'],
    queryFn: () => fetchLocationStock(client),
    staleTime: 15_000,
  });

  const { exportCsv } = useCsvExport();
  const reportData: LocationStockReport | undefined = report.data;
  const rows = reportData?.rows ?? EMPTY_ROWS;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rows;

    return rows.filter(
      (row) =>
        row.location_code.toLowerCase().includes(needle) ||
        row.location_name.toLowerCase().includes(needle),
    );
  }, [rows, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  const totalQty = rows.reduce((total, row) => total + row.total_qty, 0);
  const emptyCount = rows.filter((row) => row.total_qty === 0).length;
  const generatedAt = reportData?.generated_at ?? '';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Inventory Reporting"
        subtitle="Agregat stok per lokasi MES (WH/WIP, Virtual/Production, WH/FG, Virtual/Scrap)"
        breadcrumb={[{ label: 'Inventory' }, { label: 'Reporting' }]}
      />

      <section className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <KpiCard
          label="Total Lokasi"
          value={String(reportData?.total_locations ?? 0)}
          trend="GET /inventory/reporting/"
          tone="blue"
          icon={Boxes}
        />
        <KpiCard
          label="Total Stok"
          value={`${totalQty.toLocaleString('id-ID')} pcs`}
          trend="jumlah qty seluruh lokasi"
          tone="muted"
          icon={Package}
        />
        <KpiCard
          label="Lokasi Kosong"
          value={String(emptyCount)}
          trend="qty 0 (bisa karena env lokasi Odoo belum diisi)"
          tone={emptyCount > 0 ? 'coral' : 'muted'}
          icon={AlertOctagon}
        />
      </section>

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari lokasi"
        searchPlaceholder="Cari kode / nama lokasi"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'inventory-reporting.csv', CSV_COLUMNS)}
        refreshing={report.isFetching}
        onRefresh={() => {
          void report.refetch();
        }}
      />

      <p className="text-xs text-muted-foreground">
        {generatedAt.length === 0
          ? 'Waktu pembuatan laporan belum tersedia.'
          : `Laporan dibuat: ${new Date(generatedAt).toLocaleString('id-ID')}`}
      </p>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat laporan stok per lokasi.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Tidak ada lokasi yang cocok."
        />
      </section>

      <PaginationBar
        page={pagination.page}
        totalPages={pagination.totalPages}
        rangeStart={pagination.rangeStart}
        rangeEnd={pagination.rangeEnd}
        total={pagination.total}
        canPrev={pagination.canPrev}
        canNext={pagination.canNext}
        onPrev={pagination.goPrev}
        onNext={pagination.goNext}
      />
    </div>
  );
}
