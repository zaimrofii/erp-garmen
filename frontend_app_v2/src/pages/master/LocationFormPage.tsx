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
import {
  createLocation,
  fetchLocation,
  fetchLocations,
  LOCATIONS_LIMIT_MAX,
  updateLocation,
} from '@/api/masterLocations';
import { fetchWarehouses, WAREHOUSES_LIMIT_MAX } from '@/api/masterWarehouses';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  EMPTY_LOCATION_FORM,
  isLocationFormValid,
  isLocationUsage,
  LOCATION_USAGE_OPTIONS,
  locationFormFromRow,
  locationInputFromForm,
  locationOptionLabel,
  selectableParentOptions,
  validateLocationForm,
  type LocationFormValues,
} from '@/lib/master-location';
import { warehouseOptionLabel } from '@/lib/master-warehouse';
import { CARD } from '@/lib/tokens';

/**
 * LocationFormPage - route `/master/locations/new` + `/master/locations/:id/edit` (H1.4).
 *
 * 6 field (code, name, usage, parent_id, warehouse_id, active):
 *
 *   * create → `POST /api/v1/master/locations/` (`createLocation`);
 *   * edit   → `PUT /api/v1/master/locations/<id>/` (`updateLocation`);
 *   * validasi `lib/master-location.ts::validateLocationForm` (PURE) — error muncul
 *     setelah submit pertama; tombol tidak dimatikan supaya penyebabnya terlihat;
 *   * sukses → Toast + pindah ke detail; push Odoo asinkron
 *     (`erp_sync.push_master_location`; `create` BOLEH karena Odoo hanya wajib
 *     `name`+`usage`, tapi push **gagal** kalau induk belum punya `odoo_id`);
 *   * izin tulis dibatasi role ADMIN/OWNER di backend (403 kalau bukan).
 *
 * Dropdown induk memakai daftar lokasi AKTIF (diri sendiri disembunyikan saat edit);
 * dropdown gudang memakai master gudang H1.3. Backend tetap penjaga terakhir untuk
 * siklus hierarki (400) dan `warehouse_id` yang tidak ada.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi "kosong" untuk `<select>` induk/gudang (mengirim `null` ke backend). */
const NO_PARENT_OPTION = { value: '', label: '— Tanpa induk (lokasi akar) —' };
const NO_WAREHOUSE_OPTION = { value: '', label: '— Tanpa gudang (lokasi global) —' };
const EMPTY_PARENT_OPTIONS: { value: string; label: string }[] = [NO_PARENT_OPTION];
const EMPTY_WAREHOUSE_OPTIONS: { value: string; label: string }[] = [NO_WAREHOUSE_OPTION];

export function LocationFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const locationId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = locationId !== null;

  const [draft, setDraft] = useState<LocationFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['master-location', locationId],
    queryFn: () => fetchLocation(client, locationId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  /** Kandidat induk: seluruh lokasi AKTIF (diri sendiri disembunyikan saat edit). */
  const parents = useQuery({
    queryKey: ['master-locations', 'parent-options'],
    queryFn: () => fetchLocations(client, { limit: LOCATIONS_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /** Kandidat gudang: master gudang H1.3 yang aktif. */
  const warehouses = useQuery({
    queryKey: ['master-warehouses', 'warehouse-options'],
    queryFn: () => fetchWarehouses(client, { limit: WAREHOUSES_LIMIT_MAX, active: true }),
    staleTime: 60_000,
  });

  /** Nilai form = draft pengguna → data GET (mode edit) → form kosong (tanpa effect). */
  const values: LocationFormValues =
    draft ?? (detail.data === undefined ? EMPTY_LOCATION_FORM : locationFormFromRow(detail.data));

  const errors = useMemo(() => validateLocationForm(values), [values]);
  const valid = isLocationFormValid(errors);

  const parentOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = parents.data?.rows ?? [];

    return [
      NO_PARENT_OPTION,
      ...selectableParentOptions(rows, locationId).map((row) => ({
        value: String(row.id),
        label: locationOptionLabel(row),
      })),
    ];
  }, [parents.data, locationId]);

  const warehouseOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = warehouses.data?.rows ?? [];

    return [
      NO_WAREHOUSE_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: warehouseOptionLabel(row) })),
    ];
  }, [warehouses.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = locationInputFromForm(values);

      return isEdit ? updateLocation(client, locationId, input) : createLocation(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: isEdit ? 'Lokasi diperbarui' : 'Lokasi dibuat',
        description: `${saved.code} — push Odoo ${
          saved.queued ? 'diantrekan' : 'belum masuk broker'
        } (Odoo ID: ${saved.odoo_id === null ? 'belum ada' : String(saved.odoo_id)}).`,
      });
      navigate(`/master/locations/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan lokasi',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof LocationFormValues>(
    field: K,
    value: LocationFormValues[K],
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
        title={isEdit ? 'Edit Lokasi' : 'Lokasi Baru'}
        subtitle="Master lokasi MES — disimpan di MES lalu di-push ke Odoo (asinkron)"
        breadcrumb={[
          { label: 'Inventory', href: '/inventory/products' },
          { label: 'Master Lokasi', href: '/master/locations' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button variant="ghost" icon={ArrowLeft} onClick={() => navigate('/master/locations')}>
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat lokasi…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat lokasi (perlu login atau lokasi tidak ada).
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
            placeholder="mis. WH/STOCK"
            onChange={(event) => setField('code', event.target.value)}
            {...(showErrors && errors.code !== undefined ? { error: errors.code } : {})}
          />
          <Input
            label="Nama *"
            value={values.name}
            placeholder="mis. Stok Gudang Utama"
            onChange={(event) => setField('name', event.target.value)}
            {...(showErrors && errors.name !== undefined ? { error: errors.name } : {})}
          />
          <Select
            label="Jenis"
            options={LOCATION_USAGE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            value={values.usage}
            onChange={(event) => {
              const next = event.target.value;
              if (isLocationUsage(next)) setField('usage', next);
            }}
            {...(showErrors && errors.usage !== undefined ? { error: errors.usage } : {})}
          />
          <Select
            label="Induk"
            options={parentOptions.length === 0 ? EMPTY_PARENT_OPTIONS : parentOptions}
            value={values.parent_id}
            onChange={(event) => setField('parent_id', event.target.value)}
            {...(showErrors && errors.parent_id !== undefined ? { error: errors.parent_id } : {})}
          />
          <Select
            label="Gudang"
            options={warehouseOptions.length === 0 ? EMPTY_WAREHOUSE_OPTIONS : warehouseOptions}
            value={values.warehouse_id}
            onChange={(event) => setField('warehouse_id', event.target.value)}
            {...(showErrors && errors.warehouse_id !== undefined
              ? { error: errors.warehouse_id }
              : {})}
          />
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-1">
            <Checkbox
              label="Lokasi aktif (dipakai transaksi stok)"
              checked={values.active}
              onCheckedChange={(checked) => setField('active', checked)}
            />
            <p className="text-xs text-muted-foreground">
              Catatan: push butuh induk yang sudah punya Odoo ID — kalau induk belum sinkron,
              lokasi ini ditandai gagal (data MES tetap utuh). Gudang tidak dikirim ke Odoo
              karena diturunkan dari hierarki.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Lokasi'}
            </Button>
            <Button type="button" variant="secondary" onClick={() => navigate('/master/locations')}>
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


