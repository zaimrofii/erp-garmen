import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchWorkCenter } from '@/api/masterWorkCenters';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  activeBundlesLabel,
  displayOrDash,
  formatCapacity,
  productionLinesLabel,
  workCenterDetailItems,
} from '@/lib/master-work-center';
import { CARD } from '@/lib/tokens';

/**
 * WorkCenterDetailPage - route `/master/work-centers/:id` (H1.7, READ-ONLY).
 *
 * Menampilkan satu work center (tipe stasiun, kapasitas/jam, tag kapabilitas,
 * catatan) + jejak pemakaian dari backend: `active_bundles_count` (dasar guard soft
 * delete) dan `production_lines` (M2M `ProductionLine.work_centers`, dikelola H1.8).
 *
 * Halaman ini TIDAK menulis apa pun:
 *
 *   * **Edit** → `/master/work-centers/:id/edit` (soft delete lewat checkbox aktif);
 *   * **badge "MES-only"** + tombol **Sync ke Odoo DISABLED** + tooltip: Work Center
 *     memang tidak disinkron ke Odoo (probe `mrp.workcenter` mewajibkan `resource_id`
 *     yang tidak ada di MES) — ledger sync dicatat `SKIPPED` di `/settings/sync`.
 */

export function WorkCenterDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const workCenterId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: workCenter, isLoading, error, refetch } = useQuery({
    queryKey: ['master-work-center', workCenterId],
    queryFn: () => fetchWorkCenter(client, workCenterId ?? 0),
    enabled: workCenterId !== null,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={workCenter === undefined ? 'Detail Work Center' : workCenter.name}
        subtitle="Master work center MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Work Center', href: '/master/work-centers' },
          { label: workCenter === undefined ? 'Detail' : workCenter.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/master/work-centers')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={workCenter === undefined}
              onClick={() => navigate(`/master/work-centers/${String(workCenterId)}/edit`)}
            >
              Edit
            </Button>

            {/* MES-only: Work Center memang tidak dikirim ke Odoo. */}
            <Tooltip content="Work Center MES-only — tidak disinkron ke Odoo (ledger sync dicatat SKIPPED)">
              <Button variant="secondary" disabled aria-label="Sync ke Odoo (tidak berlaku, MES-only)">
                Sync ke Odoo
              </Button>
            </Tooltip>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat work center…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat work center (perlu login atau work center tidak ada).
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

      {workCenter !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {displayOrDash(workCenter.code)}
            </span>
            <Badge tone="muted">{displayOrDash(workCenter.wc_type) || 'tanpa tipe'}</Badge>
            <Badge tone={workCenter.active ? 'blue' : 'muted'}>
              {workCenter.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone="muted">{formatCapacity(workCenter.capacity_per_hour)}</Badge>
            <Badge tone="muted">{activeBundlesLabel(workCenter)}</Badge>
            <Badge tone="coral">MES-only</Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {workCenterDetailItems(workCenter).map((item) => (
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

          <section className={cn(CARD, 'flex flex-col gap-1')}>
            <span className="text-xs font-medium text-muted-foreground">
              Lini Produksi (M2M ProductionLine.work_centers)
            </span>
            <span className="text-sm text-foreground">{productionLinesLabel(workCenter)}</span>
            <span className="text-xs text-muted-foreground">
              Keanggotaan lini dikelola di modul Production Line (H1.8).
            </span>
          </section>
        </>
      ) : null}
    </div>
  );
}
