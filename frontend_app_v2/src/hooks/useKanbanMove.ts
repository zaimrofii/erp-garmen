import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query';
import { moveCardInKanban, type KanbanCardMove } from '@/lib/kanban';
import type { KanbanResponse } from '@/types/kanban';

/**
 * useKanbanMove - pindah kartu kanban lewat aksi state machine (FASE K4).
 *
 * Alur (sesuai keputusan K4): transisi SUDAH divalidasi `KanbanBoard` terhadap
 * `transitions[]` backend, jadi hook ini boleh OPTIMISTIC:
 *
 *   * `onMutate`  - snapshot cache kanban, lalu pindahkan kartu di cache
 *                   (`moveCardInKanban`) supaya papan terasa instan;
 *   * `onError`   - **ROLLBACK** ke snapshot + laporkan pesan (halaman menampilkan toast);
 *   * `onSettled` - invalidate query kanban (+ query lain, mis. list lama) agar
 *                   `count`/urutan kembali dari server sebagai sumber kebenaran.
 *
 * Karena tidak ada optimistic update untuk transisi ILEGAL (board sudah menolaknya),
 * rollback di sini hanya untuk kegagalan jaringan/server (4xx/5xx/offline).
 */

export interface KanbanMoveRequest extends KanbanCardMove {
  /** `ACTION_ID` dari `transitions[]` backend (mis. `BUNDLE_START`). */
  actionId: string;
}

export interface UseKanbanMoveOptions {
  /** Query key cache papan (WAJIB sama dengan key yang dipakai hook pembaca papan). */
  queryKey: QueryKey;
  /** Pemanggil aksi nyata: `POST /garmen/<resource>/<id>/<ACTION_ID>/`. */
  runAction: (cardId: number, actionId: string) => Promise<unknown>;
  /** Pesan error siap-tampil (dipakai halaman untuk toast). */
  onErrorMessage?: (message: string) => void;
  /** Query tambahan yang perlu disegarkan setelah settle (mis. daftar mode list). */
  alsoInvalidate?: readonly QueryKey[];
}

export function useKanbanMove({
  queryKey,
  runAction,
  onErrorMessage,
  alsoInvalidate = [],
}: UseKanbanMoveOptions) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (move: KanbanMoveRequest) => runAction(move.cardId, move.actionId),
    onMutate: async (move) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<KanbanResponse>(queryKey);
      if (previous !== undefined) {
        queryClient.setQueryData(queryKey, moveCardInKanban(previous, move));
      }

      return { previous };
    },
    onError: (error, _move, context) => {
      if (context?.previous !== undefined) {
        queryClient.setQueryData(queryKey, context.previous);
      }
      onErrorMessage?.(error.message);
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey });
      for (const key of alsoInvalidate) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
    },
  });
}
