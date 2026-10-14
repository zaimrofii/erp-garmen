import { Component, type ErrorInfo, type ReactNode } from 'react';
import { CircleAlert, LayoutDashboard, RotateCcw } from 'lucide-react';
import { cn } from '@/lib/cn';
import { PILL_PRIMARY, PILL_SECONDARY } from '@/lib/tokens';

/**
 * RouteErrorBoundary.tsx — batas error per halaman (FIX ROUTE, class component).
 *
 * Sebelum ini TIDAK ADA error boundary di seluruh aplikasi: satu exception saat render
 * membuat React melepas seluruh tree → **halaman putih** tanpa penjelasan. Boundary ini
 * dipasang di setiap elemen `<Route>` (lihat `App.tsx`) sehingga:
 *  - halaman yang gagal → pesan "Terjadi kesalahan" + tombol "Kembali ke Dashboard" &
 *    "Muat ulang" (bukan putih), sementara App Shell (sidebar/topbar) tetap terpakai;
 *  - berpindah halaman **remount** boundary (tiap route punya boundary sendiri) sehingga
 *    error satu halaman tidak "menular" ke halaman lain;
 *  - stack error tetap dicatat ke console untuk diagnosa.
 *
 * Pemulihan sengaja memakai `window.location` (bukan `useNavigate`): boundary harus tetap
 * bekerja walau yang error adalah bagian lain dari Router.
 */

export const ROUTE_ERROR_TITLE = 'Terjadi kesalahan';
export const ROUTE_ERROR_MESSAGE =
  'Halaman ini gagal ditampilkan. Coba muat ulang, atau kembali ke Dashboard.';
export const ROUTE_ERROR_BACK = 'Kembali ke Dashboard';
export const ROUTE_ERROR_RELOAD = 'Muat ulang';

function reloadPage(): void {
  if (typeof window !== 'undefined') window.location.reload();
}

function backToDashboard(): void {
  if (typeof window !== 'undefined') window.location.assign('/');
}

interface RouteErrorFallbackProps {
  /** Pesan teknis (dari `Error.message`) — ditampilkan kecil untuk diagnosa. */
  message: string;
  onBackToDashboard: () => void;
  onReload: () => void;
}

/** Presentasional — aman dirender `renderToString` (tanpa hooks/window). */
export function RouteErrorFallback({
  message,
  onBackToDashboard,
  onReload,
}: RouteErrorFallbackProps): ReactNode {
  return (
    <div
      data-route-error="true"
      className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-4 text-center"
    >
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-coral/10 text-accent-coral">
        <CircleAlert className="h-8 w-8" aria-hidden="true" />
      </div>

      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">{ROUTE_ERROR_TITLE}</h1>
        <p data-route-error-message="" className="text-sm text-muted-foreground">
          {ROUTE_ERROR_MESSAGE}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          className={cn(PILL_PRIMARY, 'gap-2 px-4 py-2 text-sm')}
          onClick={onBackToDashboard}
        >
          <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
          {ROUTE_ERROR_BACK}
        </button>

        <button
          type="button"
          className={cn(PILL_SECONDARY, 'gap-2 px-4 py-2 text-sm')}
          onClick={onReload}
        >
          <RotateCcw className="h-4 w-4" aria-hidden="true" />
          {ROUTE_ERROR_RELOAD}
        </button>
      </div>

      {message.length > 0 ? (
        <p className="mt-4 max-w-xl font-mono text-[11px] text-muted-foreground">{message}</p>
      ) : null}
    </div>
  );
}

interface RouteErrorBoundaryProps {
  children: ReactNode;
}

interface RouteErrorBoundaryState {
  error: Error | null;
}

/** Batas error: bungkus elemen route (mis. `<RouteErrorBoundary><QCPage /></RouteErrorBoundary>`). */
export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Stack + component stack dicatat supaya bisa dilaporkan (tidak ada pengiriman telemetri).
    console.error('[RouteErrorBoundary]', error, info.componentStack);
  }

  render(): ReactNode {
    const { error } = this.state;

    if (error === null) return this.props.children;

    return (
      <RouteErrorFallback
        message={error.message}
        onBackToDashboard={backToDashboard}
        onReload={reloadPage}
      />
    );
  }
}
