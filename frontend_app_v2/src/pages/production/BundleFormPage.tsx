import { useMemo, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Eye, GitMerge, Plus, Save, Scissors, Trash2, X } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createBundles,
  deleteBundle,
  fetchBundleCrud,
  mergeBundles,
  previewBundles,
  splitBundle,
  updateBundle,
  BUNDLES_CRUD_LIMIT_MAX,
} from '@/api/bundlesCrud';
import { fetchWorkOrdersCrud } from '@/api/workOrdersCrud';
import { useApiClient } from '@/hooks/useApiClient';
import {
  bundleDetailItems,
  bundleEditFormFromDetail,
  bundleUpdateInputFromForm,
  bundleCreateInputFromForm,
  bundleStateLabel,
  EMPTY_BUNDLE_FORM,
  isBundleFormValid,
  isBundleStructurallyEditable,
  parseNumberList,
  validateBundleEditForm,
  validateBundleForm,
  validateMergeIds,
  validateSplitParts,
  type BundleEditFormValues,
  type BundleFormValues,
  type BundleSizeFormRow,
} from '@/lib/bundle';
import { CARD } from '@/lib/tokens';

/**
 * BundleFormPage - route `/production/bundles/new` + `/production/bundles/:id/edit` (H2.4).
 *
 * Dua mode dalam satu halaman:
 *   * **new**  → pilih WorkOrder + matriks ukuran + `bundle_size` + preview
 *     (`POST /bundles/preview/`, memakai `BundleEngine.preview_bundles`) lalu simpan;
 *   * **edit** → muat detail (`GET /bundles/<id>/`), ubah `size`/`sku_variant`/`qty`/WC/line
 *     (DRAFT-only + `X-Base-Version`), **split**, **merge**, **hapus** (hibrida).
 *
 * Bundle = **MES-only sebagai objek** (tanpa `odoo_id`); halaman detail operator
 * (`/production/bundles/:id`) tetap dipakai untuk aksi state + chatter + sync WIP/FG.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` Work Order. */
const NO_WO_OPTION = { value: '', label: '— Pilih Work Order (DRAFT) —' };

export function BundleFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const queryClient = useQueryClient();

  const parsedId = id === undefined ? null : Number(id);
  const bundleId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = bundleId !== null;

  const [toast, setToast] = useState<ToastState | null>(null);

  // --- mode create ---
  const [createDraft, setCreateDraft] = useState<BundleFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [plan, setPlan] = useState<{ code: string; size: string; qty: number }[] | null>(null);

  // --- mode edit ---
  const [editDraft, setEditDraft] = useState<BundleEditFormValues | null>(null);
  const [splitText, setSplitText] = useState('');
  const [mergeText, setMergeText] = useState('');
  const [structError, setStructError] = useState<string | null>(null);

  const detail = useQuery({
    queryKey: ['bundle-crud', bundleId],
    queryFn: () => fetchBundleCrud(client, bundleId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const workOrders = useQuery({
    queryKey: ['work-orders', 'bundle-options'],
    queryFn: () => fetchWorkOrdersCrud(client, { limit: BUNDLES_CRUD_LIMIT_MAX }),
    enabled: !isEdit,
    staleTime: 60_000,
  });

  const formValues: BundleFormValues =
    createDraft ?? EMPTY_BUNDLE_FORM;
  const formErrors = useMemo(() => validateBundleForm(formValues), [formValues]);
  const formValid = isBundleFormValid(formErrors);

  const editValues: BundleEditFormValues | null =
    editDraft ?? (detail.data === undefined ? null : bundleEditFormFromDetail(detail.data));
  const editErrors =
    editValues === null || detail.data === undefined
      ? {}
      : validateBundleEditForm(editValues, detail.data.qty_done);

  const woOptions = useMemo(() => {
    const rows = workOrders.data?.rows ?? [];
    const options = rows
      .filter((row) => row.state === 'DRAFT')
      .map((row) => ({ value: String(row.id), label: `${row.code} (qty ${row.qty_planned})` }));

    return [NO_WO_OPTION, ...options];
  }, [workOrders.data]);

  function onFail(error: unknown) {
    setToast({
      tone: 'error',
      title: 'Gagal',
      description: error instanceof Error ? error.message : 'Terjadi kesalahan tak terduga.',
    });
  }

  function onDone(title: string, description: string) {
    void queryClient.invalidateQueries({ queryKey: ['bundle-crud', bundleId] });
    void queryClient.invalidateQueries({ queryKey: ['bundles'] });
    setToast({ tone: 'success', title, description });
  }

  const preview = useMutation({
    mutationFn: () => previewBundles(client, bundleCreateInputFromForm(formValues)),
    onSuccess: (result) => {
      setPlan(result.plan.map((row) => ({ code: row.code, size: row.size, qty: row.qty })));
      onDone('Pratinjau rencana bundle', `${String(result.summary.planned)} bundle akan dibuat.`);
    },
    onError: onFail,
  });

  const create = useMutation({
    mutationFn: () => createBundles(client, bundleCreateInputFromForm(formValues)),
    onSuccess: (saved) => {
      setPlan(null);
      onDone(
        'Bundle dibuat',
        `${String(saved.created)} bundle untuk ${String(saved.work_order_code ?? 'WO')}.`,
      );
      navigate(`/production/bundles/${String(saved.id)}`);
    },
    onError: onFail,
  });

  const update = useMutation({
    mutationFn: (values: BundleEditFormValues) =>
      updateBundle(
        client,
        bundleId ?? 0,
        bundleUpdateInputFromForm(values),
        detail.data?.version,
      ),
    onSuccess: () => onDone('Bundle diperbarui', 'Perubahan tersimpan (ledger SKIPPED).'),
    onError: onFail,
  });

  const split = useMutation({
    mutationFn: (parts: number[]) => splitBundle(client, bundleId ?? 0, parts),
    onSuccess: (saved) => {
      setSplitText('');
      setStructError(null);
      onDone('Bundle dipecah', `${String(saved.bundles?.length ?? 0)} bundle baru dibuat.`);
    },
    onError: onFail,
  });

  const merge = useMutation({
    mutationFn: (ids: number[]) => mergeBundles(client, bundleId ?? 0, ids),
    onSuccess: (saved) => {
      setMergeText('');
      setStructError(null);
      onDone('Bundle digabung', `Qty sekarang ${String(saved.summary.qty)}.`);
    },
    onError: onFail,
  });

  const remove = useMutation({
    mutationFn: () => deleteBundle(client, bundleId ?? 0),
    onSuccess: () => {
      onDone('Bundle dihapus', 'Hard delete (DRAFT tanpa jejak produksi).');
      navigate('/bundles');
    },
    onError: onFail,
  });

  function onSubmitCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitted(true);
    if (!formValid || create.isPending) return;

    create.mutate();
  }

  function onSubmitEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editValues === null || Object.keys(editErrors).length > 0 || update.isPending) return;

    update.mutate(editValues);
  }

  function updateRow(index: number, patch: Partial<BundleSizeFormRow>) {
    const sizes = formValues.sizes.map((row, position) =>
      position === index ? { ...row, ...patch } : row,
    );
    setCreateDraft({ ...formValues, sizes });
  }

  function addRow() {
    setCreateDraft({ ...formValues, sizes: [...formValues.sizes, { size: '', qty: '' }] });
  }

  function removeRow(index: number) {
    const sizes = formValues.sizes.filter((_, position) => position !== index);
    setCreateDraft({ ...formValues, sizes: sizes.length === 0 ? [{ size: '', qty: '' }] : sizes });
  }

  function onSplit() {
    const parts = parseNumberList(splitText);
    const error = validateSplitParts(parts, detail.data?.qty ?? 0);
    setStructError(error);
    if (error !== null) return;

    split.mutate(parts);
  }

  function onMerge() {
    const ids = parseNumberList(mergeText);
    const error = validateMergeIds(ids, bundleId ?? 0);
    setStructError(error);
    if (error !== null) return;

    merge.mutate(ids);
  }

  function onDelete() {
    if (typeof window !== 'undefined' && !window.confirm('Hapus permanen bundle ini?')) return;

    remove.mutate();
  }

  if (isEdit && detail.isLoading) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }

  const header = (
    <PageHeader
      title={isEdit ? `Kelola Bundle ${detail.data?.code ?? ''}` : 'Bundle Baru'}
      subtitle="Bundle = unit pelacakan terkecil (MES-only sebagai objek; gerakan stok lewat WIP/FG)."
      breadcrumb={[
        { label: 'Bundles', href: '/bundles' },
        { label: isEdit ? 'Kelola' : 'Baru' },
      ]}
      actions={
        <Button variant="secondary" icon={ArrowLeft} onClick={() => navigate(-1)}>
          Kembali
        </Button>
      }
    />
  );

  if (!isEdit) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-4">
        {header}

        <form className={CARD + ' space-y-4'} onSubmit={onSubmitCreate}>
          <Select
            label="Work Order (DRAFT)"
            value={formValues.work_order_id}
            options={woOptions}
            error={submitted ? formErrors.work_order_id : undefined}
            onChange={(event) =>
              setCreateDraft({ ...formValues, work_order_id: event.target.value })
            }
          />

          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Matriks Ukuran</p>
            {formValues.sizes.map((row, index) => (
              <div key={`size-${String(index)}`} className="flex items-end gap-2">
                <Input
                  label="Ukuran"
                  placeholder="L"
                  value={row.size}
                  onChange={(event) => updateRow(index, { size: event.target.value })}
                />
                <Input
                  label="Qty"
                  type="number"
                  min={1}
                  value={row.qty}
                  onChange={(event) => updateRow(index, { qty: event.target.value })}
                />
                <Button variant="ghost" onClick={() => removeRow(index)} aria-label="Hapus baris">
                  <X className="h-4 w-4" aria-hidden="true" />
                </Button>
              </div>
            ))}
            <Button variant="secondary" icon={Plus} onClick={addRow}>
              Tambah Ukuran
            </Button>
            {submitted && formErrors.sizes !== undefined ? (
              <p className="text-xs text-accent-coral" role="alert">
                {formErrors.sizes}
              </p>
            ) : null}
          </div>

          <Input
            label="Ukuran Bundle (opsional)"
            type="number"
            min={1}
            placeholder="kosongkan untuk 1 bundle per ukuran"
            value={formValues.bundle_size}
            error={submitted ? formErrors.bundle_size : undefined}
            onChange={(event) => setCreateDraft({ ...formValues, bundle_size: event.target.value })}
          />

          <Input
            label="SKU Varian (opsional)"
            value={formValues.sku_variant}
            onChange={(event) => setCreateDraft({ ...formValues, sku_variant: event.target.value })}
          />

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="secondary"
              icon={Eye}
              disabled={!formValid || preview.isPending}
              onClick={() => preview.mutate()}
            >
              Pratinjau
            </Button>
            <Button type="submit" icon={Save} disabled={create.isPending}>
              Simpan
            </Button>
            {submitted && !formValid ? (
              <span className="text-xs text-accent-coral" role="alert">
                Periksa field yang bertanda merah.
              </span>
            ) : null}
          </div>
        </form>

        {plan !== null ? (
          <section className={CARD + ' space-y-2'}>
            <h2 className="text-sm font-semibold text-foreground">Rencana Bundle</h2>
            <ul className="divide-y divide-border">
              {plan.map((row) => (
                <li key={row.code} className="flex items-center justify-between py-2">
                  <span className="font-mono text-sm text-foreground">{row.code}</span>
                  <span className="text-xs text-muted-foreground">
                    {row.size} · qty {row.qty}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

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

  if (detail.data === undefined || editValues === null) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 p-4">
        {header}
        <p className="text-accent-coral">Gagal memuat bundle #{String(bundleId ?? 0)}.</p>
      </div>
    );
  }

  const row = detail.data;
  const structural = isBundleStructurallyEditable(row);

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      {header}

      <section className={CARD + ' space-y-2'}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-sm font-semibold text-foreground">
            {bundleStateLabel(row.state)}
          </span>
          <Link to={`/production/bundles/${String(row.id)}`} className="text-xs underline">
            Buka halaman operator (aksi state + chatter)
          </Link>
        </div>

        <dl className="grid gap-2 sm:grid-cols-2">
          {bundleDetailItems(row).map((item) => (
            <div key={item.label} className="flex flex-col">
              <dt className="text-xs text-muted-foreground">{item.label}</dt>
              <dd
                className={
                  item.mono === true
                    ? 'font-mono text-sm text-foreground'
                    : 'text-sm text-foreground'
                }
              >
                {item.value}
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <form className={CARD + ' space-y-4'} onSubmit={onSubmitEdit}>
        <Input
          label="Ukuran"
          value={editValues.size}
          error={editErrors.size}
          onChange={(event) => setEditDraft({ ...editValues, size: event.target.value })}
        />
        <Input
          label="SKU Varian"
          value={editValues.sku_variant}
          onChange={(event) => setEditDraft({ ...editValues, sku_variant: event.target.value })}
        />
        <Input
          label="Qty"
          type="number"
          min={1}
          value={editValues.qty}
          error={editErrors.qty}
          onChange={(event) => setEditDraft({ ...editValues, qty: event.target.value })}
        />
        <Input
          label="Work Center ID"
          placeholder="kosongkan bila belum ditugaskan"
          value={editValues.current_work_center_id}
          onChange={(event) =>
            setEditDraft({ ...editValues, current_work_center_id: event.target.value })
          }
        />
        <Input
          label="Line Produksi ID"
          placeholder="kosongkan bila belum ditugaskan"
          value={editValues.production_line_id}
          onChange={(event) =>
            setEditDraft({ ...editValues, production_line_id: event.target.value })
          }
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" icon={Save} disabled={!structural || update.isPending}>
            Simpan Perubahan
          </Button>
          <Button
            type="button"
            variant="danger"
            icon={Trash2}
            disabled={!structural || remove.isPending}
            onClick={onDelete}
          >
            Hapus
          </Button>
        </div>
        {!structural ? (
          <p className="text-xs text-muted-foreground">
            Ubah/hapus hanya untuk bundle <strong>DRAFT</strong> yang belum punya event produksi.
          </p>
        ) : null}
      </form>

      <section className={CARD + ' space-y-2'}>
        <h2 className="text-sm font-semibold text-foreground">Split Bundle</h2>
        <p className="text-xs text-muted-foreground">
          Pecah qty ({row.qty}) menjadi beberapa bundle pada WorkOrder yang sama — jumlah bagian
          WAJIB = {row.qty}.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            aria-label="Qty split"
            className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="3, 2"
            value={splitText}
            onChange={(event) => setSplitText(event.target.value)}
          />
          <Button
            variant="secondary"
            icon={Scissors}
            disabled={!structural || split.isPending}
            onClick={onSplit}
          >
            Split
          </Button>
        </div>
      </section>

      <section className={CARD + ' space-y-2'}>
        <h2 className="text-sm font-semibold text-foreground">Merge Bundle</h2>
        <p className="text-xs text-muted-foreground">
          Gabungkan bundle DRAFT lain (WorkOrder + ukuran + SKU sama) ke bundle ini. Isi id
          bundle sumber, pisahkan koma.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            aria-label="Id bundle sumber"
            className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            placeholder="12, 13"
            value={mergeText}
            onChange={(event) => setMergeText(event.target.value)}
          />
          <Button
            variant="secondary"
            icon={GitMerge}
            disabled={!structural || merge.isPending}
            onClick={onMerge}
          >
            Merge
          </Button>
        </div>
      </section>

      {structError !== null ? (
        <p className="text-xs text-accent-coral" role="alert">
          {structError}
        </p>
      ) : null}

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
