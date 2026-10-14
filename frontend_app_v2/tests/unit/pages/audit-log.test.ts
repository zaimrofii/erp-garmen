import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement, type ReactElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { NAV_APPS } from '@/app/nav-config';
import { EMPTY_AUDIT_FILTERS } from '@/api/auditLogs';
import { AuditLogPage } from '@/pages/settings/AuditLogPage';
import type { AuditLogDetail, AuditLogFilters, AuditLogRow } from '@/types/audit-log';
import {
  actorLabel,
  auditDetailEntries,
  auditResultTone,
  dash,
  formatAuditTimestamp,
  formatJsonBlock,
  hasActiveFilters,
  isAuditFiltersValid,
  isIsoDate,
  metadataSummary,
  validateAuditFilters,
} from '@/lib/audit-log';
import { htmlOf, textOf } from '../../helpers/react-tree';

/**
 * H5.5 — halaman `/settings/audit-log` (Audit Log Viewer, READ-ONLY).
 *
 * Dua lapis pengujian (tanpa jsdom — `.clinerules` §ENVIRONMENT):
 *   1. RENDER nyata via `react-dom/server` (`createElement` agar file tetap `.ts`),
 *      dibungkus `QueryClientProvider` + `MemoryRouter`;
 *   2. SUMBER/pure: route + guard di `App.tsx`, nav Settings (landing tetap
 *      `/settings/routing`, `/settings/audit` milik F9 TIDAK diubah), validasi filter,
 *      helper tampilan, dan entries modal detail.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');

function read(relative: string): string {
  return readFileSync(path.join(ROOT, relative), 'utf8');
}

const APP = read('src/App.tsx');
const NAV = read('src/app/nav-config.ts');

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
      createElement(Routes, null, createElement(Route, { path: routePath, element })),
    ),
  );
  const html = htmlOf(tree);

  return { html, text: textOf(html) };
}

const ROW: AuditLogRow = {
  id: 12,
  timestamp: '2026-10-14T03:05:00+00:00',
  user_id: 4,
  username: 'admin-audit',
  full_name: 'Sari Admin',
  action: 'master.create',
  resource: 'master.product',
  resource_id: '7',
  result: 'OK',
  request_id: 'req-1',
  ip_address: '10.0.0.1',
  metadata_preview: '{"fields": ["code"]}',
};

const DETAIL: AuditLogDetail = {
  ...ROW,
  payload: { code: 'PRD-1', api_key: '***' },
  metadata: { fields: ['code'] },
  user_agent: 'vitest',
};

describe('H5.5 — route, guard & nav', () => {
  it('App.tsx: /settings/audit-log dengan guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/audit-log"');
    expect(APP).toContain('<AuditLogPage />');
    expect(APP).toContain("import('@/pages/settings/AuditLogPage')");
    expect(APP).toContain('roles={SETTINGS_ROLES}');
  });

  it('nav-config menambah "Audit Log" setelah WA Gateway + F9 /settings/audit TETAP', () => {
    expect(NAV).toContain("label: 'Audit Log', path: '/settings/audit-log'");

    const settings = NAV_APPS.find((app) => app.id === 'settings');
    const paths = settings?.topbar.map((item) => item.path) ?? [];

    expect(paths).toContain('/settings/audit-log');
    // route-fix: landing app Settings tetap item topbar PERTAMA
    expect(settings?.topbar[0]?.path).toBe('/settings/routing');
    // F9 (audit produk) tidak digeser/diganti
    expect(paths).toContain('/settings/audit');
    // H5.5 dipasang SETELAH WA Gateway (relatif — tahan modul H5 berikutnya)
    expect(paths.indexOf('/settings/audit-log')).toBeGreaterThan(
      paths.indexOf('/settings/wa'),
    );
  });
});

describe('H5.5 — render halaman (react-dom/server)', () => {
  it('AuditLogPage render filter + tabel + aksi read-only', () => {
    const { text } = renderPage(createElement(AuditLogPage), '/settings/audit-log');

    expect(text).toContain('Audit Log');
    expect(text).toContain('Filter');
    expect(text).toContain('Kata kunci');
    expect(text).toContain('Resource');
    expect(text).toContain('Hasil');
    expect(text).toContain('Dari tanggal');
    expect(text).toContain('Sampai tanggal (inklusif)');
    expect(text).toContain('Terapkan Filter');
    expect(text).toContain('Bersihkan');
    expect(text).toContain('Read-only: audit trail append-only');
  });

  it('AuditLogPage sumber: GET daftar/detail + klik baris → modal (tanpa aksi tulis)', () => {
    const page = read('src/pages/settings/AuditLogPage.tsx');

    expect(page).toContain('fetchAuditLogs');
    expect(page).toContain('fetchAuditLog');
    expect(page).toContain('onRowClick');
    expect(page).toContain('Modal');
    expect(page).toContain('metadataSummary');
    expect(page).toContain('PaginationBar');
    // READ-ONLY: tidak ada tombol simpan/hapus/ubah
    expect(page).not.toContain('Simpan');
    expect(page).not.toContain('Hapus');
  });
});

describe('H5.5 — lib filter & tampilan (PURE)', () => {
  it('validateAuditFilters + isIsoDate (cermin filter backend)', () => {
    expect(validateAuditFilters(EMPTY_AUDIT_FILTERS)).toEqual({});
    expect(isAuditFiltersValid(validateAuditFilters(EMPTY_AUDIT_FILTERS))).toBe(true);

    const valid: AuditLogFilters = {
      ...EMPTY_AUDIT_FILTERS,
      user_id: '4',
      result: 'FAILED',
      date_from: '2026-10-01',
      date_to: '2026-10-14',
      search: 'master',
    };

    expect(validateAuditFilters(valid)).toEqual({});

    // user id bukan angka / nol
    expect(validateAuditFilters({ ...valid, user_id: 'abc' }).user_id).toContain('≥ 1');
    expect(validateAuditFilters({ ...valid, user_id: '0' }).user_id).toContain('≥ 1');

    // result di luar enum
    expect(validateAuditFilters({ ...valid, result: 'NGACO' }).result).toContain(
      'salah satu',
    );

    // tanggal salah format / tanggal tidak ada di kalender
    expect(validateAuditFilters({ ...valid, date_from: '01-10-2026' }).date_from).toContain(
      'YYYY-MM-DD',
    );
    expect(validateAuditFilters({ ...valid, date_to: '2026-02-31' }).date_to).toContain(
      'YYYY-MM-DD',
    );

    // search maksimal 100 karakter
    expect(
      validateAuditFilters({ ...valid, search: 'x'.repeat(101) }).search,
    ).toContain('maksimal');

    expect(isIsoDate('2026-10-14')).toBe(true);
    expect(isIsoDate('2026-13-01')).toBe(false);
    expect(isIsoDate('14/10/2026')).toBe(false);
    expect(isIsoDate('')).toBe(false);
  });

  it('helper tampilan: timestamp, pelaku, dash, metadata, tone, filter aktif', () => {
    expect(formatAuditTimestamp('2026-10-14T03:05:00+00:00')).toMatch(
      /^2026-10-14 \d{2}:\d{2}$/,
    );
    expect(formatAuditTimestamp(null)).toBe('—');
    expect(formatAuditTimestamp('')).toBe('—');
    expect(formatAuditTimestamp('bukan-tanggal')).toBe('—');

    expect(actorLabel(ROW)).toBe('Sari Admin');
    expect(actorLabel({ ...ROW, full_name: '' })).toBe('admin-audit');
    expect(actorLabel({ ...ROW, full_name: '', username: null })).toBe('sistem');

    expect(dash(null)).toBe('—');
    expect(dash('  ')).toBe('—');
    expect(dash('OK')).toBe('OK');

    expect(metadataSummary(ROW)).toBe('{"fields": ["code"]}');
    expect(metadataSummary({ ...ROW, metadata_preview: '' })).toBe('—');

    expect(auditResultTone('OK')).toBe('blue');
    expect(auditResultTone('failed')).toBe('coral');
    expect(auditResultTone('CONFLICT')).toBe('coral');
    expect(auditResultTone('DENIED')).toBe('muted');
    expect(auditResultTone('ANEh')).toBe('default');

    expect(hasActiveFilters(EMPTY_AUDIT_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_AUDIT_FILTERS, action: 'master.' })).toBe(true);
    expect(hasActiveFilters({ ...EMPTY_AUDIT_FILTERS, search: '   ' })).toBe(false);
  });

  it('auditDetailEntries + formatJsonBlock (payload/metadata ter-mask)', () => {
    const entries = auditDetailEntries(DETAIL);
    const labels = entries.map((entry) => entry.label);

    expect(labels).toEqual([
      'Waktu',
      'Pelaku',
      'Aksi',
      'Resource',
      'Resource ID',
      'Hasil',
      'Request ID',
      'IP',
      'User agent',
      'Payload',
      'Metadata',
    ]);

    const payloadEntry = entries.find((entry) => entry.label === 'Payload');

    expect(payloadEntry?.value).toContain('"api_key": "***"');
    expect(payloadEntry?.value).toContain('PRD-1');
    expect(payloadEntry?.mono).toBe(true);

    const actorEntry = entries.find((entry) => entry.label === 'Pelaku');

    expect(actorEntry?.value).toBe('Sari Admin');
    expect(actorEntry?.mono).toBe(false);

    // payload/metadata kosong → „—"
    expect(auditDetailEntries({ ...DETAIL, payload: {}, metadata: {} }).at(-1)?.value).toBe(
      '—',
    );
    expect(formatJsonBlock({})).toBe('—');
    expect(formatJsonBlock({ a: 1 })).toContain('"a": 1');
  });
});

