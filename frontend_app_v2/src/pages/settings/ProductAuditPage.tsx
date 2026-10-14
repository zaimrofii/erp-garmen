import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { PageHeader } from '@/components/molecules/PageHeader';
import { getProductAudit, type AuditProduct } from '@/api/audit';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * ProductAuditPage - route `/settings/audit` (F9/9.2).
 *
 * Menampilkan produk master tanpa `odoo_id` (kontrak §6.1,
 * `GET /audit/products-missing-odoo-id/`). Produk seperti itu TIDAK ikut rekonsiliasi stok
 * dan tidak bisa ditautkan ke PO/vendor bill/invoice Odoo — jadi angka ini yang menjelaskan
 * kenapa laporan rekonsiliasi bisa "kekurangan" data.
 *
 * Dua potret dari backend: `products` (semua tanpa `odoo_id`, dipotong `limit`) dan
 * `used_in_open_bundles` (subset yang sedang dipakai bundle di lantai = paling mendesak).
 * Read-only: halaman ini TIDAK menyentuh Odoo dan tidak mengubah produk.
 *
 * Tabel memakai `DenseTable` (Fase 20); baris di-`key` dengan `id` produk dari backend.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

const COLUMNS: DenseTableColumn<AuditProduct>[] = [
  {
    key: 'code',
    label: 'Kode',
    render: (row) => <span className="font-mono text-xs">{row.code}</span>,
  },
  { key: 'name', label: 'Nama', render: (row) => row.name },
  { key: 'id', label: 'ID MES', align: 'right' },
];

function countLabel(count: number, limit: number | null): string {
  if (limit === null || count <= limit) return `${String(count)} produk`;
  return `${String(count)} produk (menampilkan ${String(limit)})`;
}

export function ProductAuditPage() {
  const apiClient = useApiClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const audit = useQuery({
    queryKey: ['product-audit'],
    queryFn: () => getProductAudit(apiClient),
    staleTime: 60_000,
  });

  async function handleRefresh(): Promise<void> {
    const result = await audit.refetch();

    if (result.error !== null && result.error !== undefined) {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal memuat audit',
        description:
          result.error instanceof Error ? result.error.message : 'Audit produk gagal dimuat.',
      });
      return;
    }

    trigger('success');
    setToast({
      tone: 'success',
      title: 'Audit dimuat',
      description: `${String(result.data?.count ?? 0)} produk tanpa odoo_id.`,
    });
  }

  const data = audit.data;
  const missing = data?.products ?? [];
  const urgent = data?.used_in_open_bundles;
  const urgentProducts = urgent?.products ?? [];
  const queryError = audit.error === null || audit.error === undefined ? null : audit.error;
  const loadError = queryError === null ? null : 'Gagal memuat audit produk (perlu login?).';

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Audit Produk"
        subtitle="Produk master tanpa odoo_id — tidak ikut rekonsiliasi stok & tidak bisa ditautkan ke dokumen Odoo"
        breadcrumb={[{ label: 'Settings' }, { label: 'Audit' }]}
      />

      <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold text-foreground">
              {audit.isLoading ? 'Memuat…' : countLabel(data?.count ?? 0, urgent?.limit ?? null)}
            </span>
            <span className="text-xs text-muted-foreground">tanpa odoo_id di master MES</span>
          </div>

          <div className="flex flex-col gap-0.5">
            <Badge tone={urgentProducts.length > 0 ? 'coral' : 'muted'}>
              {`${String(urgent?.count ?? 0)} dipakai bundle terbuka`}
            </Badge>
            <span className="text-xs text-muted-foreground">
              {`${String(urgentProducts.length)} di antaranya ditampilkan`}
            </span>
          </div>
        </div>

        <Button
          variant="secondary"
          icon={RefreshCw}
          loading={audit.isFetching}
          disabled={audit.isFetching}
          onClick={() => {
            void handleRefresh();
          }}
        >
          Muat Ulang
        </Button>
      </section>

      <section className={cn(CARD, 'flex flex-col gap-2 p-0')}>
        <h2 className="px-4 pt-4 text-sm font-semibold text-foreground">
          Paling mendesak — dipakai bundle terbuka
        </h2>
        <DenseTable
          columns={COLUMNS}
          rows={urgentProducts}
          loading={audit.isLoading}
          error={loadError}
          onRetry={() => {
            void audit.refetch();
          }}
          emptyMessage="Tidak ada produk tanpa odoo_id yang sedang dipakai bundle terbuka."
        />
      </section>

      <section className={cn(CARD, 'flex flex-col gap-2 p-0')}>
        <h2 className="px-4 pt-4 text-sm font-semibold text-foreground">
          Semua produk tanpa odoo_id
        </h2>
        <DenseTable
          columns={COLUMNS}
          rows={missing}
          loading={audit.isLoading}
          error={loadError}
          onRetry={() => {
            void audit.refetch();
          }}
          emptyMessage="Semua produk sudah punya odoo_id."
        />
      </section>

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
