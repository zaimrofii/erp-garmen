import { useQuery } from '@tanstack/react-query';
import { Card } from '@/components/atoms/Card';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchLocationStock, type LocationStockRow } from '@/api/inventory';
import { useApiClient } from '@/hooks/useApiClient';

/**
 * ConfigurationPage - route `/inventory/config` (khusus `admin`).
 *
 * F2C.2: master "Warehouse"/"UoM" DIBUANG (tidak ada sumber backend — operasi kini
 * monitor sync & produk tanpa `uom`).
 *
 * F5.4.CLOSE: daftar lokasi berasal dari endpoint REAL `GET /inventory/reporting/`
 * (B30) — `rows[]` = lokasi MES + `product_count`/`total_qty`; tidak lagi diturunkan
 * dari mutasi stok dummy (endpoint mutasi stok tidak ada di kontrak v4.3).
 */

const LOCATION_COLUMNS: DenseTableColumn<LocationStockRow>[] = [
  {
    key: 'location_code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.location_code}</span>,
  },
  { key: 'location_name', label: 'Nama' },
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
];

export function ConfigurationPage() {
  const client = useApiClient();

  const report = useQuery({
    queryKey: ['inventory-reporting'],
    queryFn: () => fetchLocationStock(client),
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Inventory Configuration"
        subtitle="Master lokasi MES (read-only, dari laporan stok per lokasi)"
        breadcrumb={[{ label: 'Inventory' }, { label: 'Configuration' }]}
      />

      <Card as="section" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-foreground">Locations</h2>
        <DenseTable
          columns={LOCATION_COLUMNS}
          rows={report.data?.rows ?? []}
          loading={report.isLoading}
          error={report.error === null ? null : 'Gagal memuat daftar lokasi.'}
          onRetry={() => {
            void report.refetch();
          }}
          emptyMessage="Belum ada lokasi."
        />
      </Card>
    </div>
  );
}
