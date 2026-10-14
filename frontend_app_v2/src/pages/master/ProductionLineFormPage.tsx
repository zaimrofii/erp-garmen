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
import { fetchWorkCenters, WORK_CENTERS_LIMIT_MAX } from '@/api/masterWorkCenters';
import {
  createProductionLine,
  fetchProductionLine,
  updateProductionLine,
} from '@/api/masterProductionLines';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  addTag,
  EMPTY_PRODUCTION_LINE_FORM,
  isProductionLineFormValid,
  MAX_TAGS,
  productionLineFormFromRow,
  productionLineInputFromForm,
  removeTag,
  toggleWorkCenter,
  validateProductionLineForm,
  type ProductionLineFormValues,
} from '@/lib/master-production-line';
import { CARD } from '@/lib/tokens';

/**
 * ProductionLineFormPage - route `/master/production-lines/new` + `/:id/edit` (H1.8).
 *
 * Field: kode (wajib) · nama (wajib) · catatan · **tag kapabilitas** (input tag
 * sama seperti H1.7) · **anggota work center** (multi-select checkbox dari
 * `GET /master/work-centers/`) · aktif.
 *
 *   * create → `POST /api/v1/master/production-lines/` (`createProductionLine`);
 *   * edit   → `PUT /api/v1/master/production-lines/<id>/` (`updateProductionLine`);
 *     `work_center_ids` = **replace penuh** anggota lini (backend atomic;
 *     id tidak dikenal → 400 tanpa mengubah apa pun);
 *   * validasi PURE `lib/master-production-line.ts` (kode & nama wajib, tag
 *     ≤ 20 × 32, catatan ≤ 2000) — error muncul setelah submit pertama;
 *   * anggota WC **boleh kosong** (lini tanpa stasiun) — backend juga membolehkan;
 *   * sukses → Toast + pindah ke detail. MES-only: ledger sync `SKIPPED`, tidak ada push.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function ProductionLineFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const lineId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = lineId !== null;

  const [draft, setDraft] = useState<ProductionLineFormValues | null>(null);
  const [tagInput, setTagInput] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-production-line', lineId],
    queryFn: () => fetchProductionLine(client, lineId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const workCenters = useQuery({
    queryKey: ['master-work-centers', 'options'],
    queryFn: () => fetchWorkCenters(client, { limit: WORK_CENTERS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong. */
  const values: ProductionLineFormValues =
    draft ??
    (detail.data === undefined
      ? EMPTY_PRODUCTION_LINE_FORM
      : productionLineFormFromRow(detail.data));

  const errors = useMemo(() => validateProductionLineForm(values), [values]);
  const valid = isProductionLineFormValid(errors);

  const save = useMutation({
    mutationFn: async () => {
      const input = productionLineInputFromForm(values);

      return isEdit ? updateProductionLine(client, lineId, input) : createProductionLine(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Production line diperbarui' : 'Production line dibuat',
        description: `${saved.code} — ${String(saved.work_centers_count)} work center. MES-only: ledger ${
          saved.sync_status ?? 'SKIPPED'
        }.`,
      });
      navigate(`/master/production-lines/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan production line',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof ProductionLineFormValues>(
    field: K,
    value: ProductionLineFormValues[K],
  ): void {
    setDraft({ ...values, [field]: value });
  }

  function commitTag(): void {
    setField('capability_tags', addTag(values.capability_tags, tagInput));
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
        title={isEdit ? 'Edit Production Line' : 'Production Line Baru'}
        subtitle="Master lini produksi MES (MES-only — tidak disinkron ke Odoo)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Production Line', href: '/master/production-lines' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button
            variant="ghost"
            icon={ArrowLeft}
            onClick={() => navigate('/master/production-lines')}
          >
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat production line…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat production line (perlu login atau lini tidak ada).
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
            placeholder="mis. LINE-A"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Lini Jahit A"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <div className="md:col-span-2">
            <Input
              label="Catatan"
              value={values.description}
              placeholder="mis. lini utama shift 1"
              onChange={(event) => setField('description', event.target.value)}
              {...(showErrors && errors.description !== undefined
                ? { error: errors.description }
                : {})}
            />
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <span className="text-sm font-medium text-foreground">
            Tag Kapabilitas Lini (maksimal 20; Enter atau koma untuk menambah)
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

          {showErrors && errors.capability_tags !== undefined ? (
            <p role="alert" className="text-sm font-medium text-accent-coral">
              {errors.capability_tags}
            </p>
          ) : null}
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-sm font-medium text-foreground">
              Anggota Work Center ({values.work_center_ids.length} dipilih — boleh kosong)
            </span>
            {values.work_center_ids.length > 0 ? (
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => setField('work_center_ids', [])}
              >
                Kosongkan
              </Button>
            ) : null}
          </div>

          {workCenters.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner size="sm" /> Memuat pilihan work center…
            </div>
          ) : null}

          {workCenters.error !== null ? (
            <p role="alert" className="text-sm font-medium text-accent-coral">
              Gagal memuat daftar work center (butuh login). Anggota bisa diatur setelah
              daftar tersedia.
            </p>
          ) : null}

          <div className="flex max-h-72 flex-col gap-2 overflow-y-auto rounded border border-border p-3">
            {(workCenters.data?.rows ?? []).length === 0 ? (
              <span className="text-xs text-muted-foreground">
                Belum ada work center aktif. Tambahkan lewat modul Master Work Center.
              </span>
            ) : (
              (workCenters.data?.rows ?? []).map((center) => (
                <Checkbox
                  key={center.id}
                  label={`${center.code} — ${center.name}`}
                  checked={values.work_center_ids.includes(center.id)}
                  onCheckedChange={() =>
                    setField('work_center_ids', toggleWorkCenter(values.work_center_ids, center.id))
                  }
                />
              ))
            )}
          </div>

          <p className="text-xs text-muted-foreground">
            Anggota lini dipakai `capability_allocator`: lini dianggap mampu kalau
            **superset** work center yang dibutuhkan routing. Submit mengirim
            `work_center_ids` sebagai replace penuh (backend atomic).
          </p>
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-2">
            <Checkbox
              label="Production line aktif"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            <p className="text-xs text-muted-foreground">
              Guard backend: lini yang masih menampung bundle aktif (state bukan
              DONE/CANCELLED) tidak bisa dinonaktifkan. `LineAllocationRule` tidak
              memblokir (soft delete tidak menghapus baris).
            </p>
            <p className="text-xs text-muted-foreground">
              Production Line = data MES: tidak ada push/pull Odoo (ledger sync ditulis
              `SKIPPED`, lihat `/settings/sync`).
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Production Line'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/master/production-lines')}
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
