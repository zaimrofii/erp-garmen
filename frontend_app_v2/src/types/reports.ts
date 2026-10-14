/**
 * reports.ts - kontrak KPI & ringkasan pabrik (dashboard, reports, buffer queue).
 *
 * KPI memakai satuan literal (`unit`) supaya halaman tidak perlu menebak format:
 * LineEfficiencyKPI/OnTimeDeliveryKPI = '%', LeadTimeKPI = 'hari', WIPKPI = 'bundle'.
 */

export interface TrendPoint {
  /** 'W1', 'Jan', '2026-09-01', dst. */
  label: string;
  value: number;
}

export interface KPIBase {
  label: string;
  value: number;
  /** '%', 'hari', 'bundle', 'pcs'. */
  unit: string;
  /** Delta dalam persen - boleh negatif. */
  trend: number;
  series?: TrendPoint[];
}

export interface LineEfficiencyKPI extends KPIBase {
  unit: '%';
}

export interface LeadTimeKPI extends KPIBase {
  unit: 'hari';
}

export interface OnTimeDeliveryKPI extends KPIBase {
  unit: '%';
}

export interface WIPKPI extends KPIBase {
  unit: 'bundle';
}

/**
 * Ringkasan dashboard pabrik (GET /dashboard/summary).
 * Field `snake_case` mengikuti Aturan Mutlak #5 - dipakai apa adanya dari backend.
 * (Cleanup Fase 14.1: `total_wip` / `line_efficiency` menggantikan versi camelCase.)
 */
export interface DashboardSummary {
  total_wip: number;
  bottleneck: string;
  line_efficiency: number;
  trend: TrendPoint[];
}

/* ------------------------------------------------------------------
   Buffer queue antar work center (supervisor) - GET /production/buffer-queue
   ------------------------------------------------------------------ */

export type BufferQueueStatus = 'waiting' | 'in_transit' | 'blocked';

export interface BufferQueueRow {
  id: number;
  bundle_code: string;
  from_wc: string;
  to_wc: string;
  qty: number;
  waiting_minutes: number;
  status: BufferQueueStatus;
}

export interface BufferQueueSummary {
  rows: BufferQueueRow[];
  total_bundle: number;
  max_wait_minutes: number;
  generated_at: string;
}

/* ------------------------------------------------------------------
   Detail baris Reports (Fase 21) - ADITIF, tidak mengubah kontrak di atas.
   Endpoint masa depan (belum ada di backend):
     GET /reports/line-efficiency/by-wc
     GET /reports/lead-time/bundles
     GET /reports/on-time-delivery/orders
     GET /reports/wip/by-wc
   ------------------------------------------------------------------ */

/** Satu baris efisiensi per work center per tanggal. */
export interface LineEfficiencyDetailRow {
  id: number;
  wc: string;
  efficiency_pct: number;
  output_pcs: number;
  downtime_min: number;
  /** ISO date, mis. '2026-09-30'. */
  date: string;
}

/** Lead time satu bundle dari WC awal sampai WC akhir. */
export interface LeadTimeDetailRow {
  id: number;
  bundle_code: string;
  from_wc: string;
  to_wc: string;
  lead_time_hours: number;
  /** ISO datetime. */
  started_at: string;
  /** ISO datetime. */
  finished_at: string;
}

export type OnTimeDeliveryStatus = 'on_time' | 'late' | 'pending';

/** Ketepatan kirim per work order. */
export interface OnTimeDeliveryDetailRow {
  id: number;
  work_order_code: string;
  target_date: string;
  /** `null` kalau belum dikirim (status 'pending'). */
  actual_date: string | null;
  status: OnTimeDeliveryStatus;
  /** Negatif = lebih cepat dari target, positif = terlambat (hari). */
  delta_days: number;
}

export type WipStatus = 'on_track' | 'delay' | 'bottleneck';

/** Sebaran WIP per work center (`wip_total` = `waiting` + `in_progress`). */
export interface WIPDetailRow {
  id: number;
  wc: string;
  waiting: number;
  in_progress: number;
  output: number;
  wip_total: number;
  status: WipStatus;
}
