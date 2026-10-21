import { NAV_APPS } from '@/app/nav-config';

/**
 * PURE — path item topbar app `appId`, dibaca dari SUMBER TUNGGAL `NAV_APPS`.
 *
 * PRA-0A.1 (K2): test lama mem-pin LABEL (mis. "Currencies") sehingga setiap
 * perubahan copy nav-config mematahkan puluhan test. Kontrak yang benar adalah
 * PATH (halaman mana yang bisa dibuka); label bebas berubah.
 */
export function topbarPaths(appId: string): string[] {
  return (NAV_APPS.find((app) => app.id === appId)?.topbar ?? []).map((item) => item.path);
}

/** PURE — label item topbar untuk `path` (undefined kalau item tidak ada). */
export function topbarLabel(appId: string, path: string): string | undefined {
  return (NAV_APPS.find((app) => app.id === appId)?.topbar ?? []).find(
    (item) => item.path === path,
  )?.label;
}
