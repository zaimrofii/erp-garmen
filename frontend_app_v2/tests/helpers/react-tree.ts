import type { ReactElement, ReactNode } from 'react';
import { isValidElement } from 'react';
import { renderToString } from 'react-dom/server';

/**
 * Helper test komponen — **TANPA DOM** (jsdom tidak jalan di bun, `.clinerules` §ENVIRONMENT).
 *
 * - `htmlOf`  → React MERENDER sungguhan (komponen fungsi & hooks murni terlihat),
 *               tapi hasilnya hanya STRING HTML: jangan mengklaim event browser/DOM.
 * - `walk`    → pohon React element; dipakai mencari identitas komponen yang tidak
 *               muncul di HTML.
 * - `textOf`  → teks yang dilihat user (tag dibuang) untuk assertion isi.
 * - `attrOf` / `attrsOf` → nilai atribut (mis. `data-chatter-preview-count`).
 *
 * File ini TIDAK berakhiran `.test` → tidak dijalankan vitest sebagai test
 * (`include: ['tests/**\/*.test.{ts,tsx}']` di `vitest.config.ts`).
 */

export function walk(
  node: ReactNode,
  visit: (element: ReactElement<Record<string, unknown>>) => void
): void {
  if (node === null || node === undefined || typeof node === 'boolean') return;

  if (Array.isArray(node)) {
    for (const child of node) walk(child, visit);
    return;
  }

  if (isValidElement<Record<string, unknown>>(node)) {
    visit(node);
    walk(node.props['children'] as ReactNode, visit);
  }
}

/** HTML hasil render (komponen fungsi benar-benar dieksekusi React). */
export function htmlOf(node: ReactNode): string {
  return renderToString(node);
}

function decodeEntities(value: string): string {
  return value
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

/** Teks yang dilihat user (tag dibuang & entitas di-decode). */
export function textOf(node: ReactNode): string {
  return decodeEntities(htmlOf(node).replace(/<[^>]*>/g, ' '));
}

/** Nilai atribut PERTAMA yang cocok. */
export function attrOf(node: ReactNode, key: string): string | undefined {
  return new RegExp(`${key}="([^"]*)"`).exec(htmlOf(node))?.[1];
}

/** SEMUA nilai atribut dengan nama tertentu. */
export function attrsOf(node: ReactNode, key: string): string[] {
  return [...htmlOf(node).matchAll(new RegExp(`${key}="([^"]*)"`, 'g'))].map(
    (match) => match[1] ?? ''
  );
}

/** Cari element React (host atau komponen) dengan predikat pada `props`. */
export function findElement(
  node: ReactNode,
  predicate: (element: ReactElement<Record<string, unknown>>) => boolean
): ReactElement<Record<string, unknown>> | undefined {
  const found: ReactElement<Record<string, unknown>>[] = [];
  walk(node, (element) => {
    if (predicate(element)) found.push(element);
  });

  return found[0];
}

/** Panggil handler props langsung (hanya untuk komponen tanpa state). */
export function callProp(
  element: ReactElement<Record<string, unknown>>,
  key: string,
  ...args: unknown[]
): unknown {
  const handler = element.props[key];
  if (typeof handler !== 'function') return undefined;

  return (handler as (...rest: unknown[]) => unknown)(...args);
}
