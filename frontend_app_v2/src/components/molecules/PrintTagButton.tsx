import { useState } from 'react';
import { Printer } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { printBundleTag } from '@/api/print';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';

/**
 * PrintTagButton - cetak tag bundle (`POST /print/bundle-tag/`, kontrak §7.1).
 *
 * Logikanya TIDAK ditulis ulang di sini: pemanggilan endpoint ada di adapter
 * `@/api/print` (`api/real/print.ts`). F14 (opsi B) memigrasikan komponen ini dari
 * `integrations/print-tag.ts` (file legacy dihapus) sehingga SEMUA cetak lewat satu adapter.
 *
 * Perbedaan perilaku yang disengaja (F14): adapter baru melempar Error saat gagal
 * (`unwrap`, pola `printCoupon` F6) — komponen ini menangkapnya, menampilkan Toast, dan
 * meneruskan pesan ke `onError`. Komponen hanya mengurus state pending + Toast + callback.
 */

interface PrintTagButtonProps {
  bundleId: string;
  onSuccess?: () => void;
  onError?: (message: string) => void;
  disabled?: boolean;
  className?: string;
}

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function PrintTagButton({
  bundleId,
  onSuccess,
  onError,
  disabled = false,
  className,
}: PrintTagButtonProps) {
  const client = useApiClient();
  const [pending, setPending] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  async function handleClick(): Promise<void> {
    setPending(true);

    try {
      const job = await printBundleTag(client, bundleId);

      setToast({
        tone: 'success',
        title: 'Tag terkirim ke printer',
        description: `Tag terkirim ke printer (${job.bytes} bytes, backend ${job.backend}).`,
      });
      onSuccess?.();
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Gagal mencetak tag.';

      setToast({ tone: 'error', title: 'Gagal mencetak tag', description: message });
      onError?.(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={cn('flex flex-col items-end gap-2', className)}>
      <Button
        variant="secondary"
        icon={Printer}
        loading={pending}
        disabled={disabled}
        onClick={() => {
          void handleClick();
        }}
      >
        Cetak Tag
      </Button>

      {/* Toast tetap ter-mount supaya `AnimatePresence` bisa menganimasi saat keluar. */}
      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        tone={toast?.tone ?? 'default'}
        title={toast?.title ?? ''}
        description={toast?.description}
      />
    </div>
  );
}
