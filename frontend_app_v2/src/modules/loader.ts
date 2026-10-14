/**
 * loader.ts (v2 minimal) — subset dari `../frontend_app/src/modules/loader.ts`.
 *
 * v2 belum memakai plugin system industri, jadi file ini HANYA menyediakan
 * tipe + konstanta + fungsi murni yang dibutuhkan `@/app/config.ts`:
 * `IndustryPlugin`, `INDUSTRY_PLUGINS`, `DEFAULT_INDUSTRY_PLUGIN`,
 * `isIndustryPlugin`.
 *
 * TIDAK ada `dynamic import('./garmen/register')` dkk. — tidak menyeret
 * `modules/garmen|cold-storage|rmu`. Simbol disalin apa adanya dari sumber.
 */

export type IndustryPlugin = 'garmen' | 'cold-storage' | 'rmu';

export const INDUSTRY_PLUGINS: readonly IndustryPlugin[] = ['garmen', 'cold-storage', 'rmu'];

export const DEFAULT_INDUSTRY_PLUGIN: IndustryPlugin = 'garmen';

export function isIndustryPlugin(value: string): value is IndustryPlugin {
  return (INDUSTRY_PLUGINS as readonly string[]).includes(value);
}
