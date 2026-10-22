import { readFileSync } from 'node:fs';
import path from 'node:path';
import { createElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AIChatPage } from '@/pages/ai/AIChatPage';
import { htmlOf } from '../../helpers/react-tree';

/**
 * Fix #19B — chat: input tidak boleh disabled (blur saat loading) dan
 * auto-focus tidak boleh merebut fokus saat user sudah mengetik.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const PAGE = readFileSync(path.join(ROOT, 'src/pages/ai/AIChatPage.tsx'), 'utf8');
const FLOATING = readFileSync(
  path.join(ROOT, 'src/components/organisms/FloatingAIAssistant.tsx'),
  'utf8',
);

describe('Fix #19B — chat input tidak kehilangan fokus', () => {
  it('auto-focus punya guard saat input sedang aktif', () => {
    expect(PAGE).toContain('document.activeElement?.tagName === "INPUT"');
    expect(PAGE).toContain('if (chat.loading) return;');
  });

  it('auto-focus hanya bergantung pada chat.loading', () => {
    expect(PAGE).toMatch(/document\.activeElement\?\.tagName[\s\S]{0,200}\}, \[chat\.loading\]\);/);
  });

  it('floating memakai readOnly + aria-busy (bukan disabled)', () => {
    expect(FLOATING).toContain('readOnly={chat.loading}');
    expect(FLOATING).toContain('aria-busy={chat.loading}');
    expect(FLOATING).not.toContain('disabled={chat.loading}');
  });

  it('input chat tidak memakai key dinamis', () => {
    const input = PAGE.slice(PAGE.indexOf('<Input'), PAGE.indexOf('</form>'));
    expect(input).not.toMatch(/\bkey=/);
    expect(input).toContain('value={draft}');
  });

  it('halaman chat tetap merender input', () => {
    const html = htmlOf(
      createElement(
        MemoryRouter,
        { initialEntries: ['/ai/chat'] },
        createElement(AIChatPage),
      ),
    );

    expect(html).toContain('placeholder="Tanya tentang produksi..."');
    expect(html).toContain('<input');
  });
});
