// ADAPTER - satu-satunya pintu data master Routing DAG (H1.9, TANPA logic domain).
//
// H1.9 memakai **B22 yang di-extend di tempat** (`/api/v1/settings/routing/…`), jadi
// tidak ada endpoint paralel `/master/routings/` — dua halaman memakai jalur yang sama:
//   * `/settings/routing` (F3A, editor DAG ringkas) → `api/settings.ts` / `settingsRouting`;
//   * `/master/routings…` (H1.9, CRUD lengkap) → berkas ini.
// MODE.masterRoutings = 'real' (`_adapter.ts`) — tanpa dummy. **MES-only** (Odoo 17
// tidak punya DAG routing), jadi tanpa `odoo_id`.
import { pickAdapter } from './_adapter';
import * as real from './real/masterRoutings';

/** Daftar routing (`GET /settings/routing/`, shape B22) — REAL (H1.9). */
export const fetchRoutings = pickAdapter(
  'masterRoutings',
  real.fetchMasterRoutings,
  real.fetchMasterRoutings,
);

/** Detail routing (`GET /settings/routing/<id>/` + `nodes[]`/`edges[]`) — REAL. */
export const fetchRouting = pickAdapter(
  'masterRoutings',
  real.fetchMasterRouting,
  real.fetchMasterRouting,
);

/** Buat routing (`POST /settings/routing/`, body B22 `steps[]`) — REAL. */
export const createRouting = pickAdapter(
  'masterRoutings',
  real.createMasterRouting,
  real.createMasterRouting,
);

/** Ubah header routing (`PUT /settings/routing/<id>/`, ADMIN/OWNER) — REAL. */
export const updateRouting = pickAdapter(
  'masterRoutings',
  real.updateMasterRouting,
  real.updateMasterRouting,
);

/** Nonaktifkan routing (`DELETE` = soft delete; 400 bila dipakai rule aktif) — REAL. */
export const deleteRouting = pickAdapter(
  'masterRoutings',
  real.deleteMasterRouting,
  real.deleteMasterRouting,
);

/** Tambah step/node DAG (`POST /settings/routing/<id>/steps/`) — REAL. */
export const addRoutingStep = pickAdapter(
  'masterRoutings',
  real.createRoutingStep,
  real.createRoutingStep,
);

/** Ubah step + edge (`PUT /settings/routing/<id>/steps/<step_id>/`) — REAL. */
export const updateRoutingStep = pickAdapter(
  'masterRoutings',
  real.updateRoutingStep,
  real.updateRoutingStep,
);

/** Hapus step (`DELETE /settings/routing/<id>/steps/<step_id>/`) — REAL. */
export const removeRoutingStep = pickAdapter(
  'masterRoutings',
  real.deleteRoutingStep,
  real.deleteRoutingStep,
);

export {
  buildMasterRoutingsPath,
  MASTER_ROUTINGS_PATH,
  readMasterRoutingDetail,
  readMasterRoutingPage,
  readMasterRoutingRow,
  readMasterRoutingSaved,
  readMasterRoutingStepRow,
  ROUTINGS_LIMIT_DEFAULT,
  ROUTINGS_LIMIT_MAX,
  routingDetailPath,
  routingStepPath,
  routingStepsPath,
  stripUndefined,
  toMasterRoutingBody,
  toMasterRoutingCreateBody,
  toMasterRoutingStepBody,
} from './real/masterRoutings';
export type { MasterRoutingPage, MasterRoutingsParams } from './real/masterRoutings';
export type {
  MasterRoutingCreateInput,
  MasterRoutingDetail,
  MasterRoutingEdge,
  MasterRoutingInput,
  MasterRoutingNode,
  MasterRoutingRow,
  MasterRoutingSaved,
  MasterRoutingStepB22Input,
  MasterRoutingStepInput,
  MasterRoutingStepRow,
} from '@/types/master-routing';
