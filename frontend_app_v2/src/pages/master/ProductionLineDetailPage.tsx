import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchProductionLine } from '@/api/masterProductionLines';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  activeBundlesLabel,
  allocationRulesLabel,
  displayOrDash,
  productionLineDetailItems,
  workCentersSummary,
} from '@/lib/master-production-line';
import { CARD } from '@/lib/tokens';

/**
 * ProductionLineDetailPage - route `/master/production-lines/:id` (H1.8, READ-ONLY).
 *
 * Menampilkan satu lini: tag kapabilitas lini, **tabel anggota work center**
 * (`work_centers[]` dari M2M), jumlah bundle aktif (dasar guard soft delete) dan
 * jumlah aturan alokasi (info — `LineAllocationRule` CASCADE tapi soft delete tidak
 * menghapus baris).
 *
 * Halaman ini TIDAK menulis apa pun:
 *   * **Edit** → `/master/production-lines/:id/edit` (soft delete lewat checkbox aktif);
 *   * **badge "MES-only"** + tombol **Sync ke Odoo DISABLED** + tooltip: Odoo 17 tidak
 *     punya wadah lini (`mrp.routing` dihapus, `mrp.routing.workcenter` = Operation
 *     per-BoM) → ledger sync dicatat `SKIPPED` di `/settings/sync`.
 */

export function ProductionLineDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const lineId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: line, isLoading, error, refetch } = useQuery({
    queryKey: ['master-production-line', lineId],
    queryFn: () => fetchProductionLine(client, lineId ?? 0),
    enabled: lineId !== null,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={line === undefined ? 'Detail Production Line' : line.name}
        subtitle="Master lini produksi MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Production Line', href: '/master/production-lines' },
          { label: line === undefined ? 'Detail' : line.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/master/production-lines')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={line === undefined}
              onClick={() => navigate(`/master/production-lines/${String(lineId)}/edit`)}
            >
              Edit
            </Button>

            {/* MES-only: Odoo 17 tidak punya wadah lini. */}
            <Tooltip content="Production Line MES-only — Odoo tidak punya wadah lini (ledger sync dicatat SKIPPED)">
              <Button
                variant="secondary"
                disabled
                aria-label="Sync ke Odoo (tidak berlaku, MES-only)"
              >
                Sync ke Odoo
              </Button>
            </Tooltip>
          </div>
        }
      />

      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat production line…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat production line (perlu login atau lini tidak ada).
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

      {line !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {displayOrDash(line.code)}
            </span>
            {line.capability_tags.map((tag) => (
              <Badge key={tag} tone="muted">
                {tag}
              </Badge>
            ))}
            <Badge tone={line.active ? 'blue' : 'muted'}>
              {line.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone="muted">{workCentersSummary(line)}</Badge>
            <Badge tone="muted">{activeBundlesLabel(line)}</Badge>
            <Badge tone="muted">{allocationRulesLabel(line)}</Badge>
            <Badge tone="coral">MES-only</Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {productionLineDetailItems(line).map((item) => (
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

          <section className={cn(CARD, 'flex flex-col gap-2')}>
            <span className="text-xs font-medium text-muted-foreground">
              Anggota Work Center (M2M ProductionLine.work_centers)
            </span>

            {line.work_centers.length === 0 ? (
              <span className="text-sm text-muted-foreground">
                Belum ada work center anggota. Tambahkan lewat Edit; lini tanpa anggota
                tidak akan dipilih `capability_allocator`.
              </span>
            ) : (
              <ul className="flex flex-col gap-1">
                {line.work_centers.map((center) => (
                  <li key={center.id} className="text-sm text-foreground">
                    <span className="font-mono">{center.code}</span> — {center.name}
                  </li>
                ))}
              </ul>
            )}

            <span className="text-xs text-muted-foreground">
              Keanggotaan ini juga tampil di detail Work Center (H1.7) dan dipakai
              `capability_allocator` (lini superset WC routing).
            </span>
          </section>
        </>
      ) : null}
    </div>
  );
}
