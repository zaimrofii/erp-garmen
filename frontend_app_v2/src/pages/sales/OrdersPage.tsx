import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { fetchOrders, SALES_ORDERS_LIMIT_MAX } from '@/api/salesOrders';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  displayDate,
  displayOrDash,
  ORDER_STATE_FILTERS,
  orderStateLabel,
  stateParamForFilter,
} from '@/lib/sales-order';
import { CARD } from '@/lib/tokens';
import type { SalesOrderRow } from '@/types/sales-order';

/**
 * OrdersPage - route `/sales/orders` (H2.1, app Sales).
 *
 * Transaksi satu arah MES → Odoo (`docs/CHANGES-DETAIL-H1H5.md` §1): daftar order
 * NYATA dari `GET /api/v1/garmen/orders/` (`api/salesOrders.ts`, MODE='real').
 *
 *   * filter server: `?search=` (kode/nama customer) + `?state=` (DRAFT/CONFIRMED/
 *     DONE/CANCELLED);
 *   * kolom: Kode, Customer, Deadline, Baris, Total, State, Odoo ID;
 *   * klik baris → detail (`/sales/orders/:id`); "Order Baru" → `/sales/orders/new`;
 *   * izin tulis API hanya ADMIN/OWNER (backend `api/orders.py`); guard route
 *     `SALES_ROLES` di `App.tsx`.
 */

const EMPTY_ROWS: SalesOrderRow[] = [];

const STATE_IDS: readonly string[] = ORDER_STATE_FILTERS.map((filter) => filter.id);

/** PURE - menyempitkan `string` dari Tabs ke salah satu id filter. */
function isStateFilter(value: string): boolean {
  return STATE_IDS.includes(value);
}

const CSV_COLUMNS: CsvColumn<SalesOrderRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'customer_name', label: 'Customer' },
  { key: 'state', label: 'State' },
  { key: 'deadline', label: 'Deadline' },
  { key: 'lines_count', label: 'Baris' },
  { key: 'amount_total', label: 'Total' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<SalesOrderRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'customer_name', label: 'Customer', render: (row) => displayOrDash(row.customer_name) },
  { key: 'deadline', label: 'Deadline', render: (row) => displayDate(row.deadline) },
  {
    key: 'lines_count',
    label: 'Baris',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.lines_count}</span>,
  },
  {
    key: 'amount_total',
    label: 'Total',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.amount_total}</span>,
  },
  {
    key: 'state',
    label: 'State',
    render: (row) => (
      <Badge tone={row.state === 'CANCELLED' ? 'coral' : 'muted'}>{orderStateLabel(row.state)}</Badge>
    ),
  },
  {
    key: 'odoo_id',
    label: 'Odoo ID',
    align: 'right',
    render: (row) =>
      row.odoo_id === null ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="tabular-nums">{row.odoo_id}</span>
      ),
  },
];

export function OrdersPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [state, setState] = useState('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['sales-orders', search, state],
    queryFn: () =>
      fetchOrders(client, {
        search,
        state: stateParamForFilter(state),
        limit: SALES_ORDERS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || state !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleState(id: string): void {
    if (!isStateFilter(id)) return;

    setState(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setState('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Sales Order"
        subtitle={`Order MES — ${String(data?.total_count ?? 0)} baris (push Odoo saat dikonfirmasi)`}
        breadcrumb={[{ label: 'Sales', href: '/sales/orders' }, { label: 'Order' }]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/sales/orders/new')}>
            Order Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari order"
          searchPlaceholder="Cari kode / customer"
          filters={ORDER_STATE_FILTERS}
          activeFilter={state}
          onFilterChange={handleState}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'sales-orders.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <Button variant="secondary" size="sm" disabled={!hasFilter} onClick={resetFilters}>
            Reset Filter
          </Button>
        </div>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat Sales Order.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/sales/orders/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada order yang cocok dengan filter.'
              : 'Belum ada order. Tambahkan lewat tombol "Order Baru".'
          }
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

