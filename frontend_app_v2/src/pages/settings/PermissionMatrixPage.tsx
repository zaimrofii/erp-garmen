import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, RefreshCw, Save, ShieldCheck, Undo2 } from 'lucide-react';
import { Badge } from '@/components/atoms/Badge';
import { Button } from '@/components/atoms/Button';
import { Checkbox } from '@/components/atoms/Checkbox';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { fetchPermissionMatrix, updateRolePermissions } from '@/api/permissionMatrix';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  actionLabel,
  defaultRoleId,
  diffUpdates,
  readCell,
  readDivergenceCell,
  resourceLabel,
  roleDraft,
  roleOptions,
  roleSummary,
  toggleCell,
} from '@/lib/permission-matrix';
import { CARD, TABLE_CELL, TABLE_HEAD } from '@/lib/tokens';
import {
  PERMISSION_BANNER_FALLBACK,
  type PermissionEnvelope,
} from '@/types/permission-matrix';

/**
 * PermissionMatrixPage - route `/settings/permissions` (H5.4, ADMIN/OWNER untuk menulis).
 *
 * **Opsi A′ (keputusan STEP 0)**: tabel menampilkan DUA kolom per aksi —
 * **profil** (checkbox, tersimpan di DB + ledger `SKIPPED` + `AuditLog`) dan
 * **efektif** (aturan yang **benar-benar berlaku** sekarang: snapshot guard kode).
 *
 * ⚠️ **Banner wajib** di atas tabel: perubahan di sini **tidak** mengubah enforcement
 * (backend masih memakai guard hardcoded `_require_admin`, `OPERATOR_CODE_ROLES`, dan
 * 16 daftar role frontend). Sprint enforcement terpisah yang akan menghubungkannya.
 *
 * Alur simpan: draft per role → `diffUpdates()` (hanya sel yang berubah) →
 * `PUT /api/v1/settings/permissions/<role_id>/` (ADMIN/OWNER) → amplop terbaru + toast
 * yang menyebut jumlah sel serta status ledger `SKIPPED`.
 *
 * Guard route: `SETTINGS_ROLES` (pola `/settings/roles`, `/settings/audit`).
 */

const QUERY_KEY = 'settings-permissions';

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

export function PermissionMatrixPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();
  const { trigger } = useFeedback();

  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [draft, setDraft] = useState<Record<string, Record<string, boolean>> | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: [QUERY_KEY],
    queryFn: () => fetchPermissionMatrix(client),
    staleTime: 15_000,
  });

  const envelope: PermissionEnvelope | null = detail.data ?? null;
  /** Daftar dari backend dimemo-kan supaya stabil antar-render (dep hook). */
  const roles = useMemo(() => envelope?.roles ?? [], [envelope]);
  const resources = useMemo(() => envelope?.resources ?? [], [envelope]);
  const actions = useMemo(() => envelope?.actions ?? [], [envelope]);

  /** Role aktif = pilihan pengguna → role pertama dari backend (tanpa effect). */
  const roleId = selectedRoleId ?? defaultRoleId(roles);

  /** Nilai profil awal role terpilih (bentuk lengkap: semua resource × action). */
  const baseline = useMemo(
    () =>
      envelope !== null && roleId !== null
        ? roleDraft(envelope.matrix, roleId, resources, actions)
        : {},
    [envelope, roleId, resources, actions],
  );

  /** Nilai yang ditampilkan/diedit = draft pengguna → baseline dari server. */
  const values = draft ?? baseline;

  /** Sel yang berubah saja (yang dikirim ke PUT). */
  const updates = useMemo(
    () => diffUpdates(baseline, values, resources, actions),
    [baseline, values, resources, actions],
  );

  const summary = envelope !== null && roleId !== null ? roleSummary(envelope, roleId) : null;

  const save = useMutation({
    mutationFn: () => updateRolePermissions(client, roleId ?? 0, { updates }),
    onSuccess: (result) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: 'Profil izin disimpan',
        description:
          result.updated_count === 0
            ? 'Tidak ada sel yang berubah — tidak ada ledger/audit baru.'
            : `${String(result.updated_count)} sel tersimpan sebagai PROFIL (ledger ${String(result.sync_status ?? 'SKIPPED')}). Enforcement belum berubah sampai sprint enforcement.`,
      });
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: [QUERY_KEY] });
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan profil izin',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function handleToggle(resource: string, action: string, allowed: boolean): void {
    setDraft(toggleCell(values, resource, action, allowed));
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Permissions"
        subtitle="Matrix izin role × resource × action — profil tersimpan vs aturan yang berlaku"
        breadcrumb={[{ label: 'Settings' }, { label: 'Permissions' }]}
        actions={
          <Button
            variant="ghost"
            icon={RefreshCw}
            onClick={() => {
              setDraft(null);
              void detail.refetch();
            }}
          >
            Muat Ulang
          </Button>
        }
      />

      <section className={cn(CARD, 'flex items-start gap-3')} role="status">
        <AlertTriangle className="h-4 w-4 shrink-0 text-accent-coral" aria-hidden="true" />
        <p className="text-xs text-muted-foreground">
          {envelope?.banner ?? PERMISSION_BANNER_FALLBACK}
        </p>
      </section>

      {detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat matrix izin…
        </div>
      ) : null}

      {detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat matrix izin (perlu login?).
          </p>
        </section>
      ) : null}

      {envelope === null ? null : (
        <>
          <section className={cn(CARD, 'flex flex-wrap items-end justify-between gap-3')}>
            <div className="flex flex-wrap items-end gap-3">
              <Select
                label="Role"
                options={roleOptions(roles)}
                value={roleId === null ? '' : String(roleId)}
                className="w-64"
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setDraft(null);
                  setSelectedRoleId(Number.isFinite(next) ? next : null);
                }}
              />

              <div className="flex flex-col gap-0.5 pb-2">
                <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
                  <ShieldCheck className="h-3 w-3" aria-hidden="true" />
                  {summary === null
                    ? '—'
                    : `${String(summary.stored)} sel aktif (profil)`}
                </span>
                <span className="text-xs text-muted-foreground">
                  {summary === null
                    ? 'menunggu backend'
                    : `efektif ${String(summary.effective)} sel · beda ${String(summary.divergent)} sel · ${String(summary.resources)} resource`}
                </span>
                <span className="text-xs text-muted-foreground">
                  Kotak = profil tersimpan · tulisan kecil di samping kotak = efektif
                  (aturan yang berlaku sekarang).
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={updates.length === 0 ? 'muted' : 'coral'}>
                {updates.length === 0
                  ? 'Tidak ada perubahan'
                  : `${String(updates.length)} sel siap disimpan`}
              </Badge>
              <Button
                type="button"
                variant="ghost"
                icon={Undo2}
                disabled={updates.length === 0}
                onClick={() => setDraft(null)}
              >
                Batalkan
              </Button>
              <Button
                type="button"
                icon={Save}
                loading={save.isPending}
                disabled={updates.length === 0 || roleId === null}
                onClick={() => save.mutate()}
              >
                Simpan Profil
              </Button>
            </div>
          </section>

          <section className={cn(CARD, 'p-0')}>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className={TABLE_HEAD}>Resource</th>
                    {actions.map((action) => (
                      <th key={action} className={TABLE_HEAD}>
                      {actionLabel(action)}
                    </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {resources.map((resource) => (
                    <tr key={resource}>
                      <td className={TABLE_CELL}>
                        <span className="font-medium text-foreground">
                          {resourceLabel(resource)}
                        </span>
                        <span className="block font-mono text-xs text-muted-foreground">
                          {resource}
                        </span>
                      </td>
                      {actions.map((action) => {
                        const divergence = readDivergenceCell(
                          envelope.diverges,
                          roleId ?? 0,
                          resource,
                          action,
                        );
                        const effective = readCell(
                          envelope.effective,
                          roleId ?? 0,
                          resource,
                          action,
                        );

                        return (
                          <td key={action} className={TABLE_CELL}>
                            <div className="flex items-center gap-2">
                              <Checkbox
                                aria-label={`${resource}.${action} untuk profil role terpilih`}
                                checked={values[resource]?.[action] === true}
                                onCheckedChange={(checked) =>
                                  handleToggle(resource, action, checked)
                                }
                              />
                              <span className="text-xs text-muted-foreground">
                                {effective ? 'ya' : '—'}
                              </span>
                              {divergence === null ? null : <Badge tone="coral">beda</Badge>}
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}

      {toast !== null ? (
        <Toast
          open={toast !== null}
          onOpenChange={() => setToast(null)}
          title={toast.title}
          tone={toast.tone}
          description={toast.description}
        />
      ) : null}
    </div>
  );
}

