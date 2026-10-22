import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { AIChart } from '@/components/molecules/AIChart';
import { htmlOf, textOf } from '../../helpers/react-tree';

const SRC = readFileSync(
  path.resolve(import.meta.dirname, '../../../src/components/molecules/AIChart.tsx'),
  'utf8',
);

const DATA = [
  { label: '18 Okt', value: 1.6 },
  { label: '20 Okt', value: 21 },
];

describe('Fix #18C — AIChart (Recharts)', () => {
  it('render line chart + judul', () => {
    const tree = createElement(AIChart, {
      type: 'line',
      data: DATA,
      title: 'Tren Scrap',
      unit: '%',
    });
    const html = htmlOf(tree);

    expect(html).toContain('data-testid="ai-chart"');
    expect(textOf(tree)).toContain('Tren Scrap');
    expect(html).toContain('text-accent-blue');
  });

  it('render bar chart', () => {
    const tree = createElement(AIChart, {
      type: 'bar',
      data: DATA,
      title: 'Scrap per Line',
    });

    expect(htmlOf(tree)).toContain('data-testid="ai-chart"');
    expect(textOf(tree)).toContain('Scrap per Line');
  });

  it('data kosong tidak merender apa pun', () => {
    const tree = createElement(AIChart, { type: 'line', data: [] });

    expect(htmlOf(tree)).toBe('');
  });

  it('komponen memakai Recharts (bukan chart manual)', () => {
    expect(SRC).toContain('from "recharts"');
    expect(SRC).toContain('LineChart');
    expect(SRC).toContain('BarChart');
  });
});
