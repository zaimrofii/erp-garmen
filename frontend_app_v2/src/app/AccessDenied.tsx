import { useEffect, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutDashboard, ShieldAlert } from 'lucide-react';
import { useCurrentPath } from '@/app/use-current-path';
import { ROLE_LABELS, useRole } from '@/app/useRole';
import { cn } from '@/lib/cn';
import { PILL_PRIMARY } from '@/lib/tokens';

/**
 * AccessDenied.tsx — halaman "Akses Ditolak" (FIX ROUTE).
 *
 * Dipakai `RoleRoute` + `RoleGuardFallback` + `AppIndexRedirect` supaya role yang tidak
 * berhak melihat **pesan jelas**, bukan halaman kosong / redirect diam-diam:
 *  - judul + pesan + tombol "Kembali ke Dashboard";
 *  - auto-redirect ke `/` setelah `ACCESS_DENIED_REDIRECT_MS` (opsional tapi menjaga
 *    perilaku lama: user tidak nyangkut di halaman terlarang);
 *  - baris diagnostik role + path (memudahkan admin memetakan masalah izin).
 *
 * Dipisah dua komponen (pola repo `RoleRoute`/`NotFoundPage`):
 *  - `AccessDeniedView` = presentasional murni props → bisa diuji `renderToString`;
 *  - `AccessDenied`      = pembungkus hooks (role + path + timer navigasi).
 */

/** Lama tampil sebelum dialihkan ke Dashboard (ms). */
export const ACCESS_DENIED_REDIRECT_MS = 5000;

export const ACCESS_DENIED_TITLE = 'Akses Ditolak';
export const ACCESS_DENIED_MESSAGE =
  'Role Anda tidak punya akses ke halaman ini. Hubungi admin.';
export const ACCESS_DENIED_ACTION = 'Kembali ke Dashboard';

interface AccessDeniedViewProps {
  /** Label role aktif (mis. "Operator Lantai"). */
  roleLabel: string;
  /** Path yang ditolak (ditampilkan untuk diagnosa). */
  pathname: string;
  onBackToDashboard: () => void;
}

/** Presentasional — tanpa hooks, aman dirender `renderToString` tanpa Router. */
export function AccessDeniedView({
  roleLabel,
  pathname,
  onBackToDashboard,
}: AccessDeniedViewProps): ReactNode {
  return (
    <div
      data-access-denied="true"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-4 text-center"
    >
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-coral/10 text-accent-coral">
        <ShieldAlert className="h-8 w-8" aria-hidden="true" />
      </div>

      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{ACCESS_DENIED_TITLE}</h1>
        <p data-access-denied-message="" className="text-sm text-muted-foreground">
          {ACCESS_DENIED_MESSAGE}
        </p>
      </div>

      <button
        type="button"
        className={cn(PILL_PRIMARY, 'gap-2 px-4 py-2 text-sm')}
        onClick={onBackToDashboard}
      >
        <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
        {ACCESS_DENIED_ACTION}
      </button>

      <p className="mt-4 font-mono text-[11px] text-muted-foreground">
        Role: {roleLabel} · Path: {pathname}
      </p>
      <p className="text-[11px] text-muted-foreground">
        Dialihkan ke Dashboard dalam {ACCESS_DENIED_REDIRECT_MS / 1000} detik…
      </p>
    </div>
  );
}

/** Gerbang akses siap pakai: butuh Router (dipakai `RoleRoute`/`RoleGuardFallback`). */
export function AccessDenied(): ReactNode {
  const role = useRole();
  const [pathname] = useCurrentPath();
  const navigate = useNavigate();

  const goDashboard = (): void => {
    void navigate('/', { replace: true });
  };

  useEffect(() => {
    const timer = globalThis.setTimeout(() => {
      void navigate('/', { replace: true });
    }, ACCESS_DENIED_REDIRECT_MS);

    return () => {
      globalThis.clearTimeout(timer);
    };
  }, [navigate]);

  return (
    <AccessDeniedView
      roleLabel={ROLE_LABELS[role]}
      pathname={pathname}
      onBackToDashboard={goDashboard}
    />
  );
}
