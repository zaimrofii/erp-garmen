/**
 * journal-entry.ts — logic PURE halaman Journal Entry manual (H3.4).
 *
 * Dipisah dari halaman supaya bisa diuji TANPA DOM (jsdom tidak jalan di bun —
 * `.clinerules` §ENVIRONMENT): validasi form, balance double-entry, konversi
 * row/detail ↔ form, label state, opsi filter, dan item detail.
 *
 * Cermin guard backend (`garment/services/journal_entry_services.py`):
 *   * journal wajib punya `odoo_id` & **general** (dropdown MES memakai
 *     `?type=general`, tetap ditegakkan backend);
 *   * minimal 2 baris; tiap baris **debit XOR credit** (> 0, tidak negatif);
 *   * **Σ debit = Σ kredit** dengan toleransi `JOURNAL_ENTRY_BALANCE_TOLERANCE` (0.01);
 *   * setiap baris wajib punya akun yang sudah punya `odoo_id` (hasil pull Odoo).
 *
 * Angka dibiarkan **string** selama di form; konversi ke `number` hanya saat submit
 * (`journalEntryInputFromForm`). Balance dihitung client-side untuk **membantu**
 * operator — backend tetap menegakkan kebenaran (400 bila tidak seimbang).
 */
import { displayOrDash, parseFormNumber } from '@/lib/master-uom';
import {
  JOURNAL_ENTRY_BALANCE_TOLERANCE,
  JOURNAL_ENTRY_MEMO_MAX_LENGTH,
  JOURNAL_ENTRY_REF_MAX_LENGTH,
  JOURNAL_ENTRY_STATE_LABELS,
  type JournalEntryDetail,
  type JournalEntryInput,
  type JournalEntryLineInput,
  type JournalEntryLineRow,
  type JournalEntryRow,
  type JournalEntryState,
} from '@/types/journal-entry';

/** Satu baris jurnal di form (semua nilai string — konversi saat submit). */
export interface JournalEntryFormLine {
  /** Kunci React stabil (bukan id backend — baris baru belum punya id). */
  key: string;
  account_id: string;
  partner_id: string;
  name: string;
  debit: string;
  credit: string;
}

/** Nilai form journal entry (header + baris). */
export interface JournalEntryFormValues {
  journal_id: string;
  entry_date: string;
  ref: string;
  memo: string;
  lines: JournalEntryFormLine[];
}

export interface JournalEntryFormErrors {
  journal_id?: string;
  entry_date?: string;
  ref?: string;
  memo?: string;
  /** Pesan tunggal untuk baris jurnal (akun/baris kosong/XOR). */
  lines?: string;
  /** Pesan khusus Σ debit ≠ Σ kredit. */
  balance?: string;
}

/** Minimal baris jurnal backend (double-entry). */
export const MIN_JOURNAL_ENTRY_LINES = 2;

/** Penghitung kunci baris (module-level, cukup untuk UI — bukan identitas domain). */
let lineSeq = 0;

/** PURE — baris form kosong dengan kunci stabil. */
export function newJournalEntryLine(seed: Partial<JournalEntryFormLine> = {}): JournalEntryFormLine {
  lineSeq += 1;

  return {
    key: `line-${String(lineSeq)}`,
    account_id: '',
    partner_id: '',
    name: '',
    debit: '',
    credit: '',
    ...seed,
  };
}

/** PURE — tanggal hari ini (`YYYY-MM-DD`) untuk nilai awal form. */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Template form kosong (**selalu** pakai `emptyJournalEntryForm()` agar barisnya baru). */
export const EMPTY_JOURNAL_ENTRY_FORM: JournalEntryFormValues = {
  journal_id: '',
  entry_date: '',
  ref: '',
  memo: '',
  lines: [],
};

/** PURE — form kosong: tanggal hari ini + 2 baris jurnal siap diisi. */
export function emptyJournalEntryForm(): JournalEntryFormValues {
  return {
    journal_id: '',
    entry_date: todayIso(),
    ref: '',
    memo: '',
    lines: [newJournalEntryLine(), newJournalEntryLine()],
  };
}

/** Filter state di halaman daftar (`all` = tidak difilter). */
export const JOURNAL_ENTRY_STATE_FILTERS: { id: string; label: string }[] = [
  { id: 'all', label: 'Semua' },
  { id: 'DRAFT', label: 'Draft' },
  { id: 'CONFIRMED', label: 'Terkonfirmasi' },
  { id: 'SENT', label: 'Terkirim' },
  { id: 'DONE', label: 'Selesai' },
  { id: 'CANCELLED', label: 'Dibatalkan' },
];

const STATE_FILTER_IDS: readonly string[] = JOURNAL_ENTRY_STATE_FILTERS.map((filter) => filter.id);

/** PURE — menyempitkan `string` dari Tabs ke filter state TANPA cast `as`. */
export function isJournalEntryStateFilter(value: string): value is 'all' | JournalEntryState {
  return STATE_FILTER_IDS.includes(value);
}

/** PURE — filter UI → param `state` backend (`null` = tidak difilter). */
export function stateParamForJournalEntryFilter(
  filter: 'all' | JournalEntryState,
): JournalEntryState | null {
  return filter === 'all' ? null : filter;
}

/** PURE — label state journal entry (Indonesia). */
export function journalEntryStateLabel(state: JournalEntryState): string {
  return JOURNAL_ENTRY_STATE_LABELS[state] ?? state;
}

/** PURE — tone badge per state (`blue`=aktif, `muted`=netral, `coral`=batal). */
export function journalEntryStateTone(state: JournalEntryState): 'blue' | 'muted' | 'coral' {
  if (state === 'CANCELLED') return 'coral';
  if (state === 'DRAFT') return 'muted';

  return 'blue';
}

/** PURE — label tombol aksi per state target. */
export const JOURNAL_ENTRY_ACTION_LABELS: Record<string, string> = {
  CONFIRMED: 'Konfirmasi & Kirim',
  DONE: 'Tandai Selesai',
  CANCELLED: 'Batalkan',
};

/** PURE — map state target → nama aksi API (`confirm`/`done`/`cancel`). */
export const JOURNAL_ENTRY_STATE_TO_ACTION: Record<string, 'confirm' | 'done' | 'cancel'> = {
  CONFIRMED: 'confirm',
  DONE: 'done',
  CANCELLED: 'cancel',
};

/** Hasil hitung balance (angka, bukan string form). */
export interface JournalEntryBalance {
  debit: number;
  credit: number;
  difference: number;
  balanced: boolean;
}

function balanceOf(debit: number, credit: number): JournalEntryBalance {
  const difference = Number((debit - credit).toFixed(2));

  return {
    debit: Number(debit.toFixed(2)),
    credit: Number(credit.toFixed(2)),
    difference,
    balanced: Math.abs(difference) <= JOURNAL_ENTRY_BALANCE_TOLERANCE,
  };
}

/** PURE — Σ debit/kredit dari baris FORM (baris tanpa akun tetap dihitung). */
export function journalEntryFormBalance(lines: JournalEntryFormLine[]): JournalEntryBalance {
  let debit = 0;
  let credit = 0;

  for (const line of lines) {
    debit += parseFormNumber(line.debit) ?? 0;
    credit += parseFormNumber(line.credit) ?? 0;
  }

  return balanceOf(debit, credit);
}

/** PURE — Σ debit/kredit dari ENTRY backend (`total_debit`/`total_credit`). */
export function journalEntryBalance(row: JournalEntryRow): JournalEntryBalance {
  return balanceOf(parseFormNumber(row.total_debit) ?? 0, parseFormNumber(row.total_credit) ?? 0);
}

/** PURE — true kalau baris form punya tepat satu sisi (debit XOR credit) > 0. */
export function isJournalEntryLineBalanced(line: JournalEntryFormLine): boolean {
  const debit = parseFormNumber(line.debit) ?? 0;
  const credit = parseFormNumber(line.credit) ?? 0;

  return debit >= 0 && credit >= 0 && debit > 0 !== credit > 0;
}

/** PURE — true kalau entry sudah punya `odoo_id` (pernah dikirim ke Odoo). */
export function isJournalEntrySent(row: JournalEntryRow): boolean {
  return row.odoo_id !== null;
}

/** PURE — true kalau entry masih DRAFT (satu-satunya state yang boleh diubah/dihapus). */
export function isJournalEntryDraft(row: JournalEntryRow): boolean {
  return row.state === 'DRAFT';
}

/** PURE — label opsi dropdown akun (`code — nama`). */
export function accountOptionLabel(row: { code: string; name: string }): string {
  return `${row.code} — ${row.name}`;
}

/** PURE — label opsi dropdown journal (`code — nama (tipe)`; tanpa tipe bila kosong). */
export function journalOptionLabel(row: {
  code: string;
  name: string;
  journal_type_label: string;
}): string {
  const type = row.journal_type_label.trim();

  return type === '' ? `${row.code} — ${row.name}` : `${row.code} — ${row.name} (${type})`;
}

/** PURE — label akun satu baris jurnal (`code nama`; `—` bila akun belum terisi). */
export function journalEntryLineAccountLabel(line: JournalEntryLineRow): string {
  const label = `${line.account_code ?? ''} ${line.account_name ?? ''}`.trim();

  return label === '' ? '—' : label;
}

/** PURE — true kalau baris form belum diisi sama sekali (kandidat dibuang saat submit). */
export function isBlankJournalEntryLine(line: JournalEntryFormLine): boolean {
  return (
    line.account_id.trim() === '' &&
    line.debit.trim() === '' &&
    line.credit.trim() === '' &&
    line.name.trim() === ''
  );
}

/** PURE — baris form yang BENAR-BENAR diisi (tanpa baris kosong sisa). */
export function filledJournalEntryLines(lines: JournalEntryFormLine[]): JournalEntryFormLine[] {
  return lines.filter((line) => !isBlankJournalEntryLine(line));
}

/** PURE — tambah satu baris kosong di bawah. */
export function addJournalEntryLine(values: JournalEntryFormValues): JournalEntryFormValues {
  return { ...values, lines: [...values.lines, newJournalEntryLine()] };
}

/** PURE — hapus satu baris (minimal 1 baris di form; guard "≥ 2" ada di validasi). */
export function removeJournalEntryLine(
  values: JournalEntryFormValues,
  key: string,
): JournalEntryFormValues {
  if (values.lines.length <= 1) return values;

  return { ...values, lines: values.lines.filter((line) => line.key !== key) };
}

/** PURE — ubah satu baris (patch parsial; kunci baris tetap). */
export function updateJournalEntryLine(
  values: JournalEntryFormValues,
  key: string,
  patch: Partial<Omit<JournalEntryFormLine, 'key'>>,
): JournalEntryFormValues {
  return {
    ...values,
    lines: values.lines.map((line) => (line.key === key ? { ...line, ...patch } : line)),
  };
}

/** PURE — true kalau string tanggal berbentuk ISO `YYYY-MM-DD` yang sah. */
export function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) return false;

  const parsed = new Date(`${value.trim()}T00:00:00Z`);

  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value.trim();
}

/**
 * PURE — validasi form; objek KOSONG berarti boleh dikirim.
 *
 * Baris yang **belum diisi sama sekali** diabaikan (operator boleh menyisakan baris
 * kosong) — sisanya wajib lengkap, XOR, dan totalnya seimbang (cermin backend).
 */
export function validateJournalEntryForm(values: JournalEntryFormValues): JournalEntryFormErrors {
  const errors: JournalEntryFormErrors = {};

  if (values.journal_id.trim() === '') {
    errors.journal_id = 'Journal wajib dipilih (hanya journal general).';
  }

  if (values.entry_date.trim() === '') {
    errors.entry_date = 'Tanggal entry wajib diisi.';
  } else if (!isIsoDate(values.entry_date)) {
    errors.entry_date = 'Tanggal entry harus format ISO (YYYY-MM-DD).';
  }

  if (values.ref.trim().length > JOURNAL_ENTRY_REF_MAX_LENGTH) {
    errors.ref = `Referensi maksimal ${String(JOURNAL_ENTRY_REF_MAX_LENGTH)} karakter.`;
  }
  if (values.memo.trim().length > JOURNAL_ENTRY_MEMO_MAX_LENGTH) {
    errors.memo = `Catatan maksimal ${String(JOURNAL_ENTRY_MEMO_MAX_LENGTH)} karakter.`;
  }

  const filled = filledJournalEntryLines(values.lines);
  if (filled.length < MIN_JOURNAL_ENTRY_LINES) {
    errors.lines = `Journal entry butuh minimal ${String(MIN_JOURNAL_ENTRY_LINES)} baris (debit & kredit).`;
  } else if (filled.some((line) => line.account_id.trim() === '')) {
    errors.lines = 'Setiap baris jurnal wajib punya akun (pull chart of accounts dulu).';
  } else if (!filled.every(isJournalEntryLineBalanced)) {
    errors.lines =
      'Tiap baris harus salah satu: debit > 0 ATAU kredit > 0 (tidak keduanya, tidak negatif).';
  }

  const balance = journalEntryFormBalance(filled);
  if (errors.lines === undefined && !balance.balanced) {
    errors.balance = `Σ debit (${balance.debit.toFixed(2)}) ≠ Σ kredit (${balance.credit.toFixed(
      2,
    )}) — selisih ${balance.difference.toFixed(2)}.`;
  }

  return errors;
}

/** PURE — true kalau tidak ada error (siap submit). */
export function isJournalEntryFormValid(errors: JournalEntryFormErrors): boolean {
  return Object.keys(errors).length === 0;
}

/** PURE — baris form → `lines[]` body backend (baris kosong dibuang). */
export function journalEntryLineInputs(lines: JournalEntryFormLine[]): JournalEntryLineInput[] {
  return filledJournalEntryLines(lines).map((line) => {
    const partnerId = line.partner_id.trim();
    const input: JournalEntryLineInput = {
      account_id: Number(line.account_id),
      debit: parseFormNumber(line.debit) ?? 0,
      credit: parseFormNumber(line.credit) ?? 0,
    };

    if (partnerId !== '') input.partner_id = Number(partnerId);
    if (line.name.trim() !== '') input.name = line.name.trim();

    return input;
  });
}

/**
 * PURE — nilai form → body API.
 *
 * `null` kalau `journal_id`/`entry_date` belum sah (pemanggil wajib memeriksa
 * `isJournalEntryFormValid` lebih dulu; pola H3.1–H3.3).
 */
export function journalEntryInputFromForm(values: JournalEntryFormValues): JournalEntryInput | null {
  const journalId = values.journal_id.trim();
  if (journalId === '' || !Number.isFinite(Number(journalId))) return null;
  if (!isIsoDate(values.entry_date)) return null;

  return {
    journal_id: Number(journalId),
    entry_date: values.entry_date.trim(),
    ref: values.ref.trim(),
    memo: values.memo.trim(),
    lines: journalEntryLineInputs(values.lines),
  };
}

/** PURE — detail backend → nilai form (dipakai halaman edit). */
export function journalEntryFormFromDetail(detail: JournalEntryDetail): JournalEntryFormValues {
  return {
    journal_id: String(detail.journal_id),
    entry_date: detail.entry_date === null ? '' : detail.entry_date.slice(0, 10),
    ref: detail.ref,
    memo: detail.memo,
    lines: detail.lines.map((line) =>
      newJournalEntryLine({
        account_id: String(line.account_id),
        partner_id: line.partner_id === null ? '' : String(line.partner_id),
        name: line.name,
        debit: line.debit,
        credit: line.credit,
      }),
    ),
  };
}

/** Satu baris detail journal entry (label + nilai siap tampil). */
export interface JournalEntryDetailItem {
  label: string;
  value: string;
  mono?: boolean;
}

/** PURE — daftar field halaman detail (urutan tetap). */
export function journalEntryDetailItems(row: JournalEntryRow): JournalEntryDetailItem[] {
  const journalLabel = `${row.journal_code ?? '-'} — ${row.journal_name ?? '-'}`;

  return [
    { label: 'Kode', value: displayOrDash(row.code), mono: true },
    { label: 'Journal', value: journalLabel },
    { label: 'Tipe journal', value: displayOrDash(row.journal_type) },
    { label: 'Tanggal', value: displayOrDash(row.entry_date) },
    { label: 'Referensi', value: displayOrDash(row.ref), mono: true },
    {
      label: 'Total debit',
      value: journalEntryBalance(row).debit.toFixed(2),
      mono: true,
    },
    {
      label: 'Total kredit',
      value: journalEntryBalance(row).credit.toFixed(2),
      mono: true,
    },
    { label: 'State', value: journalEntryStateLabel(row.state) },
    { label: 'Odoo ID', value: row.odoo_id === null ? 'belum dikirim' : String(row.odoo_id) },
  ];
}

/** Satu baris jurnal siap render tabel detail (nilai = string apa adanya). */
export interface JournalEntryLineItem {
  key: number;
  account: string;
  name: string;
  partner: string;
  debit: string;
  credit: string;
}

/** PURE — baris jurnal detail → item tabel (label akun dari `code` + `name`). */
export function journalEntryLineItems(lines: JournalEntryLineRow[]): JournalEntryLineItem[] {
  return lines.map((line) => ({
    key: line.id,
    account: journalEntryLineAccountLabel(line),
    name: displayOrDash(line.name),
    partner: displayOrDash(line.partner_name),
    debit: line.debit,
    credit: line.credit,
  }));
}

/** PURE — teks ringkas balance untuk banner form (mis. `Seimbang: 1500.00`). */
export function journalEntryBalanceText(balance: JournalEntryBalance): string {
  return balance.balanced
    ? `Seimbang — Σ debit = Σ kredit = ${balance.debit.toFixed(2)}`
    : `Belum seimbang — selisih ${balance.difference.toFixed(2)}`;
}
