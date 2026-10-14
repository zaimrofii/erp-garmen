/**
 * qc.ts - kontrak Quality Control (form defect visual + multi-qty per jenis cacat).
 *
 * ATURAN: field `snake_case` dari backend dipakai APA ADANYA - jangan dikonversi
 * ke camelCase. `id` backend = number.
 */

/** Region siluet pakaian (titik klik pada `DefectSilhouette`, Fase 16). */
export type DefectRegion = 'sleeve_left' | 'sleeve_right' | 'body' | 'collar' | 'hem' | 'pocket';

export type DefectType = 'jahitan_loncat' | 'ukuran_tidak_sesuai' | 'kain_rusak' | 'lainnya';

/** Lokasi cacat = region siluet (alias eksplisit supaya makna domain terbaca). */
export type BodyLocation = DefectRegion;

export interface DefectEntry {
  type: DefectType;
  /** Multi-qty: jumlah pcs cacat PER jenis cacat dalam satu bundle. */
  qty: number;
  location: BodyLocation;
  /** Foto bukti (data URL / object URL) - opsional. */
  photo?: string;
}

export interface QCLog {
  id: number;
  bundle_code: string;
  wc_asal: string;
  defect_entries: DefectEntry[];
  action: 'rework' | 'scrap';
  created_at: string;
}

export interface AQLSummary {
  wc: string;
  total_inspected: number;
  total_defect: number;
  aql_percent: number;
}

export interface ReworkRecord {
  id: number;
  bundle_code: string;
  from_wc: string;
  to_wc: string;
  reason: string;
  created_at: string;
}
