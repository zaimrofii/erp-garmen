import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Save } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createWorkOrderCrud,
  fetchWorkOrderCrud,
  updateWorkOrderCrud,
  WORK_ORDERS_CRUD_LIMIT_MAX,
} from '@/api/workOrdersCrud';
import { getOrderLines } from '@/api/orderLines';
import { useApiClient } from '@/hooks/useApiClient';
import {
  EMPTY_WO_FORM,
  isWoEditable,
  isWoFormValid,
  validateWoForm,
  woFormFromDetail,
  woInputFromForm,
  type WoFormValues,
} from '@/lib/work-order';
import { CARD } from '@/lib/tokens';

/**
 * WorkOrderFormPage - route `/production/work-orders/new` + `/:id/edit` (H2.3).
 *
 * Satu WO = satu `OrderLine` (pecahan lebih lanjut lewat halaman detail → Split):
 *   * **nomor** TIDAK wajib diisi — kosong ⇒ backend memakai `next_number('WO')`
 *     (`WO-<TAHUN>-<SEQ>`, Sprint C); kode manual tetap boleh (unik);
 *   * **qty rencana** kosong ⇒ backend memakai `OrderLine.qty`;
 *   * `order_line` TIDAK bisa dipindah saat edit (backend mengabaikan field itu);
 *   * edit hanya saat `DRAFT` (guard `isWoEditable`, backend menolak 400);
 *   * Work Order = **MES-only** ⇒ tidak ada field Odoo di form (probe H2.3:
 *     `mrp.workorder` = operasi per `mrp.production`, bukan WO per OrderLine).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` baris order. */
const NO_ORDER_LINE_OPTION = { value: '', label: '— Pilih baris order —' };

/** PURE — satu baris mentah list `order-lines` → `{id, label}` (defensif). */
function toOrderLineOption(row: Record<string, unknown>): { value: string; label: string } | null {
  const id = Number(row['id']);
  if (!Number.isFinite(id) || id <= 0) return null;

  const orderCode = String(row['order_code'] ?? '').trim();
  const productCode = String(row['product_code'] ?? '').trim();
  const qty = String(row['qty'] ?? '').trim();
  const label = [orderCode, productCode, qty.length > 0 ? `qty ${qty}` : '']
    .filter((part) => part.length > 0)
    .join(' / ');

  return { value: String(id), label: label.length === 0 ? `#${String(id)}` : label };
}

export function WorkOrderFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();

  const parsedId = id === undefined ? null : Number(id);
  const workOrderId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = workOrderId !== null;

  const [draft, setDraft] = useState<WoFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['work-order-crud', workOrderId],
    queryFn: () => fetchWorkOrderCrud(client, workOrderId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Baris order untuk dropdown (resource `order-lines` F1/F2 — list publik). */
  const orderLines = useQuery({
    queryKey: ['order-lines', 'work-order-options'],
    queryFn: () => getOrderLines(client, { limit: WORK_ORDERS_CRUD_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const values: WoFormValues =
    draft ?? (detail.data === undefined ? EMPTY_WO_FORM : woFormFromDetail(detail.data));
  const errors = useMemo(() => validateWoForm(values), [values]);
  const valid = isWoFormValid(errors);
  const editable = detail.data === undefined ? true : isWoEditable(detail.data.state);

  const orderLineOptions = useMemo(() => {
    const rows = orderLines.data?.rows ?? [];
    const options = rows
      .map((row) => toOrderLineOption(row as Record<string, unknown>))
      .filter((option): option is { value: string; label: string } => option !== null);

    return [NO_ORDER_LINE_OPTION, ...options];
  }, [orderLines.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = woInputFromForm(values);

      return isEdit
        ? updateWorkOrderCrud(client, workOrderId ?? 0, input)
        : createWorkOrderCrud(client, input);
    },
    onSuccess: (saved) => {
      setToast({
        tone: 'success',
        title: isEdit ? 'Work Order diperbarui' : 'Work Order dibuat',
        description: `WO ${saved.code} (${saved.state}). Jejak ledger MES: ${
          saved.ledger_id === null ? 'tidak ada' : String(saved.ledger_id)
        }.`,
      });
      navigate(`/production/work-orders/${String(saved.id)}`);
    },
    onError: (error: unknown) => {
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan Work Order',
        description: error instanceof Error ? error.message : 'Terjadi kesalahan tak terduga.',
      });
    },
  });

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!valid || save.isPending) return;

    save.mutate();
  }

  if (isEdit && detail.isLoading && draft === null) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <PageHeader
        title={isEdit ? `Ubah Work Order ${detail.data?.code ?? ''}` : 'Work Order Baru'}
        subtitle="MES-only: WO tidak dikirim ke Odoo — jejaknya ledger SyncRecord (SKIPPED)."
        breadcrumb={[
          { label: 'Production', href: '/production/work-orders' },
          { label: isEdit ? 'Ubah WO' : 'WO Baru' },
        ]}
        actions={
          <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate(-1)}>
            Kembali
          </Button>
        }
      />

      {!editable ? (
        <p className={CARD + ' text-sm text-accent-coral'} role="alert">
          WO berstatus {detail.data?.state ?? '-'} tidak bisa diubah (hanya DRAFT).
        </p>
      ) : null}

      <form className={CARD + ' space-y-4'} onSubmit={onSubmit}>
        <Select
          label="Baris Order"
          value={values.order_line_id}
          disabled={isEdit}
          options={orderLineOptions}
          error={submitted ? errors.order_line_id : undefined}
          onChange={(event) =>
            setDraft({ ...values, order_line_id: event.target.value })
          }
        />
        {isEdit ? (
          <p className="text-xs text-muted-foreground">
            Baris order tidak dapat dipindah setelah WO dibuat.
          </p>
        ) : null}

        <Input
          label="Kode (opsional)"
          placeholder="kosongkan untuk WO-<tahun>-<nomor>"
          value={values.code}
          error={submitted ? errors.code : undefined}
          onChange={(event) => setDraft({ ...values, code: event.target.value })}
        />

        <Input
          label="Qty Rencana (opsional)"
          type="number"
          min={1}
          placeholder="kosongkan untuk memakai qty baris order"
          value={values.qty_planned}
          error={submitted ? errors.qty_planned : undefined}
          onChange={(event) => setDraft({ ...values, qty_planned: event.target.value })}
        />

        <div className="flex items-center gap-2">
          <Button type="submit" icon={Save} disabled={!editable || save.isPending}>
            {save.isPending ? 'Menyimpan…' : 'Simpan'}
          </Button>
          {submitted && !valid ? (
            <span className="text-xs text-accent-coral" role="alert">
              Periksa field yang bertanda merah.
            </span>
          ) : null}
        </div>
      </form>

      {toast !== null ? (
        <Toast
          open
          onOpenChange={(open) => {
            if (!open) setToast(null);
          }}
          tone={toast.tone}
          title={toast.title}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}

