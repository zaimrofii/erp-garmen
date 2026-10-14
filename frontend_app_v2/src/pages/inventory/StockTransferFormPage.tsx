import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, RefreshCw, Save, Send } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchStockQty } from '@/api/inventoryAdjustments';
import { fetchLocations } from '@/api/masterLocations';
import { fetchProducts } from '@/api/masterProducts';
import { createTransfer, STOCK_TRANSFERS_LIMIT_MAX } from '@/api/stockTransfers';
import { useApiClient } from '@/hooks/useApiClient';
import {
  EMPTY_TRANSFER_FORM,
  isTransferFormValid,
  parseTransferQty,
  transferCreateInputFromForm,
  validateTransferForm,
  type TransferFormErrors,
  type TransferFormValues,
} from '@/lib/stock-transfer';
import { CARD } from '@/lib/tokens';

/**
 * StockTransferFormPage — route `/inventory/transfer` (H2.6).
 *
 * Membuat **log** transfer (DRAFT) atau langsung mengirimnya ke Odoo (`commit=true`).
 * Lokasi tujuan otomatis TIDAK menawarkan lokasi asal (guard `from != to` juga dipaksa
 * backend). Karena **MES tidak menyimpan stok**, tombol "Pratinjau stok Odoo" membaca
 * on-hand lokasi ASAL langsung dari endpoint H2.5 (`/inventory/stock-qty/`, read-only).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk dropdown. */
const NO_PRODUCT = { value: '', label: '— Pilih produk —' };
const NO_LOCATION = { value: '', label: '— Pilih lokasi (internal) —' };
const NO_QTY = '—';

export function StockTransferFormPage() {
  const client = useApiClient();
  const navigate = useNavigate();

  const [values, setValues] = useState<TransferFormValues>(EMPTY_TRANSFER_FORM);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [stockQty, setStockQty] = useState<string | null>(null);
  const [stockError, setStockError] = useState<string | null>(null);

  const errors: TransferFormErrors = useMemo(() => validateTransferForm(values), [values]);
  const valid = isTransferFormValid(errors);

  const products = useQuery({
    queryKey: ['master-products', 'stock-transfer-form'],
    queryFn: () => fetchProducts(client, { limit: STOCK_TRANSFERS_LIMIT_MAX }),
    staleTime: 60_000,
  });
  const locations = useQuery({
    queryKey: ['master-locations', 'stock-transfer-form'],
    queryFn: () => fetchLocations(client, { limit: STOCK_TRANSFERS_LIMIT_MAX }),
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
  /** Lokasi internal saja; untuk "tujuan" lokasi asal dikecualikan (guard from != to). */
  const internalLocations = useMemo(
    () => (locations.data?.rows ?? []).filter((row) => row.usage === 'internal'),
    [locations.data],
  );
  const fromOptions = useMemo(
    () => [
      NO_LOCATION,
      ...internalLocations.map((row) => ({ value: String(row.id), label: row.complete_name || row.code })),
    ],
    [internalLocations],
  );
  const toOptions = useMemo(
    () => [
      NO_LOCATION,
      ...internalLocations
        .filter((row) => String(row.id) !== values.fromLocationId)
        .map((row) => ({ value: String(row.id), label: row.complete_name || row.code })),
    ],
    [internalLocations, values.fromLocationId],
  );

  /** Ubah satu field + (kalau lokasi asal berubah) reset tujuan & pratinjau stok. */
  function update<K extends keyof TransferFormValues>(key: K, value: TransferFormValues[K]) {
    setValues((current) => {
      const next = { ...current, [key]: value };
      if (key === 'fromLocationId' && next.toLocationId === value) {
        next.toLocationId = '';
      }

      return next;
    });
    if (key === 'productId' || key === 'fromLocationId') {
      setStockQty(null);
      setStockError(null);
    }
  }

  const submit = useMutation({
    mutationFn: async (commit: boolean) =>
      createTransfer(client, transferCreateInputFromForm(values), { commit }),
    onSuccess: (result) => {
      const failedCommit = result.commit !== undefined && !result.commit.ok;
      if (failedCommit) {
        setToast({
          tone: 'error',
          title: `Commit ${result.code} gagal`,
          description: result.commit?.detail ?? 'Transfer tersimpan sebagai DRAFT.',
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
            : 'Transfer COMMITTED — menunggu hasil push ke Odoo.',
      });
      navigate(`/inventory/transfers/${String(result.id)}`);
    },
    onError: (error: unknown) => {
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan transfer',
        description: error instanceof Error ? error.message : 'Terjadi kesalahan.',
      });
    },
  });

  /** Baca on-hand Odoo lokasi ASAL (endpoint H2.5, read-only). */
  const readStock = useMutation({
    mutationFn: async () =>
      fetchStockQty(client, Number(values.productId), Number(values.fromLocationId)),
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

  const showError = (key: keyof TransferFormErrors) => (submitted ? errors[key] : undefined);
  const qty = parseTransferQty(values.qty);
  const cukup = stockQty !== null && qty !== null ? Number(stockQty) >= qty : null;

  return (
    <div className="mx-auto max-w-3xl space-y-3 p-4">
      <PageHeader
        title="Buat Stock Transfer"
        subtitle="Catat pemindahan stok antar lokasi internal, lalu kirim ke Odoo (satu arah)."
        breadcrumb={[{ label: 'Stock Transfer', href: '/inventory/transfers' }]}
        actions={
          <Link to="/inventory/transfers">
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
          label="Lokasi asal (usage internal)"
          options={fromOptions}
          value={values.fromLocationId}
          error={showError('fromLocationId')}
          onChange={(event) => update('fromLocationId', event.target.value)}
        />
        <Select
          label="Lokasi tujuan (usage internal, beda dari asal)"
          options={toOptions}
          value={values.toLocationId}
          error={showError('toLocationId')}
          onChange={(event) => update('toLocationId', event.target.value)}
        />
        <Input
          label="Qty"
          inputMode="decimal"
          value={values.qty}
          error={showError('qty')}
          onChange={(event) => update('qty', event.target.value)}
        />
        <Input
          label="Catatan (opsional)"
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
            disabled={values.productId.length === 0 || values.fromLocationId.length === 0}
            onClick={() => readStock.mutate()}
          >
            Pratinjau stok Odoo (asal)
          </Button>
          <span className="text-xs text-muted-foreground">
            Stok asal: {stockQty === null ? NO_QTY : stockQty}
            {cukup === null ? '' : cukup ? ' (cukup)' : ' (kurang dari qty — Odoo bisa menolak)'}
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
          Jalur Odoo: picking internal + validasi (stok bergerak di Odoo). Snapshot stok asal
          hanya informatif — MES tidak menyimpan stok.
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
