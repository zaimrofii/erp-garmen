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
import { fetchPartners, PARTNERS_LIMIT_MAX } from '@/api/masterPartners';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { displayOrDash, formatNpwp, partnerRoleLabels } from '@/lib/master-partner';
import { CARD } from '@/lib/tokens';
import type { MasterPartnerRow } from '@/types/master-partner';

/**
 * PartnersPage - route `/master/partners` (H1.6, app Inventory).
 *
 * MES = source of truth master (docs/REPLACE-NOTICE.md): daftar partner NYATA dari
 * `GET /api/v1/master/partners/` (`api/masterPartners.ts` → MODE.masterPartners='real').
 *
 *   * filter server: `?search=` (kode/nama/email/kota) + `?is_customer=`/`?is_vendor=`;
 *   * tab peran: Semua / Pelanggan (`is_customer=true`) / Supplier (`is_vendor=true`);
 *   * kolom: Kode, Nama, Peran, Kota, Telepon, NPWP, Status, Odoo ID;
 *   * klik baris → detail (`/master/partners/:id`); "Partner Baru" → `/master/partners/new`;
 *   * Export CSV via `useCsvExport` (kolom = bentuk backend).
 *
 * Guard route: `INVENTORY_ROLES` (konsisten H1.1–H1.5); izin **tulis** API hanya
 * ADMIN/OWNER (brief H1.6).
 */

const EMPTY_ROWS: MasterPartnerRow[] = [];

const ROLE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'customer', label: 'Pelanggan' },
  { id: 'vendor', label: 'Supplier' },
];

const ROLE_IDS: readonly string[] = ROLE_FILTERS.map((filter) => filter.id);

type PartnerRoleFilter = 'all' | 'customer' | 'vendor';

/** PURE - menyempitkan `string` dari Tabs ke filter peran TANPA cast `as`. */
function isRoleFilter(value: string): value is PartnerRoleFilter {
  return ROLE_IDS.includes(value);
}

/** PURE - filter peran UI → param backend (`null` = tidak difilter). */
function roleParamsForStatus(status: PartnerRoleFilter): {
  is_customer: boolean | null;
  is_vendor: boolean | null;
} {
  if (status === 'customer') return { is_customer: true, is_vendor: null };
  if (status === 'vendor') return { is_customer: null, is_vendor: true };

  return { is_customer: null, is_vendor: null };
}

const COLUMNS: DenseTableColumn<MasterPartnerRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  {
    key: 'is_customer',
    label: 'Peran',
    render: (row) => (
      <span className="flex flex-wrap gap-1">
        {partnerRoleLabels(row).map((label) => (
          <Badge key={label} tone="muted">
            {label}
          </Badge>
        ))}
      </span>
    ),
  },
  { key: 'city', label: 'Kota', render: (row) => displayOrDash(row.city) },
  { key: 'phone', label: 'Telepon', render: (row) => displayOrDash(row.phone) },
  {
    key: 'npwp',
    label: 'NPWP',
    render: (row) => (
      <span className="font-mono text-xs tabular-nums">{formatNpwp(row.npwp)}</span>
    ),
  },
  {
    key: 'active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
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

const CSV_COLUMNS: CsvColumn<MasterPartnerRow>[] = [
  { key: 'code', label: 'code' },
  { key: 'name', label: 'name' },
  { key: 'email', label: 'email' },
  { key: 'phone', label: 'phone' },
  { key: 'city', label: 'city' },
  { key: 'npwp', label: 'npwp' },
  { key: 'is_customer', label: 'is_customer' },
  { key: 'is_vendor', label: 'is_vendor' },
  { key: 'is_company', label: 'is_company' },
  { key: 'active', label: 'active' },
  { key: 'odoo_id', label: 'odoo_id' },
];

export function PartnersPage() {
  const client = useApiClient();
  const navigate = useNavigate();
  const { exportCsv } = useCsvExport();

  const [search, setSearch] = useState('');
  const [role, setRole] = useState<PartnerRoleFilter>('all');

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['master-partners', search, role],
    queryFn: () =>
      fetchPartners(client, {
        search,
        ...roleParamsForStatus(role),
        limit: PARTNERS_LIMIT_MAX,
      }),
    staleTime: 15_000,
  });

  const rows = data?.rows ?? EMPTY_ROWS;
  const pagination = usePagination(rows, { pageSize: 20 });

  const hasFilter = search.trim().length > 0 || role !== 'all';

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleRole(id: string): void {
    if (!isRoleFilter(id)) return;

    setRole(id);
    pagination.reset();
  }

  function resetFilters(): void {
    setSearch('');
    setRole('all');
    pagination.reset();
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Master Partner"
        subtitle={`Pelanggan & supplier MES — ${String(data?.total_count ?? 0)} baris`}
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Partner' },
        ]}
        actions={
          <Button icon={Plus} onClick={() => navigate('/master/partners/new')}>
            Partner Baru
          </Button>
        }
      />

      <section className={cn(CARD, 'flex flex-col gap-3 p-4')}>
        <TableToolbar
          search={search}
          onSearchChange={handleSearch}
          searchLabel="Cari partner"
          searchPlaceholder="Cari kode / nama / email / kota"
          filters={ROLE_FILTERS}
          activeFilter={role}
          onFilterChange={handleRole}
          exportDisabled={rows.length === 0}
          onExport={() => exportCsv(rows, 'master-partners.csv', CSV_COLUMNS)}
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
          error={error === null ? null : 'Gagal memuat master partner.'}
          onRetry={() => {
            void refetch();
          }}
          onRowClick={(row) => navigate(`/master/partners/${String(row.id)}`)}
          emptyMessage={
            hasFilter
              ? 'Tidak ada partner yang cocok dengan filter.'
              : 'Belum ada partner. Tambahkan lewat tombol "Partner Baru".'
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
