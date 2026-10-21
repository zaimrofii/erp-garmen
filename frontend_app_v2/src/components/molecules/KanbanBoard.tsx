import { useState, type DragEvent } from 'react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { KanbanCard } from '@/components/molecules/KanbanCard';
import { cn } from '@/lib/cn';
import {
  decodeKanbanDrag,
  encodeKanbanDrag,
  KANBAN_COLUMN_CLASS,
  KANBAN_DRAG_FORMAT,
  KANBAN_SKELETON_CARDS,
  kanbanConfirmText,
  kanbanRowClass,
  resolveKanbanDrop,
} from '@/lib/kanban';
import type { KanbanCardData, KanbanColumn, KanbanTransition } from '@/types/kanban';

/**
 * KanbanBoard - papan kanban HTML5-native (FASE K3), TANPA library drag & drop.
 *
 * Alur drop (brief K3): `onDrop` membaca payload dari `dataTransfer`, lalu
 * `resolveKanbanDrop()` mencocokkan `transitions[]` dari BACKEND.
 *
 *   * transisi ADA  -> `onCardMove({cardId, from, to, actionId})` (halaman yang POST);
 *   * transisi TIDAK ADA -> `onInvalidMove(...)` + BATAL (TANPA optimistic update,
 *     tanpa request apa pun). Halaman yang menampilkan toast error dari alasan itu.
 *
 * `KanbanBoard` sengaja TANPA hook (state hover/redup ada di `KanbanColumnView`) supaya
 * bisa diuji sebagai fungsi biasa + walker React (`tests/helpers/react-tree.ts`), gaya
 * yang dipakai repo ini (jsdom tidak jalan di bun).
 */

export interface KanbanMove {
  cardId: number;
  /** Kode kartu (dipakai dialog konfirmasi, mis. `BND-1`). */
  cardCode: string;
  from: string;
  to: string;
  actionId: string;
}

export interface KanbanInvalidMove {
  cardId: number;
  from: string;
  to: string;
  reason: string;
}

export interface KanbanBoardProps {
  columns: readonly KanbanColumn[];
  transitions: readonly KanbanTransition[];
  onCardMove: (move: KanbanMove) => void;
  /**
   * K4.4 - kalau diisi, drop VALID tidak langsung dieksekusi: papan menyerahkan
   * `move` ke pemanggil (dipakai `KanbanBoardWithConfirm` untuk membuka dialog).
   * Tanpa prop ini perilaku lama dipertahankan (`onCardMove` dipanggil langsung).
   */
  onMoveRequest?: (move: KanbanMove) => void;
  /** Dipanggil saat transisi tidak valid (BATAL) - halaman menampilkan toast error. */
  onInvalidMove?: (invalid: KanbanInvalidMove) => void;
  onCardClick?: (card: KanbanCardData) => void;
  loading?: boolean;
  emptyMessage?: string;
  className?: string;
}

interface KanbanColumnViewProps {
  column: KanbanColumn;
  loading: boolean;
  emptyMessage?: string;
  onCardClick?: (card: KanbanCardData) => void;
  onDragOverColumn: (event: DragEvent<HTMLElement>) => void;
  onDropCard: (event: DragEvent<HTMLElement>, to: string) => void;
  onCardDragStart: (card: KanbanCardData, from: string, event: DragEvent<HTMLDivElement>) => void;
}

/** Satu kolom kanban; menyimpan state sorotan (ring-2) & kartu yang sedang di-drag. */
function KanbanColumnView({
  column,
  loading,
  emptyMessage,
  onCardClick,
  onDragOverColumn,
  onDropCard,
  onCardDragStart,
}: KanbanColumnViewProps) {
  const [isOver, setIsOver] = useState(false);
  const [draggingId, setDraggingId] = useState<number | null>(null);

  return (
    <article
      data-kanban-column={column.state}
      data-kanban-column-over={isOver ? 'true' : undefined}
      aria-label={`Kolom ${column.label}`}
      onDragOver={(event) => {
        onDragOverColumn(event);
        setIsOver(true);
      }}
      onDragLeave={() => setIsOver(false)}
      onDrop={(event) => {
        setIsOver(false);
        setDraggingId(null);
        onDropCard(event, column.state);
      }}
      className={cn(
        'flex flex-col gap-2 rounded-card border border-border/70 bg-muted/30 p-2',
        KANBAN_COLUMN_CLASS,
        isOver ? 'ring-2 ring-ring' : undefined,
      )}
    >
      <header className="flex items-center justify-between gap-2 px-1">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          {column.label}
        </span>
        <span className="flex items-center gap-1" data-kanban-column-count={column.count}>
          <Badge tone={column.truncated ? 'coral' : 'muted'}>{column.count}</Badge>
          <span className="sr-only">{`${String(column.count)} kartu`}</span>
          {column.truncated ? (
            <span
              data-kanban-column-truncated={column.state}
              aria-hidden="true"
              className="text-[11px] font-semibold text-accent-coral"
            >
              {`+${String(column.count - column.cards.length)} kartu`}
            </span>
          ) : null}
        </span>
      </header>

      {loading ? (
        Array.from({ length: KANBAN_SKELETON_CARDS }, (_item, index) => (
          <span
            key={index}
            data-kanban-skeleton={column.state}
            className="h-16 animate-pulse rounded-card bg-muted"
          />
        ))
      ) : (
        <>
          {column.cards.map((card) => (
            <KanbanCard
              key={card.id}
              card={card}
              draggable
              dragging={draggingId === card.id}
              onDragStart={(item, event) => {
                setDraggingId(item.id);
                onCardDragStart(item, column.state, event);
              }}
              onDragEnd={() => setDraggingId(null)}
              onClick={onCardClick}
            />
          ))}

          {column.cards.length === 0 ? (
            <p
              data-kanban-column-empty={column.state}
              className="rounded-card border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground"
            >
              {emptyMessage ?? 'Belum ada kartu'}
            </p>
          ) : null}
        </>
      )}
    </article>
  );
}

export function KanbanBoard({
  columns,
  transitions,
  onCardMove,
  onMoveRequest,
  onInvalidMove,
  onCardClick,
  loading = false,
  emptyMessage,
  className,
}: KanbanBoardProps) {
  function handleDragOver(event: DragEvent<HTMLElement>): void {
    // WAJIB `preventDefault()` - tanpa ini browser membatalkan drop (default HTML5).
    event.preventDefault();
    if (event.dataTransfer != null) event.dataTransfer.dropEffect = 'move';
  }

  function handleDrop(event: DragEvent<HTMLElement>, to: string): void {
    event.preventDefault();

    const payload = decodeKanbanDrag(event.dataTransfer?.getData(KANBAN_DRAG_FORMAT) ?? '');
    if (payload === null) return; // drag dari luar papan / payload rusak -> abaikan

    const result = resolveKanbanDrop(payload, to, transitions);
    if (!result.ok) {
      onInvalidMove?.({ cardId: result.cardId, from: result.from, to: result.to, reason: result.reason });
      return; // BATAL: tidak ada optimistic update, tidak ada request
    }

    const move: KanbanMove = {
      cardId: result.cardId,
      cardCode:
        columns
          .flatMap((column) => column.cards)
          .find((card) => card.id === result.cardId)?.code ?? `#${String(result.cardId)}`,
      from: result.from,
      to: result.to,
      actionId: result.actionId,
    };

    if (onMoveRequest !== undefined) {
      onMoveRequest(move); // K4.4 - pemanggil (dialog) yang mengonfirmasi lebih dulu
      return;
    }

    onCardMove(move);
  }

  function handleCardDragStart(
    card: KanbanCardData,
    from: string,
    event: DragEvent<HTMLDivElement>,
  ): void {
    if (event.dataTransfer == null) return;

    event.dataTransfer.setData(KANBAN_DRAG_FORMAT, encodeKanbanDrag({ id: card.id, from }));
    event.dataTransfer.effectAllowed = 'move';
  }

  return (
    <section
      aria-label="Papan kanban"
      data-kanban-columns={columns.length}
      className={cn('flex flex-col gap-3', className)}
    >
      <div className={kanbanRowClass(columns.length)}>
        {columns.map((column) => (
          <KanbanColumnView
            key={column.state}
            column={column}
            loading={loading}
            emptyMessage={emptyMessage}
            onCardClick={onCardClick}
            onDragOverColumn={handleDragOver}
            onDropCard={handleDrop}
            onCardDragStart={handleCardDragStart}
          />
        ))}
      </div>

      {!loading && columns.length === 0 ? (
        <p className="text-sm text-muted-foreground">{emptyMessage ?? 'Belum ada kolom kanban.'}</p>
      ) : null}
    </section>
  );
}
/* ------------------------------------------------------------------
   FASE K4.4 - KONFIRMASI SEBELUM PINDAH (atom `Modal` existing).
   Drop VALID membuka dialog; `onCardMove` (mutation optimistic) hanya dipanggil
   setelah user menekan "Ya, Pindahkan". Drop ILEGAL tetap langsung toast.
   ------------------------------------------------------------------ */

export interface KanbanMoveConfirmDialogProps {
  move: KanbanMove;
  /** Label resource untuk kalimat tanya (mis. `bundle`, `work order`). */
  resourceLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Isi dialog konfirmasi (TANPA hook supaya bisa diuji dengan walker React):
 * kalimat tanya + tombol Batal / Ya, Pindahkan.
 */
export function KanbanMoveConfirmDialog({
  move,
  resourceLabel = 'kartu',
  onConfirm,
  onCancel,
}: KanbanMoveConfirmDialogProps) {
  return (
    <>
      <p className="text-sm text-foreground" data-kanban-confirm-text={move.cardId}>
        {kanbanConfirmText({
          cardCode: move.cardCode,
          from: move.from,
          to: move.to,
          label: resourceLabel,
        })}
      </p>

      <div className="mt-4 flex flex-wrap items-center justify-end gap-2">
        <Button variant="secondary" size="sm" aria-label="Batal" onClick={onCancel}>
          Batal
        </Button>
        <Button size="sm" aria-label="Ya, Pindahkan" onClick={onConfirm}>
          Ya, Pindahkan
        </Button>
      </div>
    </>
  );
}

export interface KanbanBoardWithConfirmProps extends KanbanBoardProps {
  /** `false` = tanpa konfirmasi (aksi langsung; dipakai test/halaman instan). */
  confirmMove?: boolean;
  /** Label resource untuk kalimat konfirmasi (default `kartu`). */
  resourceLabel?: string;
}

/**
 * `KanbanBoard` + dialog konfirmasi. Drop valid -> `onMoveRequest` mengisi state
 * `pendingMove` -> `Modal` terbuka -> "Ya, Pindahkan" memanggil `onCardMove`
 * (mutation optimistic + rollback + invalidate yang sudah ada).
 */
export function KanbanBoardWithConfirm({
  confirmMove = true,
  resourceLabel,
  ...boardProps
}: KanbanBoardWithConfirmProps) {
  const [pendingMove, setPendingMove] = useState<KanbanMove | null>(null);

  return (
    <>
      <KanbanBoard {...boardProps} onMoveRequest={confirmMove ? setPendingMove : undefined} />

      <Modal
        open={pendingMove !== null}
        onOpenChange={(open) => {
          if (!open) setPendingMove(null);
        }}
        title="Konfirmasi pindah kartu"
        description="Aksi ini mengirim permintaan ke server (state machine) dan tidak bisa dibatalkan."
      >
        {pendingMove !== null ? (
          <KanbanMoveConfirmDialog
            move={pendingMove}
            resourceLabel={resourceLabel}
            onCancel={() => setPendingMove(null)}
            onConfirm={() => {
              boardProps.onCardMove(pendingMove);
              setPendingMove(null);
            }}
          />
        ) : null}
      </Modal>
    </>
  );
}