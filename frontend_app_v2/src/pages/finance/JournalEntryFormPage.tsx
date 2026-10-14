import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, Plus, Save, Trash2 } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Select } from '@/components/atoms/Select';
import { Spinner } from '@/components/atoms/Spinner';
import { Toast, type ToastTone } from '@/components/atoms/Toast';
import { PageHeader } from '@/components/molecules/PageHeader';
import { createJournalEntry, fetchJournalEntry, updateJournalEntry } from '@/api/journalEntries';
import { fetchAccounts, ACCOUNTS_LIMIT_MAX } from '@/api/masterAccounts';
import { fetchJournals, JOURNALS_LIMIT_MAX } from '@/api/masterJournals';
import { fetchPartners, PARTNERS_LIMIT_MAX } from '@/api/masterPartners';
import { useFeedback } from '@/app/app-runtime';
import { useApiClient } from '@/hooks/useApiClient';
import { cn } from '@/lib/cn';
import {
  accountOptionLabel,
  addJournalEntryLine,
  emptyJournalEntryForm,
  filledJournalEntryLines,
  isJournalEntryFormValid,
  journalEntryBalanceText,
  journalEntryFormBalance,
  journalEntryFormFromDetail,
  journalEntryInputFromForm,
  journalOptionLabel,
  removeJournalEntryLine,
  updateJournalEntryLine,
  validateJournalEntryForm,
  type JournalEntryFormValues,
} from '@/lib/journal-entry';
import { CARD } from '@/lib/tokens';

/**
 * JournalEntryFormPage - route `/finance/journal-entries/new` + `…/:id/edit` (H3.4).
 *
 * Form jurnal **manual double-entry** MES (greenfield H3.4 — MES belum punya jurnal
 * manual sebelum ini):
 *
 *   * **journal** hanya `general` (`GET /master/journals/?type=general&active=true`);
 *     journal non-general ditolak backend dengan 400 (keputusan STEP 0);
 *   * **baris** ≥ 2, tiap baris **debit XOR credit** (> 0), akun dari
 *     `GET /master/accounts/?active=true` (hasil pull Odoo — wajib punya `odoo_id`);
 *   * **Σ debit = Σ kredit** dengan toleransi 0.01 dihitung client-side
 *     (`journalEntryFormBalance`) sebagai bantuan; backend tetap menegakkan (400);
 *   * create → `POST /api/v1/finance/journal-entries/`; edit → `PUT …/<id>/` (DRAFT-only);
 *   * push ke Odoo (`account.move` `move_type='entry'` **draft**) terjadi saat `CONFIRMED`
 *     di halaman detail — **posting bukan tanggung jawab MES**.
 */

interface ToastState {
  tone: ToastTone;
  title: string;
  description: string;
}

/** Opsi kosong untuk dropdown journal/akun/partner. */
const NO_JOURNAL_OPTION = { value: '', label: '— Pilih journal general —' };
const NO_ACCOUNT_OPTION = { value: '', label: '— Pilih akun —' };
const NO_PARTNER_OPTION = { value: '', label: '— Tanpa partner —' };

export function JournalEntryFormPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const client = useApiClient();
  const { trigger } = useFeedback();

  const parsedId = id === undefined ? null : Number(id);
  const entryId = parsedId !== null && Number.isFinite(parsedId) ? parsedId : null;
  const isEdit = entryId !== null;

  const [draft, setDraft] = useState<JournalEntryFormValues | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const detail = useQuery({
    queryKey: ['journal-entry', entryId],
    queryFn: () => fetchJournalEntry(client, entryId ?? 0),
    enabled: isEdit,
    staleTime: 15_000,
  });

  const journals = useQuery({
    queryKey: ['journal-entry-journals'],
    queryFn: () =>
      fetchJournals(client, { type: 'general', active: true, limit: JOURNALS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const accounts = useQuery({
    queryKey: ['journal-entry-accounts'],
    queryFn: () => fetchAccounts(client, { active: true, limit: ACCOUNTS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const partners = useQuery({
    queryKey: ['journal-entry-partners'],
    queryFn: () => fetchPartners(client, { limit: PARTNERS_LIMIT_MAX }),
    staleTime: 60_000,
  });

  const values = useMemo<JournalEntryFormValues | null>(() => {
    if (draft !== null) return draft;
    if (isEdit) {
      return detail.data === undefined ? null : journalEntryFormFromDetail(detail.data);
    }

    return emptyJournalEntryForm();
  }, [draft, detail.data, isEdit]);

  const current = values ?? emptyJournalEntryForm();
  const errors = useMemo(() => validateJournalEntryForm(current), [current]);
  const valid = values !== null && isJournalEntryFormValid(errors);
  const balance = journalEntryFormBalance(filledJournalEntryLines(current.lines));

  const journalOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = journals.data?.rows ?? [];

    return [
      NO_JOURNAL_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: journalOptionLabel(row) })),
    ];
  }, [journals.data]);

  const accountOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = accounts.data?.rows ?? [];

    return [
      NO_ACCOUNT_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: accountOptionLabel(row) })),
    ];
  }, [accounts.data]);

  const partnerOptions = useMemo<{ value: string; label: string }[]>(() => {
    const rows = partners.data?.rows ?? [];

    return [
      NO_PARTNER_OPTION,
      ...rows.map((row) => ({ value: String(row.id), label: `${row.code} — ${row.name}` })),
    ];
  }, [partners.data]);

  const save = useMutation({
    mutationFn: async () => {
      const input = journalEntryInputFromForm(current);
      if (input === null) {
        throw new Error('Journal dan tanggal entry wajib diisi.');
      }

      return isEdit
        ? updateJournalEntry(client, entryId ?? 0, input)
        : createJournalEntry(client, input);
    },
    onSuccess: (saved) => {
      trigger('success');
      setToast({
        tone: 'success',
        title: `${saved.code} tersimpan`,
        description: 'Entry lahir DRAFT (MES). Push draft ke Odoo terjadi saat CONFIRMED.',
      });
      navigate(`/finance/journal-entries/${String(saved.id)}`);
    },
    onError: (caught) => {
      trigger('error');
      setToast({
        tone: 'error',
        title: 'Gagal menyimpan journal entry',
        description: caught instanceof Error ? caught.message : 'Permintaan simpan gagal.',
      });
    },
  });

  function setField<K extends keyof JournalEntryFormValues>(
    field: K,
    value: JournalEntryFormValues[K],
  ): void {
    setDraft({ ...current, [field]: value });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    setSubmitted(true);

    if (!valid || save.isPending) return;

    save.mutate();
  }

  const showErrors = submitted;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title={isEdit ? 'Edit Journal Entry' : 'Journal Entry Baru'}
        subtitle="Jurnal manual double-entry MES — draft account.move dikirim ke Odoo saat CONFIRMED"
        breadcrumb={[
          { label: 'Finance', href: '/finance/journal-entries' },
          { label: isEdit ? 'Edit' : 'Baru' },
        ]}
        actions={
          <Button
            variant="ghost"
            icon={ArrowLeft}
            onClick={() => navigate('/finance/journal-entries')}
          >
            Kembali
          </Button>
        }
      />

      {isEdit && detail.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Memuat journal entry…
        </div>
      ) : null}

      {isEdit && detail.error !== null ? (
        <section className={cn(CARD, 'flex flex-col gap-2')}>
          <p role="alert" className="text-sm font-medium text-accent-coral">
            Gagal memuat journal entry (perlu login atau entry tidak ada).
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              void detail.refetch();
            }}
          >
            Coba Lagi
          </Button>
        </section>
      ) : null}

      <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
        <section className={cn(CARD, 'grid grid-cols-1 gap-4 md:grid-cols-3')}>
          <Select
            label="Journal (general) *"
            options={journalOptions}
            value={current.journal_id}
            onChange={(event) => setField('journal_id', event.target.value)}
            {...(showErrors && errors.journal_id !== undefined ? { error: errors.journal_id } : {})}
          />

          <Input
            label="Tanggal entry *"
            type="date"
            value={current.entry_date}
            onChange={(event) => setField('entry_date', event.target.value)}
            {...(showErrors && errors.entry_date !== undefined ? { error: errors.entry_date } : {})}
          />

          <Input
            label="Referensi"
            value={current.ref}
            placeholder="mis. JE-MANUAL-001 (boleh kosong)"
            onChange={(event) => setField('ref', event.target.value)}
            {...(showErrors && errors.ref !== undefined ? { error: errors.ref } : {})}
          />

          <div className="md:col-span-3">
            <Input
              label="Catatan"
              value={current.memo}
              placeholder="mis. penyesuaian stok opname"
              onChange={(event) => setField('memo', event.target.value)}
              {...(showErrors && errors.memo !== undefined ? { error: errors.memo } : {})}
            />
          </div>
        </section>

        <section className={cn(CARD, 'flex flex-col gap-3')}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Baris Jurnal ({String(current.lines.length)} baris)
            </h2>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              icon={Plus}
              onClick={() => setDraft(addJournalEntryLine(current))}
            >
              Tambah Baris
            </Button>
          </div>

          {current.lines.map((line, index) => (
            <div
              key={line.key}
              className="grid grid-cols-1 items-end gap-3 border-t border-border pt-3 md:grid-cols-12"
            >
              <div className="md:col-span-3">
                <Select
                  label={`Akun ${String(index + 1)}`}
                  options={accountOptions}
                  value={line.account_id}
                  onChange={(event) =>
                    setDraft(
                      updateJournalEntryLine(current, line.key, { account_id: event.target.value }),
                    )
                  }
                />
              </div>
              <div className="md:col-span-2">
                <Select
                  label={`Partner ${String(index + 1)}`}
                  options={partnerOptions}
                  value={line.partner_id}
                  onChange={(event) =>
                    setDraft(
                      updateJournalEntryLine(current, line.key, { partner_id: event.target.value }),
                    )
                  }
                />
              </div>
              <div className="md:col-span-2">
                <Input
                  label={`Keterangan ${String(index + 1)}`}
                  value={line.name}
                  placeholder="deskripsi baris"
                  onChange={(event) =>
                    setDraft(updateJournalEntryLine(current, line.key, { name: event.target.value }))
                  }
                />
              </div>
              <div className="md:col-span-2">
                <Input
                  label="Debit"
                  type="number"
                  min="0"
                  step="0.01"
                  value={line.debit}
                  onChange={(event) =>
                    setDraft(
                      updateJournalEntryLine(current, line.key, {
                        debit: event.target.value,
                        credit: event.target.value.trim() === '' ? line.credit : '',
                      }),
                    )
                  }
                />
              </div>
              <div className="md:col-span-2">
                <Input
                  label="Kredit"
                  type="number"
                  min="0"
                  step="0.01"
                  value={line.credit}
                  onChange={(event) =>
                    setDraft(
                      updateJournalEntryLine(current, line.key, {
                        credit: event.target.value,
                        debit: event.target.value.trim() === '' ? line.debit : '',
                      }),
                    )
                  }
                />
              </div>
              <div className="md:col-span-1">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  icon={Trash2}
                  aria-label={`Hapus baris ${String(index + 1)}`}
                  onClick={() => setDraft(removeJournalEntryLine(current, line.key))}
                >
                  Hapus
                </Button>
              </div>
            </div>
          ))}

          {showErrors && errors.lines !== undefined ? (
            <p role="alert" className="text-xs font-medium text-accent-coral">
              {errors.lines}
            </p>
          ) : null}

          <p
            className={cn(
              'text-xs font-medium',
              balance.balanced ? 'text-muted-foreground' : 'text-accent-coral',
            )}
          >
            {journalEntryBalanceText(balance)}
          </p>
          {showErrors && errors.balance !== undefined ? (
            <p role="alert" className="text-xs font-medium text-accent-coral">
              {errors.balance}
            </p>
          ) : null}
        </section>

        <section className={cn(CARD, 'flex flex-wrap items-center justify-between gap-3')}>
          <div className="flex flex-col gap-1">
            <p className="text-sm font-semibold text-foreground">
              Debit <span className="font-mono tabular-nums">{balance.debit.toFixed(2)}</span> ·
              Kredit <span className="font-mono tabular-nums">{balance.credit.toFixed(2)}</span>
            </p>
            <p className="text-xs text-muted-foreground">
              Entry lahir DRAFT (MES-only). Push ke Odoo (draft `account.move` `entry`) terjadi saat
              CONFIRMED; posting &amp; rekonsiliasi dilakukan akuntan di Odoo.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" icon={Save} loading={save.isPending}>
              {isEdit ? 'Simpan Perubahan' : 'Simpan Journal Entry'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => navigate('/finance/journal-entries')}
            >
              Batal
            </Button>
          </div>
        </section>
      </form>

      <Toast
        open={toast !== null}
        onOpenChange={() => setToast(null)}
        title={toast?.title ?? ''}
        {...(toast === null ? {} : { tone: toast.tone, description: toast.description })}
      />
    </div>
  );
}
