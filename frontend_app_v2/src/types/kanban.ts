/**
 * types/kanban.ts - kontrak endpoint kanban backend (FASE K2) yang dipakai FASE K3.
 *
 * Bentuk = PERSIS `django_app/apps_industry/garment/services/kanban_services.py`
 * (`build_kanban_response`): kolom + kartu + transisi dibaca dari DATABASE
 * (`core.state_machine`), jadi frontend tidak boleh menyimpan daftar state/transisi.
 *
 * Kartu WORK ORDER memakai kunci yang sama dengan BUNDLE (kontrak K2): `work_order_code`
 * = kode WO itu sendiri, `size` = `null`, `qty` = `qty_planned`.
 */

/** Satu aksi yang boleh dijalankan dari state kartu (bentuk sama dgn list/metadata). */
export interface KanbanAction {
  id: string;
  label: string;
  /** `optimistic` | `pessimistic` (huruf kecil dari backend). */
  mode?: string;
  /** Path aksi relatif `VITE_API_BASE_URL`, mis. `/garmen/bundles/42/BUNDLE_START/`. */
  endpoint?: string;
}

/** Kartu kanban (bundle atau work order). */
export interface KanbanCardData {
  id: number;
  code: string;
  work_order_code: string | null;
  size: string | null;
  qty: number;
  state: string;
  allowed_actions: KanbanAction[];
}

/** Satu kolom kanban = satu `State` mesin (+ kartunya). */
export interface KanbanColumn {
  state: string;
  label: string;
  order: number;
  /** Jumlah SELURUH baris state ini (bisa > `cards.length` kalau `truncated`). */
  count: number;
  cards: KanbanCardData[];
  truncated: boolean;
}

/** Transisi aktif mesin (`Transition` di DB) - sumber validasi drag & drop. */
export interface KanbanTransition {
  from: string;
  to: string;
  action_id: string;
  label: string;
}

/** Laporan filter yang dipakai/diabaikan backend (mis. `work_center_id` pada WO). */
export interface KanbanFilters {
  applied: Record<string, string | number>;
  ignored: string[];
}

/** Query param endpoint kanban (semua opsional). */
export interface KanbanQuery {
  search?: string;
  state?: string;
  work_center_id?: number;
  line_id?: number;
  work_order_id?: number;
  /** Batas kartu PER KOLOM (default 50, maks 200). */
  limit?: number;
}

/** Bentuk response `GET /api/v1/garmen/<resource>/kanban/`. */
export interface KanbanResponse {
  resource: string;
  industry: string;
  machine: string;
  columns: KanbanColumn[];
  transitions: KanbanTransition[];
  total_count: number;
  limit: number;
  truncated: boolean;
  /** State di luar definisi mesin; tidak dibuatkan kolom tapi tetap dilaporkan. */
  unknown_states: Record<string, number>;
  filters: KanbanFilters;
}
