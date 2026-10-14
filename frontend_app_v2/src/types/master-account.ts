/**
 * master-account.ts — baris master Account (chart of accounts) dari
 * `/api/v1/master/accounts/` (H3.4).
 *
 * Field = PERSIS `django_app/master/account_services.py::account_row`:
 *   * `code` = kode akun Odoo natural (mis. `11120005`) atau `ODOO-<id>` bila kosong;
 *   * `account_type`/`account_type_label` = `account.account.account_type` Odoo (18 tipe);
 *   * `reconcile` = akun boleh direkonsiliasi (info saja — MES tidak merekonsiliasi);
 *   * `active` = nama publik `Account.is_active`; Odoo 17 **tidak** punya field `active`
 *     di `account.account` ⇒ hasil pull memakai `not deprecated`;
 *   * `odoo_id` = kunci push (`null` = belum pernah di-pull; entry ditolak saat CONFIRM).
 *
 * **Read-only**: chart of accounts = wewenang akuntan di Odoo (keputusan STEP 0 H3.4) ⇒
 * tidak ada POST/PUT/DELETE di MES (request tulis → **405**).
 */

export interface MasterAccountRow {
  id: number;
  odoo_id: number | null;
  code: string;
  name: string;
  account_type: string;
  account_type_label: string;
  reconcile: boolean;
  active: boolean;
}
