import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * use-current-path.ts - SEAM navigasi App Shell.
 *
 * CATATAN PENTING (temuan verifikasi Fase 16): proyek ini SUDAH memakai
 * `react-router-dom` v7 - `main.tsx` membungkus aplikasi dengan `<BrowserRouter>`
 * dan `App.tsx` memakai `Routes/Route`. `app/useMode.ts` memang state-based, tapi itu
 * mode UX (management/operator/telemetry), BUKAN routing.
 *
 * Karena itu seam ini diimplementasikan di atas router yang sudah ada
 * (`useLocation` + `useNavigate`) - API-nya sama persis dengan adapter
 * `window.location` yang direncanakan (`[pathname, navigate]`), jadi kalau nanti
 * router diganti/dihapus, cukup ganti isi file ini saja:
 *
 *   const [pathname, navigate] = useCurrentPath()
 *
 * Tidak ada dependency baru, dan tidak ada desync: `window.history.pushState` langsung
 * TIDAK memicu `popstate` sehingga React Router tidak akan re-render - jadi jangan
 * mengganti isi hook ini dengan pushState selama BrowserRouter masih terpasang.
 */
export function useCurrentPath(): [string, (path: string) => void] {
  const location = useLocation();
  const navigate = useNavigate();

  const go = useCallback(
    (path: string): void => {
      void navigate(path);
    },
    [navigate],
  );

  return [location.pathname, go];
}
