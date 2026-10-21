import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AIObservabilityPage } from '@/pages/settings/AIObservabilityPage';
import { NAV_APPS } from '@/app/nav-config';
import { defaultRange } from '@/lib/ai-observability';
import { htmlOf, textOf } from '../../helpers/react-tree';
import type { AIObservabilityStats } from '@/types/ai-observability';

/**
 * Sprint F.3 — dashboard observability AI (SSR + sumber).
 * Event klik tidak dijalankan (tanpa jsdom); wiring diverifikasi dari sumber.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const read = (relative: string): string => readFileSync(path.join(ROOT, relative), 'utf8');
const PAGE = read('src/pages/settings/AIObservabilityPage.tsx');
const APP = read('src/App.tsx');

const STATS: AIObservabilityStats = {
  date_from: '2026-10-12',
  date_to: '2026-10-18',
  group_by: 'day',
  totals: {
    requests: 5,
    tokens_prompt: 50,
    tokens_completion: 100,
    cost_usd: 0.005,
    cache_hits: 2,
    hitl_required: 4,
    hitl_approved: 3,
    hitl_rejected: 1,
    latency_avg_ms: 120,
  },
  by_day: [
    { date: '2026-10-17', requests: 2, cost_usd: 0.002, latency_avg_ms: 100 },
    { date: '2026-10-18', requests: 3, cost_usd: 0.003, latency_avg_ms: 140 },
  ],
  by_tool: [{ tool: 'mcp-analytics', calls: 2, avg_duration_ms: 20 }],
  by_decision_gate: { RULE_HIT: 2, LLM_NEEDED: 3, BLOCKED: 0 },
  cache_hit_ratio: 0.4,
  hitl_approval_rate: 0.75,
  top_queries: [{ query_hash: 'abc123def456', count: 2 }],
  computed_at: '2026-10-18T08:00:00+00:00',
  cached: false,
};

function render(stats?: AIObservabilityStats): { html: string; text: string } {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = createElement(
    QueryClientProvider,
    { client },
    createElement(
      MemoryRouter,
      { initialEntries: ['/settings/ai-observability'] },
      createElement(
        AIObservabilityPage,
        stats === undefined ? {} : { initialStats: stats },
      ),
    ),
  );

  return { html: htmlOf(tree), text: textOf(tree) };
}

describe('Sprint F.3 — halaman observability', () => {
  it('KPI cards tampil', () => {
    const { html, text } = render(STATS);

    expect(html).toContain('data-testid="ai-observability-kpi"');
    expect(text).toContain('Total request');
    expect(text).toContain('$0.0050');
    expect(text).toContain('40.0%');
    expect(text).toContain('75.0%');
    expect(text).toContain('120 ms');
  });

  it('grafik biaya per hari', () => {
    const { html } = render(STATS);

    expect(html).toContain('aria-label="Grafik biaya per hari"');
    expect(html).toContain('<polyline');
  });

  it('filter tanggal ada + sumber mengirim date range', () => {
    const { html } = render(STATS);

    expect(html).toContain('type="date"');
    expect(PAGE).toContain('dateFrom');
    expect(PAGE).toContain('dateTo');
  });

  it('Muat Ulang memakai _nocache', () => {
    expect(PAGE).toContain('nocache: refresh > 0');
    expect(PAGE).toContain('Muat Ulang');
  });

  it('empty state saat belum ada data', () => {
    const { text } = render({
      ...STATS,
      totals: { ...STATS.totals, requests: 0 },
      by_day: [],
      by_tool: [],
      top_queries: [],
    });

    expect(text).toContain('Belum ada data observability');
  });

  it('loading state saat query pending', () => {
    const { text } = render();

    expect(text).toContain('Memuat observability AI');
  });

  it('nav item muncul tepat setelah Analitik', () => {
    const settings = NAV_APPS.find((app) => app.id === 'settings');
    const labels = settings?.topbar.map((item) => item.label) ?? [];
    const index = labels.indexOf('Analitik');

    expect(labels[index + 1]).toBe('AI Observability');
  });

  it('route memakai guard SETTINGS_ROLES', () => {
    expect(APP).toContain('path="/settings/ai-observability"');
    expect(APP).toMatch(/path="\/settings\/ai-observability"[\s\S]{0,180}SETTINGS_ROLES/);
  });

  it('defaultRange 7 hari', () => {
    const range = defaultRange(7, new Date('2026-10-18T00:00:00Z'));

    expect(range).toEqual({ from: '2026-10-12', to: '2026-10-18' });
  });
});
