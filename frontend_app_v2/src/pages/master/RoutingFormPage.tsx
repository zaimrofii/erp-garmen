import { useMemo, useRef, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { RoutingGraph } from '@/components/molecules/RoutingGraph';
import {
  addRoutingStep,
  createRouting,
  fetchRouting,
  removeRoutingStep,
  updateRouting,
  updateRoutingStep,
} from '@/api/masterRoutings';
import { fetchWorkCenters, WORK_CENTERS_LIMIT_MAX } from '@/api/masterWorkCenters';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { addTag, MAX_TAGS, removeTag } from '@/lib/master-work-center';
import {
  AUTO_ORDER_STEP,
  detailToForm,
  EMPTY_ROUTING_FORM,
  formRowToStepPayload,
  formRowsToB22Steps,
  formToGraph,
  makeStepFormRow,
  nextStepOrder,
  validateRoutingForm,
  validateStepRows,
  type RoutingFormValues,
  type RoutingStepFormRow,
} from '@/lib/master-routing';
import { CARD } from '@/lib/tokens';

/**
 * RoutingFormPage - route `/master/routings/new` + `/master/routings/:id/edit` (H1.9).
 *
 * Header: nama (wajib) · kode (opsional; kosong = backend menurunkan slug) · catatan ·
 * **tag kapabilitas** (input tag sama H1.7/H1.8) · aktif.
 *
 * **Editor DAG** (node `RoutingStep`, edge `allowed_next_steps`):
 *   * tiap node = label (wajib), order (unik per routing), work center (opsional),
 *     predecessor (`depends_on` checkbox) + tujuan rework (dropdown step_no);
 *   * pratinjau graf memakai molekul `RoutingGraph` (Fase 15); posisi node dihitung
 *     auto-layout oleh `lib/master-routing.ts::formToGraph`;
 *   * validasi klien `validateStepRows` (label wajib, order unik, **siklus** DFS
 *     MAX_DAG_DEPTH) → peringatan visual; backend tetap memvalidasi ulang & menjawab
 *     400 (pesan `{"detail": …}` diteruskan ke Toast apa adanya).
 *
 * Simpan:
 *   * create → `POST /api/v1/settings/routing/` (B22) dengan `steps[]`
 *     (`formRowsToB22Steps`; `depends_on` = `step_no`) — semua node sekaligus;
 *   * edit → `PUT /api/v1/settings/routing/<id>/` untuk header, lalu sinkron node:
 *     `PUT` node lama, `POST` node baru, `DELETE` node yang dibuang
 *     (`removedStepIds`). Catatan: node **baru** yang bergantung pada node baru lain
 *     belum punya id backend pada putaran yang sama (backend mengabaikan id yang bukan
 *     milik routing) — pasang edge itu pada penyimpanan berikutnya.
 *
 * MES-only (ledger `SKIPPED`), tanpa `odoo_id`; izin tulis backend ADMIN/OWNER.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function RoutingFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const routingId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = routingId !== null;

  const [draftValues, setDraftValues] = useState<RoutingFormValues | null>(null);
  const [draftSteps, setDraftSteps] = useState<RoutingStepFormRow[] | null>(null);
  const [fallbackSteps] = useState<RoutingStepFormRow[]>(() => [
    makeStepFormRow(AUTO_ORDER_STEP),
  ]);
  const [tagInput, setTagInput] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const removedStepIds = useRef<number[]>([]);

  const detail = useQuery({
    queryKey: ['master-routing', routingId],
    queryFn: () => fetchRouting(client, routingId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const workCenters = useQuery({
    queryKey: ['master-work-centers', 'options'],
    queryFn: () => fetchWorkCenters(client, { limit: WORK_CENTERS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /**
   * Nilai form = draft pengguna → data GET (mode edit) → form kosong.
   *
   * Pola **derive during render** (sama H1.8 `ProductionLineFormPage`): tidak ada
   * `setState` di `useEffect`, jadi tidak ada render ganda & warning lint react-hooks.
   */
  const form = detail.data === undefined ? null : detailToForm(detail.data);
  const values: RoutingFormValues = draftValues ?? form?.values ?? EMPTY_ROUTING_FORM;
  // identitas `fallbackSteps` stabil (useState initializer) supaya memo di bawah
  // tidak dihitung ulang tiap render (warning react-hooks/exhaustive-deps).
  const steps: RoutingStepFormRow[] = draftSteps ?? form?.steps ?? fallbackSteps;

  const errors = useMemo(() => validateRoutingForm(values), [values]);
  const stepError = useMemo(() => validateStepRows(steps), [steps]);
  const valid = Object.keys(errors).length === 0 && stepError === undefined;

  const save = useMutation({
    mutationFn: async () => {
      if (!isEdit) {
        return createRouting(client, {
          name: values.name.trim(),
          description: values.description.trim(),
          steps: formRowsToB22Steps(steps),
        });
      }

      await updateRouting(client, routingId, {
        name: values.name.trim(),
        description: values.description.trim(),
        capability_tags: values.capability_tags,
        active: values.active,
      });

      for (const step of steps) {
        const payload = formRowToStepPayload(step, steps);
        if (step.id === null) {
          await addRoutingStep(client, routingId, payload);
        } else {
          await updateRoutingStep(client, routingId, step.id, payload);
        }
      }

      for (const stepId of removedStepIds.current) {
        await removeRoutingStep(client, routingId, stepId);
      }

      return fetchRouting(client, routingId);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Routing diperbarui' : 'Routing dibuat',
        description: `${saved.code} — ${String(saved.steps_count)} step. MES-only: ledger SKIPPED.`,
      });
      navigate(`/master/routings/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan routing',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof RoutingFormValues>(
    field: K,
    value: RoutingFormValues[K],
  ): void {
    setDraftValues({ ...values, [field]: value });
  }

  function commitTag(): void {
    setField('capability_tags', addTag(values.capability_tags, tagInput));
    setTagInput('');
  }

  function addStep(): void {
    setDraftSteps([...steps, makeStepFormRow(nextStepOrder(steps))]);
  }

  function updateStepRow(key: string, patch: Partial<RoutingStepFormRow>): void {
    setDraftSteps(steps.map((step) => (step.key === key ? { ...step, ...patch } : step)));
  }

  function removeStepRow(step: RoutingStepFormRow): void {
    if (step.id !== null) removedStepIds.current = [...removedStepIds.current, step.id];
    setDraftSteps(
      steps
        .filter((row) => row.key !== step.key)
        .map((row) => ({
          ...row,
          depends_on_keys: row.depends_on_keys.filter((key) => key !== step.key),
          rework_target_step:
            row.rework_target_step === step.order ? null : row.rework_target_step,
        })),
    );
  }

  function toggleDepend(row: RoutingStepFormRow, depKey: string, checked: boolean): void {
    const next = checked
      ? [...row.depends_on_keys, depKey]
      : row.depends_on_keys.filter((key) => key !== depKey);
    updateStepRow(row.key, { depends_on_keys: next });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSubmitted(true);

    if (!valid || save.isPending) return;

    save.mutate();
  }

  const showErrors = submitted;
  const graph = useMemo(() => formToGraph(steps), [steps]);
  const wcRows = workCenters.data?.rows ?? [];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Routing' : 'Routing Baru'}
        subtitle="Alur proses produksi (DAG) — MES-only, tidak disinkron ke Odoo"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Routing', href: '/master/routings' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/routings')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat routing…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat routing (perlu login atau routing tidak ada).
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
            label="Nama *"
            value={values.name}
            placeholder="mis. Routing Kaos Sablon"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Input
            label="Catatan"
            value={values.description}
            placeholder="mis. sablon dulu, baru jahit"
            onChange={(event) => setField('description', event.target.value)}
            {...(showErrors && errors.description !== undefined
              ? { error: errors.description }
              : {})}
          />
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <span className="text-sm font-medium text-foreground">
            Tag Kapabilitas Routing (maksimal {String(MAX_TAGS)}; Enter atau koma untuk menambah)
          </span>

          <div className="flex flex-wrap items-end gap-2">
            <Input
              label="Tambah tag"
              value={tagInput}
              placeholder="mis. JAHIT"
              onChange={(event) => setTagInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ',') {
                  event.preventDefault();
                  commitTag();
                }
              }}
            />
            <Button
              type="button"
              variant="secondary"
              icon={Plus}
              disabled={tagInput.trim().length === 0 || values.capability_tags.length >= MAX_TAGS}
              onClick={commitTag}
            >
              Tambah
            </Button>
          </div>

          <div className="flex flex-wrap gap-2">
            {values.capability_tags.length === 0 ? (
              <span className="text-xs text-muted-foreground">Belum ada tag kapabilitas.</span>
            ) : (
              values.capability_tags.map((tag, index) => (
                <span key={tag} className="flex items-center gap-1">
                  <span className="rounded-full border border-line px-2 py-0.5 text-xs">
                    {tag}
                  </span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-label={`Hapus tag ${tag}`}
                    onClick={() =>
                      setField('capability_tags', removeTag(values.capability_tags, index))
                    }
                  >
                    ×
                  </Button>
                </span>
              ))
            )}
          </div>

          <div className="flex items-center gap-2">
            <Checkbox
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
              label="Aktif"
            />
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-foreground">
              Step / Node DAG ({steps.length} step)
            </span>
            <Button type="button" variant="secondary" size="sm" icon={Plus} onClick={addStep}>
              Tambah Step
            </Button>
          </div>

          {stepError !== undefined ? (
            <p role="alert" className="text-sm font-medium text-accent-coral">
              {stepError}
            </p>
          ) : null}

          <div className="flex flex-col gap-3">
            {steps.map((step) => (
              <div key={step.key} className="flex flex-col gap-3 rounded-md border border-line p-3">
                <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <Input
                    label="Label *"
                    value={step.label}
                    placeholder="mis. SEWING"
                    onChange={(event) => updateStepRow(step.key, { label: event.target.value })}
                  />
                  <Input
                    label="Order"
                    type="number"
                    value={String(step.order)}
                    onChange={(event) =>
                      updateStepRow(step.key, { order: Number(event.target.value) })
                    }
                  />
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Work Center</span>
                    <select
                      className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
                      value={step.work_center_id === null ? '' : String(step.work_center_id)}
                      onChange={(event) =>
                        updateStepRow(step.key, {
                          work_center_id:
                            event.target.value === '' ? null : Number(event.target.value),
                        })
                      }
                    >
                      <option value="">(tanpa work center)</option>
                      {wcRows.map((wc) => (
                        <option key={wc.id} value={String(wc.id)}>
                          {wc.code}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Rework ke (step_no)</span>
                    <select
                      className="h-9 rounded-md border border-line bg-surface px-2 text-sm"
                      value={step.rework_target_step === null ? '' : String(step.rework_target_step)}
                      onChange={(event) =>
                        updateStepRow(step.key, {
                          rework_target_step:
                            event.target.value === '' ? null : Number(event.target.value),
                        })
                      }
                    >
                      <option value="">(tanpa rework)</option>
                      {steps
                        .filter((row) => row.key !== step.key)
                        .map((row) => (
                          <option key={row.key} value={String(row.order)}>
                            order {row.order} — {row.label.trim() || '(tanpa label)'}
                          </option>
                        ))}
                    </select>
                  </label>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <span className="text-xs text-muted-foreground">Menunggu (depends_on):</span>
                  {steps.filter((row) => row.key !== step.key).length === 0 ? (
                    <span className="text-xs text-muted-foreground">(step pertama)</span>
                  ) : (
                    steps
                      .filter((row) => row.key !== step.key)
                      .map((row) => (
                        <Checkbox
                          key={row.key}
                          checked={step.depends_on_keys.includes(row.key)}
                          label={`order ${String(row.order)}`}
                          onCheckedChange={(checked) => toggleDepend(step, row.key, checked)}
                        />
                      ))
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    icon={Trash2}
                    aria-label={`Hapus step order ${String(step.order)}`}
                    onClick={() => removeStepRow(step)}
                  >
                    Hapus
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <span className="text-sm font-medium text-foreground">Pratinjau DAG</span>
          <RoutingGraph graph={graph} />
        </section>

        <div className="flex items-center gap-2">
          <Button type="submit" icon={Save} disabled={save.isPending} loading={save.isPending}>
            Simpan Routing
          </Button>
          <Button type="button" variant="ghost" onClick={() => navigate('/master/routings')}>
            Batal
          </Button>
        </div>
      </form>

      {toast !== null ? (
        <Toast
          open={toast !== null}
          onOpenChange={() => setToast(null)}
          title={toast.title}
          tone={toast.tone}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}



