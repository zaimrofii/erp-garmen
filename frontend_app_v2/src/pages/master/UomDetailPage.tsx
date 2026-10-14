import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchUom } from '@/api/masterUoms';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { uomDetailItems } from '@/lib/master-uom';
import { CARD } from '@/lib/tokens';

/**
 * UomDetailPage - route `/master/uoms/:id` (H1.2, READ-ONLY).
 *
 * Menampilkan satu UoM + jejak sync (`odoo_id`; `null` = belum pernah terkirim ke
 * Odoo). Halaman ini TIDAK menulis apa pun:
 *
 *   * **Edit** → `/master/uoms/:id/edit` (form yang sama dengan "UoM Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip "H2" (endpoint push
 *     manual belum ada — push otomatis & asinkron tiap POST/PUT/DELETE lewat task
 *     `erp_sync.push_master_uom`, pantau di `/settings/sync`).
 */

export function UomDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const uomId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: uom, isLoading, error, refetch } = useQuery({
    queryKey: ['master-uom', uomId],
    queryFn: () => fetchUom(client, uomId ?? 0),
    enabled: uomId !== null,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={uom === undefined ? 'Detail UoM' : uom.name}
        subtitle="Master UoM MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master UoM', href: '/master/uoms' },
          { label: uom === undefined ? 'Detail' : uom.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate('/master/uoms')}>
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={uom === undefined}
              onClick={() => navigate(`/master/uoms/${String(uomId)}/edit`)}
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
          <Spinner size="sm" /> Memuat UoM…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat UoM (perlu login atau UoM tidak ada).
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

      {uom !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{uom.code}</span>
            <Badge tone={uom.active ? 'blue' : 'muted'}>
              {uom.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone={uom.odoo_id === null ? 'coral' : 'blue'}>
              {uom.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(uom.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {uomDetailItems(uom).map((item) => (
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
        </>
      ) : null}
    </div>
  );
}
