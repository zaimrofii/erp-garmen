import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Pencil, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Tooltip } from '@/components/atoms/Tooltip';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchBom } from '@/api/masterBoms';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { bomDetailItems, displayOrDash, productOptionLabel } from '@/lib/master-bom';
import { CARD } from '@/lib/tokens';
import type { MasterBomLineRow } from '@/types/master-bom';

/**
 * BomDetailPage - route `/master/boms/:id` (H1.5, READ-ONLY).
 *
 * Menampilkan header BOM + tabel komponen aktif + jejak sync (`odoo_id`; `null` =
 * belum pernah terkirim ke Odoo). Halaman ini TIDAK menulis apa pun:
 *
 *   * **Edit** → `/master/boms/:id/edit` (form yang sama dengan "BOM Baru");
 *   * **Sync ke Odoo** → **placeholder DISABLED** + tooltip (endpoint push manual
 *     belum ada — push otomatis & asinkron tiap POST/PUT lewat task
 *     `erp_sync.push_master_bom`, pantau di `/settings/sync`).
 *
 * Soft delete dilakukan lewat form (checkbox `active` → PUT), konsisten H1.1–H1.4.
 */

const LINE_COLUMNS: DenseTableColumn<MasterBomLineRow>[] = [
  {
    key: 'sequence',
    label: 'Urut',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.sequence}</span>,
  },
  {
    key: 'product_code',
    label: 'Komponen',
    render: (row) =>
      row.product_code === null && row.product_name === null
        ? '-'
        : productOptionLabel({ code: row.product_code ?? '', name: row.product_name ?? '' }),
  },
  {
    key: 'qty',
    label: 'Qty',
    align: 'right',
    render: (row) => <span className="tabular-nums">{row.qty}</span>,
  },
  {
    key: 'uom_code',
    label: 'Satuan',
    render: (row) => displayOrDash(row.uom_code),
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

export function BomDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const bomId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: bom, isLoading, error, refetch } = useQuery({
    queryKey: ['master-bom', bomId],
    queryFn: () => fetchBom(client, bomId ?? 0),
    enabled: bomId !== null,
    staleTime: 15_000,
  });

  const lines = bom?.lines ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={bom === undefined ? 'Detail BOM' : bom.name || bom.code}
        subtitle="Bill of Material MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master BOM', href: '/master/boms' },
          { label: bom === undefined ? 'Detail' : bom.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate('/master/boms')}>
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={bom === undefined}
              onClick={() => navigate(`/master/boms/${String(bomId)}/edit`)}
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
          <Spinner size="sm" /> Memuat BOM…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat BOM (perlu login atau BOM tidak ada).
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

      {bom !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{bom.code}</span>
            <Badge tone="muted">{`${String(bom.output_qty)} ${bom.uom_code ?? ''}`.trim()}</Badge>
            <Badge tone={bom.active ? 'blue' : 'muted'}>
              {bom.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            <Badge tone={bom.odoo_id === null ? 'coral' : 'blue'}>
              {bom.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(bom.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {bomDetailItems(bom).map((item) => (
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
              Komponen ({String(lines.length)})
            </h2>
            <div className={cn(CARD, 'p-0')}>
              <DenseTable
                columns={LINE_COLUMNS}
                rows={lines}
                loading={isLoading}
                error={null}
                emptyMessage="Belum ada komponen pada BOM ini."
              />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
