import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { MENU_APPS } from '@/app/menu-config';
import { JournalEntriesPage } from '@/pages/finance/JournalEntriesPage';
import { JournalEntryDetailPage } from '@/pages/finance/JournalEntryDetailPage';
import { JournalEntryFormPage } from '@/pages/finance/JournalEntryFormPage';
import { JOURNAL_ENTRY_STATE_FILTERS } from '@/lib/journal-entry';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H3.4 — halaman Journal Entry (`/finance/journal-entries*`).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata lewat `react-dom/server` (pohon dibangun `createElement`), dibungkus
 *      `QueryClientProvider` + `MemoryRouter` + konteks feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav, dan wiring API
 *      (`fetchJournals({type:'general'})`, `fetchAccounts`, `fetchPartners`) plus
 *      keputusan STEP 0 (hanya journal general, posting di Odoo).
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const LIST_PAGE = 'src/pages/finance/JournalEntriesPage.tsx';
const FORM_PAGE = 'src/pages/finance/JournalEntryFormPage.tsx';
const DETAIL_PAGE = 'src/pages/finance/JournalEntryDetailPage.tsx';
const NAV = read('src/app/nav-config.ts');
const API_ADAPTER = read('src/api/journalEntries.ts');

/** Konteks feedback palsu — `useFeedback()` di halaman form/detail butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(element: ReactElement, initialPath: string): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const routePath = initialPath.split('?')[0] ?? initialPath;
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: [initialPath] },
      createElement(
        FeedbackRuntimeContext.Provider,
        { value: FEEDBACK },
        createElement(Routes, null, createElement(Route, { path: routePath, element })),
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('H3.4 — route, guard & nav', () => {
  it('App.tsx mendaftarkan 4 route `/finance/journal-entries*` dengan guard FINANCE_ROLES', () => {
    for (const route of [
      'path="/finance/journal-entries"',
      'path="/finance/journal-entries/new"',
      'path="/finance/journal-entries/:id"',
      'path="/finance/journal-entries/:id/edit"',
    ]) {
      expect(APP).toContain(route);
    }

    expect(APP).toContain('<JournalEntriesPage />');
    expect(APP).toContain('<JournalEntryFormPage />');
    expect(APP).toContain('<JournalEntryDetailPage />');
    expect(APP).toContain("import('@/pages/finance/JournalEntriesPage')");
    expect(APP).toContain('const FINANCE_ROLES: Role[] = ');

    // Non-breaking: jalur H3.1–H3.3 & F15 tetap terdaftar.
    for (const keep of [
      'path="/finance/invoices"',
      'path="/finance/customer-invoices"',
      'path="/finance/vendor-bills"',
      'path="/finance/payments"',
    ]) {
      expect(APP).toContain(keep);
    }
  });

  it('nav Finance punya item Journal Entries & menu-config menurunkannya', () => {
    expect(NAV).toContain("{ label: 'Journal Entries', path: '/finance/journal-entries' }");

    const finance = NAV_APPS.find((app) => app.id === 'finance');
    const paths = (finance?.topbar ?? []).map((item) => item.path);

    expect(paths).toContain('/finance/journal-entries');
    expect(paths).toContain('/finance/payments');

    const menuFinance = MENU_APPS.find((app) => app.id === 'finance');
    const menuPaths = (menuFinance?.items ?? []).map((item) => item.path);

    expect(menuPaths).toContain('/finance/journal-entries');
  });

  it('adapter journalEntries = pintu tunggal (pickAdapter + re-export tipe/label)', () => {
    expect(API_ADAPTER).toContain("pickAdapter(");
    expect(API_ADAPTER).toContain("'journalEntries',");
    expect(API_ADAPTER).toContain('JOURNAL_ENTRY_STATE_LABELS');
    expect(API_ADAPTER).toContain('JOURNAL_ENTRY_ACTIONS');
  });
});

describe('H3.4 — render halaman (react-dom/server)', () => {
  it('list: judul, tombol "Journal Entry Baru", filter state & CSV', () => {
    const { text } = renderPage(createElement(JournalEntriesPage), '/finance/journal-entries');

    expect(text).toContain('Journal Entry');
    expect(text).toContain('Journal Entry Baru');
    expect(text).toContain('Reset Filter');
    expect(read(LIST_PAGE)).toContain('journal-entries.csv');

    for (const filter of JOURNAL_ENTRY_STATE_FILTERS) {
      expect(text).toContain(filter.label);
    }
  });

  it('form: judul "Journal Entry Baru" + 2 baris jurnal + catatan balance/keputusan STEP 0', () => {
    const { text } = renderPage(
      createElement(JournalEntryFormPage),
      '/finance/journal-entries/new',
    );

    expect(text).toContain('Journal Entry Baru');
    expect(text).toContain('Journal (general) *');
    expect(text).toContain('Akun 1');
    expect(text).toContain('Akun 2');
    expect(text).toContain('Tambah Baris');
    expect(text).toContain('Simpan Journal Entry');
    expect(text).toContain('Baris Jurnal');
    expect(text).toContain('posting & rekonsiliasi dilakukan akuntan di Odoo');
  });

  it('form: dropdown journal/akun/partner memakai data real (general + active)', () => {
    const form = read(FORM_PAGE);

    expect(form).toContain("type: 'general'");
    expect(form).toContain('active: true');
    expect(form).toContain('fetchJournals');
    expect(form).toContain('fetchAccounts');
    expect(form).toContain('fetchPartners');
    expect(form).toContain('ACCOUNTS_LIMIT_MAX');
    expect(form).toContain('JOURNALS_LIMIT_MAX');
  });

  it('detail: state awal tanpa entry → judul detail + tombol kembali', () => {
    const { text } = renderPage(
      createElement(JournalEntryDetailPage),
      '/finance/journal-entries/41',
    );

    expect(text).toContain('Detail Journal Entry');
    expect(text).toContain('Kembali');
    expect(text).toContain('Edit');
    expect(text).toContain('Hapus');
  });

  it('detail & list: aksi state hanya dari `allowed_actions`, edit/hapus DRAFT-only', () => {
    const detail = read(DETAIL_PAGE);

    expect(detail).toContain('entry?.allowed_actions ?? []');
    expect(detail).toContain('JOURNAL_ENTRY_STATE_TO_ACTION[target]');
    expect(detail).toContain('JOURNAL_ENTRY_ACTION_LABELS[target]');
    expect(detail).toContain('const isDraft = entry?.state ===');
    expect(detail).toContain('journalEntryLineItems(entry.lines)');
    expect(detail).toContain('Posting bukan di MES');

    const list = read(LIST_PAGE);
    expect(list).toContain("navigate(`/finance/journal-entries/${String(row.id)}`)");
    expect(list).toContain('journalEntryStateTone(row.state)');
    expect(list).toContain('date_from');
    expect(list).toContain('date_to');
  });
});
