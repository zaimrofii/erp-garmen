import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  buildChatRequest,
  chatErrorMessage,
  minimalContext,
} from '@/lib/ai-context';

/**
 * Sprint E.5 — fallback forbidden di panel floating (kanal FLOATING).
 * Wiring diverifikasi dari SUMBER komponen; payload minimal diuji PURE.
 */

const ROOT = path.resolve(import.meta.dirname, '../../..');
const SOURCE = readFileSync(
  path.join(ROOT, 'src/components/organisms/FloatingAIAssistant.tsx'),
  'utf8',
);

describe('Sprint E.5 — floating forbidden/fallback', () => {
  it('pre-validasi dijalankan sebelum kirim', () => {
    expect(SOURCE).toContain('validateContextForSubmit(effectiveContext)');
    expect(SOURCE).toMatch(/if \(!validation\.ok\) \{[\s\S]{0,180}return;/);
  });

  it('response forbidden_context menampilkan pesan + tombol fallback', () => {
    expect(SOURCE).toContain('chat.error === "forbidden_context"');
    expect(SOURCE).toContain('Kirim tanpa konteks');
    expect(chatErrorMessage('forbidden_context')).toContain('tidak berhak');
  });

  it('fallback mengirim konteks minimal dengan channel FLOATING', () => {
    const context = minimalContext('/master/products/1');
    const request = buildChatRequest('halo', [], context, 'FLOATING');

    expect(request.context).toMatchObject({ page_type: null, resource_id: null });
    expect(request.channel).toBe('FLOATING');
    expect(SOURCE).toContain('retryWithoutContext(minimalContext(pathname))');
  });
});
