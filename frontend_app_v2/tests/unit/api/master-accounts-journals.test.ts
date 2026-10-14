import { describe, expect, it } from 'vitest';
import {
  buildMasterAccountsPath,
  fetchAccount,
  fetchAccounts,
  MASTER_ACCOUNTS_PATH,
  readMasterAccountPage,
  readMasterAccountRow,
} from '@/api/masterAccounts';
import {
  buildMasterJournalsPath,
  fetchJournal,
  fetchJournals,
  MASTER_JOURNALS_PATH,
  readMasterJournalPage,
  readMasterJournalRow,
} from '@/api/masterJournals';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { MasterAccountRow } from '@/types/master-account';
import type { MasterJournalRow } from '@/types/master-journal';

/**
 * H3.4 — adapter master Account/Journal **read-only** (`/master/accounts/`,
 * `/master/journals/`) yang dipakai dropdown form Journal Entry.
 *
 * Bentuk = PERSIS `django_app/master/account_services.py::account_row` dan
 * `journal_services.py::journal_row` (pull `erp_sync`; tidak ada POST/PUT/DELETE).
 */

const ACCOUNT: MasterAccountRow = {
  id: 5,
  odoo_id: 181,
  code: '51000010',
  name: 'Cost of Goods Sold',
  account_type: 'expense',
  account_type_label: 'Expenses',
  reconcile: false,
  active: true,
};

const JOURNAL: MasterJournalRow = {
  id: 10,
  odoo_id: 10,
  code: 'MISC',
  name: 'Operasi Lain-lain',
  journal_type: 'general',
  journal_type_label: 'Miscellaneous',
  is_general: true,
  active: true,
};

interface RecordedRequest {
  path: string;
  method: string;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
  } as unknown as ApiClient;

  return { client, requests };
}

function failingClient(status: number, message: string): ApiClient {
  const response = <T,>(): ApiResponse<T> => ({
    ok: false,
    status,
    error: { kind: 'http_error', message },
  });

  return {
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H3.4 — master Account (read-only)', () => {
  it('MODE + path: real, hanya param terisi yang dikirim', () => {
    expect(MODE['masterAccounts']).toBe('real');
    expect(MASTER_ACCOUNTS_PATH).toBe('/master/accounts/');
    expect(buildMasterAccountsPath()).toBe('/master/accounts/');
    expect(buildMasterAccountsPath({ account_type: 'expense', active: false })).toBe(
      '/master/accounts/?account_type=expense&active=false',
    );
    expect(buildMasterAccountsPath({ search: 'kas', limit: 200, cursor: 20 })).toBe(
      '/master/accounts/?search=kas&limit=200&cursor=20',
    );
    expect(buildMasterAccountsPath({ active: null })).toBe('/master/accounts/');
  });

  it('readMasterAccountRow/Page: bentuk backend + baris rusak dibuang', () => {
    const row = readMasterAccountRow(ACCOUNT);

    expect(row?.code).toBe('51000010');
    expect(row?.odoo_id).toBe(181);
    expect(row?.account_type_label).toBe('Expenses');
    expect(row?.active).toBe(true);
    expect(readMasterAccountRow({ code: 'tanpa-id' })).toBeNull();

    const page = readMasterAccountPage({
      rows: [ACCOUNT, { code: 'rusak' }],
      total_count: 2,
      has_more: false,
      next_cursor: null,
    });

    expect(page?.rows).toHaveLength(1);
    expect(page?.total_count).toBe(2);
  });

  it('fetchAccounts/fetchAccount: path + pesan 404 dilempar', async () => {
    const { client, requests } = stubClient({
      rows: [ACCOUNT],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchAccounts(client, { active: true, limit: 200 });
    expect(requests).toEqual([{ path: '/master/accounts/?active=true&limit=200', method: 'GET' }]);
    expect(page.rows[0]?.name).toBe('Cost of Goods Sold');

    const detail = stubClient(ACCOUNT);
    const account = await fetchAccount(detail.client, 5);
    expect(detail.requests).toEqual([{ path: '/master/accounts/5/', method: 'GET' }]);
    expect(account.reconcile).toBe(false);

    await expect(fetchAccount(failingClient(404, 'Account 5 tidak ditemukan.'), 5)).rejects.toThrow(
      /tidak ditemukan/,
    );
  });
});

describe('H3.4 — master Journal (read-only)', () => {
  it('MODE + path: filter `type=general` untuk form Journal Entry', () => {
    expect(MODE['masterJournals']).toBe('real');
    expect(MASTER_JOURNALS_PATH).toBe('/master/journals/');
    expect(buildMasterJournalsPath({ type: 'general', active: true })).toBe(
      '/master/journals/?type=general&active=true',
    );
    expect(buildMasterJournalsPath({ search: 'MISC', limit: 50 })).toBe(
      '/master/journals/?search=MISC&limit=50',
    );
    expect(buildMasterJournalsPath()).toBe('/master/journals/');
  });

  it('readMasterJournalRow/Page: `is_general` + `journal_type` kosong tetap terbaca', () => {
    const row = readMasterJournalRow(JOURNAL);

    expect(row?.journal_type).toBe('general');
    expect(row?.is_general).toBe(true);
    expect(row?.journal_type_label).toBe('Miscellaneous');

    const legacy = readMasterJournalRow({ ...JOURNAL, id: 11, journal_type: '', is_general: false });
    expect(legacy?.journal_type).toBe('');
    expect(legacy?.is_general).toBe(false);
    expect(readMasterJournalRow(null)).toBeNull();

    const page = readMasterJournalPage({
      rows: [JOURNAL],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });
    expect(page?.rows).toHaveLength(1);
  });

  it('fetchJournals/fetchJournal: path + detail journal general + tolakan 400', async () => {
    const { client, requests } = stubClient({
      rows: [JOURNAL],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    const page = await fetchJournals(client, { type: 'general', active: true });
    expect(requests).toEqual([
      { path: '/master/journals/?type=general&active=true', method: 'GET' },
    ]);
    expect(page.rows[0]?.code).toBe('MISC');

    const detail = stubClient(JOURNAL);
    const journal = await fetchJournal(detail.client, 10);
    expect(detail.requests).toEqual([{ path: '/master/journals/10/', method: 'GET' }]);
    expect(journal.odoo_id).toBe(10);

    await expect(
      fetchJournals(failingClient(400, "Parameter 'type' harus salah satu dari general.")),
    ).rejects.toThrow(/general/);
  });
});
