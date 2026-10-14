import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchWarehouse } from '@/api/masterWarehouses';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { warehouseDetailItems } from '@/lib/master-warehouse';
import { CARD } from '@/lib/tokens';

/**
 * WarehouseDetailPage - route `/master/warehouses/:id` (H1.3, READ-ONLY).
 *
 * Menampilkan satu gudang + jejak sync (`odoo_id`; `null` = belum pernah terkirim ke
 * Odoo — push H1.3 **update-only**, jadi gudang baru akan FAILED sampai H1.4 Location
 * menyediakan `view_location_id`/`lot_stock_id`/`company_id`). Halaman ini TIDAK
 * menulis apa pun:
 *
 *   * **Edit** → `/master/warehouses/:id/edit` (form yang sama dengan "Gudang Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip "H2" (endpoint push manual
 *     belum ada — push otomatis & asinkron tiap POST/PUT/DELETE lewat task
 *     `erp_sync.push_master_warehouse`, pantau di `/settings/sync`).
 */

export function WarehouseDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const warehouseId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: warehouse, isLoading, error, refetch } = useQuery({
    queryKey: ['master-warehouse', warehouseId],
    queryFn: () => fetchWarehouse(client, warehouseId ?? 0),
    enabled: warehouseId !== null,
    staleTime: 15_000,
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={warehouse === undefined ? 'Detail Gudang' : warehouse.name}
        subtitle="Master gudang MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Gudang', href: '/master/warehouses' },
          { label: warehouse === undefined ? 'Detail' : warehouse.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              icon={ArrowLeft}
              onClick={() => navigate('/master/warehouses')}
            >
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={warehouse === undefined}
              onClick={() => navigate(`/master/warehouses/${String(warehouseId)}/edit`)}
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
          <Spinner size="sm" /> Memuat gudang…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat gudang (perlu login atau gudang tidak ada).
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

      {warehouse !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">
              {warehouse.code}
            </span>
            <Badge tone={warehouse.active ? 'blue' : 'muted'}>
              {warehouse.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone={warehouse.odoo_id === null ? 'coral' : 'blue'}>
              {warehouse.odoo_id === null
                ? 'Belum sync Odoo (update-only)'
                : `Odoo #${String(warehouse.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {warehouseDetailItems(warehouse).map((item) => (
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
