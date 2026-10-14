import { describe, expect, it } from 'vitest';
import {
  buildExportBody,
  buildExportPath,
  exportReport,
  EXPORT_FORMAT_DEFAULT,
  EXPORT_FORMAT_LABELS,
  EXPORT_FORMAT_VALUES,
  EXPORT_PATH_PREFIX,
  EXPORT_REPORT_LABELS,
} from '@/api/export';
import { MODE } from '@/api/_adapter';
import type { ApiBlobResponse, ApiClient } from '@/integrations/api-client';

/** H4.8 - export laporan (POST /export/<report>/): path, body, blob, error. */

function blobClient(response: ApiBlobResponse, paths: string[], bodies: unknown[]): ApiClient {
  return {
    requestBlob: async (path: string, body: unknown) => {
      paths.push(path);
      bodies.push(body);
      return response;
    },
  } as unknown as ApiClient;
}

describe('H4.8 - exportReport (konstanta & MODE)', () => {
  it('MODE export = real; 7 laporan + 2 format + label UI', () => {
    expect(MODE['export']).toBe('real');
    expect(EXPORT_PATH_PREFIX).toBe('/export/');
    expect(EXPORT_FORMAT_DEFAULT).toBe('xlsx');
    expect(EXPORT_FORMAT_VALUES).toEqual(['xlsx', 'pdf']);
    expect(EXPORT_FORMAT_LABELS['pdf']).toBe('PDF (.pdf)');
    expect(Object.keys(EXPORT_REPORT_LABELS)).toEqual([
      'sales',
      'purchases',
      'stock',
      'cogs',
      'pnl',
      'production',
      'executive',
    ]);
  });

  it('buildExportPath mengarah ke endpoint backend H4.8', () => {
    expect(buildExportPath('sales')).toBe('/export/sales/');
    expect(buildExportPath('executive')).toBe('/export/executive/');
  });
});

describe('H4.8 - buildExportBody', () => {
  it('mengirim format + filter terisi (camelCase → param H4.x)', () => {
    expect(
      buildExportBody('pdf', {
        period: '2026-10',
        groupBy: 'product',
        customerId: 7,
        onlyNonzero: true,
      }),
    ).toEqual({
      format: 'pdf',
      period: '2026-10',
      group_by: 'product',
      customer_id: 7,
      only_nonzero: 1,
    });
  });

  it('melewati nilai kosong/null dan memetakan boolean ke 1/0', () => {
    expect(
      buildExportBody('xlsx', {
        period: null,
        dateFrom: '',
        onlyNonzero: false,
        workCenterId: 3,
      }),
    ).toEqual({ format: 'xlsx', only_nonzero: 0, work_center_id: 3 });
    expect(buildExportBody('viral' as never)).toEqual({ format: 'xlsx' });
  });
});

describe('H4.8 - exportReport', () => {
  it('sukses → blob + filename dari Content-Disposition', async () => {
    const paths: string[] = [];
    const bodies: unknown[] = [];
    const blob = new Blob(['xlsx']);
    const client = blobClient(
      {
        ok: true,
        status: 200,
        blob,
        filename: 'sales-2026-10.xlsx',
        contentType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      },
      paths,
      bodies,
    );

    const file = await exportReport(client, 'sales', 'xlsx', { period: '2026-10' });

    expect(paths).toEqual(['/export/sales/']);
    expect(bodies).toEqual([{ format: 'xlsx', period: '2026-10' }]);
    expect(file.blob).toBe(blob);
    expect(file.filename).toBe('sales-2026-10.xlsx');
  });

  it('filename absen → fallback `<report>.<ext>`', async () => {
    const client = blobClient({ ok: true, status: 200, blob: new Blob(['x']) }, [], []);

    const file = await exportReport(client, 'production', 'pdf');

    expect(file.filename).toBe('production.pdf');
  });

  it('gagal (403/400) → melempar pesan backend', async () => {
    const client = {
      requestBlob: async () => ({
        ok: false,
        status: 403,
        error: { kind: 'http_error', message: 'Forbidden' },
      }),
    } as unknown as ApiClient;

    await expect(exportReport(client, 'sales')).rejects.toThrow('Forbidden');
  });
});
