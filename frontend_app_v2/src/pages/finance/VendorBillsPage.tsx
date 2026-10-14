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
import { fetchVendorBills, VENDOR_BILLS_LIMIT_MAX } from '@/api/vendorBills';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  BILL_STATE_FILTERS,
  billStateLabel,
  billStateTone,
  isBillStateFilter,
  stateParamForFilter,
} from '@/lib/vendor-bill';
import { CARD } from '@/lib/tokens';
import type { VendorBillRow, VendorBillState } from '@/types/vendor-bill';

/**
 * VendorBillsPage - route `/finance/vendor-bills` (H3.2, app Finance).
 *
 * Daftar bill MES NYATA dari `GET /api/v1/finance/vendor-bills/`
 * (`api/vendorBills.ts` → MODE.vendorBills='real') — **berbeda** dari:
 *
 *   * I6 `MaterialReadiness.vendor_bill_*` (hasil **tarikan** Odoo, read-only);
 *   * B10 `/purchase/orders/` (monitoring PO Odoo, read-only).
 *
 *   * filter server: `?search=` (kode/ref/vendor/PO) + `?state=` (tab per state);
 *   * kolom: Kode, PO, Vendor, Ref, Tanggal, Total, State, Odoo ID (`-` = belum push);
 *   * klik baris → detail; "Bill Baru" → `/finance/vendor-bills/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `FINANCE_ROLES`; izin **tulis** API = ADMIN/OWNER.
 */

const EMPTY_ROWS: VendorBillRow[] = [];

const CSV_COLUMNS: CsvColumn<VendorBillRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'purchase_order_no', label: 'PO' },
  { key: 'vendor_name', label: 'Vendor' },
  { key: 'ref', label: 'Ref vendor' },
  { key: 'invoice_date', label: 'Tanggal' },
  { key: 'due_date', label: 'Jatuh tempo' },
  { key: 'state', label: 'State' },
  { key: 'amount_total', label: 'Total' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<VendorBillRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  {
    key: 'purchase_order_no',
    label: 'PO',
    render: (row) => (
      <span className="font-mono tabular-nums">{row.purchase_order_no ?? '-'}</span>
    ),
  },
  { key: 'vendor_name', label: 'Vendor' },
  {
    key: 'ref',
    label: 'Ref vendor',
    render: (row) =>
      row.ref === '' ? (
        <span className="text-muted-foreground">-</span>
      ) : (
        <span className="font-mono tabular-nums">{row.ref}</span>
      ),
  },
  { key: 'invoice_date', label: 'Tanggal' },
  { key: 'amount_total', label: 'Total', align: 'right' },
  {
    key: 'state',
    label: 'State',
    render: (row) => (
      <Badge tone={billStateTone(row.state)}>{billStateLabel(row.state)}</Badge>
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

export function VendorBillsPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | VendorBillState>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['vendor-bills', search, filter],
    queryFn: () =>
      fetchVendorBills(client, {
        search,
        state: stateParamForFilter(filter),
        limit: VENDOR_BILLS_LIMIT_MAX,
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
    if (!isBillStateFilter(id)) return;

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
        title="Vendor Bill"
        subtitle={`Tagihan vendor MES (draft in_invoice ke Odoo) — ${String(
          data?.total_count ?? 0,
        )} baris`}
        breadcrumb={[{ label: 'Finance', href: '/finance/vendor-bills' }, { label: 'Bill' }]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/finance/vendor-bills/new')}>
            Bill Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari bill"
          searchPlaceholder="Cari kode / ref vendor / vendor / PO"
          filters={BILL_STATE_FILTERS}
          activeFilter={filter}
          onFilterChange={handleFilter}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'vendor-bills.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat vendor bill.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/finance/vendor-bills/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada bill yang cocok dengan filter.'
              : 'Belum ada vendor bill. Tambahkan lewat tombol "Bill Baru".'
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

