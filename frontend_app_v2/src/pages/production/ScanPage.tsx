import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, ScanLine, Settings } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Spinner } from '@/components/atoms/Spinner';
import { BundleCard } from '@/components/molecules/BundleCard';
import { ScanInput } from '@/components/molecules/ScanInput';
import { useFeedback } from '@/app/app-runtime';
import { fetchBundleDetail } from '@/api/bundles';
import { useApiClient } from '@/hooks/useApiClient';
import { useScan } from '@/hooks/use-scan';
import { cn } from '@/lib/cn';
import { cardStatusFromState } from '@/lib/state-display';
import { CARD, PILL_GHOST } from '@/lib/tokens';
import type { BundleDetail } from '@/types/bundle';

/**
 * ScanPage - Screen A (Visual Design System v3 bagian 3.1): operator HP.
 *
 * Alur: scan -> cari bundle -> tampilkan kartu singkat -> otomatis buka Shop Floor
 * (`AUTO_OPEN_MS`) supaya operator tidak perlu tap dua kali.
 *
 * Viewfinder kamera BELUM ada (butuh library eksternal - belum disetujui), jadi yang
 * dipakai adalah `ScanInput` (barcode gun USB / ketik manual) + placeholder viewfinder
 * sebagai penanda slot UI. Debounce 500 ms ditangani `useScan`.
 */

/** Jeda sebelum auto-pindah ke Shop Floor (ms) - memberi waktu feedback suara/getar. */
const AUTO_OPEN_MS = 500;

export function ScanPage() {
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const [bundle, setBundle] = useState<BundleDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (openTimerRef.current !== null) window.clearTimeout(openTimerRef.current);
    };
  }, []);

  const handleScan = useCallback(
    async (code: string): Promise<void> => {
      // QR bisa berbentuk URL (`.../bundles/42`) -> ambil segmen terakhir.
      const target = code.replace(/^.*\//, '');

      setLoading(true);
      setError(null);
      setBundle(null);

      try {
        const detail = await fetchBundleDetail(client, target);
        setBundle(detail);

        openTimerRef.current = window.setTimeout(() => {
          openTimerRef.current = null;
          navigate(`/production/shop-floor/${detail.id}`);
        }, AUTO_OPEN_MS);
      } catch (caught) {
        trigger('error');
        setError(caught instanceof Error ? caught.message : 'Bundle tidak ditemukan.');
      } finally {
        setLoading(false);
      }
    },
    [client, navigate, trigger],
  );

  const onScan = useScan((code) => {
    void handleScan(code);
  });

  return (
    <div className="flex min-h-full flex-col bg-background">
      <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border/40 bg-background/80 px-4 backdrop-blur">
        <button
          type="button"
          onClick={() => navigate('/')}
          aria-label="Kembali ke Dashboard"
          className={cn(
            PILL_GHOST,
            'p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
        </button>

        <h1 className="text-base font-semibold tracking-tight text-foreground">Scan Bundle</h1>

        <button
          type="button"
          onClick={() => navigate('/settings/devices')}
          aria-label="Pengaturan perangkat"
          className={cn(
            PILL_GHOST,
            'p-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
          )}
        >
          <Settings className="h-5 w-5" aria-hidden="true" />
        </button>
      </header>

      <div className="flex flex-1 flex-col gap-4 p-4 pb-40">
        <section className={cn(CARD, 'flex flex-col items-center gap-3 text-center')}>
          <div className="flex h-24 w-24 items-center justify-center rounded-card border-2 border-dashed border-border/80 bg-muted/40">
            <ScanLine className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
          </div>
          <p className="text-sm font-medium text-foreground">Arahkan kamera HP ke QR bundle</p>
          <p className="text-xs text-muted-foreground">
            Modul kamera belum aktif - pakai barcode gun USB atau ketik kode bundle.
          </p>
          <ScanInput onScan={onScan} className="w-full" />
        </section>

        {loading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
            <Spinner size="sm" />
            Mencari bundle...
          </div>
        ) : null}

        {error !== null ? (
          <section className={cn(CARD, 'flex flex-col gap-3 border border-accent-coral/30')}>
            <p className="text-sm font-semibold text-foreground">Bundle tidak ditemukan</p>
            <p className="text-xs text-muted-foreground">{error}</p>
            <Button variant="secondary" onClick={() => setError(null)}>
              Coba Lagi
            </Button>
          </section>
        ) : null}

        {bundle !== null ? (
          <>
            <BundleCard
              bundleId={bundle.code}
              size={bundle.size || '-'}
              skuVariant={bundle.sku_variant}
              currentWc={bundle.current_work_center_code ?? '-'}
              status={cardStatusFromState(bundle.state)}
              qty={bundle.qty}
            />
            <p className="text-center text-xs text-muted-foreground">Membuka Shop Floor...</p>
          </>
        ) : null}
      </div>
    </div>
  );
}
