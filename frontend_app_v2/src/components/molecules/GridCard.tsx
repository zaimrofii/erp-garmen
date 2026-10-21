import type { ReactNode } from "react";
import { Package, type LucideIcon } from "lucide-react";
import { Card } from "@/components/atoms/Card";
import { cn } from "@/lib/cn";
import { mediaUrl } from "@/lib/media-url";

/**
 * GridCard - kartu mode GRID halaman master (FASE K3).
 *
 * Dipakai ProductsPage (`image_url` dari master produk) & PartnersPage (belum punya
 * gambar -> ikon pengganti). Upload gambar baru masuk fase K5, jadi sekarang jalur
 * gambarnya hanya URL yang SUDAH ada di data; kalau kosong -> kotak muted + ikon.
 *
 * Aksesibilitas: gambar diberi `alt=""` (dekoratif - judul sudah jadi teks di bawahnya),
 * dan kalau kartu bisa diklik pembungkusnya `<button type="button">` dengan `aria-label`.
 */

export interface GridCardProps {
  title: string;
  subtitle?: string;
  /**
   * URL gambar (unggahan: `Product.image_display_url` / `Partner.image_display_url`,
   * atau `image_url` legacy). URL relatif `/media/...` di-prefix `mediaUrl()`;
   * `null`/kosong -> `fallbackIcon`.
   */
  imageUrl?: string | null;
  fallbackIcon?: LucideIcon;
  /** Badge/ikon tambahan (mis. `Badge` status) - ditata membungkus di bawah judul. */
  badges?: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function GridCard({
  title,
  subtitle,
  imageUrl,
  fallbackIcon: FallbackIcon = Package,
  badges,
  onClick,
  className,
}: GridCardProps) {
  // K5.5 — URL relatif `/media/...` dari backend di-prefix origin backend.
  const image = mediaUrl(imageUrl) ?? null;

  const body = (
    <>
      {image === null ? (
        <span
          data-grid-image-fallback={title}
          className="flex h-30 xl:h-48 w-full items-center justify-center rounded-card bg-muted"
        >
          <FallbackIcon
            className="h-8 w-8 text-muted-foreground"
            aria-hidden="true"
          />
        </span>
      ) : (
        <img
          src={image}
          alt=""
          data-grid-image={title}
          className=" h-30 xl:h-48 w-full rounded-lg xl:rounded-card object-cover"
        />
      )}

      <span className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold text-foreground">{title}</span>
        {subtitle !== undefined ? (
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        ) : null}
      </span>

      {badges !== undefined ? (
        <span className="flex flex-wrap gap-1">{badges}</span>
      ) : null}
    </>
  );

  return (
    <Card
      as="article"
      className={cn(
        "flex flex-col gap-3 rounded-lg xl:rounded-card p-2 xl:p-3 hover:shadow-xl transition-shadow duration-300",
        className,
      )}
    >
      {onClick === undefined ? (
        <div className="flex flex-col items-stretch gap-3">{body}</div>
      ) : (
        <button
          type="button"
          onClick={onClick}
          aria-label={`Buka ${title}`}
          className="flex flex-col items-stretch gap-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          {body}
        </button>
      )}
    </Card>
  );
}
