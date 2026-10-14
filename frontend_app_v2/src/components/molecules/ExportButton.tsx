import { useState } from 'react';
import { Download } from 'lucide-react';
import { Button } from '@/components/atoms/Button';
import { Modal } from '@/components/atoms/Modal';
import { Select, type SelectOption } from '@/components/atoms/Select';
import {
  exportReport,
  EXPORT_FORMAT_DEFAULT,
  EXPORT_FORMAT_LABELS,
  EXPORT_FORMAT_VALUES,
  EXPORT_REPORT_LABELS,
} from '@/api/export';
import { useApiClient } from '@/hooks/useApiClient';
import { downloadBlob } from '@/lib/download';
import type { ExportFilters, ExportFormat, ExportReport } from '@/types/export';

/**
 * ExportButton - tombol unduh laporan H4 sebagai Excel/PDF (H4.8).
 *
 * Satu komponen untuk **7 laporan** (DRY): tombol membuka modal pilih format
 * (`xlsx` default / `pdf`), lalu `POST /api/v1/export/<report>/` dikirim lewat
 * ApiClient (`requestBlob` — satu-satunya pintu HTTP) dan hasilnya diunduh
 * dengan `downloadBlob` (`<a download>` sementara, BUKAN `<a href>` ke endpoint
 * karena endpoint-nya POST + butuh cookie sesi).
 *
 * `filters` = filter yang SEDANG aktif di halaman (period/group_by/customer/…),
 * jadi berkas berisi angka yang sama dengan yang dilihat user. Gagal (format
 * tidak didukung/403/500) → pesan backend ditampilkan di modal; tombol tetap
 * bisa dicoba lagi (tanpa retry otomatis — keputusan H4.8).
 */

/** Opsi format untuk dropdown di modal (nilai = kontrak backend H4.8). */
const FORMAT_OPTIONS: SelectOption[] = EXPORT_FORMAT_VALUES.map((value) => ({
  value,
  label: EXPORT_FORMAT_LABELS[value],
}));

interface ExportButtonProps {
  /** Laporan yang diexport (7 modul FASE H4). */
  report: ExportReport;
  /** Filter aktif halaman (hanya key terisi yang dikirim). */
  filters?: ExportFilters;
  /** Label tombol (default `Export`). */
  label?: string;
  size?: 'sm' | 'md';
}

export function ExportButton({
  report,
  filters = {},
  label = 'Export',
  size = 'sm',
}: ExportButtonProps) {
  const client = useApiClient();
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>(EXPORT_FORMAT_DEFAULT);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const title = EXPORT_REPORT_LABELS[report];

  async function submit(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const file = await exportReport(client, report, format, filters);
      downloadBlob(file.blob, file.filename);
      setOpen(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Export gagal.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button
        variant="secondary"
        size={size}
        icon={Download}
        aria-label={`Export ${title}`}
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        {label}
      </Button>

      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!busy) setOpen(next);
        }}
        title={`Export ${title}`}
        description="Berkas mengikuti filter yang sedang aktif di halaman ini."
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              disabled={busy}
              onClick={() => {
                setOpen(false);
              }}
            >
              Batal
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={Download}
              loading={busy}
              onClick={() => {
                void submit();
              }}
            >
              Unduh
            </Button>
          </>
        }
      >
        <Select
          label="Format berkas"
          options={FORMAT_OPTIONS}
          value={format}
          onChange={(event) => {
            setFormat(event.target.value as ExportFormat);
          }}
        />

        <p className="mt-2 text-xs text-muted-foreground">
          Excel: ringkasan KPI + data (dashboard eksekutif: satu sheet per section).
          PDF: ringkasan KPI + tabel data.
        </p>

        {error === null ? null : (
          <p role="alert" className="mt-2 text-sm font-medium text-accent-coral">
            {error}
          </p>
        )}
      </Modal>
    </>
  );
}
