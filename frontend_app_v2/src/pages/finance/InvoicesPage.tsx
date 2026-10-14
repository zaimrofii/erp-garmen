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
import { fetchCustomerInvoices, INVOICES_LIMIT_MAX } from '@/api/customerInvoices';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  INVOICE_STATE_FILTERS,
  invoiceStateLabel,
  invoiceStateTone,
  isInvoiceStateFilter,
  stateParamForFilter,
} from '@/lib/customer-invoice';
import { CARD } from '@/lib/tokens';
import type { CustomerInvoiceRow, CustomerInvoiceState } from '@/types/customer-invoice';

/**
 * InvoicesPage - route `/finance/customer-invoices` (H3.1, app Finance).
 *
 * Daftar invoice MES NYATA dari `GET /api/v1/finance/customer-invoices/`
 * (`api/customerInvoices.ts` → MODE.customerInvoices='real') — **berbeda** dari
 * `InvoiceQueuePage` (F15) yang menampilkan antrean I5 read-only dari `SyncRecord`.
 *
 *   * filter server: `?search=` (kode/customer/order) + `?state=` (tab per state);
 *   * kolom: Kode, Order, Customer, Tanggal, Total, State, Odoo ID (`-` = belum push);
 *   * klik baris → detail; "Invoice Baru" → `/finance/invoices/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `FINANCE_ROLES`; izin **tulis** API = ADMIN/OWNER.
 */

const EMPTY_ROWS: CustomerInvoiceRow[] = [];

const CSV_COLUMNS: CsvColumn<CustomerInvoiceRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'order_no', label: 'Order' },
  { key: 'customer_name', label: 'Customer' },
  { key: 'invoice_date', label: 'Tanggal' },
  { key: 'due_date', label: 'Jatuh tempo' },
  { key: 'state', label: 'State' },
  { key: 'amount_total', label: 'Total' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<CustomerInvoiceRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  {
    key: 'order_no',
    label: 'Order',
    render: (row) => <span className="font-mono tabular-nums">{row.order_no ?? '-'}</span>,
  },
  { key: 'customer_name', label: 'Customer' },
  { key: 'invoice_date', label: 'Tanggal' },
  { key: 'amount_total', label: 'Total', align: 'right' },
  {
    key: 'state',
    label: 'State',
    render: (row) => (
      <Badge tone={invoiceStateTone(row.state)}>{invoiceStateLabel(row.state)}</Badge>
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
        <span className="font-mono tabular-nums">{String(row.odoo_id)}</span>
      ),
  },
];

export function InvoicesPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | CustomerInvoiceState>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['customer-invoices', search, filter],
    queryFn: () =>
      fetchCustomerInvoices(client, {
        search,
        state: stateParamForFilter(filter),
        limit: INVOICES_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || filter !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    if (!isInvoiceStateFilter(id)) return;

    setFilter(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setFilter('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Customer Invoice"
        subtitle={`Invoice MES (harga & pajak nyata, draft ke Odoo) — ${String(
          data?.total_count ?? 0,
        )} baris`}
        breadcrumb={[{ label: 'Finance', href: '/finance/invoices' }, { label: 'Invoice' }]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/finance/invoices/new')}>
            Invoice Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari invoice"
          searchPlaceholder="Cari kode / customer / order"
          filters={INVOICE_STATE_FILTERS}
          activeFilter={filter}
          onFilterChange={handleFilter}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'customer-invoices.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat customer invoice.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/finance/invoices/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada invoice yang cocok dengan filter.'
              : 'Belum ada invoice. Tambahkan lewat tombol "Invoice Baru".'
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

