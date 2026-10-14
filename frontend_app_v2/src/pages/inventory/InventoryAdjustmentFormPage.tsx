import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw, Save, Send } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createAdjustment,
  fetchStockQty,
  INVENTORY_ADJUSTMENTS_LIMIT_MAX,
} from '@/api/inventoryAdjustments';
import { fetchLocations } from '@/api/masterLocations';
import { fetchProducts } from '@/api/masterProducts';
import { useApiClient } from '@/hooks/useApiClient';
import {
  adjustmentCreateInputFromForm,
  EMPTY_ADJUSTMENT_FORM,
  isAdjustmentFormValid,
  parseQtyDelta,
  stockQtyLabel,
  validateAdjustmentForm,
  type AdjustmentFormErrors,
  type AdjustmentFormValues,
} from '@/lib/inventory-adjustment';
import { CARD } from '@/lib/tokens';

/**
 * InventoryAdjustmentFormPage — route `/inventory/adjust` (H2.5).
 *
 * Membuat **log** adjustment (DRAFT) atau langsung mengirimnya ke Odoo
 * (`commit=true`). Dua tombol: **Simpan Draft** (MES-only) dan **Simpan & Kirim**
 * (COMMITTED + enqueue push). Karena **MES tidak menyimpan stok**, tombol
 * "Pratinjau stok Odoo" membaca on-hand langsung dari Odoo (read-only).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk dropdown produk/lokasi. */
const NO_PRODUCT = { value: '', label: '— Pilih produk —' };
const NO_LOCATION = { value: '', label: '— Pilih lokasi (internal) —' };
/** Cache stok on-demand: dibaca hanya saat tombol pratinjau ditekan. */
const NO_QTY = '—';

export function InventoryAdjustmentFormPage() {
  const client = useApiClient();
  const navigate = useNavigate();

  const [values, setValues] = useState<AdjustmentFormValues>(EMPTY_ADJUSTMENT_FORM);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [stockQty, setStockQty] = useState<string | null>(null);
  const [stockError, setStockError] = useState<string | null>(null);

  const errors: AdjustmentFormErrors = useMemo(() => validateAdjustmentForm(values), [values]);
  const valid = isAdjustmentFormValid(errors);

  const products = useQuery({
    queryKey: ['master-products', 'inventory-adjust-form'],
    queryFn: () => fetchProducts(client, { limit: INVENTORY_ADJUSTMENTS_LIMIT_MAX }),
    staleTime: 60_000,
  });
  const locations = useQuery({
    queryKey: ['master-locations', 'inventory-adjust-form'],
    queryFn: () => fetchLocations(client, { limit: INVENTORY_ADJUSTMENTS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const productOptions = useMemo(
    () => [
      NO_PRODUCT,
      ...(products.data?.rows ?? []).map((row) => ({
        value: String(row.id),
        label: `${row.code} — ${row.name}`,
      })),
    ],
    [products.data],
  );
  const locationOptions = useMemo(
    () => [
      NO_LOCATION,
      ...(locations.data?.rows ?? [])
        .filter((row) => row.usage === 'internal')
        .map((row) => ({ value: String(row.id), label: row.complete_name || row.code })),
    ],
    [locations.data],
  );

  /** Ubah satu field form + reset pratinjau stok (nilai lama jadi tidak relevan). */
  function update<K extends keyof AdjustmentFormValues>(key: K, value: AdjustmentFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    if (key === 'productId' || key === 'locationId') {
      setStockQty(null);
      setStockError(null);
    }
  }

  const submit = useMutation({
    mutationFn: async (commit: boolean) =>
      createAdjustment(client, adjustmentCreateInputFromForm(values), { commit }),
    onSuccess: (result) => {
      const failedCommit = result.commit !== undefined && !result.commit.ok;
      if (failedCommit) {
        setToast({
          tone: 'error',
          title: `Commit ${result.code} gagal`,
          description: result.commit?.detail ?? 'Adjustment tersimpan sebagai DRAFT.',
        });

        return;
      }

      setToast({
        tone: 'success',
        title:
          result.commit === undefined ? `Draft ${result.code} dibuat` : `${result.code} dikirim`,
        description:
          result.commit === undefined
            ? 'Log tersimpan di MES (belum dikirim ke Odoo).'
            : 'Adjustment COMMITTED — menunggu hasil push ke Odoo.',
      });
      navigate(`/inventory/adjustments/${String(result.id)}`);
    },
    onError: (error: unknown) => {
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan adjustment',
        description: error instanceof Error ? error.message : 'Terjadi kesalahan.',
      });
    },
  });

  /** Baca on-hand Odoo on-demand (read-only; MES tidak menyimpan stok). */
  const readStock = useMutation({
    mutationFn: async () =>
      fetchStockQty(client, Number(values.productId), Number(values.locationId)),
    onSuccess: (result) => {
      setStockQty(result.qty);
      setStockError(null);
    },
    onError: (error: unknown) => {
      setStockQty(null);
      setStockError(error instanceof Error ? error.message : 'Gagal membaca stok Odoo.');
    },
  });

  function submitForm(event: FormEvent<HTMLFormElement>, commit: boolean) {
    event.preventDefault();
    setSubmitted(true);
    if (!valid || submit.isPending) return;

    submit.mutate(commit);
  }

  const showError = (key: keyof AdjustmentFormErrors) => (submitted ? errors[key] : undefined);
  const delta = parseQtyDelta(values.qtyDelta);
  const projected =
    stockQty !== null && delta !== null ? (Number(stockQty) + delta).toFixed(2) : null;

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <PageHeader
        title="Buat Inventory Adjustment"
        subtitle="Catat penyesuaian stok, lalu kirim ke Odoo (satu arah MES → Odoo)."
        breadcrumb={[{ label: 'Inventory Adjustment', href: '/inventory/adjustments' }]}
        actions={
          <Link to="/inventory/adjustments">
            <Button variant="secondary" size="sm" icon={ArrowLeft}>
              Kembali
            </Button>
          </Link>
        }
      />

      <form className={`${CARD} space-y-3`} onSubmit={(event) => submitForm(event, false)}>
        <Select
          label="Produk"
          options={productOptions}
          value={values.productId}
          error={showError('productId')}
          onChange={(event) => update('productId', event.target.value)}
        />
        <Select
          label="Lokasi (usage internal)"
          options={locationOptions}
          value={values.locationId}
          error={showError('locationId')}
          onChange={(event) => update('locationId', event.target.value)}
        />
        <Input
          label="Qty delta (boleh negatif, mis. -3.5)"
          inputMode="decimal"
          value={values.qtyDelta}
          error={showError('qtyDelta')}
          onChange={(event) => update('qtyDelta', event.target.value)}
        />
        <Input
          label="Alasan"
          value={values.reason}
          error={showError('reason')}
          onChange={(event) => update('reason', event.target.value)}
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            icon={RefreshCw}
            loading={readStock.isPending}
            disabled={values.productId.length === 0 || values.locationId.length === 0}
            onClick={() => readStock.mutate()}
          >
            Pratinjau stok Odoo
          </Button>
          <span className="text-xs text-muted-foreground">
            Stok sekarang: {stockQty === null ? NO_QTY : stockQtyLabel(stockQty)}
            {projected === null ? '' : ` → setelah adjustment: ${projected}`}
          </span>
        </div>
        {stockError !== null ? <p className="text-xs text-danger">{stockError}</p> : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" icon={Save} loading={submit.isPending && submit.variables === false}>
            Simpan Draft
          </Button>
          <Button
            type="button"
            variant="secondary"
            icon={Send}
            loading={submit.isPending && submit.variables === true}
            onClick={() => submit.mutate(true)}
          >
            Simpan &amp; Kirim ke Odoo
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Prasyarat Odoo: user API harus punya grup Inventory / Manager — tanpa itu push
          berakhir FAILED (lihat detail setelah commit).
        </p>
      </form>

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

