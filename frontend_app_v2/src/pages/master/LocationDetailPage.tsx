import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchLocation, fetchLocations, LOCATIONS_LIMIT_MAX } from '@/api/masterLocations';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { displayOrDash, locationDetailItems, usageLabel } from '@/lib/master-location';
import { CARD } from '@/lib/tokens';
import type { MasterLocationRow } from '@/types/master-location';

/**
 * LocationDetailPage - route `/master/locations/:id` (H1.4, READ-ONLY).
 *
 * Menampilkan satu lokasi + hierarki langsung (`children_count` + tabel anak) dan
 * jejak sync (`odoo_id`; `null` = belum pernah terkirim ke Odoo). Halaman ini TIDAK
 * menulis apa pun:
 *
 *   * **Edit** → `/master/locations/:id/edit` (form yang sama dengan "Lokasi Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip (endpoint push manual belum
 *     ada — push otomatis & asinkron tiap POST/PUT tiap task
 *     `erp_sync.push_master_location`, pantau di `/settings/sync`).
 *
 * Soft delete dilakukan lewat form (checkbox `active` → PUT), supaya guard backend
 * "masih punya anak aktif" (400) tetap terlihat sebagai pesan di Toast.
 */

const CHILD_COLUMNS: DenseTableColumn<MasterLocationRow>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
  },
  { key: 'name', label: 'Nama' },
  { key: 'usage', label: 'Jenis', render: (row) => usageLabel(row.usage) },
  {
    key: 'active',
    label: 'Status',
    render: (row) => (
      <Badge tone={row.active ? 'blue' : 'muted'}>{row.active ? 'Aktif' : 'Nonaktif'}</Badge>
    ),
  },
];

export function LocationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const locationId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: location, isLoading, error, refetch } = useQuery({
    queryKey: ['master-location', locationId],
    queryFn: () => fetchLocation(client, locationId ?? 0),
    enabled: locationId !== null,
    staleTime: 15_000,
  });

  /** Anak langsung (satu query kecil; lokasi nonaktif ikut supaya jejaknya terlihat). */
  const children = useQuery({
    queryKey: ['master-locations', 'children', locationId],
    queryFn: () => fetchLocations(client, { parent_id: locationId, limit: LOCATIONS_LIMIT_MAX }),
    enabled: locationId !== null,
    staleTime: 15_000,
  });

  const childRows = children.data?.rows ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={location === undefined ? 'Detail Lokasi' : location.name}
        subtitle="Master lokasi MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Lokasi', href: '/master/locations' },
          { label: location === undefined ? 'Detail' : location.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/master/locations')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={location === undefined}
              onClick={() => navigate(`/master/locations/${String(locationId)}/edit`)}
            >
              Edit
            </Button>

            {/* H2 — endpoint push manual belum ada; push otomatis lewat task Celery. */}
            <Tooltip content="Sync manual tersedia di H2 — push sekarang otomatis & asinkron">
              <Button
                variant="secondary"
                icon={RefreshCw}
                disabled
                aria-label="Sync ke Odoo (belum tersedia, H2)"
              >
                Sync ke Odoo
              </Button>
            </Tooltip>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat lokasi…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat lokasi (perlu login atau lokasi tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      {location !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {displayOrDash(location.complete_name)}
            </span>
            <Badge tone="muted">{usageLabel(location.usage)}</Badge>
            <Badge tone={location.active ? 'blue' : 'muted'}>
              {location.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone={location.odoo_id === null ? 'coral' : 'blue'}>
              {location.odoo_id === null
                ? 'Belum sync Odoo'
                : `Odoo #${String(location.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {locationDetailItems(location).map((item) => (
              <div key={item.label} className="flex flex-col gap-1">
                <span className="text-xs font-medium text-muted-foreground">{item.label}</span>
                <span
                  className={cn(
                    'text-sm text-foreground',
                    item.mono === true ? 'font-mono' : undefined,
                  )}
                >
                  {item.value}
                </span>
              </div>
            ))}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Anak langsung ({String(childRows.length)})
            </h2>
            <div className={cn(CARD, 'p-0')}>
              <DenseTable
                columns={CHILD_COLUMNS}
                rows={childRows}
                loading={children.isLoading}
                error={children.error === null ? null : 'Gagal memuat anak lokasi.'}
                onRetry={() => {
                  void children.refetch();
                }}
                onRowClick={(row) => navigate(`/master/locations/${String(row.id)}`)}
                emptyMessage="Tidak ada anak langsung di lokasi ini."
              />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
