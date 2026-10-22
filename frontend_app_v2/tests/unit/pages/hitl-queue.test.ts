import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { HitlQueuePage } from '@/pages/ai/HitlQueuePage';
import { NAV_APPS } from '@/app/nav-config';
import { MODE } from '@/api/_adapter';
import { parseHitlQueue, parseHitlQueueRow } from '@/api/hitlQueue';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { HitlQueuePage as HitlPage, HitlQueueRow } from '@/types/hitl-queue';

const ROOT = path.resolve(import.meta.dirname, '../../..');
const read = (relative: string): string => readFileSync(path.join(ROOT, relative), 'utf8');
const PAGE_SRC = read('src/pages/ai/HitlQueuePage.tsx');
const API_SRC = read('src/api/real/hitlQueue.ts');
const APP = read('src/App.tsx');

const ROW_PENDING: HitlQueueRow = {
  id: 12,
  decision_log_id: 5,
  risk_level: 'MEDIUM',
  proposed_action: {
    type: 'suggest_actions',
    problem: 'scrap SEWING-2 8.4%',
    actions: [
      {
        action: 'rework BND-A-12',
        impact: 'MEDIUM',
        confidence: 0.82,
        reason: '3.2% scrap',
      },
    ],
    count: 1,
  },
  required_approver_role: 'SUPERVISOR',
  channel: 'WA',
  status: 'PENDING',
  query_text: 'apa yang harus saya lakukan?',
  intent: 'SUGGEST_ACTION',
  confidence_score: 0.82,
  expires_at: '2026-10-22T08:00:00+00:00',
  created_at: '2026-10-21T08:00:00+00:00',
  decided_by: null,
  decided_at: null,
  rejection_reason: '',
};

const ROW_APPROVED: HitlQueueRow = {
  ...ROW_PENDING,
  id: 11,
  status: 'APPROVED',
  decided_by: 'sup1',
  decided_at: '2026-10-21T09:00:00+00:00',
};

const PAGE_DATA: HitlPage = {
  rows: [ROW_PENDING, ROW_APPROVED],
  total_count: 2,
  has_more: false,
  next_cursor: null,
};

function render(page?: HitlPage): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: ['/ai/hitl'] },
      createElement(HitlQueuePage, page === undefined ? {} : { initialPage: page }),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('S.3 — halaman antrean HITL', () => {
  it('render header + tabel + aksi', () => {
    const { html, text } = render(PAGE_DATA);

    expect(text).toContain('Antrean Persetujuan AI');
    expect(text).toContain('rework BND-A-12');
    expect(text).toContain('PENDING');
    expect(text).toContain('sup1');
    expect(html).toContain('<table');
  });

  it('filter status & risiko ada dan mengirim param', () => {
    const { html } = render(PAGE_DATA);

    expect(html).toContain('aria-label="Filter status"');
    expect(html).toContain('aria-label="Filter risiko"');
    expect(PAGE_SRC).toContain('status,');
    expect(PAGE_SRC).toContain('risk: risk || undefined');
  });

  it('klik baris membuka modal detail JSON', () => {
    render(PAGE_DATA);

    expect(PAGE_SRC).toContain('onRowClick={(row) => {');
    expect(PAGE_SRC).toContain('<Modal');
    expect(PAGE_SRC).toContain('JSON.stringify(selected.proposed_action');
    expect(PAGE_SRC).toContain('aria-label="Alasan penolakan"');
  });

  it('tombol Setujui memanggil approveHitl', () => {
    render(PAGE_DATA);

    expect(PAGE_SRC).toContain('Setujui');
    expect(PAGE_SRC).toContain('approveHitl(client, row.id, note)');
  });

  it('tombol Tolak wajib alasan + memanggil rejectHitl', () => {
    render(PAGE_DATA);

    expect(PAGE_SRC).toContain('Tolak');
    expect(PAGE_SRC).toContain('reason.trim().length === 0');
    expect(PAGE_SRC).toContain('rejectHitl(client, row.id, reason)');
  });

  it('empty state saat tidak ada usulan', () => {
    const { text } = render({ ...PAGE_DATA, rows: [], total_count: 0 });

    expect(text).toContain('Tidak ada usulan aksi pada filter ini.');
  });

  it('loading state saat query pending', () => {
    const { text } = render();

    expect(text).toContain('Memuat antrean HITL');
  });

  it('error state tersedia', () => {
    expect(PAGE_SRC).toContain('Gagal memuat antrean HITL.');
    expect(PAGE_SRC).toContain('query.error instanceof Error');
  });

  it('pagination memakai PaginationBar + offset', () => {
    expect(PAGE_SRC).toContain('<PaginationBar');
    expect(PAGE_SRC).toContain('offset: (page - 1) * PAGE_SIZE');
    expect(PAGE_SRC).toContain('totalPages');
  });

  it('route /ai/hitl memakai guard AI_ROLES (operator ditolak)', () => {
    expect(APP).toContain('path="/ai/hitl"');
    expect(APP).toMatch(/path="\/ai\/hitl"[\s\S]{0,200}AI_ROLES/);
    expect(APP).toMatch(/const AI_ROLES: Role\[\] = \["supervisor", "admin", "owner"\]/);
  });

  it('nav AI menampilkan item HITL', () => {
    const ai = NAV_APPS.find((app) => app.id === 'ai');

    expect(ai?.topbar.map((item) => item.label)).toContain('HITL');
    expect(ai?.topbar.find((item) => item.label === 'HITL')?.path).toBe('/ai/hitl');
  });

  it('adapter parse respons queue', () => {
    const parsed = parseHitlQueue({
      rows: [
        {
          id: 7,
          risk_level: 'HIGH',
          proposed_action: {
            problem: 'scrap',
            actions: [{ action: 'rework BND-9', impact: 'HIGH', confidence: 0.9 }],
            count: 1,
          },
          status: 'PENDING',
          confidence_score: 0.9,
        },
      ],
      total_count: 1,
      has_more: false,
      next_cursor: null,
    });

    expect(parsed?.rows).toHaveLength(1);
    expect(parsed?.rows[0]?.proposed_action.actions?.[0]?.action).toBe('rework BND-9');
    expect(parsed?.rows[0]?.status).toBe('PENDING');
  });

  it('adapter menolak bentuk rusak', () => {
    expect(parseHitlQueue(null)).toBeNull();
    expect(parseHitlQueue({ rows: 'x' })).toBeNull();
    expect(parseHitlQueueRow({ id: 0 })).toBeNull();
  });

  it('mode adapter hitlQueue = real + path approve/reject', () => {
    expect(MODE['hitlQueue']).toBe('real');
    expect(API_SRC).toContain("'/ai/hitl/queue/'");
    expect(API_SRC).toContain('/approve/');
    expect(API_SRC).toContain('/reject/');
  });

});
