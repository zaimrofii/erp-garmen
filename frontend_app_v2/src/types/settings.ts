import type { RoutingGraph } from './routing';

/**
 * settings.ts - kontrak konfigurasi admin (routing, bundling, alokasi line, user) + HITL.
 *
 * `snake_case` dari backend dipakai apa adanya; `id` backend = number.
 * `RoutingConfig.graph` memakai tipe DAG dari `types/routing.ts` supaya editor DAG
 * dan halaman visualisasi routing berbicara dengan bentuk yang SAMA.
 */

export type Role =
  | 'operator'
  | 'supervisor'
  | 'qc'
  | 'admin'
  | 'inventory'
  | 'purchasing'
  | 'owner';

export interface RoutingConfig {
  id: number;
  name: string;
  graph: RoutingGraph;
  active: boolean;
}

export interface BundlingRule {
  id: number;
  sku_variant: string;
  size: string;
  qty_per_bundle: number;
}

export interface LineAllocation {
  id: number;
  line_code: string;
  work_center_code: string;
  capability: string[];
}

export interface DeviceProfile {
  /** 'OPERATOR_HP' | 'KIOSK_TABLET' | 'SCANNER_USB' | 'DESKTOP'. */
  code: string;
  id: number;
  label: string;
  description: string;
}

export interface User {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  active: boolean;
  /** Aditif backend B26 (`serialize_user`); dipakai form admin. */
  email?: string;
  /**
   * F6.3 — kode operator (4/6 digit untuk role OPERATOR/QC; `null` untuk role lain).
   * Dipakai kolom "Kode Operator" + aksi Regenerate di `/settings/users`.
   */
  operator_code?: string | null;
}

/* ------------------------------------------------------------------
   HITL (Human-in-the-Loop) - approval supervisor sebelum agen AI bertindak.
   Endpoint masa depan: GET /hitl/approvals, POST /hitl/approvals/{id}/decide
   ------------------------------------------------------------------ */

export type HitlStatus = 'pending' | 'approved' | 'rejected' | 'expired';

export type HitlDecision = 'approve' | 'reject';

export interface HitlApproval {
  id: number;
  requester: string;
  /** Aksi yang diajukan agen, mis. 'SCRAP_BUNDLE'. */
  action: string;
  resource: string;
  resource_id: string;
  reason: string;
  status: HitlStatus;
  created_at: string;
  /* Aditif kontrak B29 (dipakai kartu riwayat / audit). */
  priority?: string;
  decided_by?: string | null;
  decision_note?: string | null;
  expires_at?: string | null;
}
