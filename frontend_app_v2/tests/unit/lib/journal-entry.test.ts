import { describe, expect, it } from 'vitest';
import {
  accountOptionLabel,
  addJournalEntryLine,
  EMPTY_JOURNAL_ENTRY_FORM,
  emptyJournalEntryForm,
  filledJournalEntryLines,
  isBlankJournalEntryLine,
  isIsoDate,
  isJournalEntryDraft,
  isJournalEntryFormValid,
  isJournalEntryLineBalanced,
  isJournalEntrySent,
  isJournalEntryStateFilter,
  journalEntryBalance,
  journalEntryBalanceText,
  journalEntryDetailItems,
  journalEntryFormBalance,
  journalEntryFormFromDetail,
  journalEntryInputFromForm,
  journalEntryLineAccountLabel,
  journalEntryLineItems,
  journalEntryStateLabel,
  journalEntryStateTone,
  journalOptionLabel,
  newJournalEntryLine,
  removeJournalEntryLine,
  stateParamForJournalEntryFilter,
  updateJournalEntryLine,
  validateJournalEntryForm,
  type JournalEntryFormValues,
} from '@/lib/journal-entry';
import type {
  JournalEntryDetail,
  JournalEntryLineRow,
  JournalEntryRow,
} from '@/types/journal-entry';

/**
 * H3.4 — logic PURE halaman Journal Entry (`lib/journal-entry.ts`).
 *
 * Cermin guard backend `journal_entry_services.py`: ≥ 2 baris, debit XOR credit,
 * Σ debit = Σ kredit (toleransi 0.01), tanggal ISO — semuanya diuji tanpa DOM
 * (`.clinerules` §ENVIRONMENT: jsdom tidak jalan di bun).
 */

const ROW: JournalEntryRow = {
  id: 41,
  code: 'JE-2026-0001',
  journal_id: 10,
  journal_code: 'MISC',
  journal_name: 'Operasi Lain-lain',
  journal_type: 'general',
  entry_date: '2026-10-13',
  ref: 'JE-MANUAL-001',
  memo: 'penyesuaian',
  total_debit: '1500.00',
  total_credit: '1500.00',
  state: 'DRAFT',
  odoo_id: null,
  created_at: null,
  updated_at: null,
};

const LINE: JournalEntryLineRow = {
  id: 91,
  account_id: 181,
  account_code: '51000010',
  account_name: 'Cost of Goods Sold',
  partner_id: null,
  partner_name: null,
  name: 'Beban pokok',
  debit: '1500.00',
  credit: '0.00',
};

const DETAIL: JournalEntryDetail = {
  ...ROW,
  lines: [
    LINE,
    { ...LINE, id: 92, account_id: 223, account_code: '11120005', account_name: 'Bank', debit: '0.00', credit: '1500.00' },
  ],
  line_count: 2,
  odoo_sync_status: 'PENDING',
  odoo_sync_error: null,
  allowed_actions: ['CONFIRMED', 'CANCELLED'],
};

/** Form seimbang yang SAH dipakai beberapa test. */
function validForm(): JournalEntryFormValues {
  return {
    journal_id: '10',
    entry_date: '2026-10-13',
    ref: 'JE-MANUAL-001',
    memo: '',
    lines: [
      newJournalEntryLine({ account_id: '181', debit: '1500.00' }),
      newJournalEntryLine({ account_id: '223', credit: '1500.00' }),
    ],
  };
}

describe('H3.4 — filter, label & tone', () => {
  it('filter state: all + 5 state; param backend `null` saat all', () => {
    expect(isJournalEntryStateFilter('all')).toBe(true);
    expect(isJournalEntryStateFilter('SENT')).toBe(true);
    expect(isJournalEntryStateFilter('POSTED')).toBe(false);
    expect(stateParamForJournalEntryFilter('all')).toBeNull();
    expect(stateParamForJournalEntryFilter('DRAFT')).toBe('DRAFT');
  });

  it('label/tone state + label opsi dropdown', () => {
    expect(journalEntryStateLabel('SENT')).toBe('Terkirim ke Odoo');
    expect(journalEntryStateLabel('CANCELLED')).toBe('Dibatalkan');
    expect(journalEntryStateTone('DRAFT')).toBe('muted');
    expect(journalEntryStateTone('CANCELLED')).toBe('coral');
    expect(journalEntryStateTone('CONFIRMED')).toBe('blue');

    expect(accountOptionLabel({ code: '51000010', name: 'COGS' })).toBe('51000010 — COGS');
    expect(
      journalOptionLabel({ code: 'MISC', name: 'Lain-lain', journal_type_label: 'Miscellaneous' }),
    ).toBe('MISC — Lain-lain (Miscellaneous)');
    expect(journalOptionLabel({ code: 'LEGACY', name: 'Lama', journal_type_label: '' })).toBe(
      'LEGACY — Lama',
    );
  });

  it('helper state: DRAFT-only boleh ubah/hapus; SENT punya odoo_id', () => {
    expect(isJournalEntryDraft(ROW)).toBe(true);
    expect(isJournalEntrySent(ROW)).toBe(false);
    expect(isJournalEntryDraft({ ...ROW, state: 'CONFIRMED' })).toBe(false);
    expect(isJournalEntrySent({ ...ROW, odoo_id: 555 })).toBe(true);
  });
});

describe('H3.4 — balance double-entry (cermin `BALANCE_TOLERANCE`)', () => {
  it('journalEntryFormBalance: seimbang, selisih 0.01 masih seimbang, di atas toleransi tidak', () => {
    const balanced = journalEntryFormBalance([
      newJournalEntryLine({ account_id: '181', debit: '1500.00' }),
      newJournalEntryLine({ account_id: '223', credit: '1500.00' }),
    ]);

    expect(balanced.debit).toBe(1500);
    expect(balanced.credit).toBe(1500);
    expect(balanced.difference).toBe(0);
    expect(balanced.balanced).toBe(true);

    const tolerance = journalEntryFormBalance([
      newJournalEntryLine({ account_id: '181', debit: '1500.00' }),
      newJournalEntryLine({ account_id: '223', credit: '1499.99' }),
    ]);

    expect(tolerance.difference).toBe(0.01);
    expect(tolerance.balanced).toBe(true);

    const broken = journalEntryFormBalance([
      newJournalEntryLine({ account_id: '181', debit: '1500.00' }),
      newJournalEntryLine({ account_id: '223', credit: '1000.00' }),
    ]);

    expect(broken.difference).toBe(500);
    expect(broken.balanced).toBe(false);
    expect(journalEntryBalanceText(broken)).toContain('Belum seimbang');
  });

  it('journalEntryBalance(row) + balanceText: dari total_debit/total_credit backend', () => {
    const balance = journalEntryBalance(ROW);

    expect(balance.balanced).toBe(true);
    expect(balance.debit).toBe(1500);
    expect(journalEntryBalanceText(balance)).toContain('Seimbang');

    const unbalanced = journalEntryBalance({ ...ROW, total_credit: '1200.00' });
    expect(unbalanced.balanced).toBe(false);
    expect(unbalanced.difference).toBe(300);
  });

  it('isJournalEntryLineBalanced: debit XOR credit, bukan keduanya, bukan negatif', () => {
    expect(isJournalEntryLineBalanced(newJournalEntryLine({ debit: '1500.00' }))).toBe(true);
    expect(isJournalEntryLineBalanced(newJournalEntryLine({ credit: '10.00' }))).toBe(true);
    expect(isJournalEntryLineBalanced(newJournalEntryLine({ debit: '1', credit: '1' }))).toBe(false);
    expect(isJournalEntryLineBalanced(newJournalEntryLine())).toBe(false);
    expect(isJournalEntryLineBalanced(newJournalEntryLine({ debit: '-5' }))).toBe(false);
  });
});

describe('H3.4 — baris form (tambah/hapus/ubah)', () => {
  it('emptyJournalEntryForm: 2 baris kosong + tanggal hari ini; template tanpa baris', () => {
    const form = emptyJournalEntryForm();

    expect(form.lines).toHaveLength(2);
    expect(form.journal_id).toBe('');
    expect(isIsoDate(form.entry_date)).toBe(true);
    expect(EMPTY_JOURNAL_ENTRY_FORM.lines).toEqual([]);
  });

  it('newJournalEntryLine: kunci unik & menerima seed', () => {
    const a = newJournalEntryLine();
    const b = newJournalEntryLine({ account_id: '181', debit: '10.00' });

    expect(a.key).not.toBe(b.key);
    expect(b.account_id).toBe('181');
    expect(isBlankJournalEntryLine(a)).toBe(true);
    expect(isBlankJournalEntryLine(b)).toBe(false);
  });

  it('addJournalEntryLine/removeJournalEntryLine/updateJournalEntryLine', () => {
    const form = validForm();
    const added = addJournalEntryLine(form);

    expect(added.lines).toHaveLength(3);

    const removed = removeJournalEntryLine(added, added.lines[2]?.key ?? '');
    expect(removed.lines).toHaveLength(2);

    const twoLines = validForm();
    const single = removeJournalEntryLine(twoLines, twoLines.lines[0]?.key ?? '');
    expect(single.lines).toHaveLength(1);
    expect(removeJournalEntryLine(single, single.lines[0]?.key ?? '').lines).toHaveLength(1);

    const updated = updateJournalEntryLine(form, form.lines[0]?.key ?? '', { name: 'Kas keluar' });
    expect(updated.lines[0]?.name).toBe('Kas keluar');
    expect(updated.lines[1]?.name).toBe('');

    expect(filledJournalEntryLines(addJournalEntryLine(form).lines)).toHaveLength(2);
  });
});

describe('H3.4 — validasi form (cermin guard backend)', () => {
  it('form sah → tanpa error; baris kosong sisa diabaikan', () => {
    const errors = validateJournalEntryForm(addJournalEntryLine(validForm()));

    expect(errors).toEqual({});
    expect(isJournalEntryFormValid(errors)).toBe(true);
  });

  it('journal & tanggal wajib + tanggal harus ISO', () => {
    const noJournal = validateJournalEntryForm({ ...validForm(), journal_id: '' });
    expect(noJournal.journal_id).toBeDefined();

    const noDate = validateJournalEntryForm({ ...validForm(), entry_date: '' });
    expect(noDate.entry_date).toContain('wajib');

    const badDate = validateJournalEntryForm({ ...validForm(), entry_date: '13-10-2026' });
    expect(badDate.entry_date).toContain('ISO');
    expect(isIsoDate('2026-02-30')).toBe(false);
    expect(isIsoDate('2026-02-28')).toBe(true);
  });

  it('minimal 2 baris & setiap baris wajib akun', () => {
    const oneLine = validForm();
    const satu = validateJournalEntryForm({
      ...oneLine,
      lines: [newJournalEntryLine({ account_id: '181', debit: '1500.00' })],
    });
    expect(satu.lines).toContain('minimal 2 baris');

    const noAccount = validateJournalEntryForm({
      ...oneLine,
      lines: [
        newJournalEntryLine({ debit: '1500.00' }),
        newJournalEntryLine({ account_id: '223', credit: '1500.00' }),
      ],
    });
    expect(noAccount.lines).toContain('wajib punya akun');
  });

  it('XOR baris + balance: pesan `balance` khusus selisih', () => {
    const xor = validForm();
    const xorErrors = validateJournalEntryForm({
      ...xor,
      lines: [
        newJournalEntryLine({ account_id: '181', debit: '1500.00', credit: '10.00' }),
        newJournalEntryLine({ account_id: '223', credit: '1500.00' }),
      ],
    });
    expect(xorErrors.lines).toContain('debit > 0 ATAU kredit');

    const unbalanced = validForm();
    const balanceErrors = validateJournalEntryForm({
      ...unbalanced,
      lines: [
        newJournalEntryLine({ account_id: '181', debit: '1500.00' }),
        newJournalEntryLine({ account_id: '223', credit: '1000.00' }),
      ],
    });
    expect(balanceErrors.balance).toContain('selisih');
    expect(balanceErrors.lines).toBeUndefined();
  });

  it('batas panjang `ref`/`memo`', () => {
    const longRef = validateJournalEntryForm({ ...validForm(), ref: 'x'.repeat(65) });
    expect(longRef.ref).toContain('64');

    const longMemo = validateJournalEntryForm({ ...validForm(), memo: 'x'.repeat(256) });
    expect(longMemo.memo).toContain('255');
  });
});

describe('H3.4 — konversi form ↔ API & item detail', () => {
  it('journalEntryInputFromForm: angka number, baris kosong dibuang, partner opsional', () => {
    const form: JournalEntryFormValues = {
      ...validForm(),
      lines: [
        newJournalEntryLine({
          account_id: '181',
          debit: '1500.00',
          name: ' Beban pokok ',
          partner_id: '10',
        }),
        newJournalEntryLine({ account_id: '223', credit: '1500.00' }),
      ],
    };

    const input = journalEntryInputFromForm(addJournalEntryLine(form));

    expect(input?.journal_id).toBe(10);
    expect(input?.entry_date).toBe('2026-10-13');
    expect(input?.lines).toEqual([
      { account_id: 181, debit: 1500, credit: 0, name: 'Beban pokok', partner_id: 10 },
      { account_id: 223, debit: 0, credit: 1500 },
    ]);
  });

  it('journalEntryInputFromForm: null kalau journal/tanggal belum sah', () => {
    expect(journalEntryInputFromForm({ ...validForm(), journal_id: '' })).toBeNull();
    expect(journalEntryInputFromForm({ ...validForm(), entry_date: 'salah' })).toBeNull();
  });

  it('journalEntryFormFromDetail: baris & tanggal di-map ke form (tanggal di-slice 10)', () => {
    const form = journalEntryFormFromDetail({ ...DETAIL, entry_date: '2026-10-13T00:00:00Z' });

    expect(form.journal_id).toBe('10');
    expect(form.entry_date).toBe('2026-10-13');
    expect(form.ref).toBe('JE-MANUAL-001');
    expect(form.lines).toHaveLength(2);
    expect(form.lines[0]?.account_id).toBe('181');
    expect(form.lines[1]?.credit).toBe('1500.00');
  });

  it('journalEntryDetailItems/LineItems: label siap tampil (tanpa field reconcile)', () => {
    const items = journalEntryDetailItems(ROW);
    const labels = items.map((item) => item.label);

    expect(labels).toEqual([
      'Kode',
      'Journal',
      'Tipe journal',
      'Tanggal',
      'Referensi',
      'Total debit',
      'Total kredit',
      'State',
      'Odoo ID',
    ]);
    expect(items.find((item) => item.label === 'Odoo ID')?.value).toBe('belum dikirim');
    expect(items.find((item) => item.label === 'State')?.value).toBe('Draft');
    expect(journalEntryLineAccountLabel(LINE)).toBe('51000010 Cost of Goods Sold');
    expect(journalEntryLineAccountLabel({ ...LINE, account_code: null, account_name: null })).toBe(
      '—',
    );

    const lineItems = journalEntryLineItems(DETAIL.lines);
    expect(lineItems[0]).toEqual({
      key: 91,
      account: '51000010 Cost of Goods Sold',
      name: 'Beban pokok',
      partner: '-',
      debit: '1500.00',
      credit: '0.00',
    });
  });
});
