/**
 * master-journal.ts — baris master Journal dari `/api/v1/master/journals/` (H3.4).
 *
 * Field = PERSIS `django_app/master/journal_services.py::journal_row`:
 *   * `journal_type` = `account.journal.type` Odoo hasil pull (`general`/`sale`/`purchase`/
 *     `bank`/`cash`); nilai tak dikenal / belum pernah di-pull → `''` (guard MES longgar);
 *   * `is_general` = helper UI untuk filter dropdown Journal Entry (manual entry **hanya**
 *     boleh di journal `general` — keputusan STEP 0 H3.4);
 *   * `active` = nama publik `Journal.is_active` (mirror I1);
 *   * `odoo_id` = kunci push (`null` = belum di-pull; confirm entry ditolak).
 *
 * **Read-only**: journal = konfigurasi akuntansi Odoo ⇒ tidak ada POST/PUT/DELETE di MES.
 */

export interface MasterJournalRow {
  id: number;
  odoo_id: number | null;
  code: string;
  name: string;
  journal_type: string;
  journal_type_label: string;
  is_general: boolean;
  active: boolean;
}
