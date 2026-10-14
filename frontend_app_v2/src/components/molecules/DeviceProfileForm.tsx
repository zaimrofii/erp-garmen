import { useId, useState, type FormEvent } from 'react';
import { Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Card } from '@/components/atoms/Card';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { Select, type SelectOption } from '@/components/atoms/Select';
import { Textarea } from '@/components/atoms/Textarea';
import { FormField } from '@/components/molecules/FormField';
import type { DeviceProfile } from '@/types/settings';

/**
 * DeviceProfileForm - form profil perangkat (HP / kios / scanner / desktop).
 * `id <= 0` pada hasil `onSave` berarti profil baru (belum ada di backend).
 * Unbind sengaja lewat `Modal` konfirmasi karena itu aksi destruktif.
 */

const DEVICE_CODE_OPTIONS: SelectOption[] = [
  { value: 'OPERATOR_HP', label: 'HP Operator' },
  { value: 'KIOSK_TABLET', label: 'Tablet Kios' },
  { value: 'SCANNER_USB', label: 'Scanner USB' },
  { value: 'DESKTOP', label: 'Desktop Admin' },
];

const DEFAULT_CODE = 'OPERATOR_HP';

interface DeviceProfileFormProps {
  current?: DeviceProfile;
  onSave: (profile: DeviceProfile) => void;
  onBind?: () => void;
  onUnbind?: () => void;
  className?: string;
}

export function DeviceProfileForm({
  current,
  onSave,
  onBind,
  onUnbind,
  className,
}: DeviceProfileFormProps) {
  const labelFieldId = useId();
  const [code, setCode] = useState(current?.code ?? DEFAULT_CODE);
  const [label, setLabel] = useState(current?.label ?? '');
  const [description, setDescription] = useState(current?.description ?? '');
  const [confirmUnbind, setConfirmUnbind] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();

    onSave({
      id: current?.id ?? 0,
      code,
      label: label.trim(),
      description: description.trim(),
    });
  }

  return (
    <Card as="section" className={className}>
      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <Select
          label="Kode perangkat"
          value={code}
          options={DEVICE_CODE_OPTIONS}
          onChange={(event) => setCode(event.target.value)}
        />

        <FormField label="Label perangkat" htmlFor={labelFieldId} required>
          <Input
            id={labelFieldId}
            value={label}
            placeholder="mis. HP Operator Jahit-01"
            onChange={(event) => setLabel(event.target.value)}
          />
        </FormField>

        <Textarea
          label="Deskripsi"
          value={description}
          placeholder="Catatan lokasi / pemakaian perangkat"
          onChange={(event) => setDescription(event.target.value)}
        />

        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary">
            Simpan
          </Button>

          {onBind !== undefined ? (
            <Button type="button" variant="secondary" onClick={onBind}>
              Bind perangkat
            </Button>
          ) : null}

          {onUnbind !== undefined ? (
            <Button
              type="button"
              variant="danger"
              icon={Trash2}
              onClick={() => setConfirmUnbind(true)}
            >
              Unbind
            </Button>
          ) : null}
        </div>
      </form>

      <Modal
        open={confirmUnbind}
        onOpenChange={setConfirmUnbind}
        title="Lepas binding perangkat?"
        description="Perangkat ini berhenti memakai identitas yang ter-bind. Aksi ini perlu diulang bind untuk mengaktifkan kembali."
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmUnbind(false)}>
              Batal
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirmUnbind(false);
                onUnbind?.();
              }}
            >
              Ya, lepas
            </Button>
          </>
        }
      />
    </Card>
  );
}
