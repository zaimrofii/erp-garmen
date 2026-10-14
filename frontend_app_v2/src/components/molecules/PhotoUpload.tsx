import { useEffect, useId, useRef, useState, type ChangeEvent } from 'react';
import { Camera, X } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL_SECONDARY } from '@/lib/tokens';

/**
 * PhotoUpload - bukti foto cacat (opsional).
 *
 * Fase 18: murni lokal - file dibaca jadi **object URL** dan dipakai sebagai preview;
 * upload nyata ke backend (multipart) ditangani fase berikutnya. Object URL di-revoke
 * saat preview diganti/komponen dilepas supaya tidak bocor memori.
 *
 * Input file `hidden` + tombol ber-`aria-label`; `capture="environment"` supaya di HP
 * langsung membuka kamera belakang.
 */

interface PhotoUploadProps {
  value?: string;
  onChange: (dataUrl: string | undefined) => void;
  disabled?: boolean;
  className?: string;
}

export function PhotoUpload({ value, onChange, disabled = false, className }: PhotoUploadProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  // Bersihkan object URL saat komponen dilepas / foto diganti.
  useEffect(() => {
    return () => {
      if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  function handleFile(event: ChangeEvent<HTMLInputElement>): void {
    const file = event.target.files?.[0];
    if (file === undefined) return;

    if (objectUrl !== null) URL.revokeObjectURL(objectUrl);

    const nextUrl = URL.createObjectURL(file);
    setObjectUrl(nextUrl);
    onChange(nextUrl);

    // Reset input supaya file yang sama bisa dipilih lagi.
    event.target.value = '';
  }

  function handleClear(): void {
    if (objectUrl !== null) URL.revokeObjectURL(objectUrl);
    setObjectUrl(null);
    onChange(undefined);
  }

  const preview = value ?? objectUrl;

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        disabled={disabled}
        onChange={handleFile}
      />

      {preview === undefined || preview === null ? (
        <button
          type="button"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
          className={cn(
            'flex items-center justify-center gap-2 rounded-card border border-dashed border-border/80 bg-card py-6',
            'text-sm text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          <Camera className="h-4 w-4" aria-hidden="true" />
          Upload Foto (opsional)
        </button>
      ) : (
        <div className="flex items-center gap-3">
          <img
            src={preview}
            alt="Pratinjau foto cacat"
            className="h-20 w-20 rounded-lg border border-border/60 object-cover"
          />
          <button
            type="button"
            onClick={handleClear}
            disabled={disabled}
            aria-label="Hapus foto"
            className={cn(
              PILL_SECONDARY,
              'h-9 w-9 shrink-0 disabled:opacity-50',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
            )}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
