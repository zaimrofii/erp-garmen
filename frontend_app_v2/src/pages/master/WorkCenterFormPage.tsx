import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, X } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Input } from '@/components/atoms/Input';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import {
  createWorkCenter,
  fetchWorkCenter,
  updateWorkCenter,
} from '@/api/masterWorkCenters';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addTag,
  EMPTY_WORK_CENTER_FORM,
  isWorkCenterFormValid,
  MAX_TAGS,
  removeTag,
  validateWorkCenterForm,
  WC_TYPE_SUGGESTIONS,
  workCenterFormFromRow,
  workCenterInputFromForm,
  type WorkCenterFormValues,
} from '@/lib/master-work-center';
import { CARD } from '@/lib/tokens';

/**
 * WorkCenterFormPage - route `/master/work-centers/new` + `/:id/edit` (H1.7).
 *
 * Field: kode (wajib) · nama (wajib) · tipe stasiun (`datalist` saran, free-form) ·
 * kapasitas/jam · **tag kapabilitas** (input tag: Enter/koma menambah, klik ×
 * menghapus, dedupe case-insensitive) · catatan · aktif.
 *
 *   * create → `POST /api/v1/master/work-centers/` (`createWorkCenter`);
 *   * edit   → `PUT /api/v1/master/work-centers/<id>/` (`updateWorkCenter`);
 *   * validasi PURE `lib/master-work-center.ts` (kode & nama wajib, kapasitas angka
 *     ≥ 0, ≤ 20 tag × 32 karakter) — error muncul setelah submit pertama;
 *   * sukses → Toast + pindah ke detail. Work Center **MES-only**: tidak ada push
 *     Odoo, ledger sync ditulis `SKIPPED` (lihat `/settings/sync`);
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function WorkCenterFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const workCenterId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = workCenterId !== null;

  const [draft, setDraft] = useState<WorkCenterFormValues | null>(null);
  const [tagInput, setTagInput] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-work-center', workCenterId],
    queryFn: () => fetchWorkCenter(client, workCenterId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong. */
  const values: WorkCenterFormValues =
    draft ??
    (detail.data === undefined ? EMPTY_WORK_CENTER_FORM : workCenterFormFromRow(detail.data));

  const errors = useMemo(() => validateWorkCenterForm(values), [values]);
  const valid = isWorkCenterFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = workCenterInputFromForm(values);

      return isEdit
        ? updateWorkCenter(client, workCenterId, input)
        : createWorkCenter(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Work center diperbarui' : 'Work center dibuat',
        description: `${saved.code} — MES-only: tidak dikirim ke Odoo (ledger ${
          saved.sync_status ?? 'SKIPPED'
        }).`,
      });
      navigate(`/master/work-centers/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan work center',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof WorkCenterFormValues>(
    field: K,
    value: WorkCenterFormValues[K],
  ): void {
    setDraft({ ...values, [field]: value });
  }

  function commitTag(): void {
    const next = addTag(values.capability_tags, tagInput);
    setField('capability_tags', next);
    setTagInput('');
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
        title={isEdit ? 'Edit Work Center' : 'Work Center Baru'}
        subtitle="Master work center MES (MES-only — tidak disinkron ke Odoo)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Work Center', href: '/master/work-centers' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/work-centers')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat work center…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat work center (perlu login atau work center tidak ada).
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
            placeholder="mis. SEWING-1"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Stasiun Jahit 1"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <div className="flex flex-col gap-2">
            <Input
              label="Tipe Stasiun"
              value={values.wc_type}
              placeholder={`mis. ${WC_TYPE_SUGGESTIONS.join(' / ')}`}
              onChange={(event) => setField('wc_type', event.target.value)}
              {...(showErrors && errors.wc_type !== undefined ? { error: errors.wc_type } : {})}
            />
            <div className="flex flex-wrap gap-1">
              {WC_TYPE_SUGGESTIONS.map((type) => (
                <button
                  key={type}
                  type="button"
                  className="rounded border border-border px-2 py-0.5 text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setField('wc_type', type)}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>
          <Input
            label="Kapasitas per Jam"
            inputMode="decimal"
            value={values.capacity_per_hour}
            placeholder="mis. 40.5 (0 = belum diukur)"
            onChange={(event) => setField('capacity_per_hour', event.target.value)}
            {...(showErrors && errors.capacity_per_hour !== undefined
              ? { error: errors.capacity_per_hour }
              : {})}
          />
          <div className="md:col-span-2">
            <Input
              label="Catatan"
              value={values.description}
              placeholder="mis. meja jahit utama, mesin JUKI"
              onChange={(event) => setField('description', event.target.value)}
              {...(showErrors && errors.description !== undefined
                ? { error: errors.description }
                : {})}
            />
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <span className="text-sm font-medium text-foreground">
            Tag Kapabilitas (maksimal 20; Enter atau koma untuk menambah)
          </span>

          <div className="flex flex-wrap items-end gap-2">
            <Input
              label="Tambah tag"
              value={tagInput}
              placeholder="mis. JAHIT_LURUS"
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
                <span
                  key={tag}
                  className="flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs"
                >
                  {tag}
                  <button
                    type="button"
                    aria-label={`Hapus tag ${tag}`}
                    onClick={() =>
                      setField('capability_tags', removeTag(values.capability_tags, index))
                    }
                  >
                    <X className="h-3 w-3" aria-hidden="true" />
                  </button>
                </span>
              ))
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            Tag dipakai allocator/routing untuk mencocokkan kapabilitas stasiun
            (duplikat otomatis dibuang, huruf dipertahankan).
          </p>

          {showErrors && errors.capability_tags !== undefined ? (
            <p role="alert" className="text-sm font-medium text-accent-coral">
              {errors.capability_tags}
            </p>
          ) : null}
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-2">
            <Checkbox
              label="Work center aktif"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            <p className="text-xs text-muted-foreground">
              Guard backend: work center yang masih memegang bundle aktif (state bukan
              DONE/CANCELLED) tidak bisa dinonaktifkan.
            </p>
            <p className="text-xs text-muted-foreground">
              Work Center = data MES: tidak ada push/pull Odoo (ledger sync ditulis
              `SKIPPED`, lihat `/settings/sync`).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Work Center'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/master/work-centers')}
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
