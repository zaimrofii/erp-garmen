import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, RefreshCw } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Input } from '@/components/atoms/Input';
import { Modal } from '@/components/atoms/Modal';
import { DenseTable, type DenseTableColumn } from '@/components/molecules/DenseTable';
import { FormField } from '@/components/molecules/FormField';
import { PageHeader } from '@/components/molecules/PageHeader';
import { PaginationBar } from '@/components/molecules/PaginationBar';
import { TableToolbar } from '@/components/molecules/TableToolbar';
import { createBundlingRule, fetchBundlingRules, type BundlingRuleRow } from '@/api/settings';
import { useApiClient } from '@/hooks/useApiClient';
import { useCsvExport, type CsvColumn } from '@/hooks/use-csv-export';
import { usePagination } from '@/hooks/use-pagination';
import { cn } from '@/lib/cn';
import { CARD } from '@/lib/tokens';

/**
 * BundlingRulesPage - route `/settings/bundling` (khusus admin).
 *
 * REAL (F3A.CLOSE / B24): `GET` + `POST /api/v1/settings/bundling/`.
 * Model backend = `{name, size_matrix:{ukuran: qty}, bundle_size_default}` —
 * BUKAN lagi per-baris `sku_variant/size/qty_per_bundle` (dummy lama).
 */

const QUERY_KEY = ['settings-bundling-rules'];
const EMPTY_RULES: BundlingRuleRow[] = [];

function sizeMatrixText(matrix: Record<string, number>): string {
  const entries = Object.entries(matrix);
  if (entries.length === 0) return '—';

  return entries.map(([size, qty]) => `${size}:${qty}`).join(', ');
}

/** PURE — teks `S=10, M=12` → `{S: 10, M: 12}`; `null` kalau format salah. */
function parseSizeMatrix(text: string): Record<string, number> | null {
  const trimmed = text.trim();
  if (trimmed.length === 0) return {};

  const matrix: Record<string, number> = {};
  for (const chunk of trimmed.split(',')) {
    const [rawKey, rawValue] = chunk.split(/[=:]/);
    const key = (rawKey ?? '').trim();
    const value = Number((rawValue ?? '').trim());

    if (key.length === 0 || !Number.isFinite(value) || value < 0) return null;
    matrix[key] = value;
  }

  return matrix;
}

const COLUMNS: DenseTableColumn<BundlingRuleRow>[] = [
  { key: 'name', label: 'Nama' },
  {
    key: 'size_matrix',
    label: 'Matriks Ukuran',
    render: (row) => <span className="font-mono text-xs">{sizeMatrixText(row.size_matrix)}</span>,
  },
  {
    key: 'bundle_size_default',
    label: 'Default / Bundle',
    align: 'right',
    render: (row) => `${row.bundle_size_default} pcs`,
  },
  {
    key: 'is_active',
    label: 'Status',
    render: (row) => (row.is_active ? 'Aktif' : 'Nonaktif'),
  },
];

const CSV_COLUMNS: CsvColumn<BundlingRuleRow>[] = [
  { key: 'name', label: 'name' },
  { key: 'bundle_size_default', label: 'bundle_size_default' },
];

export function BundlingRulesPage() {
  const client = useApiClient();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState('');
  const [matrixText, setMatrixText] = useState('');
  const [defaultText, setDefaultText] = useState('12');
  const [errorText, setErrorText] = useState<string | null>(null);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: QUERY_KEY,
    queryFn: () => fetchBundlingRules(client),
    staleTime: 30_000,
  });

  const create = useMutation({
    mutationFn: (payload: { name: string; size_matrix: Record<string, number>; bundle_size_default: number }) =>
      createBundlingRule(client, payload),
    onSuccess: () => {
      setFormOpen(false);
      setName('');
      setMatrixText('');
      setDefaultText('12');
      setErrorText(null);
      void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    },
    onError: () => {
      setErrorText('Gagal menyimpan aturan bundling.');
    },
  });

  const { exportCsv } = useCsvExport();
  const rules = data?.rows ?? EMPTY_RULES;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (needle.length === 0) return rules;

    return rules.filter((rule) => rule.name.toLowerCase().includes(needle));
  }, [rules, search]);

  const pagination = usePagination(filtered, { pageSize: 20 });

  function handleSearch(value: string): void {
    setSearch(value);
    pagination.reset();
  }

  function handleSubmit(): void {
    const matrix = parseSizeMatrix(matrixText);
    const bundleSize = Number(defaultText);

    if (name.trim().length === 0) {
      setErrorText('Nama wajib diisi.');
      return;
    }
    if (matrix === null) {
      setErrorText('Matriks ukuran harus format "S=10, M=12".');
      return;
    }
    if (!Number.isInteger(bundleSize) || bundleSize < 0) {
      setErrorText('Default per bundle harus angka >= 0.');
      return;
    }

    setErrorText(null);
    create.mutate({
      name: name.trim(),
      size_matrix: matrix,
      bundle_size_default: bundleSize,
    });
  }

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <PageHeader
        title="Bundling Rules"
        subtitle="Aturan pembentukan bundle (matriks ukuran + qty default)"
        breadcrumb={[{ label: 'Settings' }, { label: 'Bundling' }]}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={RefreshCw}
              loading={isFetching}
              onClick={() => {
                void refetch();
              }}
            >
              Refresh
            </Button>
            <Button variant="primary" size="sm" icon={Plus} onClick={() => setFormOpen(true)}>
              Tambah Rule
            </Button>
          </>
        }
      />

      <TableToolbar
        search={search}
        onSearchChange={handleSearch}
        searchLabel="Cari rule"
        searchPlaceholder="Cari nama rule"
        exportDisabled={filtered.length === 0}
        onExport={() => exportCsv(filtered, 'settings-bundling-rules.csv', CSV_COLUMNS)}
        refreshing={isFetching}
        onRefresh={() => {
          void refetch();
        }}
      />

      <section className={cn(CARD, 'p-0')}>
        <DenseTable
          columns={COLUMNS}
          rows={pagination.pageRows}
          loading={isLoading}
          error={error === null ? null : 'Gagal memuat aturan bundling.'}
          onRetry={() => {
            void refetch();
          }}
          emptyMessage="Belum ada aturan bundling."
        />
      </section>

      <PaginationBar
        page={pagination.page}
        totalPages={pagination.totalPages}
        rangeStart={pagination.rangeStart}
        rangeEnd={pagination.rangeEnd}
        total={pagination.total}
        canPrev={pagination.canPrev}
        canNext={pagination.canNext}
        onPrev={pagination.goPrev}
        onNext={pagination.goNext}
      />

      <Modal
        open={formOpen}
        onOpenChange={setFormOpen}
        title="Tambah Rule"
        description="Matriks ukuran opsional; kosongkan bila hanya memakai default per bundle."
        footer={
          <>
            <Button variant="secondary" onClick={() => setFormOpen(false)}>
              Batal
            </Button>
            <Button variant="primary" loading={create.isPending} onClick={handleSubmit}>
              Tambah
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <FormField label="Nama" htmlFor="rule-name" required>
            <Input
              id="rule-name"
              value={name}
              placeholder="mis. Kaos Basic"
              onChange={(event) => setName(event.target.value)}
            />
          </FormField>

          <FormField label="Matriks Ukuran" htmlFor="rule-matrix">
            <Input
              id="rule-matrix"
              value={matrixText}
              placeholder="mis. S=10, M=12, L=12"
              onChange={(event) => setMatrixText(event.target.value)}
            />
          </FormField>

          <FormField label="Default per Bundle" htmlFor="rule-default" required>
            <Input
              id="rule-default"
              type="number"
              min={0}
              value={defaultText}
              onChange={(event) => setDefaultText(event.target.value)}
            />
          </FormField>

          {errorText === null ? null : (
            <p role="alert" className="text-xs font-medium text-accent-coral">
              {errorText}
            </p>
          )}
        </div>
      </Modal>
    </div>
  );
}
