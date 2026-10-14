import { Link2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Select } from '@/components/atoms/Select';
import { FormField } from '@/components/molecules/FormField';
import { bindDeviceError, isManualWc, wcSelectOptions } from '@/lib/device-mode';

/**
 * BindDeviceModal — modal bind perangkat ini (F6.4).
 *
 * Kontrak backend: `POST /api/v1/devices/bind` body `{device_profile, wc_code?}` →
 * 200 + **Set-Cookie `device_token`** (HttpOnly). Response/penanganan cookie tetap milik
 * `integrations/device-binding.ts`; modal ini hanya mengumpulkan pilihan admin.
 *
 * Catatan kontrak (tidak ada yang dikarang):
 *  - **Profil** dari katalog `GET /settings/devices/` (B28) — bukan daftar hardcode;
 *  - **WC** dari `work_center_code` yang sudah dipakai di `GET /settings/line-allocation/`
 *    (master WorkCenter belum punya endpoint) + opsi "Lainnya (isi manual)…";
 *  - **Nama Device TIDAK diminta**: `DeviceBinding` (F6.1/Fase G) tidak punya kolom nama
 *    (`wc_code`, `device_profile`, `user`, `cookie_token`, `last_seen_at`) sehingga input
 *    nama akan dibuang backend diam-diam — menambah kolomnya = migration (dilarang F6.4).
 *
 * Komponen ini **controlled** (state dimiliki halaman) supaya perilakunya bisa diuji tanpa
 * DOM: `tests/unit/components/bind-device-modal.test.ts`.
 */

export interface BindDeviceSelection {
  profile: string;
  wcCode: string;
}

export interface BindDeviceModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Katalog profil (`code` + `label`) dari `GET /settings/devices/`. */
  profiles: readonly { code: string; label: string }[];
  /** Kode WC yang diketahui (boleh kosong → input manual). */
  wcOptions: readonly string[];
  profile: string;
  wcSelection: string;
  wcManual: string;
  busy: boolean;
  /** Pesan kegagalan dari percobaan bind sebelumnya (`null` = belum ada). */
  error: string | null;
  onProfileChange: (value: string) => void;
  onWcSelectionChange: (value: string) => void;
  onWcManualChange: (value: string) => void;
  onSubmit: () => void;
}

export function BindDeviceModal({
  open,
  onOpenChange,
  profiles,
  wcOptions,
  profile,
  wcSelection,
  wcManual,
  busy,
  error,
  onProfileChange,
  onWcSelectionChange,
  onWcManualChange,
  onSubmit,
}: BindDeviceModalProps) {
  const validation = bindDeviceError({ profile });
  const canSubmit = validation === null && !busy;

  const profileOptions = profiles.map((item) => ({
    value: item.code,
    label: `${item.code} — ${item.label}`,
  }));

  return (
    <Modal
      open={open}
      onOpenChange={onOpenChange}
      title="Bind Device Baru"
      description="Perangkat ini akan diikat ke profil & work center yang dipilih (cookie device_token)."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Batal
          </Button>
          <Button
            icon={Link2}
            loading={busy}
            disabled={!canSubmit}
            onClick={() => {
              if (canSubmit) onSubmit();
            }}
          >
            Bind
          </Button>
        </>
      }
    >
      <div data-bind-device-form="true" className="flex flex-col gap-4">
        <Select
          label="Profil device"
          value={profile}
          options={profileOptions}
          disabled={busy}
          error={validation ?? undefined}
          onChange={(event) => onProfileChange(event.target.value)}
        />

        <Select
          label="Work center"
          value={wcSelection}
          options={wcSelectOptions(wcOptions)}
          disabled={busy}
          onChange={(event) => onWcSelectionChange(event.target.value)}
        />

        {isManualWc(wcSelection) ? (
          <FormField label="Kode WC (manual)" htmlFor="bind-device-wc-manual">
            <Input
              id="bind-device-wc-manual"
              value={wcManual}
              placeholder="mis. SEW-01"
              disabled={busy}
              onChange={(event) => onWcManualChange(event.target.value)}
            />
          </FormField>
        ) : null}

        {error === null ? null : (
          <p role="alert" className="text-xs font-medium text-accent-coral">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
