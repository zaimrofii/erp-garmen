import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createWarehouse, fetchWarehouse, updateWarehouse } from '@/api/masterWarehouses';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  DELIVERY_STEP_OPTIONS,
  EMPTY_WAREHOUSE_FORM,
  isDeliverySteps,
  isReceptionSteps,
  isWarehouseFormValid,
  ODOO_CODE_MAX_LENGTH,
  RECEPTION_STEP_OPTIONS,
  validateWarehouseForm,
  warehouseFormFromRow,
  warehouseInputFromForm,
  type WarehouseFormValues,
} from '@/lib/master-warehouse';
import { CARD } from '@/lib/tokens';

/**
 * WarehouseFormPage - route `/master/warehouses/new` + `/master/warehouses/:id/edit` (H1.3).
 *
 * 5 field (code, name, reception_steps, delivery_steps, active) — dua field langkah
 * disimpan karena **wajib** di `stock.warehouse` Odoo (probe `fields_get`), sehingga
 * push memakai nilai nyata.
 *
 *   * create → `POST /api/v1/master/warehouses/` (`createWarehouse`);
 *   * edit   → `PUT /api/v1/master/warehouses/<id>/` (`updateWarehouse`);
 *   * validasi `lib/master-warehouse.ts::validateWarehouseForm` (PURE) — error muncul
 *     setelah submit pertama; tombol tidak dimatikan supaya penyebabnya terlihat;
 *   * sukses → Toast + pindah ke detail; push Odoo asinkron (update-only, lihat task);
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 *
 * Hint: `code` MES boleh 64 karakter, tapi ``short_name`` Odoo hanya 5 — task akan
 * menandai FAILED dengan pesan jelas kalau kodenya lebih panjang.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function WarehouseFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const warehouseId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = warehouseId !== null;

  const [draft, setDraft] = useState<WarehouseFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-warehouse', warehouseId],
    queryFn: () => fetchWarehouse(client, warehouseId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: WarehouseFormValues =
    draft ?? (detail.data === undefined ? EMPTY_WAREHOUSE_FORM : warehouseFormFromRow(detail.data));

  const errors = useMemo(() => validateWarehouseForm(values), [values]);
  const valid = isWarehouseFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = warehouseInputFromForm(values);

      return isEdit ? updateWarehouse(client, warehouseId, input) : createWarehouse(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Gudang diperbarui' : 'Gudang dibuat',
        description: `${saved.code} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? 'belum ada — update-only' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/warehouses/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan gudang',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof WarehouseFormValues>(
    field: K,
    value: WarehouseFormValues[K],
  ): void {
    setDraft({ ...values, [field]: value });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSubmitted(true);

    if (!valid || save.isPending) return;

    save.mutate();
  }

  const showErrors = submitted;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Gudang' : 'Gudang Baru'}
        subtitle="Master gudang MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Gudang', href: '/master/warehouses' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/warehouses')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat gudang…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat gudang (perlu login atau gudang tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void detail.refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-2')}>
          <Input
            label="Kode *"
            value={values.code}
            placeholder="mis. WH"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Gudang Utama"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Select
            label="Penerimaan"
            options={RECEPTION_STEP_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.reception_steps}
            onChange={(event) => {
              const next = event.target.value;
              if (isReceptionSteps(next)) setField('reception_steps', next);
            }}
          />
          <Select
            label="Pengiriman"
            options={DELIVERY_STEP_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.delivery_steps}
            onChange={(event) => {
              const next = event.target.value;
              if (isDeliverySteps(next)) setField('delivery_steps', next);
            }}
          />
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-1">
            <Checkbox
              label="Gudang aktif (dipakai transaksi stok)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            <p className="text-xs text-muted-foreground">
              Catatan: short_name Odoo hanya menerima {String(ODOO_CODE_MAX_LENGTH)} karakter —
              kode lebih panjang akan ditandai gagal saat push (data MES tetap utuh).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Gudang'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/master/warehouses')}
            >
              Batal
            </Button>
          </div>
        </section>
      </form>

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}

