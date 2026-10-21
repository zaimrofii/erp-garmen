/**
 * kanban.ts - LOGIC papan kanban yang bisa diuji tanpa DOM (FASE K3).
 *
 * Backend (K2) sudah mengirim `transitions[]` dari `core.state_machine`, jadi keputusan
 * "boleh dipindah ke kolom X?" = mencari pasangan (`from`,`to`) di data itu. Frontend
 * TIDAK menyimpan daftar transisi/state sendiri - backend tetap source of truth.
 *
 * Aturan UX (brief K3): transisi tidak valid => **BATAL** (tanpa optimistic update,
 * tanpa memanggil API). Fungsi di sini murni: keputusan dihitung di sini,
 * `KanbanBoard` mengeksekusi, halaman yang menampilkan toast.
 */

import type { KanbanCardData, KanbanResponse, KanbanTransition } from '@/types/kanban';

/** MIME kunci drag kartu: ditulis `dragstart`, dibaca `drop` (HTML5 native, tanpa lib). */
export const KANBAN_DRAG_FORMAT = 'application/x-mes-kanban-card';

/** Jumlah kartu "hantu" per kolom saat memuat (skeleton). */
export const KANBAN_SKELETON_CARDS = 3;

export interface KanbanDragPayload {
  id: number;
  from: string;
}

/** PURE - payload drag -> string untuk `dataTransfer.setData`. */
export function encodeKanbanDrag(payload: KanbanDragPayload): string {
  return JSON.stringify({ id: payload.id, from: payload.from });
}

/** PURE - string `dataTransfer` -> payload; `null` kalau kosong/rusak/asing. */
export function decodeKanbanDrag(raw: string): KanbanDragPayload | null {
  if (raw.trim().length === 0) return null;

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (typeof parsed !== 'object' || parsed === null) return null;

  const map = new Map(Object.entries(parsed));
  const id = map.get('id');
  const from = map.get('from');
  if (typeof id !== 'number' || typeof from !== 'string' || from.length === 0) return null;

  return { id, from };
}

/** PURE - transisi `from -> to` dari `transitions[]` backend (`null` = tidak diizinkan). */
export function findKanbanTransition(
  transitions: readonly KanbanTransition[],
  from: string,
  to: string,
): KanbanTransition | null {
  const source = from.trim().toUpperCase();
  const target = to.trim().toUpperCase();
  if (source.length === 0 || target.length === 0) return null;

  return (
    transitions.find(
      (transition) =>
        transition.from.trim().toUpperCase() === source &&
        transition.to.trim().toUpperCase() === target,
    ) ?? null
  );
}

export type KanbanDropResult =
  | { ok: true; cardId: number; from: string; to: string; actionId: string }
  | { ok: false; cardId: number; from: string; to: string; reason: string };

/**
 * PURE - hasil drop: valid -> `actionId`; tidak valid -> alasan siap-tampil (toast).
 * Dipanggil `KanbanBoard.onDrop` SEBELUM apa pun dikirim ke server.
 */
export function resolveKanbanDrop(
  payload: KanbanDragPayload,
  to: string,
  transitions: readonly KanbanTransition[],
): KanbanDropResult {
  const target = to.trim().toUpperCase();

  if (payload.from.trim().toUpperCase() === target) {
    return {
      ok: false,
      cardId: payload.id,
      from: payload.from,
      to,
      reason: 'Kartu sudah berada di kolom ini.',
    };
  }

  const transition = findKanbanTransition(transitions, payload.from, to);
  if (transition === null) {
    return {
      ok: false,
      cardId: payload.id,
      from: payload.from,
      to,
      reason: `Transisi ${payload.from} ke ${target} tidak tersedia di state machine.`,
    };
  }

  return { ok: true, cardId: payload.id, from: payload.from, to, actionId: transition.action_id };
}

/** PURE - baris info kartu: `L · 5 pcs · WO-2026-0001` (bagian kosong dibuang). */
export function kanbanCardSubtitle(card: KanbanCardData): string {
  const parts: string[] = [];
  if (card.size !== null && card.size.length > 0) parts.push(card.size);
  parts.push(`${String(card.qty)} pcs`);
  if (card.work_order_code !== null && card.work_order_code.length > 0) {
    parts.push(card.work_order_code);
  }

  return parts.join(' · ');
}

/**
 * Kelas baris kolom: geser-horizontal (snap) di HP, grid penuh di `xl`.
 * `XL_COLUMNS` ditulis literal supaya Tailwind v4 tetap menghasilkan kelasnya
 * (utility dinamis `xl:grid-cols-${n}` TIDAK terdeteksi).
 */
export const KANBAN_ROW_CLASS =
  'flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 xl:grid xl:items-start xl:overflow-visible';

/** Lebar kolom saat mode geser (HP) - di `xl` kolom mengikuti grid. */
export const KANBAN_COLUMN_CLASS = 'w-72 shrink-0 snap-start xl:w-auto';

const XL_COLUMNS: Record<number, string> = {
  2: 'xl:grid-cols-2',
  3: 'xl:grid-cols-3',
  4: 'xl:grid-cols-4',
  5: 'xl:grid-cols-5',
  6: 'xl:grid-cols-6',
};

/** PURE - kelas baris kanban + grid N kolom saat `columnCount` didukung. */
export function kanbanRowClass(columnCount: number): string {
  const columns = XL_COLUMNS[columnCount];
  return columns === undefined ? KANBAN_ROW_CLASS : `${KANBAN_ROW_CLASS} ${columns}`;
}

/* ------------------------------------------------------------------
   FASE K4 — OPTIMISTIC UPDATE (cache React Query) + ROLLBACK.
   Transisi SUDAH divalidasi di `KanbanBoard` (terhadap `transitions[]` backend),
   jadi perpindahan cache di bawah ini hanya meniru hasil yang PASTI diterima server;
   rollback dipakai kalau server/jaringan gagal (4xx/5xx/offline).
   ------------------------------------------------------------------ */

/** Permintaan pindah kartu (hasil validasi `KanbanBoard`). */
export interface KanbanCardMove {
  cardId: number;
  from: string;
  to: string;
}

/**
 * PURE - pindahkan SATU kartu antar kolom di response kanban (immutable).
 *
 * `count` ikut disesuaikan supaya badge kolom tidak "melompat" saat refetch; kalau
 * kartu/kolom tidak ditemukan, response ASLI dikembalikan (tidak ada perubahan).
 */
export function moveCardInKanban(response: KanbanResponse, move: KanbanCardMove): KanbanResponse {
  const source = response.columns.find((column) => column.state === move.from);
  const target = response.columns.find((column) => column.state === move.to);
  const card = source?.cards.find((item) => item.id === move.cardId);
  if (source === undefined || target === undefined || card === undefined) return response;

  return {
    ...response,
    columns: response.columns.map((column) => {
      if (column.state === move.from) {
        return {
          ...column,
          count: Math.max(0, column.count - 1),
          cards: column.cards.filter((item) => item.id !== move.cardId),
        };
      }
      if (column.state === move.to) {
        return {
          ...column,
          count: column.count + 1,
          cards: [...column.cards, { ...card, state: move.to }],
        };
      }

      return column;
    }),
  };
}

/* ------------------------------------------------------------------
   FASE K4.4 — teks konfirmasi pindah kartu (PURE, dipakai dialog).
   ------------------------------------------------------------------ */

export interface KanbanConfirmTextInput {
  cardCode: string;
  from: string;
  to: string;
  /** Label resource manusiawi (mis. "bundle", "work order"); default "kartu". */
  label?: string;
}

/** PURE - kalimat tanya konfirmasi: `Pindah bundle BND-1 dari DRAFT ke CUTTING?`. */
export function kanbanConfirmText(input: KanbanConfirmTextInput): string {
  return `Pindah ${input.label ?? 'kartu'} ${input.cardCode} dari ${input.from} ke ${input.to}?`;
}
