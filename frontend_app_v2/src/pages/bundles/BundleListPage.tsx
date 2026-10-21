import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useBundles } from "@/hooks/useBundles";
import {
  bundlesKanbanQueryKey,
  useBundlesKanban,
} from "@/hooks/useBundlesKanban";
import { useKanbanMove } from "@/hooks/useKanbanMove";
import { useApiClient } from "@/hooks/useApiClient";
import { submitBundleAction } from "@/api/bundles";
import { StatusChip } from "@/components/molecules/StatusChip";
import { KanbanBoardWithConfirm } from "@/components/molecules/KanbanBoard";
import { ViewToggle } from "@/components/molecules/ViewToggle";
import { Spinner } from "@/components/atoms/Spinner";
import { Button } from "@/components/atoms/Button";
import { Toast } from "@/components/atoms/Toast";
import { chipStatusFromState } from "@/lib/state-display";
import {
  readViewMode,
  VIEW_STORAGE_KEYS,
  type ViewMode,
} from "@/lib/view-mode";
import type { KanbanQuery } from "@/types/kanban";

/**
 * BundleListPage - route `/bundles` (F13) + mode KANBAN (FASE K3).
 *
 * Mode toggle (bukan route baru): `list` = daftar lama (kontrak F13 tidak diubah),
 * `kanban` = papan dari `GET /garmen/bundles/kanban/` (K2) - SATU request untuk semua
 * kolom, bukan N request `?state=`. Pilihan disimpan di `localStorage['mes-view-bundles']`.
 *
 * Pindah kartu antar kolom = aksi state machine NYATA (`POST /garmen/bundles/<id>/<ACTION>/`
 * lewat `submitBundleAction`): `KanbanBoard` memvalidasi dulu terhadap `transitions[]`
 * backend - kalau tidak valid, TIDAK ada request dan muncul toast error.
 */

const PAGE_SIZE = 20;

/** Mode yang ditawarkan halaman ini (grid hanya untuk halaman master). */
const MODES: readonly ViewMode[] = ["kanban", "list"];

/** Param papan; dipakai juga sebagai query key mutation optimistic (K4). */
const KANBAN_PARAMS: KanbanQuery = { limit: 50 };

export function BundleListPage() {
  const client = useApiClient();
  const navigate = useNavigate();

  const [view, setView] = useState<ViewMode>(() =>
    readViewMode(VIEW_STORAGE_KEYS.bundles, MODES),
  );
  const [offset, setOffset] = useState(0);
  const [moveError, setMoveError] = useState<string | null>(null);

  const isKanban = view === "kanban";
  const { data, isLoading, error } = useBundles({ limit: PAGE_SIZE, offset });
  // Papan hanya ditarik saat mode kanban aktif (`enabled`) - mode list tetap 1 request.
  const board = useBundlesKanban(KANBAN_PARAMS, isKanban);
  const listLoading = isLoading && data === undefined;
  const listUnavailable = error != null || data === undefined;

  // K4 - optimistic + rollback cache (detail di `useKanbanMove`).
  const move = useKanbanMove({
    queryKey: bundlesKanbanQueryKey(KANBAN_PARAMS),
    runAction: (cardId, actionId) =>
      submitBundleAction(client, cardId, actionId),
    onErrorMessage: (message) => setMoveError(message),
    alsoInvalidate: [["bundles"]],
  });

  return (
    <div
      className={
        isKanban ? "flex flex-col gap-3 p-4" : "mx-auto max-w-3xl space-y-3 p-4"
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-foreground">Daftar Bundle</h1>
        <ViewToggle
          modes={MODES}
          value={view}
          onChange={setView}
          storageKey={VIEW_STORAGE_KEYS.bundles}
          label="Mode tampilan bundle"
        />
      </div>

      {/* H2.4 — pintu masuk form bundle (matriks ukuran; MES-only). ADITIF. */}
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/production/bundles/new">
          <Button size="sm">Buat Bundle</Button>
        </Link>
        <span className="text-xs text-muted-foreground">
          Kelola (ubah/split/merge/hapus) lewat halaman bundle.
        </span>
      </div>

      {isKanban ? (
        board.isLoading && board.data === undefined ? (
          <Spinner />
        ) : board.error != null || board.data === undefined ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-danger">Gagal memuat papan kanban bundle.</p>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => {
                void board.refetch();
              }}
            >
              Coba Lagi
            </Button>
          </div>
        ) : (
          <KanbanBoardWithConfirm
            resourceLabel="bundle"
            columns={board.data.columns}
            transitions={board.data.transitions}
            loading={board.isFetching || move.isPending}
            emptyMessage="Belum ada bundle"
            onCardMove={(payload) => {
              move.mutate(payload);
            }}
            onInvalidMove={(invalid) => {
              setMoveError(invalid.reason);
            }}
            onCardClick={(card) => navigate(`/bundles/${String(card.id)}`)}
          />
        )
      ) : listLoading ? (
        <Spinner />
      ) : listUnavailable ? (
        <p className="text-danger">Gagal memuat daftar bundle.</p>
      ) : (
        <>
          <ul className="divide-y divide-border rounded-card border border-border bg-card shadow-soft-card">
            {(data?.rows ?? []).map((row) => (
              <li key={row.id} className="p-3">
                <Link
                  to={`/bundles/${row.id}`}
                  className="flex items-center justify-between gap-2"
                >
                  <span className="font-medium text-foreground">
                    {String(row.code ?? row.id)}
                  </span>
                  <StatusChip
                    status={chipStatusFromState(String(row.state ?? ""))}
                    label={String(row.state ?? "-")}
                  />
                </Link>
                <div className="mt-1 text-xs text-muted-foreground">
                  {String(row.size ?? "—")} · {String(row.qty_done ?? 0)} /{" "}
                  {String(row.qty ?? 0)} ·{" "}
                  {String(row.current_work_center_code ?? "—")}
                </div>
              </li>
            ))}
          </ul>

          {(data?.rows ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">Belum ada bundle.</p>
          ) : null}

          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {(data?.rows ?? []).length} dari {data?.total_count ?? 0}
            </span>
            {data?.has_more ? (
              <Button
                variant="secondary"
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
              >
                Muat lebih banyak
              </Button>
            ) : null}
          </div>
        </>
      )}

      <Toast
        open={moveError !== null}
        onOpenChange={() => setMoveError(null)}
        tone="error"
        title="Perpindahan tidak valid"
        description={moveError ?? undefined}
      />
    </div>
  );
}
