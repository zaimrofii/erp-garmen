import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Pencil, Star } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchTax, setDefaultTax } from '@/api/masterTaxes';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { taxDetailItems } from '@/lib/master-tax';
import { CARD } from '@/lib/tokens';

/**
 * TaxDetailPage - route `/master/taxes/:id` (H3.6, read-only + aksi Set Default).
 *
 * Menampilkan satu pajak + jejak sync (`odoo_id`; `null` = belum pernah terkirim ke
 * Odoo) dan penanda `is_default` (mes-only, tidak dikirim ke Odoo):
 *
 *   * **Edit** → `/master/taxes/:id/edit` (form yang sama dengan "Pajak Baru");
 *   * **Jadikan Default** → `POST /api/v1/master/taxes/<id>/set-default/` — ATOMIK:
 *     backend meng-unset default lain, jadi selalu maksimal satu pajak default MES
 *     (dipakai form SO/PO H2.1/H2.2 & invoice untuk mengisi `tax_ids`).
 *
 * Push ke Odoo otomatis & asinkron setiap POST/PUT/DELETE (`erp_sync.push_master_tax`,
 * pantau di `/settings/sync`); aksi default TIDAK memicu push (keputusan MES).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function TaxDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [toast, setToast] = useState<ToastState | null>(null);

  const parsedId = id === undefined ? null : Number(id);
  const taxId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;

  const { data: tax, isLoading, error, refetch } = useQuery({
    queryKey: ['master-tax', taxId],
    queryFn: () => fetchTax(client, taxId ?? 0),
    enabled: taxId !== null,
    staleTime: 15_000,
  });

  const makeDefault = useMutation({
    mutationFn: async () => setDefaultTax(client, taxId ?? 0),
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Pajak default diperbarui',
        description: `${saved.code || saved.name} kini pajak default MES (maksimal satu).`,
      });
      void queryClient.invalidateQueries({ queryKey: ['master-taxes'] });
      void refetch();
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menjadikan default',
        description: caught instanceof Error ? caught.message : 'Permintaan gagal.',
      });
    },
  });

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={tax === undefined ? 'Detail Pajak' : tax.name}
        subtitle="Master pajak MES (read-only) — gunakan Edit untuk mengubah"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Pajak', href: '/master/taxes' },
          { label: tax === undefined ? 'Detail' : tax.code },
        ]}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate('/master/taxes')}>
              Kembali
            </Button>

            <Button
              icon={Pencil}
              disabled={tax === undefined}
              onClick={() => navigate(`/master/taxes/${String(taxId)}/edit`)}
            >
              Edit
            </Button>

            <Button
              variant="secondary"
              icon={Star}
              disabled={tax === undefined || tax.is_default || !tax.active}
              loading={makeDefault.isPending}
              onClick={() => makeDefault.mutate()}
            >
              Jadikan Default
            </Button>
          </div>
        }
      />


      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat pajak…
        </div>
      ) : null}

      {error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat pajak (perlu login atau pajak tidak ada).
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

      {tax !== undefined ? (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-center gap-3')}>
            <span className="font-mono text-sm font-semibold text-foreground">{tax.code}</span>
            <Badge tone={tax.active ? 'blue' : 'muted'}>
              {tax.active ? 'Aktif' : 'Nonaktif'}
            </Badge>
            {tax.is_default ? <Badge tone="blue">Default MES</Badge> : null}
            <Badge tone={tax.odoo_id === null ? 'coral' : 'blue'}>
              {tax.odoo_id === null ? 'Belum sync Odoo' : `Odoo #${String(tax.odoo_id)}`}
            </Badge>
          </section>

          <section className={cn(CARD, 'grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3')}>
            {taxDetailItems(tax).map((item) => (
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

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}
