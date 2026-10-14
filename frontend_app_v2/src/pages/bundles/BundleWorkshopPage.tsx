import { useCallback, useState, type FormEvent } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import { useBundle } from '@/hooks/useBundle';
import { useChatter } from '@/hooks/useChatter';
import { useChatterWs } from '@/hooks/useChatterWs';
import { useApiClient } from '@/hooks/useApiClient';
import { useOfflineSync } from '@/integrations/use-offline-sync';
import { submitAction } from '@/lib/action-runner';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import { cardStatusFromState } from '@/lib/state-display';
import { BundleCard } from '@/components/molecules/BundleCard';
import { ChatterBox } from '@/components/molecules/ChatterBox';
import { Spinner } from '@/components/atoms/Spinner';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Badge } from '@/components/atoms/Badge';
import { ConflictResolver } from '@/components/ConflictResolver';
import type { AllowedAction } from '@/types/bundle';
import type { OfflineAction, FlushOutcome } from '@/integrations/offline-queue';

interface ConflictState {
  action: OfflineAction;
  current: { version: string; state: string; current_work_center?: string };
}

export function BundleWorkshopPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const apiClient = useApiClient();

  const [scanInput, setScanInput] = useState('');
  const [conflict, setConflict] = useState<ConflictState | null>(null);
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const [busyActionId, setBusyActionId] = useState<string | null>(null);

  const offlineSync = useOfflineSync({
    apiClient,
    onConflict: (action: OfflineAction, outcome: FlushOutcome) => {
      // outcome.current bisa undefined; kalau ada, tampilkan resolver.
      const cur = outcome.current;
      if (cur !== undefined) {
        setConflict({ action, current: cur });
      }
    },
  });

  const { data: bundle, isLoading, error, refetch } = useBundle(id);

  // Chatter: container memegang datanya, ChatterBox hanya merender (Fase 15).
  const [chatterCursor, setChatterCursor] = useState<string | null>(null);
  const chatter = useChatter('bundles', bundle?.id, { limit: 5, cursor: chatterCursor });

  // Real-time (F4): event WS group `bundle.<id>` di-prepend ke `preview` hasil fetch.
  const ws = useChatterWs({ resource: 'bundles', id: bundle?.id });

  const onScan = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = scanInput.trim();
      if (!trimmed) return;
      // QR = kode/id bundle; ambil segmen terakhir kalau input berbentuk URL.
      const numeric = trimmed.replace(/^.*\//, '');
      navigate(`/workshop/${numeric}`);
      setScanInput('');
    },
    [scanInput, navigate],
  );

  const handleAction = useCallback(
    async (action: AllowedAction) => {
      if (bundle === undefined || action.endpoint === undefined) return;
      setBusyActionId(action.id);
      setLastMessage(null);

      const result = await submitAction({
        queue: offlineSync.queue,
        action,
        resource: 'bundles',
        resourceId: String(bundle.id),
        baseVersion: bundle.version,
        path: action.endpoint,
      });

      setBusyActionId(null);

      if (result.kind === 'queued_offline') {
        setLastMessage('Offline — aksi masuk antrean, akan dikirim otomatis.');
        return;
      }
      if (result.kind === 'succeeded') {
        setLastMessage('Berhasil.');
        void refetch();
        return;
      }
      if (result.kind === 'conflicted') {
        const cur = result.outcome.current;
        if (cur !== undefined) {
          // OfflineAction minimal untuk resolver (pola sama seperti Fase 6b).
          setConflict({
            action: {
              id: result.outcome.id,
              path: action.endpoint,
              method: 'POST',
              body: { action: action.id, resource_id: String(bundle.id) },
              resource: 'bundles',
              resourceId: String(bundle.id),
              ts: Date.now(),
              base_version: bundle.version,
              conflict_policy: 'manual',
              status: 'conflict',
              idempotency_key: result.outcome.id, // best-effort; nilai tepat ada di queue
            },
            current: cur,
          });
        }
        return;
      }
      if (result.kind === 'failed') {
        setLastMessage(result.outcome.reason ?? 'Gagal.');
        return;
      }
      // 'deferred' → tetap di queue, tanpa pesan (hindari spam operator).
    },
    [bundle, offlineSync.queue, refetch],
  );

  if (id === undefined) {
    // Layar scan (belum pilih bundle).
    return (
      <div className="mx-auto max-w-md space-y-4 p-4">
        <h1 className="text-lg font-semibold text-foreground">Scan Bundle</h1>
        <form onSubmit={onScan} className="space-y-2">
          <Input
            value={scanInput}
            onChange={(e) => setScanInput(e.target.value)}
            placeholder="Scan / ketik kode bundle (mis. 16)"
            autoFocus
          />
          <Button type="submit" variant="primary" size="lg" className="w-full">
            Buka
          </Button>
        </form>
        <div className="flex items-center gap-2">
          <Badge tone={offlineSync.isOnline ? 'blue' : 'coral'}>
            {offlineSync.isOnline ? 'Online' : 'Offline'}
          </Badge>
          {offlineSync.pendingCount > 0 ? (
            <Badge tone="blue">Pending offline: {offlineSync.pendingCount}</Badge>
          ) : null}
        </div>
        <Link to="/bundles" className="text-sm text-info">
          ← Daftar bundle
        </Link>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }

  if (error || bundle === undefined) {
    return (
      <div className="space-y-3 p-4">
        <p className="text-danger">Bundle tidak ditemukan.</p>
        <Button variant="secondary" onClick={() => navigate('/workshop')}>
          Scan ulang
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-md space-y-4 p-4">
      <div className="flex items-center justify-between gap-2">
        <Badge tone={offlineSync.isOnline ? 'blue' : 'coral'}>
          {offlineSync.isOnline ? 'Online' : 'Offline'}
        </Badge>
        {offlineSync.pendingCount > 0 ? (
          <Badge tone="blue">Pending: {offlineSync.pendingCount}</Badge>
        ) : null}
        <Link to="/workshop" className="text-sm text-info">
          Scan lain
        </Link>
      </div>

      <BundleCard
        bundleId={bundle.code}
        size={bundle.size || '-'}
        skuVariant={bundle.sku_variant}
        currentWc={bundle.current_work_center_code ?? '-'}
        status={cardStatusFromState(bundle.state)}
        qty={bundle.qty}
      />

      {bundle.allowed_actions.length > 0 ? (
        <div className="grid grid-cols-1 gap-3">
          {bundle.allowed_actions.map((action) => (
            <Button
              key={action.id}
              variant="primary"
              size="lg"
              className="w-full py-6 text-base"
              disabled={busyActionId !== null}
              onClick={() => {
                void handleAction(action);
              }}
            >
              {busyActionId === action.id ? 'Memproses…' : action.label}
            </Button>
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Tidak ada aksi tersedia.</p>
      )}

      {lastMessage !== null ? (
        <p className="text-sm text-muted-foreground">{lastMessage}</p>
      ) : null}

      <ChatterBox
        preview={mergeChatterPreview(chatter.data?.preview ?? [], ws.events)}
        loading={chatter.isLoading}
        hasMore={chatter.data?.has_more ?? false}
        onLoadMore={() => setChatterCursor(chatter.data?.next_cursor ?? null)}
      />

      {conflict !== null ? (
        <ConflictResolver
          open
          action={conflict.action}
          current={conflict.current}
          onResolve={(choice) => {
            setConflict(null);
            if (choice === 'server_wins') void refetch();
            // 'retry_force' → retry nyata butuh flush manual (di luar scope 7b); cukup tutup.
          }}
          onClose={() => setConflict(null)}
        />
      ) : null}
    </div>
  );
}
