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
import { fetchPayments, PAYMENTS_LIMIT_MAX } from '@/api/payments';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import {
  isPaymentStateFilter,
  isPaymentTypeFilter,
  paymentStateLabel,
  paymentStateTone,
  paymentTypeLabel,
  paymentTypeTone,
  PAYMENT_STATE_FILTERS,
  PAYMENT_TYPE_FILTERS,
  stateParamForFilter,
  typeParamForFilter,
} from '@/lib/payment';
import { CARD } from '@/lib/tokens';
import type { PaymentRow, PaymentState, PaymentType } from '@/types/payment';

/**
 * PaymentsPage - route `/finance/payments` (H3.3, app Finance).
 *
 * Daftar payment MES NYATA dari `GET /api/v1/finance/payments/`
 * (`api/payments.ts` → MODE.payments='real') — **satu model dua arah**:
 *
 *   * `INBOUND` = customer membayar kita (sumber `CustomerInvoice` H3.1);
 *   * `OUTBOUND` = kita membayar vendor (sumber `VendorBill` H3.2).
 *
 *   * filter server: `?search=` (kode/referensi/partner/kode sumber), `?state=`,
 *     `?payment_type=` (+ Reset Filter);
 *   * kolom: Kode, Arah, Dokumen sumber, Partner, Jumlah, Tanggal, State, Odoo ID;
 *   * klik baris → detail; "Payment Baru" → `/finance/payments/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Rekonsiliasi BUKAN di MES (keputusan STEP 0) — payment dikirim **draft** ke Odoo
 * dan akuntan yang mem-posting + merekonsiliasi. Guard route: `FINANCE_ROLES`.
 */

const EMPTY_ROWS: PaymentRow[] = [];

const CSV_COLUMNS: CsvColumn<PaymentRow>[] = [
  { key: 'code', label: 'Kode' },
  { key: 'payment_type', label: 'Arah' },
  { key: 'source_label', label: 'Dokumen sumber' },
  { key: 'partner_name', label: 'Partner' },
  { key: 'amount', label: 'Jumlah' },
  { key: 'payment_date', label: 'Tanggal' },
  { key: 'payment_method', label: 'Cara bayar' },
  { key: 'reference', label: 'Referensi' },
  { key: 'state', label: 'State' },
  { key: 'odoo_id', label: 'Odoo ID' },
];

const COLUMNS: DenseTableColumn<PaymentRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  {
    key: 'payment_type',
    label: 'Arah',
    render: (row) => (
      <Badge tone={paymentTypeTone(row.payment_type)}>{paymentTypeLabel(row.payment_type)}</Badge>
    ),
  },
  {
    key: 'source_label',
    label: 'Dokumen sumber',
    render: (row) => <span className="font-mono tabular-nums">{row.source_label}</span>,
  },
  { key: 'partner_name', label: 'Partner' },
  { key: 'amount', label: 'Jumlah', align: 'right' },
  { key: 'payment_date', label: 'Tanggal' },
  {
    key: 'state',
    label: 'State',
    render: (row) => (
      <Badge tone={paymentStateTone(row.state)}>{paymentStateLabel(row.state)}</Badge>
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

export function PaymentsPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState<'all' | PaymentState>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | PaymentType>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['payments', search, filter, typeFilter],
    queryFn: () =>
      fetchPayments(client, {
        search,
        state: stateParamForFilter(filter),
        payment_type: typeParamForFilter(typeFilter),
        limit: PAYMENTS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || filter !== 'all' || typeFilter !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleFilter(id: string): void {
    if (!isPaymentStateFilter(id)) return;

    setFilter(id);
    pagination.reset();
  }

  function handleTypeFilter(id: string): void {
    if (!isPaymentTypeFilter(id)) return;

    setTypeFilter(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setFilter('all');
    setTypeFilter('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Payment"
        subtitle={`Pembayaran invoice & vendor bill (draft account.payment ke Odoo) — ${String(
          data?.total_count ?? 0,
        )} baris`}
        breadcrumb={[{ label: 'Finance', href: '/finance/payments' }, { label: 'Payment' }]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/finance/payments/new')}>
            Payment Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari payment"
          searchPlaceholder="Cari kode / referensi / partner / dokumen"
          filters={PAYMENT_STATE_FILTERS}
          activeFilter={filter}
          onFilterChange={handleFilter}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'payments.csv', CSV_COLUMNS)}
          refreshing={isFetching}
          onRefresh={() => {
            void refetch();
          }}
        />

        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-wrap items-center gap-2">
            {PAYMENT_TYPE_FILTERS.map((option) => (
              <Button
                key={option.id}
                variant={typeFilter === option.id ? 'primary' : 'secondary'}
                size="sm"
                onClick={() => handleTypeFilter(option.id)}
              >
                {option.label}
              </Button>
            ))}
          </div>

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
          error={error === null ? null : 'Gagal memuat payment.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/finance/payments/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada payment yang cocok dengan filter.'
              : 'Belum ada payment. Tambahkan lewat tombol "Payment Baru".'
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

