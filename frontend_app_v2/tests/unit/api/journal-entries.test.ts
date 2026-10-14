import { describe, expect, it } from 'vitest';
import {
  actJournalEntry,
  buildJournalEntriesPath,
  createJournalEntry,
  deleteJournalEntry,
  fetchJournalEntry,
  fetchJournalEntries,
  journalEntryActionPath,
  JOURNAL_ENTRIES_LIMIT_MAX,
  JOURNAL_ENTRIES_PATH,
  JOURNAL_ENTRY_ACTIONS,
  readAllowedActions,
  readJournalEntryDetail,
  readJournalEntryLines,
  readJournalEntryPage,
  readJournalEntryRow,
  readJournalEntrySaved,
  readJournalEntryState,
  toJournalEntryBody,
  updateJournalEntry,
} from '@/api/journalEntries';
import { MODE } from '@/api/_adapter';
import type { ApiClient, ApiResponse } from '@/integrations/api-client';
import type { JournalEntryInput, JournalEntryRow } from '@/types/journal-entry';

/**
 * H3.4 — adapter Journal Entry manual MES (`/api/v1/finance/journal-entries/`).
 *
 * Bentuk = PERSIS `garment/services/journal_entry_services.py`:
 * `{id, code, journal_id, journal_code, journal_name, journal_type, entry_date, ref, memo,
 * total_debit, total_credit, state, odoo_id, …}`; detail menambah `{lines[]: {id,
 * account_id, account_code, account_name, partner_id, partner_name, name, debit, credit},
 * line_count, odoo_sync_status, odoo_sync_error, allowed_actions}`; POST/PUT/aksi menambah
 * `{sync_record_id, task_id, queued}`.
 *
 * Tidak ada field posting/rekonsiliasi (keputusan STEP 0: MES hanya membuat draft).
 */

const ROW: JournalEntryRow = {
  id: 41,
  code: 'JE-2026-0001',
  journal_id: 10,
  journal_code: 'MISC',
  journal_name: 'Operasi Lain-lain',
  journal_type: 'general',
  entry_date: '2026-10-13',
  ref: 'JE-MANUAL-001',
  memo: 'penyesuaian stok opname',
  total_debit: '1500.00',
  total_credit: '1500.00',
  state: 'DRAFT',
  odoo_id: null,
  created_at: '2026-10-13T00:00:00+00:00',
  updated_at: '2026-10-13T00:00:00+00:00',
};

const LINE = {
  id: 91,
  account_id: 181,
  account_code: '51000010',
  account_name: 'Cost of Goods Sold',
  partner_id: null,
  partner_name: null,
  name: 'Beban pokok',
  debit: '1500.00',
  credit: '0.00',
};

const DETAIL = {
  ...ROW,
  lines: [LINE, { ...LINE, id: 92, account_id: 223, account_code: '11120005', debit: '0.00', credit: '1500.00' }],
  line_count: 2,
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

const SAVED = { ...DETAIL, sync_record_id: 77, task_id: 'task-je-1', queued: true };

const INPUT: JournalEntryInput = {
  journal_id: 10,
  entry_date: '2026-10-13',
  ref: ' JE-MANUAL-001 ',
  memo: ' penyesuaian stok opname ',
  lines: [
    { account_id: 181, debit: 1500, credit: 0, name: ' Beban pokok ' },
    { account_id: 223, debit: 0, credit: 1500, partner_id: 10 },
  ],
};

interface RecordedRequest {
  path: string;
  method: string;
  body?: unknown;
}

function stubClient(data: unknown): { client: ApiClient; requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const reply = <T,>(): ApiResponse<T> => ({ ok: true, status: 200, data: data as T });

  const client = {
    get: async <T,>(path: string): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'GET' });

      return reply<T>();
    },
    post: async <T,>(path: string, body: unknown): Promise<ApiResponse<T>> => {
      requests.push({ path, method: 'POST', body });

      return reply<T>();
    },
    request: async <T,>(
      path: string,
      options?: { method?: 'GET' | 'POST' | 'PUT' | 'DELETE'; body?: unknown },
    ): Promise<ApiResponse<T>> => {
      requests.push({ path, method: options?.method ?? 'GET', body: options?.body });

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
    request: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    get: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
    post: async <T,>(): Promise<ApiResponse<T>> => response<T>(),
  } as unknown as ApiClient;
}

describe('H3.4 — MODE & path journal entry', () => {
  it('MODE.journalEntries = real; H3.1–H3.3 & master tetap real', () => {
    expect(MODE['journalEntries']).toBe('real');
    expect(MODE['payments']).toBe('real');
    expect(MODE['vendorBills']).toBe('real');
    expect(MODE['masterAccounts']).toBe('real');
    expect(MODE['masterJournals']).toBe('real');
    expect(JOURNAL_ENTRIES_PATH).toBe('/finance/journal-entries/');
    expect(JOURNAL_ENTRIES_LIMIT_MAX).toBe(200);
    expect(JOURNAL_ENTRY_ACTIONS).toEqual(['confirm', 'done', 'cancel']);
  });

  it('buildJournalEntriesPath: default tanpa query, param terisi saja', () => {
    expect(buildJournalEntriesPath()).toBe('/finance/journal-entries/');
    expect(buildJournalEntriesPath({ search: 'opname', state: 'DRAFT', journal_id: 10 })).toBe(
      '/finance/journal-entries/?search=opname&state=DRAFT&journal_id=10',
    );
    expect(buildJournalEntriesPath({ date_from: '2026-10-01', date_to: '2026-10-31' })).toBe(
      '/finance/journal-entries/?date_from=2026-10-01&date_to=2026-10-31',
    );
    expect(buildJournalEntriesPath({ limit: 50, cursor: 20 })).toBe(
      '/finance/journal-entries/?limit=50&cursor=20',
    );
    expect(buildJournalEntriesPath({ state: null, journal_id: null })).toBe(
      '/finance/journal-entries/',
    );
  });

  it('journalEntryActionPath: confirm/done/cancel', () => {
    expect(journalEntryActionPath(41, 'confirm')).toBe('/finance/journal-entries/41/confirm/');
    expect(journalEntryActionPath(41, 'done')).toBe('/finance/journal-entries/41/done/');
    expect(journalEntryActionPath(41, 'cancel')).toBe('/finance/journal-entries/41/cancel/');
  });
});

describe('H3.4 — parsing baris, detail & payload', () => {
  it('readJournalEntryState: nilai sah saja; lain → DRAFT', () => {
    expect(readJournalEntryState('CONFIRMED')).toBe('CONFIRMED');
    expect(readJournalEntryState('SENT')).toBe('SENT');
    expect(readJournalEntryState('DONE')).toBe('DONE');
    expect(readJournalEntryState('CANCELLED')).toBe('CANCELLED');
    expect(readJournalEntryState('POSTED')).toBe('DRAFT');
    expect(readJournalEntryState(null)).toBe('DRAFT');
  });

  it('readJournalEntryRow: baris sah; tanpa id angka → null', () => {
    const row = readJournalEntryRow(ROW);

    expect(row?.code).toBe('JE-2026-0001');
    expect(row?.journal_type).toBe('general');
    expect(row?.total_debit).toBe('1500.00');
    expect(row?.odoo_id).toBeNull();
    expect(readJournalEntryRow({ code: 'JE-X' })).toBeNull();
    expect(readJournalEntryRow(null)).toBeNull();
  });

  it('readJournalEntryPage: envelope + baris rusak dibuang', () => {
    const page = readJournalEntryPage({
      rows: [ROW, { code: 'tanpa-id' }],
      total_count: 2,
      has_more: true,
      next_cursor: 1,
    });

    expect(page?.rows).toHaveLength(1);
    expect(page?.total_count).toBe(2);
    expect(page?.has_more).toBe(true);
    expect(page?.next_cursor).toBe(1);
    expect(readJournalEntryPage({ rows: 'bukan-array' })).toBeNull();
  });

  it('readJournalEntryLines/readAllowedActions: defensif terhadap bentuk rusak', () => {
    expect(readJournalEntryLines(DETAIL.lines)).toHaveLength(2);
    expect(readJournalEntryLines(DETAIL.lines)[0]?.account_code).toBe('51000010');
    expect(readJournalEntryLines(null)).toEqual([]);

    expect(readAllowedActions(['CONFIRMED', 5, 'CANCELLED'])).toEqual(['CONFIRMED', 'CANCELLED']);
    expect(readAllowedActions(undefined)).toEqual([]);
  });

  it('readJournalEntryDetail/Saved: info sync + jejak tulis', () => {
    const detail = readJournalEntryDetail(DETAIL);

    expect(detail?.line_count).toBe(2);
    expect(detail?.odoo_sync_status).toBe('PENDING');
    expect(detail?.odoo_sync_error).toBeNull();
    expect(detail?.allowed_actions).toEqual(['CONFIRMED', 'CANCELLED']);

    const saved = readJournalEntrySaved(SAVED);
    expect(saved?.sync_record_id).toBe(77);
    expect(saved?.task_id).toBe('task-je-1');
    expect(saved?.queued).toBe(true);
    expect(readJournalEntryDetail({ id: 1 })).toEqual({
      ...readJournalEntryRow({ id: 1 }),
      lines: [],
      line_count: 0,
      odoo_sync_status: null,
      odoo_sync_error: null,
      allowed_actions: [],
    });
  });

  it('toJournalEntryBody: angka apa adanya, teks di-trim, partner opsional', () => {
    const body = toJournalEntryBody(INPUT);

    expect(body['journal_id']).toBe(10);
    expect(body['entry_date']).toBe('2026-10-13');
    expect(body['ref']).toBe('JE-MANUAL-001');
    expect(body['memo']).toBe('penyesuaian stok opname');
    expect(body['lines']).toEqual([
      { account_id: 181, debit: 1500, credit: 0, name: 'Beban pokok' },
      { account_id: 223, debit: 0, credit: 1500, partner_id: 10 },
    ]);
  });
});

describe('H3.4 — daftar, detail, tulis & aksi', () => {
  it('fetchJournalEntries memanggil path + filter, error backend dilempar', async () => {
    const { client, requests } = stubClient({ rows: [ROW], total_count: 1, has_more: false });

    const page = await fetchJournalEntries(client, { state: 'DRAFT', limit: 200 });

    expect(requests).toEqual([
      { path: '/finance/journal-entries/?state=DRAFT&limit=200', method: 'GET' },
    ]);
    expect(page.total_count).toBe(1);

    await expect(fetchJournalEntries(failingClient(400, 'HTTP 400'))).rejects.toThrow(/400/);
  });

  it('fetchJournalEntry: detail + pesan backend saat 404', async () => {
    const { client, requests } = stubClient(DETAIL);

    const detail = await fetchJournalEntry(client, 41);

    expect(requests).toEqual([{ path: '/finance/journal-entries/41/', method: 'GET' }]);
    expect(detail.lines).toHaveLength(2);
    expect(detail.total_credit).toBe('1500.00');

    await expect(
      fetchJournalEntry(failingClient(404, 'Journal Entry tidak ditemukan.'), 41),
    ).rejects.toThrow(/tidak ditemukan/);
  });

  it('createJournalEntry: POST body + tolakan balance 400 dilempar', async () => {
    const { client, requests } = stubClient(SAVED);

    const saved = await createJournalEntry(client, INPUT);

    expect(requests).toEqual([
      { path: '/finance/journal-entries/', method: 'POST', body: toJournalEntryBody(INPUT) },
    ]);
    expect(saved.code).toBe('JE-2026-0001');
    expect(saved.queued).toBe(true);

    await expect(
      createJournalEntry(
        failingClient(400, 'Journal entry tidak seimbang: debit 1500.00 vs kredit 1000.00.'),
        INPUT,
      ),
    ).rejects.toThrow(/tidak seimbang/);
  });

  it('updateJournalEntry (PUT DRAFT-only) & deleteJournalEntry (DELETE)', async () => {
    const { client, requests } = stubClient(SAVED);

    await updateJournalEntry(client, 41, INPUT);
    expect(requests).toEqual([
      { path: '/finance/journal-entries/41/', method: 'PUT', body: toJournalEntryBody(INPUT) },
    ]);

    const deleted = stubClient({ id: 41, deleted: true });
    await deleteJournalEntry(deleted.client, 41);
    expect(deleted.requests).toEqual([
      { path: '/finance/journal-entries/41/', method: 'DELETE', body: undefined },
    ]);

    await expect(
      deleteJournalEntry(failingClient(400, 'hapus hanya boleh saat DRAFT'), 41),
    ).rejects.toThrow(/DRAFT/);
  });

  it('actJournalEntry: POST aksi + parse saved; bentuk rusak → melempar', async () => {
    const { client, requests } = stubClient({ ...SAVED, state: 'CONFIRMED' });

    const saved = await actJournalEntry(client, 41, 'confirm');

    expect(requests).toEqual([
      { path: '/finance/journal-entries/41/confirm/', method: 'POST', body: {} },
    ]);
    expect(saved.state).toBe('CONFIRMED');

    const broken = stubClient({ ok: true });

    await expect(actJournalEntry(broken.client, 41, 'cancel')).rejects.toThrow(/tidak dikenali/);
  });
});
