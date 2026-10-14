import { describe, expect, it } from 'vitest';
import { isReal, MODE, pickAdapter } from '@/api/_adapter';

/**
 * F2 — peta MODE (satu-satunya saklar dummy/real).
 * Daftar di bawah SENGAJA lengkap (bukan subset) supaya key yang tidak sengaja
 * ter-flip / terhapus langsung ketahuan.
 */

const REAL_KEYS = [
  'aiChat',
  'audit',
  // H5.5 — Audit Log Viewer (`/settings/audit/`: daftar + filter + detail; READ-ONLY).
  // Key BARU supaya tidak bentrok `audit` (F9 audit produk tanpa `odoo_id`).
  'auditLogs',
  'auth',
  'bufferQueue',
  'bundles',
  'chatter',
  'dashboard',
  'devices',
  'executiveDashboard',
  'export',
  'hitl',
  'inventoryOperations',
  'inventoryProducts',
  'inventoryReporting',
  // H2.5 — LOG inventory adjustment MES → Odoo (`/inventory/adjust*`, `/inventory/stock-qty/`).
  'inventoryAdjustments',
  // H2.6 — LOG stock transfer MES → Odoo (`/inventory/transfer*`, picking internal).
  'stockTransfers',
  'invoiceQueue',
  // H1.1 — CRUD master produk (`/master/products/`, MES = source of truth master).
  'masterProducts',
  // H1.2 — CRUD master UoM (`/master/uoms/`, H1.2).
  'masterUoms',
  // H1.3 — CRUD master gudang (`/master/warehouses/`, H1.3).
  'masterWarehouses',
  // H1.4 — CRUD master lokasi (`/master/locations/`, H1.4).
  'masterLocations',
  // H1.5 — CRUD master BOM (`/master/boms/`, H1.5).
  'masterBoms',
  // H1.6 — CRUD master partner (`/master/partners/`, H1.6).
  'masterPartners',
  // H1.7 — CRUD master work center (`/master/work-centers/`, H1.7; MES-only).
  'masterWorkCenters',
  // H1.8 — CRUD master production line (`/master/production-lines/`, H1.8; MES-only).
  'masterProductionLines',
  // H1.9 — CRUD master routing DAG (`/settings/routing/` B22 di-extend; MES-only).
  'masterRoutings',
  // Sprint C — Number Sequence (`/settings/sequences/`; MES-only).
  'masterSequences',
  // H5.2 — Currency (`/settings/currencies/`: CRUD + default MES; MES-only).
  'masterCurrencies',
  // H5.1 — Company Profile (`/settings/company/`: GET/PUT singleton; MES-only).
  'company',
  // H5.6 — Integration Config (`/settings/integration/`: GET/PUT + test-connection).
  'integrationConfig',
  // H5.8 — WA Gateway Config (`/settings/wa/`: GET/PUT + test-connection gateway).
  'waConfig',
  // H3.6 — CRUD master Tax (`/master/taxes/`: tarif/jenis + pajak default MES).
  'masterTaxes',
  // H3.1 — CRUD Customer Invoice MES (`/finance/customer-invoices/`).
  'customerInvoices',
  // H3.2 — CRUD Vendor Bill MES (`/finance/vendor-bills/`).
  'vendorBills',
  // H3.3 — CRUD Payment MES (`/finance/payments/`: satu model dua arah
  // INBOUND/OUTBOUND + draft `account.payment`; rekonsiliasi tetap di Odoo).
  'payments',
  // H3.4 — Journal Entry manual MES (`/finance/journal-entries*`; double-entry +
  // draft `account.move` `move_type='entry'`) + master Account/Journal read-only
  // (`/master/accounts*`, `/master/journals*`) untuk dropdown form-nya.
  'journalEntries',
  'masterAccounts',
  'masterJournals',
  'salesOrders',
  'purchaseOrdersCrud',
  // H2.3 — Work Order MES (F13 `workOrders` tetap terpisah & tidak diubah).
  'workOrdersCrud',
  // H2.4 — Bundle MES (F13 `bundles` tetap terpisah & tidak diubah).
  'bundlesCrud',
  'metadata',
  'orderLines',
  'print',
  // H5.7 — Printer Config (`/settings/printer/`: GET/PUT + test-connection printer).
  'printerConfig',
  // H5.4 — Permission Matrix (`/settings/permissions/`: GET matrix + PUT bulk per role).
  'permissionMatrix',
  'purchaseOrders',
  'purchaseReporting',
  'purchaseVendors',
  'qcAql',
  'qcLog',
  'qcRework',
  'qcRows',
  'qcSubmit',
  'readiness',
  'reconciliation',
  'reportCogs',
  'reportPnl',
  'reportProduction',
  'reportPurchases',
  'reportSales',
  'reportStock',
  'reportsLeadTime',
  'reportsLeadTimeBundles',
  'reportsLineEfficiency',
  'reportsLineEfficiencyByWc',
  'reportsOnTimeDeliveryOrders',
  'reportsOTD',
  'reportsWIP',
  'reportsWipByWc',
  'routing',
  'settingsBundling',
  'settingsDevices',
  'settingsLineAllocation',
  'settingsRoles',
  'settingsRouting',
  'settingsUsers',
  'syncMaster',
  'syncMonitor',
  'syncOdoo',
  'syncScrap',
  'wa',
  'workOrders',
].sort();

/** F5.4.CLOSE + F6.2 + H1.1–H4.8 + H5.1–H5.8 — TIDAK ADA key dummy (semua 85 resource real). */
const DUMMY_KEYS: string[] = [];

describe('F2 — MODE map', () => {
  it('key real = 85 (… + H5.6 Integration + H5.5 Audit Log + H5.7 Printer + H5.4 Permissions)', () => {
    const real = Object.entries(MODE)
      .filter(([, mode]) => mode === 'real')
      .map(([key]) => key)
      .sort();

    expect(real).toEqual(REAL_KEYS);
    expect(real).toHaveLength(85);
  });

  it('key dummy = 0 (F5.4.CLOSE — zero dummy, F6.2 tetap nol)', () => {
    const dummy = Object.entries(MODE)
      .filter(([, mode]) => mode === 'dummy')
      .map(([key]) => key)
      .sort();

    expect(dummy).toEqual(DUMMY_KEYS);
    expect(dummy).toHaveLength(0);
  });

  it('5 adapter baru F2 semuanya real', () => {
    for (const key of ['qcRows', 'syncOdoo', 'syncMaster', 'syncScrap', 'readiness']) {
      expect(MODE[key], key).toBe('real');
    }
  });

  it('2.5 master / 2.6 sales / 2.8 finance TIDAK dibuat (tidak ada endpoint)', () => {
    for (const key of ['master', 'sales', 'finance']) {
      expect(MODE[key], key).toBeUndefined();
    }
  });

  it('purchase & reports REAL (F2C.2 + F3A.CLOSE)', () => {
    for (const key of [
      'purchaseOrders',
      'purchaseVendors',
      'purchaseReporting',
      'reportsWIP',
      'reportsLineEfficiency',
      'reportsWipByWc',
    ]) {
      expect(MODE[key], key).toBe('real');
    }
  });

  it('key F5.4.CLOSE (B26–B30) semuanya real', () => {
    for (const key of [
      'settingsUsers',
      'settingsRoles',
      'settingsDevices',
      'hitl',
      'inventoryReporting',
    ]) {
      expect(MODE[key], key).toBe('real');
    }
  });

  it('key F6.2 (auth hybrid) real', () => {
    expect(MODE['auth']).toBe('real');
    expect(isReal('auth')).toBe(true);
  });

  it('jumlah key & nilai hanya real/dummy', () => {
    // 71 key = 47 resource lama (F5.4.CLOSE: zero dummy) + 10 master H1.1–H1.9/Sprint C
    // (`masterProducts`, `masterUoms`, `masterWarehouses`, `masterLocations`,
    // `masterBoms`, `masterPartners`, `masterWorkCenters`, `masterProductionLines`,
    // `masterRoutings`, `masterSequences`) + `salesOrders` (H2.1) +
    // `purchaseOrdersCrud` (H2.2 — B10 `purchaseOrders` tetap terpisah) +
    // `workOrdersCrud` (H2.3 — F13 `workOrders` tetap terpisah) +
    // `bundlesCrud` (H2.4 — F13 `bundles` tetap terpisah) +
    // `inventoryAdjustments` (H2.5 — B7/B8/B30 `inventory*` tetap terpisah) +
    // `stockTransfers` (H2.6 — endpoint `/inventory/transfer*` baru) +
    // `masterTaxes` (H3.6 — CRUD `/master/taxes*` + pajak default MES) +
    // `customerInvoices` (H3.1 — CRUD `/finance/customer-invoices*`) +
    // `vendorBills` (H3.2 — CRUD `/finance/vendor-bills*`; B10 & I6 tetap terpisah) +
    // `payments` (H3.3 — CRUD `/finance/payments*`; F15 `/finance/invoices` tetap) +
    // `journalEntries`/`masterAccounts`/`masterJournals` (H3.4 — CRUD
    // `/finance/journal-entries*` + master Account/Journal read-only untuk dropdown) +
    // `reportSales` (H4.1 — GET `/reports/sales/`, laporan penjualan read-only) +
    // `reportPurchases` (H4.2 — GET `/reports/purchases/`, laporan pembelian read-only) +
    // `reportStock` (H4.3 — GET `/reports/stock/`, laporan stok snapshot Odoo via I7) +
    // `reportCogs` (H4.4 — GET `/reports/cogs/`, laporan HPP/laba kotor) +
    // `reportPnl` (H4.5 — GET `/reports/pnl/`, laporan laba-rugi) +
    // `reportProduction` (H4.6 — GET `/reports/production/`, laporan produksi) +
    // `executiveDashboard` (H4.7 — GET `/dashboard/executive/`) +
    // `export` (H4.8 — POST `/export/<report>/`, berkas xlsx/pdf) +
    // `masterCurrencies` (H5.2 — CRUD `/settings/currencies*` + mata uang default MES) +
    // `company` (H5.1 — GET/PUT singleton `/settings/company/`) +
    // `integrationConfig` (H5.6 — profil config `/settings/integration/` + test-connection) +
    // `waConfig` (H5.8 — profil gateway `/settings/wa/` + test-connection gateway) +
    // `auditLogs` (H5.5 — daftar/filter/detail `/settings/audit/`, READ-ONLY) +
    // `printerConfig` (H5.7 — profil printer `/settings/printer/` + uji printer) +
    // `permissionMatrix` (H5.4 — matrix izin `/settings/permissions/` + PUT bulk per role).
    expect(Object.keys(MODE)).toHaveLength(85);
    expect([...new Set(Object.values(MODE))].sort()).toEqual(['real']);
  });
});

describe('F2 — pickAdapter / isReal', () => {
  it('isReal mengikuti MODE', () => {
    expect(isReal('qcRows')).toBe(true);
    expect(isReal('syncScrap')).toBe(true);
    expect(isReal('readiness')).toBe(true);
    expect(isReal('qcAql')).toBe(true);
    expect(isReal('tidak-ada')).toBe(false);
  });

  it('pickAdapter memilih implementasi sesuai MODE', () => {
    const realImpl = { tag: 'real' };
    const dummyImpl = { tag: 'dummy' };

    expect(pickAdapter('qcRows', realImpl, dummyImpl)).toBe(realImpl);
    expect(pickAdapter('qcAql', realImpl, dummyImpl)).toBe(realImpl);
    expect(pickAdapter('hitl', realImpl, dummyImpl)).toBe(realImpl);
    expect(pickAdapter('key-tak-dikenal', realImpl, dummyImpl)).toBe(dummyImpl);
  });
});
