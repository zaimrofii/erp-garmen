import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Send } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { StatusChip } from '@/components/molecules/StatusChip';
import { commitTransfer, fetchTransfer } from '@/api/stockTransfers';
import { useApiClient } from '@/hooks/useApiClient';
import {
  isTransferCommittable,
  transferChipStatus,
  transferQtyLabel,
  transferRouteLabel,
  transferStateLabel,
} from '@/lib/stock-transfer';
import { syncStatusLabel } from '@/lib/state-display';
import { CARD } from '@/lib/tokens';

/**
 * StockTransferDetailPage — route `/inventory/transfers/:id` (H2.6).
 *
 * Read-only + **Commit** (hanya saat `DRAFT`): mengirim log ke Odoo
 * (`DRAFT → COMMITTED` + enqueue push picking internal). Hasil push (`SYNCED`/`FAILED`)
 * muncul di blok sync & `last_error`.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function StockTransferDetailPage() {
  const { id } = useParams<{ id: string }>();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const transferId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const query = useQuery({
    queryKey: ['stock-transfer', transferId],
    queryFn: () => fetchTransfer(client, transferId ?? 0),
    enabled: transferId !== null,
    staleTime: 10_000,
  });

  const commit = useMutation({
    mutationFn: async () => commitTransfer(client, transferId ?? 0),
    onSuccess: async (result) => {
      setToast({
        tone: result.queued ? 'success' : 'default',
        title: result.queued ? `${result.code} dikirim ke Odoo` : `${result.code} COMMITTED`,
        description: result.queued
          ? 'Picking internal masuk queue worker — cek status SYNCED/FAILED di halaman ini.'
          : 'Ledger tercatat PENDING (broker tidak merespons task id).',
      });
      await queryClient.invalidateQueries({ queryKey: ['stock-transfer', transferId] });
      await queryClient.invalidateQueries({ queryKey: ['stock-transfers'] });
    },
    onError: (error: unknown) => {
      setToast({
        tone: 'error',
        title: 'Gagal commit transfer',
        description: error instanceof Error ? error.message : 'Terjadi kesalahan.',
      });
    },
  });

  if (transferId === null) {
    return (
      <div className="p-4">
        <p className="text-danger">Id transfer tidak valid.</p>
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
        <p className="text-danger">Gagal memuat detail stock transfer.</p>
      </div>
    );
  }

  const row = query.data;
  const rows: { label: string; value: string }[] = [
    { label: 'Produk', value: row.product_code ?? row.product_name ?? '—' },
    { label: 'Rute', value: transferRouteLabel(row) },
    { label: 'Qty', value: transferQtyLabel(row.qty) },
    { label: 'Stok asal (snapshot Odoo)', value: transferQtyLabel(row.qty_before) },
    { label: 'Catatan', value: row.reason.length === 0 ? '—' : row.reason },
    {
      label: 'id picking Odoo',
      value: row.odoo_picking_id === null ? '—' : String(row.odoo_picking_id),
    },
    {
      label: 'Nama picking Odoo',
      value: row.odoo_picking_name.length === 0 ? '—' : row.odoo_picking_name,
    },
    { label: 'Dibuat oleh', value: row.created_by ?? '—' },
    { label: 'Dibuat pada', value: row.created_at ?? '—' },
    {
      label: 'Ledger sync',
      value: row.sync.status === null ? '—' : syncStatusLabel(row.sync.status),
    },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <PageHeader
        title={row.code}
        subtitle="Log transfer stok (MES hanya mencatat; stok bergerak di Odoo)."
        breadcrumb={[{ label: 'Stock Transfer', href: '/inventory/transfers' }]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusChip
              status={transferChipStatus(row.state)}
              label={transferStateLabel(row.state)}
            />
            <Link to="/inventory/transfers">
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

      {isTransferCommittable(row.state) ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button icon={Send} loading={commit.isPending} onClick={() => commit.mutate()}>
            Kirim ke Odoo (Commit)
          </Button>
          <span className="text-xs text-muted-foreground">
            DRAFT = hanya log MES. Commit membuat picking internal + validasi di Odoo.
          </span>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Transfer sudah {transferStateLabel(row.state)} — tidak bisa di-commit ulang.
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
