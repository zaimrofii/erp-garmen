import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link2, RefreshCw } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { BindDeviceModal } from '@/components/molecules/BindDeviceModal';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchMyDevice } from '@/api/devices';
import { fetchWipByWc } from '@/api/reports';
import { fetchDeviceProfiles } from '@/api/settings';
import { bindDevice, canBindDevice, canUnbindDevice, unbindDevice } from '@/integrations/device-binding';
import { useFeedback } from '@/app/app-runtime';
import { deviceProfileRefresh, normalizeDeviceProfile } from '@/core/useDeviceProfile';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import { MANUAL_WC_VALUE, readWcOptions, resolveBindProfile, resolveWcCode } from '@/lib/device-mode';
import { CARD } from '@/lib/tokens';
import type { DeviceProfile } from '@/types/settings';

/**
 * DeviceProfilesPage - route `/settings/devices` (khusus admin).
 *
 * Ini SATU-SATUNYA halaman Fase 22 yang memakai endpoint REAL:
 *   - `GET /devices/me` lewat adapter `@/api/devices` (MODE.devices === 'real');
 *   - `bindDevice()` / `unbindDevice()` lewat `integrations/device-binding.ts` (Fase G).
 * Keduanya tidak pernah throw, jadi hasilnya dibaca dari `ok` lalu ditampilkan sebagai
 * badge + toast. Setelah aksi, query `/devices/me` di-invalidate (refetch) supaya status
 * yang tampil benar-benar dari server.
 *
 * Daftar profil di bawah memakai adapter REAL `fetchDeviceProfiles`
 * (MODE.settingsDevices === 'real', backend B28 — katalog `DeviceProfile`).
 *
 * F6.4 (mode operasi):
 *   * status perangkat ini dibaca dari `GET /devices/me` dengan sinyal yang BENAR:
 *     `bound = source === 'device_binding'` (endpoint selalu 200 + fallback profile,
 *     jadi status code tidak bisa dipakai) — lihat `api/real/deviceBinding.ts`;
 *   * **Bind Device Baru** membuka `BindDeviceModal` (profil dari katalog B28, WC dari
 *     laporan WIP per WC B21 + opsi manual) → `POST /devices/bind` → cookie device
 *     (HttpOnly, di-set backend) → `deviceProfileRefresh()` (TopBar/AuthGuard ikut berubah);
 *     halaman TIDAK pernah membaca nilai cookie itu sendiri;
 *   * **Unbind** selalu lewat konfirmasi (cookie dihapus = kembali ke mode login);
 *   * daftar binding SEMUA perangkat belum bisa ditampilkan: backend belum punya endpoint
 *     daftar binding (hanya `GET /devices/me` = perangkat ini) → halaman ini menampilkan
 *     status perangkat INI secara akurat, sisanya menunggu izin endpoint kecil (F6.4).
 */

const EMPTY_PROFILES: DeviceProfile[] = [];

const DEVICE_QUERY_KEY = ['devices-me'];

interface ToastState {
  title: string;
  description: string;
  tone: ToastTone;
}

export function DeviceProfilesPage() {
  const apiClient = useApiClient();
  const queryClient = useQueryClient();
  const feedback = useFeedback();

  // F6.4 — state modal bind (controlled) + konfirmasi unbind.
  const [profile, setProfile] = useState('');
  const [wcSelection, setWcSelection] = useState('');
  const [wcManual, setWcManual] = useState('');
  const [bindOpen, setBindOpen] = useState(false);
  const [bindError, setBindError] = useState<string | null>(null);
  const [confirmUnbind, setConfirmUnbind] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const profiles = useQuery({
    queryKey: ['settings-device-profiles'],
    queryFn: () => fetchDeviceProfiles(apiClient),
    staleTime: 60_000,
  });

  const device = useQuery({
    queryKey: DEVICE_QUERY_KEY,
    queryFn: () => fetchMyDevice(apiClient),
    staleTime: 15_000,
  });

  // F6.4 — kode WC untuk dropdown modal bind berasal dari laporan WIP per WC yang SUDAH
  // ADA (B21, `GET /reports/wip/by-wc/`); master WorkCenter belum punya endpoint sendiri →
  // opsi "isi manual" disediakan di modal.
  const wipByWc = useQuery({
    queryKey: ['reports-wip-by-wc'],
    queryFn: () => fetchWipByWc(apiClient),
    staleTime: 60_000,
  });

  const profileRows = profiles.data ?? EMPTY_PROFILES;
  const wcOptions = useMemo(() => readWcOptions(wipByWc.data?.rows ?? []), [wipByWc.data]);

  const currentCode = device.data?.profile ?? null;
  const currentProfile = normalizeDeviceProfile(currentCode);
  const currentLabel =
    profileRows.find((profile) => profile.code === currentCode)?.label ?? currentCode ?? '-';
  const isBound = device.data?.bound === true;

  /** Profil terpilih; kalau admin belum memilih → pakai profil aktif / profil pertama katalog. */
  const effectiveProfile = resolveBindProfile(
    profile,
    currentCode,
    profileRows.map((row) => row.code),
  );

  /** Kode WC final (dropdown atau input manual). */
  const effectiveWc = resolveWcCode(wcSelection, wcManual);

  function refreshDeviceState(): void {
    // F7 — beri tahu resolver GLOBAL (`useDeviceProfile` di App: role & layout) supaya
    // membaca ulang `/devices/me` tanpa reload, lalu segarkan query halaman ini.
    deviceProfileRefresh();
    void queryClient.invalidateQueries({ queryKey: DEVICE_QUERY_KEY });
  }

  const bind = useMutation({
    mutationFn: () => bindDevice(apiClient, effectiveProfile, effectiveWc),
    onSuccess: (outcome) => {
      if (outcome.ok) {
        feedback.trigger('success');
        setToast({
          title: 'Perangkat ter-bind',
          description: `${outcome.deviceProfile ?? effectiveProfile} aktif${
            outcome.wcCode === null ? '' : ` untuk ${outcome.wcCode}`
          }.`,
          tone: 'success',
        });
        setBindError(null);
        setBindOpen(false);
      } else {
        feedback.trigger('error');
        setToast({ title: 'Bind gagal', description: outcome.message, tone: 'error' });
        setBindError(outcome.message);
      }

      refreshDeviceState();
    },
    onError: () => {
      feedback.trigger('error');
      setToast({
        title: 'Bind gagal',
        description: 'Tidak bisa menghubungi server.',
        tone: 'error',
      });
      setBindError('Tidak bisa menghubungi server.');
      refreshDeviceState();
    },
  });

  const unbind = useMutation({
    mutationFn: () => unbindDevice(apiClient),
    onSuccess: (outcome) => {
      if (outcome.ok) {
        feedback.trigger('success');
        setToast({ title: 'Binding dicabut', description: outcome.message, tone: 'success' });
      } else {
        feedback.trigger('error');
        setToast({ title: 'Unbind gagal', description: outcome.message, tone: 'error' });
      }

      setConfirmUnbind(false);
      refreshDeviceState();
    },
    onError: () => {
      feedback.trigger('error');
      setToast({
        title: 'Unbind gagal',
        description: 'Tidak bisa menghubungi server.',
        tone: 'error',
      });
      setConfirmUnbind(false);
      refreshDeviceState();
    },
  });

  const busy = bind.isPending || unbind.isPending;

  const columns: DenseTableColumn<DeviceProfile>[] = [
    {
      key: 'code',
      label: 'Code',
      render: (row) => <span className="font-mono tabular-nums">{row.code}</span>,
    },
    { key: 'label', label: 'Label' },
    { key: 'description', label: 'Deskripsi' },
    {
      key: 'actions',
      label: 'Aksi',
      align: 'right',
      render: (row) => (
        <Button
          variant="secondary"
          size="sm"
          disabled={row.code === currentCode}
          onClick={() => setProfile(row.code)}
        >
          {row.code === currentCode ? 'Aktif' : 'Pilih'}
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Device Profiles"
        subtitle="Status perangkat ini (real backend) dan katalog profil perangkat"
        breadcrumb={[{ label: 'Settings' }, { label: 'Devices' }]}
      />

      <section className={cn(CARD, 'flex flex-col gap-4')}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Perangkat Ini</h2>
          <Button
            variant="secondary"
            size="sm"
            icon={RefreshCw}
            loading={device.isFetching}
            onClick={() => {
              void device.refetch();
            }}
          >
            Refresh Status
          </Button>
        </div>

        <dl className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              Profil
            </dt>
            <dd>
              {currentCode === null ? (
                <Badge tone="muted">Belum ada</Badge>
              ) : (
                <Badge tone="blue">{currentLabel}</Badge>
              )}
            </dd>
          </div>

          <div className="flex items-center gap-2">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              Status
            </dt>
            <dd>
              {isBound ? <Badge tone="blue">Bound</Badge> : <Badge tone="coral">Unbound</Badge>}
            </dd>
          </div>

          {currentProfile === null ? null : (
            <div className="flex items-center gap-2">
              <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
                Dikenali
              </dt>
              <dd className="font-mono text-xs text-foreground">{currentProfile}</dd>
            </div>
          )}

          {/* F6.4 — WC binding: dari cookie device (`GET /devices/me` → `wc_code`). */}
          <div className="flex items-center gap-2">
            <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              Work center
            </dt>
            <dd className="font-mono text-xs text-foreground">
              {device.data?.wcCode ?? '—'}
            </dd>
          </div>
        </dl>

        {device.data?.message === null || device.data === undefined ? null : (
          <p className="text-xs text-muted-foreground">{device.data.message}</p>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            icon={Link2}
            disabled={!canBindDevice({ deviceProfile: effectiveProfile, busy }) || profileRows.length === 0}
            onClick={() => {
              setBindError(null);
              setBindOpen(true);
            }}
          >
            Bind Device Baru
          </Button>

          <Button
            variant="secondary"
            size="sm"
            disabled={!canUnbindDevice({ busy, isBound })}
            onClick={() => setConfirmUnbind(true)}
          >
            {unbind.isPending ? 'Mencabut...' : 'Unbind Perangkat'}
          </Button>

          {profileRows.length === 0 ? (
            <p className="text-xs text-muted-foreground">Daftar profil belum termuat.</p>
          ) : null}
        </div>
      </section>

      <section className={cn(CARD, 'p-0')}>
        <div className="flex flex-wrap items-center justify-between gap-2 p-6 pb-3">
          <h2 className="text-sm font-semibold tracking-tight text-foreground">
            Katalog Device Profile
          </h2>
          <span className="text-xs text-muted-foreground">katalog profil (GET /settings/devices/)</span>
        </div>

        <DenseTable
          columns={columns}
          rows={profileRows}
          loading={profiles.isLoading}
          error={profiles.error === null ? null : 'Gagal memuat katalog device profile.'}
          onRetry={() => {
            void profiles.refetch();
          }}
          emptyMessage="Belum ada device profile."
        />
      </section>

      {/* F6.4 — modal bind device (controlled; state dimiliki halaman). */}
      <BindDeviceModal
        open={bindOpen}
        onOpenChange={(open) => {
          setBindOpen(open);
          if (!open) setBindError(null);
        }}
        profiles={profileRows.map((row) => ({ code: row.code, label: row.label }))}
        wcOptions={wcOptions}
        profile={effectiveProfile}
        wcSelection={wcSelection}
        wcManual={wcManual}
        busy={bind.isPending}
        error={bindError}
        onProfileChange={setProfile}
        onWcSelectionChange={(value) => {
          setWcSelection(value);
          if (value !== MANUAL_WC_VALUE) setWcManual('');
        }}
        onWcManualChange={setWcManual}
        onSubmit={() => bind.mutate()}
      />

      {/* F6.4 — konfirmasi unbind (aksi destruktif: cookie device HttpOnly dihapus). */}
      <Modal
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title="Cabut ikatan perangkat ini?"
        description="Cookie device (HttpOnly) dihapus; perangkat harus login lagi sebelum bisa bekerja."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmUnbind(false)}>
              Batal
            </Button>
            <Button variant="danger" loading={unbind.isPending} onClick={() => unbind.mutate()}>
              Unbind
            </Button>
          </>
        }
      >
        <p className="text-sm text-foreground">
          Perangkat ini akan kembali ke mode login (session/operator). Lanjutkan?
        </p>
      </Modal>

      <Toast
        open={toast !== null}
        onOpenChange={(open) => {
          if (!open) setToast(null);
        }}
        title={toast?.title ?? ''}
        description={toast?.description}
        tone={toast?.tone ?? 'default'}
      />
    </div>
  );
}
