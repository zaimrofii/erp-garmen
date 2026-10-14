import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Send } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { commitAdjustment, fetchAdjustment } from '@/api/inventoryAdjustments';
import { useApiClient } from '@/hooks/useApiClient';
import {
  adjustmentChipStatus,
  adjustmentStateLabel,
  isAdjustmentCommittable,
  qtyLabel,
  signedDelta,
} from '@/lib/inventory-adjustment';
import { syncStatusLabel } from '@/lib/state-display';
import { CARD } from '@/lib/tokens';

/**
 * InventoryAdjustmentDetailPage — route `/inventory/adjustments/:id` (H2.5).
 *
 * Read-only + **Commit** (hanya saat `DRAFT`): mengirim log ke Odoo
 * (`DRAFT → COMMITTED` + enqueue push). Hasil push (`SYNCED`/`FAILED`) muncul di
 * blok sync & `last_error` — termasuk petunjuk prasyarat grup Inventory/Manager.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function InventoryAdjustmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const adjustmentId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const query = useQuery({
    queryKey: ['inventory-adjustment', adjustmentId],
    queryFn: () => fetchAdjustment(client, adjustmentId ?? 0),
    enabled: adjustmentId !== null,
    staleTime: 10_000,
  });

  const commit = useMutation({
    mutationFn: async () => commitAdjustment(client, adjustmentId ?? 0),
    onSuccess: async (result) => {
      setToast({
        tone: result.queued ? 'success' : 'default',
        title: result.queued ? `${result.code} dikirim ke Odoo` : `${result.code} COMMITTED`,
        description: result.queued
          ? 'Push masuk queue Celery — cek status SYNCED/FAILED di halaman ini.'
          : 'Ledger tercatat PENDING (broker tidak merespons task id).',
      });
      await queryClient.invalidateQueries({ queryKey: ['inventory-adjustment', adjustmentId] });
      await queryClient.invalidateQueries({ queryKey: ['inventory-adjustments'] });
    },
    onError: (error: unknown) => {
      setToast({
        tone: 'error',
        title: 'Gagal commit adjustment',
        description: error instanceof Error ? error.message : 'Terjadi kesalahan.',
      });
    },
  });

  if (adjustmentId === null) {
    return (
      <div className="p-4">
        <p className="text-danger">Id adjustment tidak valid.</p>
      </div>
    );
  }
  if (query.isLoading && query.data === undefined) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }
  if (query.error !== null || query.data === undefined) {
    return (
      <div className="p-4">
        <p className="text-danger">Gagal memuat detail inventory adjustment.</p>
      </div>
    );
  }

  const row = query.data;
  const rows: { label: string; value: string }[] = [
    { label: 'Produk', value: row.product_code ?? row.product_name ?? '—' },
    { label: 'Lokasi', value: `${row.location_code ?? '—'} (${row.location_usage ?? '—'})` },
    { label: 'Qty delta', value: signedDelta(row.qty_delta) },
    { label: 'Stok Odoo sebelum', value: qtyLabel(row.qty_before) },
    { label: 'Stok Odoo sesudah', value: qtyLabel(row.qty_after) },
    { label: 'Alasan', value: row.reason },
    { label: 'id stock.move Odoo', value: row.odoo_move_id === null ? '—' : String(row.odoo_move_id) },
    { label: 'Referensi Odoo', value: row.odoo_reference.length === 0 ? '—' : row.odoo_reference },
    { label: 'Dibuat oleh', value: row.created_by ?? '—' },
    { label: 'Dibuat pada', value: row.created_at ?? '—' },
    { label: 'Ledger sync', value: row.sync.status === null ? '—' : syncStatusLabel(row.sync.status) },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <PageHeader
        title={row.code}
        subtitle="Log adjustment stok (MES hanya mencatat; stok ada di Odoo)."
        breadcrumb={[{ label: 'Inventory Adjustment', href: '/inventory/adjustments' }]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip
              status={adjustmentChipStatus(row.state)}
              label={adjustmentStateLabel(row.state)}
            />
            <Link to="/inventory/adjustments">
              <Button variant="secondary" size="sm" icon={ArrowLeft}>
                Kembali
              </Button>
            </Link>
          </div>
        }
      />

      <div className={`${CARD} space-y-2`}>
        {rows.map((item) => (
          <div key={item.label} className="flex items-start justify-between gap-3">
            <span className="text-xs text-muted-foreground">{item.label}</span>
            <span className="text-right text-sm text-foreground">{item.value}</span>
          </div>
        ))}
      </div>

      {row.last_error.length > 0 ? (
        <div className={`${CARD} space-y-2`}>
          <p className="text-xs font-medium text-muted-foreground">Error terakhir</p>
          <p className="text-sm text-danger">{row.last_error}</p>
        </div>
      ) : null}

      {isAdjustmentCommittable(row.state) ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            icon={Send}
            loading={commit.isPending}
            onClick={() => commit.mutate()}
          >
            Kirim ke Odoo (Commit)
          </Button>
          <span className="text-xs text-muted-foreground">
            DRAFT = hanya log MES. Commit mengirim satu kali (ledger INVENTORY_ADJUST).
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Adjustment sudah {adjustmentStateLabel(row.state)} — tidak bisa di-commit ulang.
        </p>
      )}

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />
    </div>
  );
}
