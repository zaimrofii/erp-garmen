import type { KeyboardEvent } from 'react';
import { cn } from '@/lib/cn';
import { BADGE } from '@/lib/tokens';
import type { DefectRegion } from '@/types/qc';

/**
 * DefectSilhouette - siluet pakaian interaktif untuk menandai lokasi cacat (QC).
 *
 * Setiap region adalah `<path>` yang bisa diklik / difokus keyboard (`role="button"`,
 * `aria-pressed`, Enter/Space). Region dibuat cukup besar (>44px) supaya tetap nyaman
 * disentuh di tablet QC. Warna memakai token: coral = terpilih, biru = hover/fokus.
 */

export type GarmentType = 'shirt' | 'pants' | 'jacket';

const BASE_PATH =
  'M70 24 L86 16 C92 30 108 30 114 16 L130 24 L176 52 L156 96 L138 84 L138 236 C138 244 132 248 124 248 L76 248 C68 248 62 244 62 236 L62 84 L44 96 L24 52 Z';

interface RegionDef {
  id: DefectRegion;
  label: string;
  path: string;
}

/** Urutan array = urutan gambar; region terakhir digambar paling atas (pocket). */
const REGIONS: RegionDef[] = [
  {
    id: 'body',
    label: 'Badan',
    path: 'M62 60 L138 60 L138 236 C138 244 132 248 124 248 L76 248 C68 248 62 244 62 236 Z',
  },
  {
    id: 'collar',
    label: 'Kerah',
    path: 'M86 16 C92 30 108 30 114 16 L128 24 L120 46 L80 46 L72 24 Z',
  },
  {
    id: 'sleeve_left',
    label: 'Lengan kiri',
    path: 'M70 24 L24 52 L44 96 L62 84 L62 58 Z',
  },
  {
    id: 'sleeve_right',
    label: 'Lengan kanan',
    path: 'M130 24 L176 52 L156 96 L138 84 L138 58 Z',
  },
  {
    id: 'hem',
    label: 'Keliman bawah',
    path: 'M62 212 L138 212 L138 236 C138 244 132 248 124 248 L76 248 C68 248 62 244 62 236 Z',
  },
  {
    id: 'pocket',
    label: 'Kantong',
    path: 'M96 96 L128 96 L128 134 L96 134 Z',
  },
];

const GARMENT_LABEL: Record<GarmentType, string> = {
  shirt: 'kaos',
  pants: 'celana',
  jacket: 'jaket',
};

interface DefectSilhouetteProps {
  selected: DefectRegion[];
  onToggle: (region: DefectRegion) => void;
  garmentType?: GarmentType;
  className?: string;
}

export function DefectSilhouette({
  selected,
  onToggle,
  garmentType = 'shirt',
  className,
}: DefectSilhouetteProps) {
  function handleKeyDown(event: KeyboardEvent<SVGPathElement>, region: DefectRegion): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;

    event.preventDefault();
    onToggle(region);
  }

  return (
    <div className={cn('flex flex-col gap-3', className)}>
      <svg
        viewBox="0 0 200 260"
        role="group"
        aria-label={`Siluet ${GARMENT_LABEL[garmentType]} untuk menandai lokasi cacat`}
        className="mx-auto h-auto w-full max-w-[240px]"
      >
        <path d={BASE_PATH} className="fill-muted stroke-border" strokeWidth={1.5} strokeLinejoin="round" />

        {REGIONS.map((region) => {
          const isSelected = selected.includes(region.id);

          return (
            <path
              key={region.id}
              d={region.path}
              role="button"
              tabIndex={0}
              aria-label={`Lokasi ${region.label}`}
              aria-pressed={isSelected}
              onClick={() => onToggle(region.id)}
              onKeyDown={(event) => handleKeyDown(event, region.id)}
              className={cn(
                'cursor-pointer outline-none transition-colors focus-visible:fill-accent-blue/20',
                isSelected
                  ? 'fill-accent-coral/40 stroke-accent-coral'
                  : 'fill-transparent stroke-transparent hover:fill-accent-blue/20',
              )}
              strokeWidth={2}
            />
          );
        })}
      </svg>

      <ul className="flex flex-wrap gap-2">
        {REGIONS.map((region) => {
          const isSelected = selected.includes(region.id);

          return (
            <li key={region.id}>
              <button
                type="button"
                onClick={() => onToggle(region.id)}
                aria-pressed={isSelected}
                className={cn(
                  BADGE,
                  'min-h-11 transition-colors',
                  isSelected
                    ? 'bg-accent-coral/10 text-accent-coral border border-accent-coral/20'
                    : 'bg-muted text-muted-foreground hover:text-foreground',
                )}
              >
                {region.label}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
