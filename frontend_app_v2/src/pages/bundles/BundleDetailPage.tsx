import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useBundle } from '@/hooks/useBundle';
import { useChatter } from '@/hooks/useChatter';
import { useChatterWs } from '@/hooks/useChatterWs';
import { mergeChatterPreview } from '@/lib/chatter-merge';
import { cardStatusFromState } from '@/lib/state-display';
import { BundleCard } from '@/components/molecules/BundleCard';
import { ApiActionButton } from '@/components/molecules/ApiActionButton';
import { ChatterBox } from '@/components/molecules/ChatterBox';
import { PrintTagButton } from '@/components/molecules/PrintTagButton';
import { Spinner } from '@/components/atoms/Spinner';
import { ConflictResolver } from '@/components/ConflictResolver';
import type { ApiConflictCurrent } from '@/integrations/api-client';
import type { OfflineAction } from '@/integrations/offline-queue';

interface ConflictState {
  current: ApiConflictCurrent;
  action: OfflineAction;
}

export function BundleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: bundle, isLoading, error, refetch } = useBundle(id);
  const [conflict, setConflict] = useState<ConflictState | null>(null);

  // Chatter: container memegang datanya, ChatterBox hanya merender (Fase 15).
  const [chatterCursor, setChatterCursor] = useState<string | null>(null);
  const chatter = useChatter('bundles', bundle?.id, { limit: 5, cursor: chatterCursor });

  // Real-time (F4): event WS group `bundle.<id>` di-prepend ke `preview` hasil fetch.
  const ws = useChatterWs({ resource: 'bundles', id: bundle?.id });

  if (isLoading) {
    return (
      <div className="p-4">
        <Spinner />
      </div>
    );
  }

  if (error || !bundle) {
    return (
      <div className="p-4">
        <p className="text-danger">Bundle tidak ditemukan.</p>
        <Link to="/bundles" className="text-sm text-info">
          ← Kembali
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-4">
      <Link to="/bundles" className="text-sm text-info">
        ← Kembali
      </Link>

      <BundleCard
        bundleId={bundle.code}
        size={bundle.size || '-'}
        skuVariant={bundle.sku_variant}
        currentWc={bundle.current_work_center_code ?? '-'}
        status={cardStatusFromState(bundle.state)}
        qty={bundle.qty}
      />

      {bundle.allowed_actions.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          {bundle.allowed_actions.map((action) => (
            <ApiActionButton
              key={action.id}
              action={action}
              resource="bundles"
              resourceId={bundle.id}
              baseVersion={bundle.version}
              onSuccess={() => {
                void refetch();
              }}
              onConflict={(payload) =>
                setConflict({ current: payload.current, action: payload.action })
              }
            />
          ))}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Tidak ada aksi tersedia.</p>
      )}

      <div className="flex justify-end">
        <PrintTagButton
          bundleId={String(bundle.id)}
          onSuccess={() => {
            void refetch();
          }}
        />
      </div>

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
            // 'retry_force' & 'cancel': Fase 7 (queue) yang menangani retry nyata; di sini cukup tutup.
          }}
          onClose={() => setConflict(null)}
        />
      ) : null}
    </div>
  );
}
