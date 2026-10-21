import type { DragEvent } from 'react';
import { GripVertical } from 'lucide-react';
import { Card } from '@/components/atoms/Card';
import { StatusChip } from '@/components/molecules/StatusChip';
import { cn } from '@/lib/cn';
import { kanbanCardSubtitle } from '@/lib/kanban';
import { chipStatusFromState } from '@/lib/state-display';
import type { KanbanCardData } from '@/types/kanban';

/**
 * KanbanCard - kartu papan kanban (FASE K3), dipakai bundle & work order.
 *
 * Isi: kode + badge state (`StatusChip`, bukan warna saja) + baris info
 * (size/qty/work order) + pegangan drag `GripVertical`. Styling memakai token repo
 * (`rounded-card`, shadow ringan, ring saat hover) - TANPA efek 3D/glass baru.
 *
 * CATATAN TEKNIS: atom `Card` tidak meneruskan props DOM (hanya `as`/`className`/
 * `children`), sedangkan drag HTML5 butuh `draggable` + `onDragStart` di elemen nyata.
 * Karena itu pembungkus `<div>` yang draggable, sedangkan isinya tetap atom `Card`.
 */

export interface KanbanCardProps {
  card: KanbanCardData;
  draggable?: boolean;
  /** Kartu sedang di-drag (efek redup) - state dipegang kolom, bukan kartu. */
  dragging?: boolean;
  onDragStart?: (card: KanbanCardData, event: DragEvent<HTMLDivElement>) => void;
  onDragEnd?: () => void;
  onClick?: (card: KanbanCardData) => void;
  className?: string;
}

export function KanbanCard({
  card,
  draggable = false,
  dragging = false,
  onDragStart,
  onDragEnd,
  onClick,
  className,
}: KanbanCardProps) {
  const body = (
    <>
      <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
        {card.code}
      </span>
      <span className="text-xs text-muted-foreground">{kanbanCardSubtitle(card)}</span>
    </>
  );

  return (
    <div
      data-kanban-card={card.id}
      data-kanban-card-dragging={dragging ? 'true' : undefined}
      draggable={draggable ? true : undefined}
      onDragStart={
        onDragStart === undefined
          ? undefined
          : (event: DragEvent<HTMLDivElement>) => onDragStart(card, event)
      }
      onDragEnd={onDragEnd}
      className={cn(
        draggable ? 'cursor-grab active:cursor-grabbing' : undefined,
        dragging ? 'opacity-60' : undefined,
        className,
      )}
    >
      <Card
        as="article"
        className={cn(
          'flex flex-col gap-2 rounded-card p-3 shadow-soft-card ring-1 ring-border/60 transition-shadow hover:ring-2 hover:ring-ring/40',
        )}
      >
        <header className="flex items-start justify-between gap-2">
          {onClick === undefined ? (
            <span className="flex flex-col items-start gap-1">{body}</span>
          ) : (
            <button
              type="button"
              onClick={() => onClick(card)}
              aria-label={`Buka ${card.code}`}
              className="flex flex-col items-start gap-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            >
              {body}
            </button>
          )}

          <StatusChip status={chipStatusFromState(card.state)} label={card.state} />
        </header>

        <footer className="flex items-center justify-end gap-1 text-muted-foreground">
          <GripVertical className="h-4 w-4" aria-hidden="true" />
          <span className="text-[11px]">Tarik untuk pindah kolom</span>
        </footer>
      </Card>
    </div>
  );
}
