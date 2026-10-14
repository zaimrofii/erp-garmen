// REAL - Company Profile (H5.1). Endpoint: `/api/v1/settings/company/` (SINGLETON)
//   GET  `/settings/company/` → `{company: {…}|null}` (null = belum diisi, tanpa seed)
//   PUT  `/settings/company/` → `{company: {…}}` (create-on-first-PUT; ADMIN/OWNER)
//
// Pemetaan UI ↔ backend (tidak ada shape yang dikarang):
//   * baris `{id, name, legal_name, address, city, country, phone, email, npwp,
//     website, logo_url, currency_id, currency, timezone, is_active, created_at,
//     updated_at}` — `currency` = baris mata uang H5.2 yang di-embed backend;
//   * field yang TIDAK dikirim tidak diubah; `name` wajib saat baris belum ada;
//   * **MES-only**: tanpa `task_id`/`queued` (ledger `SKIPPED`, tidak ada push Odoo).
//
// Catatan: `ApiClient` hanya punya `get`/`post` — PUT lewat `client.request()`.
import type { ApiClient } from '@/integrations/api-client';
import type { CompanyCurrency, CompanyInput, CompanyRow } from '@/types/company';
import { unwrap } from '../client';
import { isRecord, readBool, readNullableNum, readStr } from './_shape';

/** Path relatif terhadap `VITE_API_BASE_URL` (`…/api/v1`). */
export const SETTINGS_COMPANY_PATH = '/settings/company/';

/** PURE — baris mata uang yang di-embed (`null` kalau bukan objek tanpa id angka). */
export function readCompanyCurrency(raw: unknown): CompanyCurrency | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    code: readStr(raw['code']),
    name: readStr(raw['name']),
    symbol: readStr(raw['symbol']),
  };
}

/** PURE — satu baris mentah → `CompanyRow`; `null` kalau tanpa `id` angka. */
export function readCompanyRow(raw: unknown): CompanyRow | null {
  if (!isRecord(raw)) return null;

  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isFinite(id)) return null;

  return {
    id,
    name: readStr(raw['name']),
    legal_name: readStr(raw['legal_name']),
    address: readStr(raw['address']),
    city: readStr(raw['city']),
    country: readStr(raw['country']),
    phone: readStr(raw['phone']),
    email: readStr(raw['email']),
    npwp: readStr(raw['npwp']),
    website: readStr(raw['website']),
    logo_url: readStr(raw['logo_url']),
    currency_id: readNullableNum(raw['currency_id']),
    currency: readCompanyCurrency(raw['currency']),
    timezone: readStr(raw['timezone']),
    is_active: readBool(raw['is_active']),
    created_at: readStr(raw['created_at']),
    updated_at: readStr(raw['updated_at']),
  };
}

/** PURE — amplop `{company: …|null}` → baris atau `null` (belum diisi/rusak). */
export function readCompanyEnvelope(raw: unknown): CompanyRow | null {
  if (!isRecord(raw)) return null;

  return readCompanyRow(raw['company']);
}

/** PURE — body `PUT` (hanya field yang ada di input yang dikirim). */
export function toCompanyBody(input: CompanyInput): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body['name'] = input.name.trim();
  if (input.legal_name !== undefined) body['legal_name'] = input.legal_name.trim();
  if (input.address !== undefined) body['address'] = input.address.trim();
  if (input.city !== undefined) body['city'] = input.city.trim();
  if (input.country !== undefined) body['country'] = input.country.trim().toUpperCase();
  if (input.phone !== undefined) body['phone'] = input.phone.trim();
  if (input.email !== undefined) body['email'] = input.email.trim();
  if (input.npwp !== undefined) body['npwp'] = input.npwp.trim();
  if (input.website !== undefined) body['website'] = input.website.trim();
  if (input.logo_url !== undefined) body['logo_url'] = input.logo_url.trim();
  if (input.currency_id !== undefined) body['currency_id'] = input.currency_id;
  if (input.timezone !== undefined) body['timezone'] = input.timezone.trim();
  if (input.active !== undefined) body['active'] = input.active;

  return body;
}

/**
 * Profil perusahaan — `null` = belum diisi (200, **bukan** error).
 *
 * `getParsed` TIDAK dipakai (helper itu melempar untuk hasil `null`) — pola
 * `fetchDefaultTax`/`fetchDefaultCurrency`.
 */
export async function fetchCompany(client: ApiClient): Promise<CompanyRow | null> {
  return readCompanyEnvelope(unwrap(await client.get<unknown>(SETTINGS_COMPANY_PATH)));
}

/** Simpan profil (PUT, ADMIN/OWNER; create-on-first-PUT) → baris terbaru. */
export async function updateCompany(
  client: ApiClient,
  input: CompanyInput,
): Promise<CompanyRow> {
  const row = readCompanyEnvelope(
    unwrap(
      await client.request<unknown>(SETTINGS_COMPANY_PATH, {
        method: 'PUT',
        body: toCompanyBody(input),
      }),
    ),
  );
  if (row === null) {
    throw new Error('Bentuk respons simpan profil perusahaan tidak dikenali.');
  }

  return row;
}
