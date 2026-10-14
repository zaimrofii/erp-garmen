import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FeedbackRuntimeContext, type FeedbackRuntime } from '@/app/app-runtime';
import { NAV_APPS } from '@/app/nav-config';
import { SequencesPage } from '@/pages/settings/SequencesPage';
import {
  createSequenceInputFromForm,
  EMPTY_CREATE_SEQUENCE_FORM,
  MAX_SEQUENCE_PADDING,
  MAX_SEQUENCE_PREFIX_LENGTH,
  SEQUENCE_CODE_PATTERN,
  SEQUENCE_PREFIX_PATTERN,
  sequenceInputFromForm,
  sequenceStatusLabel,
  validateCreateSequenceForm,
  validateSequenceForm,
  type CreateSequenceFormValues,
  type SequenceFormValues,
} from '@/lib/master-sequence';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * Sprint C — halaman `/settings/sequences` (Number Sequence).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter` + feedback palsu;
 *   2. SUMBER/pure: route + guard di `App.tsx`, item nav Settings, validasi form edit
 *      (prefix/padding) dan konversi form → payload PUT.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

/** Konteks feedback palsu — `useFeedback()` di halaman butuh provider. */
const FEEDBACK: FeedbackRuntime = {
  flash: null,
  trigger: () => undefined,
  clear: () => undefined,
};

function renderPage(
  element: ReactElement,
  initialPath: string,
  routePath = initialPath,
): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
  const html = htmlOf(tree);

  return { html, text: textOf(html) };
}

describe('Sprint C — route, guard & nav', () => {
  it('App.tsx: /settings/sequences dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/sequences"');
    expect(APP).toContain('<SequencesPage />');
    expect(APP).toContain("import('@/pages/settings/SequencesPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah topbar "Number Sequence" di app Settings', () => {
    expect(NAV).toContain("label: 'Number Sequence', path: '/settings/sequences'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');

    expect(settings?.topbar.some((item) => item.path === '/settings/sequences')).toBe(true);
  });
});

describe('Sprint C — lib form (PURE)', () => {
  const valid: SequenceFormValues = {
    name: 'Sales Order',
    prefix: 'SO',
    padding: '4',
    active: true,
  };

  it('validateSequenceForm: nama & prefix wajib, padding 1..10', () => {
    expect(validateSequenceForm(valid)).toEqual({});
    expect(validateSequenceForm({ ...valid, name: '  ' }).name).toContain('wajib');
    expect(validateSequenceForm({ ...valid, prefix: '' }).prefix).toContain('wajib');
    expect(validateSequenceForm({ ...valid, padding: 'abc' }).padding).toContain('angka bulat');
    expect(validateSequenceForm({ ...valid, padding: '0' }).padding).toContain('antara');
    expect(validateSequenceForm({ ...valid, padding: '99' }).padding).toContain(
      `antara 1 dan ${MAX_SEQUENCE_PADDING}`,
    );
    expect(
      validateSequenceForm({ ...valid, prefix: 'X'.repeat(MAX_SEQUENCE_PREFIX_LENGTH + 1) }).prefix,
    ).toContain('maksimal');
  });

  it('sequenceInputFromForm + sequenceStatusLabel', () => {
    expect(sequenceInputFromForm({ ...valid, name: ' Sales Order ', prefix: ' SO-2 ' })).toEqual({
      name: 'Sales Order',
      prefix: 'SO-2',
      padding: 4,
      active: true,
    });
    expect(sequenceStatusLabel(true)).toBe('Aktif');
    expect(sequenceStatusLabel(false)).toBe('Nonaktif');
  });
});

describe('Sprint C — render halaman (react-dom/server)', () => {
  it('SequencesPage render judul, kolom, dan tanpa tombol Sync', () => {
    const { text } = renderPage(createElement(SequencesPage), '/settings/sequences');

    expect(text).toContain('Number Sequence');
    expect(text).toContain('Penomoran dokumen MES');
    expect(text).toContain('Nomor Berikutnya');
    expect(text).toContain('Padding');
    // H5.3: tombol Buat + filter tahun tersedia di halaman
    expect(text).toContain('Buat Sequence');
    expect(text).toContain('Tahun');
    // MES-only: tidak ada aksi sync ke Odoo
    expect(text).not.toContain('Sync ke Odoo');
  });

  it('SequencesPage sumber: CRUD H5.3 (create + hapus window.confirm)', () => {
    const page = read('src/pages/settings/SequencesPage.tsx');

    expect(page).toContain('createSequence');
    expect(page).toContain('deleteSequence');
    expect(page).toContain('Buat Sequence');
    expect(page).toContain('Hapus');
    expect(page).toContain('window.confirm');
    expect(page).toContain('YEAR_FILTERS');
  });
});

describe('H5.3 — form create (PURE)', () => {
  const valid: CreateSequenceFormValues = {
    code: 'adj',
    name: 'Inventory Adjustment',
    prefix: '',
    padding: '4',
  };

  it('validateCreateSequenceForm: kode A-Z/0-9 2..16, nama wajib, prefix opsional', () => {
    expect(validateCreateSequenceForm(valid)).toEqual({});
    expect(validateCreateSequenceForm({ ...valid, code: '' }).code).toContain('wajib');
    expect(validateCreateSequenceForm({ ...valid, code: 'A' }).code).toContain('Kode');
    expect(validateCreateSequenceForm({ ...valid, code: 'AB CD' }).code).toContain('Kode');
    expect(validateCreateSequenceForm({ ...valid, code: 'AB_CD' }).code).toContain('Kode');
    expect(validateCreateSequenceForm({ ...valid, name: '   ' }).name).toContain('wajib');
    expect(validateCreateSequenceForm({ ...valid, prefix: 'AB CD' }).prefix).toContain('Prefix');
    expect(validateCreateSequenceForm({ ...valid, prefix: 'CST/1' }).prefix).toContain('Prefix');
    expect(validateCreateSequenceForm({ ...valid, padding: '0' }).padding).toContain('antara');
  });

  it('createSequenceInputFromForm: kode auto-upper, prefix kosong dibuang', () => {
    expect(
      createSequenceInputFromForm({
        code: ' adj ',
        name: ' Adjustment ',
        prefix: ' cst-1 ',
        padding: '5',
      }),
    ).toEqual({ code: 'ADJ', name: 'Adjustment', prefix: 'CST-1', padding: 5 });

    expect(createSequenceInputFromForm(EMPTY_CREATE_SEQUENCE_FORM)).toEqual({
      code: '',
      name: '',
      padding: 4,
    });
  });

  it('pola kode/prefix selaras backend', () => {
    expect(SEQUENCE_CODE_PATTERN.test('AB')).toBe(true);
    expect(SEQUENCE_CODE_PATTERN.test('CUSTOM1')).toBe(true);
    expect(SEQUENCE_CODE_PATTERN.test('A')).toBe(false);
    expect(SEQUENCE_CODE_PATTERN.test('AB CD')).toBe(false);
    expect(SEQUENCE_CODE_PATTERN.test('X'.repeat(17))).toBe(false);
    expect(SEQUENCE_PREFIX_PATTERN.test('CST-1')).toBe(true);
    expect(SEQUENCE_PREFIX_PATTERN.test('')).toBe(false);
  });
});
