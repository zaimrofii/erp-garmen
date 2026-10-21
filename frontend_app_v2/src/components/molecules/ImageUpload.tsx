import {
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode,
} from 'react';
import { Image as ImageIcon, Trash2 } from 'lucide-react';
import { Spinner } from '@/components/atoms/Spinner';
import { cn } from '@/lib/cn';
import {
  IMAGE_ACCEPT,
  fileFromDropEvent,
  fileFromInputEvent,
  pickImageFile,
} from '@/lib/image-upload';
import { mediaUrl } from '@/lib/media-url';

/**
 * ImageUpload - kotak gambar kecil dengan pratinjau, drag-and-drop, dan tombol hapus
 * (FASE K5.3; backend `POST|DELETE /api/v1/master/<resource>/<id>/image/`).
 *
 * Cara pakai: klik kotak → file picker; tarik berkas ke kotak → unggah; tombol
 * keranjang di pojok kanan atas → hapus. Validasi klien (jpg/jpeg/png/webp, maks 5 MB)
 * ada di `lib/image-upload.ts`; backend tetap memverifikasi ulang.
 *
 * Komponen dipisah dua lapis supaya bisa diuji TANPA jsdom (gaya repo ini):
 *   * `ImageBox`   - PURE (tanpa hook): pratinjau/placeholder, overlay spinner,
 *                    tombol hapus, dan seluruh handler sebagai props;
 *   * `ImageUpload`- pembungkus state (drag/unggah/error) + `<input type="file">`.
 */

export type ImageUploadSize = 'sm' | 'md';

/** Kotak `sm` = 120px (default detail page), `md` = 160px. */
const BOX_SIZE: Record<ImageUploadSize, string> = {
  sm: 'h-[120px] w-[120px]',
  md: 'h-[160px] w-[160px]',
};

const BOX_BASE =
  'relative flex shrink-0 items-center justify-center overflow-hidden rounded-card border bg-card transition-colors';

export interface ImageBoxProps {
  /** `image_display_url`/`image_thumbnail_url`; kosong → placeholder ikon. */
  url?: string | null;
  fallbackIcon?: ReactNode;
  /** Overlay spinner (unggah/hapus sedang jalan). */
  uploading: boolean;
  dragActive: boolean;
  disabled: boolean;
  size: ImageUploadSize;
  errorMessage?: string | null;
  onPick: () => void;
  onDrop: (event: DragEvent<HTMLElement>) => void;
  onDragOver: (event: DragEvent<HTMLElement>) => void;
  onDragLeave: () => void;
  onDelete: (event: MouseEvent<HTMLButtonElement>) => void;
  className?: string;
}

/** PURE - kotak gambar (tanpa hook) supaya handler bisa diuji dengan walker React. */
export function ImageBox({
  url,
  fallbackIcon,
  uploading,
  dragActive,
  disabled,
  size,
  errorMessage,
  onPick,
  onDrop,
  onDragOver,
  onDragLeave,
  onDelete,
  className,
}: ImageBoxProps): ReactElement {
  const hasImage = typeof url === 'string' && url.length > 0;

  function handleKeyDown(event: KeyboardEvent<HTMLElement>): void {
    if (disabled) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;

    event.preventDefault();
    onPick();
  }

  return (
    <div className={cn('flex shrink-0 flex-col gap-1', className)}>
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-label={hasImage ? 'Ganti gambar' : 'Unggah gambar'}
        aria-disabled={disabled ? true : undefined}
        title="Klik untuk memilih gambar, atau tarik berkas ke sini"
        data-image-upload={hasImage ? 'filled' : 'empty'}
        data-image-upload-drag={dragActive ? 'true' : undefined}
        onClick={disabled ? undefined : onPick}
        onKeyDown={handleKeyDown}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          BOX_BASE,
          BOX_SIZE[size],
          'border-border/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          dragActive ? 'border-accent-blue ring-2 ring-ring' : undefined,
          disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        )}
      >
        {hasImage ? (
          <img src={url ?? ''} alt="Gambar" className="h-full w-full object-cover" />
        ) : (
          <span className="flex flex-col items-center gap-1 px-2 text-center text-muted-foreground">
            {fallbackIcon ?? <ImageIcon className="h-6 w-6" aria-hidden="true" />}
            <span className="text-[11px] font-medium">
              {dragActive ? 'Lepaskan berkas' : 'Klik / tarik gambar'}
            </span>
          </span>
        )}

        {uploading ? (
          <span className="absolute inset-0 flex items-center justify-center bg-background/70">
            <Spinner size="sm" />
          </span>
        ) : null}

        {hasImage && !disabled ? (
          <button
            type="button"
            aria-label="Hapus gambar"
            disabled={uploading}
            onClick={(event) => {
              event.stopPropagation();
              onDelete(event);
            }}
            className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-pill bg-primary text-primary-foreground opacity-90 transition-opacity hover:opacity-100 disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </div>

      {typeof errorMessage === 'string' && errorMessage.length > 0 ? (
        <p role="alert" className="w-[120px] text-[11px] text-accent-coral">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}

export interface ImageUploadProps {
  /**
   * URL gambar sekarang (`image_display_url`); kosong → placeholder ikon.
   * URL relatif `/media/...` (bentuk backend) di-prefix origin backend lewat
   * `mediaUrl()` supaya tidak tertuju ke origin frontend (:5173).
   */
  currentUrl?: string | null;
  /** Ikon placeholder (mis. `<Package />` untuk produk, `<Users />` untuk partner). */
  fallbackIcon?: ReactNode;
  onUpload: (file: File) => Promise<void>;
  onDelete?: () => Promise<void>;
  disabled?: boolean;
  size?: ImageUploadSize;
  className?: string;
  /**
   * Override status sibuk (dipakai test/halaman yang mengelola statusnya sendiri).
   * Kalau `undefined`, status sibuk dihitung dari proses unggah/hapus internal.
   */
  uploading?: boolean;
  /** Laporan validasi/kesalahan unggah supaya halaman bisa menampilkan toast. */
  onError?: (message: string) => void;
}

/**
 * Kotak gambar + input file tersembunyi. Validasi klien jalan lebih dulu
 * (`pickImageFile`); berkas cacat TIDAK memanggil `onUpload`.
 */
export function ImageUpload({
  currentUrl,
  fallbackIcon,
  onUpload,
  onDelete,
  disabled = false,
  size = 'md',
  className,
  uploading,
  onError,
}: ImageUploadProps): ReactElement {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isUploading = uploading ?? busy;
  const isDisabled = disabled || isUploading;

  function reportError(message: string): void {
    setError(message);
    if (onError !== undefined) onError(message);
  }

  async function run(action: () => Promise<void>, fallbackMessage: string): Promise<void> {
    setError(null);
    setBusy(true);
    try {
      await action();
    } catch (caught) {
      reportError(caught instanceof Error ? caught.message : fallbackMessage);
    } finally {
      setBusy(false);
    }
  }

  function accept(file: File | null): void {
    pickImageFile(file, {
      onAccept: (accepted) => {
        void run(() => onUpload(accepted), 'Gagal mengunggah gambar.');
      },
      onReject: reportError,
    });
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>): void {
    accept(fileFromInputEvent(event));
    // Reset supaya berkas yang sama bisa dipilih lagi setelah gagal.
    event.target.value = '';
  }

  return (
    <div className={cn('shrink-0', className)}>
      <input
        ref={inputRef}
        type="file"
        accept={IMAGE_ACCEPT}
        hidden
        disabled={isDisabled}
        onChange={handleChange}
        aria-label="Berkas gambar"
      />

      <ImageBox
        url={mediaUrl(currentUrl)}
        fallbackIcon={fallbackIcon}
        uploading={isUploading}
        dragActive={dragActive}
        disabled={isDisabled}
        size={size}
        errorMessage={error}
        onPick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          if (!isDisabled) setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          if (isDisabled) return;
          accept(fileFromDropEvent(event));
        }}
        onDelete={() => {
          if (onDelete === undefined) return;
          void run(onDelete, 'Gagal menghapus gambar.');
        }}
      />
    </div>
  );
}
