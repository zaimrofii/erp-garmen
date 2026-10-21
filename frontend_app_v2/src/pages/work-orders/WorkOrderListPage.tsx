import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useWorkOrders } from "@/hooks/useWorkOrders";
import { useKanbanMove } from "@/hooks/useKanbanMove";
import {
  useWorkOrdersKanban,
  workOrdersKanbanQueryKey,
} from "@/hooks/useWorkOrdersKanban";
import { useApiClient } from "@/hooks/useApiClient";
import {
  runWorkOrderCrudAction,
  WORK_ORDER_ACTIONS,
  type WorkOrderAction,
} from "@/api/workOrdersCrud";
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
 * WorkOrderListPage - route `/work-orders` (F13) + mode KANBAN (FASE K3).
 *
 * Sama seperti BundleListPage: mode toggle (bukan route baru), papan dari
 * `GET /garmen/work-orders/kanban/` (K2), preferensi di
 * `localStorage['mes-view-work-orders']`. Pindah kartu = aksi state machine
 * (`POST /garmen/work-orders/<id>/<ACTION>/` lewat `runWorkOrderCrudAction`) setelah
 * transisi divalidasi terhadap `transitions[]` backend.
 *
 * Kartu WO memakai bentuk yang SAMA dengan kartu bundle (kontrak K2): `work_order_code`
 * = kode WO itu sendiri, `size` = null, `qty` = qty_planned.
 */

const PAGE_SIZE = 20;

/** Mode yang ditawarkan halaman ini. */
const MODES: readonly ViewMode[] = ["kanban", "list"];

/** Param papan; dipakai juga sebagai query key mutation optimistic (K4). */
const KANBAN_PARAMS: KanbanQuery = { limit: 50 };

/**
 * PURE - `action_id` dari backend (DB state machine) → union `WorkOrderAction`.
 *
 * `transitions[]` datang dari DATABASE, jadi aksi baru bisa muncul sebelum union
 * frontend diperbarui: aksi di luar `WORK_ORDER_ACTIONS` DITOLAK di sini (kartu tidak
 * pernah dikirim ke server dengan aksi yang tidak dikenal).
 */
function toWorkOrderAction(actionId: string): WorkOrderAction {
  const known = WORK_ORDER_ACTIONS.find((action) => action === actionId);
  if (known === undefined) {
    throw new Error(`Aksi '${actionId}' tidak dikenal untuk Work Order.`);
  }

  return known;
}

export function WorkOrderListPage() {
  const client = useApiClient();
  const navigate = useNavigate();

  const [view, setView] = useState<ViewMode>(() =>
    readViewMode(VIEW_STORAGE_KEYS.workOrders, MODES),
  );
  const [offset, setOffset] = useState(0);
  const [moveError, setMoveError] = useState<string | null>(null);

  const isKanban = view === "kanban";
  const { data, isLoading, error } = useWorkOrders({
    limit: PAGE_SIZE,
    offset,
  });
  const board = useWorkOrdersKanban(KANBAN_PARAMS, isKanban);
  const listLoading = isLoading && data === undefined;
  const listUnavailable = error != null || data === undefined;

  // K4 - optimistic + rollback cache (detail di `useKanbanMove`).
  const move = useKanbanMove({
    queryKey: workOrdersKanbanQueryKey(KANBAN_PARAMS),
    runAction: (cardId, actionId) =>
      runWorkOrderCrudAction(client, cardId, toWorkOrderAction(actionId)),
    onErrorMessage: (message) => setMoveError(message),
    alsoInvalidate: [["work-orders"]],
  });

  // Guard full-page DIHAPUS: header + `ViewToggle` tetap tampil, status memuat/gagal
  // ditampilkan di dalam konten mode `list` (lihat rantai ternary di JSX).

  return (
    <div
      className={
        isKanban ? "flex flex-col gap-3 p-4" : "mx-auto max-w-3xl space-y-3 p-4"
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold text-foreground">Work Order</h1>
        <ViewToggle
          modes={MODES}
          value={view}
          onChange={setView}
          storageKey={VIEW_STORAGE_KEYS.workOrders}
          label="Mode tampilan work order"
        />
      </div>

      {/* H2.3 — pintu masuk form WO (nomor otomatis Sprint C; MES-only). */}
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/production/work-orders/new">
          <Button size="sm">Buat WO Baru</Button>
        </Link>
        <span className="text-xs text-muted-foreground">
          Satu WO = satu baris order; pecahan lebih lanjut lewat tombol Split di
          detail.
        </span>
      </div>

      {isKanban ? (
        board.isLoading && board.data === undefined ? (
          <Spinner />
        ) : board.error != null || board.data === undefined ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-danger">Gagal memuat papan kanban work order.</p>
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
            resourceLabel="work order"
            columns={board.data.columns}
            transitions={board.data.transitions}
            loading={board.isFetching || move.isPending}
            emptyMessage="Belum ada work order"
            onCardMove={(payload) => {
              move.mutate(payload);
            }}
            onInvalidMove={(invalid) => {
              setMoveError(invalid.reason);
            }}
            onCardClick={(card) =>
              navigate(`/production/work-orders/${String(card.id)}`)
            }
          />
        )
      ) : listLoading ? (
        <Spinner />
      ) : listUnavailable ? (
        <p className="text-danger">Gagal memuat work order.</p>
      ) : (
        <>
          <ul className="divide-y divide-border rounded-card border border-border bg-card shadow-soft-card">
            {(data?.rows ?? []).map((row) => (
              <li
                key={row.id}
                className="flex items-center justify-between gap-2 p-3"
              >
                <div>
                  <span className="font-medium text-foreground">
                    {String(row.code ?? row.id)}
                  </span>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {String(row.qty_done ?? 0)} / {String(row.qty_planned ?? 0)}
                  </div>
                </div>
                <StatusChip
                  status={chipStatusFromState(String(row.state ?? ""))}
                  label={String(row.state ?? "-")}
                />
              </li>
            ))}
          </ul>

          {(data?.rows ?? []).length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Belum ada work order.
            </p>
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
