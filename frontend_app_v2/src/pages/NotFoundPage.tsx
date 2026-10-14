import { useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, CircleAlert, LayoutDashboard } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL_PRIMARY, PILL_SECONDARY } from '@/lib/tokens';

/**
 * NotFoundPage - fallback path yang TIDAK dikenal (dipakai `RoleGuardFallback`).
 *
 * Catatan: path milik app yang bukan hak role TIDAK sampai ke sini - `RoleGuardFallback`
 * mengarahkannya ke `/` lebih dulu, jadi halaman ini murni "URL tidak ada".
 * Path ditampilkan supaya user bisa melaporkan/memperbaiki alamatnya.
 *
 * Ikon: `CircleAlert` (lucide 1.47 tidak punya `AlertTriangle`).
 */
export function NotFoundPage() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-4 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-coral/10 text-accent-coral">
        <CircleAlert className="h-8 w-8" aria-hidden="true" />
      </div>

      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          Halaman tidak ditemukan
        </h1>
        <p className="text-sm text-muted-foreground">
          Halaman yang kamu cari tidak tersedia atau sudah dipindahkan.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          className={cn(PILL_SECONDARY, 'gap-2 px-4 py-2 text-sm')}
          onClick={() => navigate(-1)}
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Kembali
        </button>

        <button
          type="button"
          className={cn(PILL_PRIMARY, 'gap-2 px-4 py-2 text-sm')}
          onClick={() => navigate('/')}
        >
          <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
          Dashboard
        </button>
      </div>

      <p className="mt-4 font-mono text-[11px] text-muted-foreground">Path: {pathname}</p>
    </div>
  );
}
