import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge, type BadgeTone } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchPurchaseOrders, type PurchaseOrderRow } from '@/api/purchase';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD, TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';

/**
 * PurchaseOrdersPage - route `/purchase/orders` (F2C.2).
 * `vendor_code`/`date_order` bisa `null` → "—"; `lines[]` ditampilkan di modal.
 */

const ALL = 'all';
const EMPTY_ROWS: PurchaseOrderRow[] = [];

const STATE_TONE: Record<string, BadgeTone> = {
  draft: 'muted',
  sent: 'blue',
  purchase: 'blue',
  done: 'blue',
  cancel: 'coral',
};

const STATES = ['draft', 'sent', 'purchase', 'done', 'cancel'];

const FILTERS = [
  { id: ALL, label: 'Semua' },
  ...STATES.map((state) => ({ id: state, label: state })),
];

function formatRupiah(value: number): string {
  return `Rp ${value.toLocaleString('id-ID')}`;
}

const CSV_COLUMNS: CsvColumn<PurchaseOrderRow>[] = [
  { key: 'name', label: 'name' },
  { key: 'partner_name', label: 'vendor' },
  { key: 'vendor_code', label: 'vendor_code' },
  { key: 'state', label: 'state' },
  { key: 'amount_total', label: 'amount_total' },
  { key: 'date_order', label: 'date_order' },
];

export function PurchaseOrdersPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [stateFilter, setStateFilter] = useState<string>(ALL);
  const [selected, setSelected] = useState<PurchaseOrderRow | null>(null);

  const orders = useQuery({
    queryKey: ['purchase-orders'],
    queryFn: () => fetchPurchaseOrders(client),
    staleTime: 15_000,
  });

  const { exportCsv } = useCsvExport();
  const rows = orders.data ?? EMPTY_ROWS;

  const columns = useMemo<DenseTableColumn<PurchaseOrderRow>[]>(
    () => [
      {
        key: 'name',
        label: 'Kode',
        render: (row) => <span className="font-mono tabular-nums">{row.name ?? '—'}</span>,
      },
      {
        key: 'partner_name',
        label: 'Vendor',
        render: (row) => (
          <span className="flex flex-col">
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {row.vendor_code ?? '—'}
            </span>
            <span className="text-sm text-foreground">{row.partner_name ?? '—'}</span>
          </span>
        ),
      },
      {
        key: 'state',
        label: 'Status',
        render: (row) => (
          <Badge tone={STATE_TONE[row.state ?? ''] ?? 'muted'}>{row.state ?? '—'}</Badge>
        ),
      },
      {
        key: 'amount_total',
        label: 'Total',
        align: 'right',
        render: (row) => formatRupiah(row.amount_total ?? 0),
      },
      {
        key: 'date_order',
        label: 'Tanggal',
        render: (row) => (row.date_order === null ? '—' : row.date_order.slice(0, 10)),
      },
    ],
    [],
  );

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();

    return rows.filter((row) => {
      if (stateFilter !== ALL && row.state !== stateFilter) return false;
      if (needle.length === 0) return true;

      return (
        (row.name ?? '').toLowerCase().includes(needle) ||
        (row.partner_name ?? '').toLowerCase().includes(needle) ||
        (row.vendor_code ?? '').toLowerCase().includes(needle)
      );
    });
  }, [rows, search, stateFilter]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    setStateFilter(id);
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Purchase Orders"
        subtitle="Daftar PO Odoo beserta vendor dan nilainya (klik baris untuk rincian)"
        breadcrumb={[{ label: 'Purchase' }, { label: 'Orders' }]}
        actions={
          // H2.2 (aditif): pintu ke CRUD PO **MES** (`/purchase/orders/new`).
          // Daftar di halaman ini tetap B10 (read-only dari Odoo) — tidak diubah.
          <Button icon={Plus} onClick={() => navigate('/purchase/orders/new')}>
            Buat PO Baru
          </Button>
        }
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari PO"
        searchPlaceholder="Cari kode PO / vendor"
        filters={FILTERS}
        activeFilter={stateFilter}
        onFilterChange={handleFilter}
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'purchase-orders.csv', CSV_COLUMNS)}
        refreshing={orders.isFetching}
        onRefresh={() => {
          void orders.refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={columns}
          rows={pagination.pageRows}
          loading={orders.isLoading}
          error={orders.error === null ? null : 'Gagal memuat daftar purchase order.'}
          onRetry={() => {
            void orders.refetch();
          }}
          onRowClick={setSelected}
          emptyMessage="Tidak ada PO yang cocok dengan filter."
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

      <Modal
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected === null ? 'Detail PO' : `PO ${selected.name ?? ''}`}
        description={
          selected === null
            ? undefined
            : `${selected.partner_name ?? selected.vendor_code ?? '—'} - ${selected.state ?? '—'}`
        }
        footer={
          <Button variant="secondary" onClick={() => setSelected(null)}>
            Tutup
          </Button>
        }
      >
        {selected === null ? null : (
          <div className="flex flex-col gap-3">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th scope="col" className={TABLE_HEAD}>
                    Produk
                  </th>
                  <th scope="col" className={TABLE_HEAD}>
                    Deskripsi
                  </th>
                  <th scope="col" className={cn(TABLE_HEAD, 'text-right')}>
                    Qty
                  </th>
                  <th scope="col" className={cn(TABLE_HEAD, 'text-right')}>
                    Harga
                  </th>
                  <th scope="col" className={cn(TABLE_HEAD, 'text-right')}>
                    Subtotal
                  </th>
                </tr>
              </thead>
              <tbody>
                {selected.lines.length === 0 ? (
                  <tr>
                    <td className={TABLE_CELL} colSpan={5}>
                      Tidak ada baris PO.
                    </td>
                  </tr>
                ) : (
                  selected.lines.map((line, index) => (
                    <tr key={`${line.product_code ?? 'x'}-${index}`}>
                      <td className={cn(TABLE_CELL, 'font-mono tabular-nums')}>
                        {line.product_code ?? '—'}
                      </td>
                      <td className={TABLE_CELL}>{line.description ?? '—'}</td>
                      <td className={cn(TABLE_CELL, 'text-right')}>{line.qty}</td>
                      <td className={cn(TABLE_CELL, 'text-right')}>
                        {formatRupiah(line.price_unit)}
                      </td>
                      <td className={cn(TABLE_CELL, 'text-right')}>
                        {formatRupiah(line.subtotal)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </Modal>
    </div>
  );
}
