import { lazy, Suspense } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from '@/app/layouts/AppShell';
import { AppIndexRedirect } from '@/app/AppIndexRedirect';
import { RoleGuardFallback, RoleRoute } from '@/app/RoleRoute';
import { RootRoute } from '@/app/RootRoute';
import { Spinner } from '@/components/atoms/Spinner';
import { AuthGuard } from '@/components/organisms/AuthGuard';
import { RouteErrorBoundary } from '@/components/organisms/RouteErrorBoundary';
import { AuthProvider } from '@/hooks/useAuth';
import type { Role } from '@/app/useRole';
// Dashboard jarang di-lazy: ini halaman default setelah login (hindari loading ekstra).
// FIX ROUTE: kini diimpor `app/RootRoute.tsx` (route `/` memakai RootRoute).

/**
 * Fase 25 - LAZY per route.
 *
 * Semua modul halaman memakai NAMED export, jadi hasil `import()` dipetakan eksplisit ke
 * `{ default }` (tanpa cast `as`, tanpa default export baru di halaman Fase 17-23).
 * Efeknya bundle terpecah per halaman sehingga warning "chunk > 500 kB" hilang.
 */
const BundleDetailPage = lazy(() =>
  import('@/pages/bundles/BundleDetailPage').then((module) => ({
    default: module.BundleDetailPage,
  })),
);

const BundleWorkshopPage = lazy(() =>
  import('@/pages/bundles/BundleWorkshopPage').then((module) => ({
    default: module.BundleWorkshopPage,
  })),
);

const BundleListPage = lazy(() =>
  import('@/pages/bundles/BundleListPage').then((module) => ({
    default: module.BundleListPage,
  })),
);

const WorkOrderListPage = lazy(() =>
  import('@/pages/work-orders/WorkOrderListPage').then((module) => ({
    default: module.WorkOrderListPage,
  })),
);

// H2.3 — Work Order MES (form + detail CRUD/split). List memakai halaman F13
// (`WorkOrderListPage`) agar tidak ada daftar kedua yang harus dijaga sinkron.
const WorkOrderFormPage = lazy(() =>
  import('@/pages/production/WorkOrderFormPage').then((module) => ({
    default: module.WorkOrderFormPage,
  })),
);

const WorkOrderCrudDetailPage = lazy(() =>
  import('@/pages/production/WorkOrderDetailPage').then((module) => ({
    default: module.WorkOrderDetailPage,
  })),
);

// H2.4 — Bundle CRUD (form create + halaman kelola: edit/split/merge/delete).
// Detail operator yang sudah ada (`/production/bundles/:id`) TIDAK diubah.
const BundleFormPage = lazy(() =>
  import('@/pages/production/BundleFormPage').then((module) => ({
    default: module.BundleFormPage,
  })),
);

const SupervisorDashboardPage = lazy(() =>
  import('@/pages/dashboard/SupervisorDashboardPage').then((module) => ({
    default: module.SupervisorDashboardPage,
  })),
);

const ProductionBundleDetailPage = lazy(() =>
  import('@/pages/production/BundleDetailPage').then((module) => ({
    default: module.ProductionBundleDetailPage,
  })),
);

const BufferQueuePage = lazy(() =>
  import('@/pages/production/BufferQueuePage').then((module) => ({
    default: module.BufferQueuePage,
  })),
);

// F8 — kesiapan material per Order (`:orderId` = id ORDER, bukan OrderLine).
const MaterialReadinessPage = lazy(() =>
  import('@/pages/production/MaterialReadinessPage').then((module) => ({
    default: module.MaterialReadinessPage,
  })),
);

// F11 — form scrap bundle (`:id` = id bundle; aksi nyata BUNDLE_SCRAP, §4.4).
const ScrapFormPage = lazy(() =>
  import('@/pages/production/ScrapFormPage').then((module) => ({
    default: module.ScrapFormPage,
  })),
);

const QCPage = lazy(() =>
  import('@/pages/production/QCPage').then((module) => ({ default: module.QCPage })),
);

const RoutingVisualizationPage = lazy(() =>
  import('@/pages/production/RoutingVisualizationPage').then((module) => ({
    default: module.RoutingVisualizationPage,
  })),
);

const ScanPage = lazy(() =>
  import('@/pages/production/ScanPage').then((module) => ({ default: module.ScanPage })),
);

const ShopFloorPage = lazy(() =>
  import('@/pages/production/ShopFloorPage').then((module) => ({ default: module.ShopFloorPage })),
);

const AQLDashboardPage = lazy(() =>
  import('@/pages/quality/AQLDashboardPage').then((module) => ({
    default: module.AQLDashboardPage,
  })),
);

const DefectLogPage = lazy(() =>
  import('@/pages/quality/DefectLogPage').then((module) => ({ default: module.DefectLogPage })),
);

const ReworkTrackingPage = lazy(() =>
  import('@/pages/quality/ReworkTrackingPage').then((module) => ({
    default: module.ReworkTrackingPage,
  })),
);

const ConfigurationPage = lazy(() =>
  import('@/pages/inventory/ConfigurationPage').then((module) => ({
    default: module.ConfigurationPage,
  })),
);

const OperationsPage = lazy(() =>
  import('@/pages/inventory/OperationsPage').then((module) => ({
    default: module.OperationsPage,
  })),
);

const ProductsPage = lazy(() =>
  import('@/pages/inventory/ProductsPage').then((module) => ({ default: module.ProductsPage })),
);

// H1.1 — master produk (MES = source of truth master; app Inventory).
const MasterProductsPage = lazy(() =>
  import('@/pages/master/ProductsPage').then((module) => ({
    default: module.ProductsPage,
  })),
);

const MasterProductFormPage = lazy(() =>
  import('@/pages/master/ProductFormPage').then((module) => ({
    default: module.ProductFormPage,
  })),
);

const MasterProductDetailPage = lazy(() =>
  import('@/pages/master/ProductDetailPage').then((module) => ({
    default: module.ProductDetailPage,
  })),
);

// H3.5 — riwayat harga produk (audit trail `master.update_price`, read-only).
const MasterProductPriceHistoryPage = lazy(() =>
  import('@/pages/master/ProductPriceHistoryPage').then((module) => ({
    default: module.ProductPriceHistoryPage,
  })),
);

// H1.2 — master UoM (satuan; app Inventory).
const MasterUomsPage = lazy(() =>
  import('@/pages/master/UomsPage').then((module) => ({
    default: module.UomsPage,
  })),
);

const MasterUomFormPage = lazy(() =>
  import('@/pages/master/UomFormPage').then((module) => ({
    default: module.UomFormPage,
  })),
);

const MasterUomDetailPage = lazy(() =>
  import('@/pages/master/UomDetailPage').then((module) => ({
    default: module.UomDetailPage,
  })),
);

// H3.6 — master Pajak (tax; app Inventory). List + form + detail (Set Default).
const MasterTaxesPage = lazy(() =>
  import('@/pages/master/TaxesPage').then((module) => ({
    default: module.TaxesPage,
  })),
);

const MasterTaxFormPage = lazy(() =>
  import('@/pages/master/TaxFormPage').then((module) => ({
    default: module.TaxFormPage,
  })),
);

const MasterTaxDetailPage = lazy(() =>
  import('@/pages/master/TaxDetailPage').then((module) => ({
    default: module.TaxDetailPage,
  })),
);

// H1.3 — master gudang (warehouse; app Inventory).
const MasterWarehousesPage = lazy(() =>
  import('@/pages/master/WarehousesPage').then((module) => ({
    default: module.WarehousesPage,
  })),
);

const MasterWarehouseFormPage = lazy(() =>
  import('@/pages/master/WarehouseFormPage').then((module) => ({
    default: module.WarehouseFormPage,
  })),
);

const MasterWarehouseDetailPage = lazy(() =>
  import('@/pages/master/WarehouseDetailPage').then((module) => ({
    default: module.WarehouseDetailPage,
  })),
);

// H1.4 — master lokasi (location; app Inventory, hierarki induk + gudang + usage).
const MasterLocationsPage = lazy(() =>
  import('@/pages/master/LocationsPage').then((module) => ({
    default: module.LocationsPage,
  })),
);

const MasterLocationFormPage = lazy(() =>
  import('@/pages/master/LocationFormPage').then((module) => ({
    default: module.LocationFormPage,
  })),
);

const MasterLocationDetailPage = lazy(() =>
  import('@/pages/master/LocationDetailPage').then((module) => ({
    default: module.LocationDetailPage,
  })),
);

// H1.5 — master BOM (header + komponen inline; app Inventory).
const MasterBomsPage = lazy(() =>
  import('@/pages/master/BomsPage').then((module) => ({
    default: module.BomsPage,
  })),
);

const MasterBomFormPage = lazy(() =>
  import('@/pages/master/BomFormPage').then((module) => ({
    default: module.BomFormPage,
  })),
);

const MasterBomDetailPage = lazy(() =>
  import('@/pages/master/BomDetailPage').then((module) => ({
    default: module.BomDetailPage,
  })),
);

// H1.6 — master partner (customer + supplier; app Inventory).
const MasterPartnersPage = lazy(() =>
  import('@/pages/master/PartnersPage').then((module) => ({
    default: module.PartnersPage,
  })),
);

const MasterPartnerFormPage = lazy(() =>
  import('@/pages/master/PartnerFormPage').then((module) => ({
    default: module.PartnerFormPage,
  })),
);

const MasterPartnerDetailPage = lazy(() =>
  import('@/pages/master/PartnerDetailPage').then((module) => ({
    default: module.PartnerDetailPage,
  })),
);

// H1.7 — master work center (MES-only; app Inventory).
const MasterWorkCentersPage = lazy(() =>
  import('@/pages/master/WorkCentersPage').then((module) => ({
    default: module.WorkCentersPage,
  })),
);

const MasterWorkCenterFormPage = lazy(() =>
  import('@/pages/master/WorkCenterFormPage').then((module) => ({
    default: module.WorkCenterFormPage,
  })),
);

const MasterWorkCenterDetailPage = lazy(() =>
  import('@/pages/master/WorkCenterDetailPage').then((module) => ({
    default: module.WorkCenterDetailPage,
  })),
);

// H1.8 — master production line (MES-only; app Inventory).
const MasterProductionLinesPage = lazy(() =>
  import('@/pages/master/ProductionLinesPage').then((module) => ({
    default: module.ProductionLinesPage,
  })),
);

const MasterProductionLineFormPage = lazy(() =>
  import('@/pages/master/ProductionLineFormPage').then((module) => ({
    default: module.ProductionLineFormPage,
  })),
);

const MasterProductionLineDetailPage = lazy(() =>
  import('@/pages/master/ProductionLineDetailPage').then((module) => ({
    default: module.ProductionLineDetailPage,
  })),
);

// H1.9 — master routing DAG (MES-only; app Inventory). Endpoint = B22 yang di-extend
// (`/settings/routing/…`), jadi TIDAK ada endpoint paralel `/master/routings/`.
const MasterRoutingsPage = lazy(() =>
  import('@/pages/master/RoutingsPage').then((module) => ({
    default: module.RoutingsPage,
  })),
);

const MasterRoutingFormPage = lazy(() =>
  import('@/pages/master/RoutingFormPage').then((module) => ({
    default: module.RoutingFormPage,
  })),
);

const MasterRoutingDetailPage = lazy(() =>
  import('@/pages/master/RoutingDetailPage').then((module) => ({
    default: module.RoutingDetailPage,
  })),
);

// H2.1 — Sales Order (transaksi satu arah MES → Odoo; app Sales).
const SalesOrdersPage = lazy(() =>
  import('@/pages/sales/OrdersPage').then((module) => ({ default: module.OrdersPage })),
);

const SalesOrderFormPage = lazy(() =>
  import('@/pages/sales/OrderFormPage').then((module) => ({ default: module.OrderFormPage })),
);

const SalesOrderDetailPage = lazy(() =>
  import('@/pages/sales/OrderDetailPage').then((module) => ({ default: module.OrderDetailPage })),
);

// Sprint C — Number Sequence (penomoran dokumen MES; MES-only, reset per tahun).
const SequencesPage = lazy(() =>
  import('@/pages/settings/SequencesPage').then((module) => ({
    default: module.SequencesPage,
  })),
);

// H5.2 — Currency (mirror `res.currency` Odoo + CRUD MES; MES-only, ledger SKIPPED).
const CurrenciesPage = lazy(() =>
  import('@/pages/settings/CurrenciesPage').then((module) => ({
    default: module.CurrenciesPage,
  })),
);

// H5.1 — Company Profile (greenfield singleton; MES-only, ledger SKIPPED).
const CompanyPage = lazy(() =>
  import('@/pages/settings/CompanyPage').then((module) => ({
    default: module.CompanyPage,
  })),
);

// H5.6 — Integration Config (profil config MES ↔ Odoo; Opsi B: konsumen baca `.env`).
const IntegrationConfigPage = lazy(() =>
  import('@/pages/settings/IntegrationConfigPage').then((module) => ({
    default: module.IntegrationConfigPage,
  })),
);

// H5.8 — WA Gateway (profil gateway WhatsApp; Opsi B: konsumen baca `.env`).
const WAConfigPage = lazy(() =>
  import('@/pages/settings/WAConfigPage').then((module) => ({
    default: module.WAConfigPage,
  })),
);

// H5.5 — Audit Log Viewer (read-only, append-only; ADMIN/OWNER).
const AuditLogPage = lazy(() =>
  import('@/pages/settings/AuditLogPage').then((module) => ({
    default: module.AuditLogPage,
  })),
);

// H5.7 — Printer Config (profil printer thermal; Opsi B: konsumen baca `.env`).
const PrinterConfigPage = lazy(() =>
  import('@/pages/settings/PrinterConfigPage').then((module) => ({
    default: module.PrinterConfigPage,
  })),
);

// H5.4 — Permission Matrix (profil izin; enforcement tetap guard kode).
const PermissionMatrixPage = lazy(() =>
  import('@/pages/settings/PermissionMatrixPage').then((module) => ({
    default: module.PermissionMatrixPage,
  })),
);

const InventoryReportingPage = lazy(() =>
  import('@/pages/inventory/ReportingPage').then((module) => ({
    default: module.InventoryReportingPage,
  })),
);

// H2.5 — Inventory Adjustment (log MES → Odoo): list audit + form + detail/commit.
const InventoryAdjustmentListPage = lazy(() =>
  import('@/pages/inventory/InventoryAdjustmentListPage').then((module) => ({
    default: module.InventoryAdjustmentListPage,
  })),
);

const InventoryAdjustmentFormPage = lazy(() =>
  import('@/pages/inventory/InventoryAdjustmentFormPage').then((module) => ({
    default: module.InventoryAdjustmentFormPage,
  })),
);

const InventoryAdjustmentDetailPage = lazy(() =>
  import('@/pages/inventory/InventoryAdjustmentDetailPage').then((module) => ({
    default: module.InventoryAdjustmentDetailPage,
  })),
);

// H2.6 — Stock Transfer (log MES → Odoo): list audit + form + detail/commit.
const StockTransferListPage = lazy(() =>
  import('@/pages/inventory/StockTransferListPage').then((module) => ({
    default: module.StockTransferListPage,
  })),
);

const StockTransferFormPage = lazy(() =>
  import('@/pages/inventory/StockTransferFormPage').then((module) => ({
    default: module.StockTransferFormPage,
  })),
);

const StockTransferDetailPage = lazy(() =>
  import('@/pages/inventory/StockTransferDetailPage').then((module) => ({
    default: module.StockTransferDetailPage,
  })),
);

const PurchaseOrdersPage = lazy(() =>
  import('@/pages/purchase/PurchaseOrdersPage').then((module) => ({
    default: module.PurchaseOrdersPage,
  })),
);

// H2.2 — Purchase Order MES (transaksi satu arah MES → Odoo; app Purchase).
const PurchaseOrderFormPage = lazy(() =>
  import('@/pages/purchase/PurchaseOrderFormPage').then((module) => ({
    default: module.PurchaseOrderFormPage,
  })),
);

const PurchaseOrderDetailPage = lazy(() =>
  import('@/pages/purchase/PurchaseOrderDetailPage').then((module) => ({
    default: module.PurchaseOrderDetailPage,
  })),
);

const PurchaseReportingPage = lazy(() =>
  import('@/pages/purchase/PurchaseReportingPage').then((module) => ({
    default: module.PurchaseReportingPage,
  })),
);

const VendorsPage = lazy(() =>
  import('@/pages/purchase/VendorsPage').then((module) => ({ default: module.VendorsPage })),
);

const LeadTimePage = lazy(() =>
  import('@/pages/reports/LeadTimePage').then((module) => ({ default: module.LeadTimePage })),
);

const LineEfficiencyPage = lazy(() =>
  import('@/pages/reports/LineEfficiencyPage').then((module) => ({
    default: module.LineEfficiencyPage,
  })),
);

const OnTimeDeliveryPage = lazy(() =>
  import('@/pages/reports/OnTimeDeliveryPage').then((module) => ({
    default: module.OnTimeDeliveryPage,
  })),
);

const WIPPage = lazy(() =>
  import('@/pages/reports/WIPPage').then((module) => ({ default: module.WIPPage })),
);

// H4.1 — laporan penjualan (agregat order/invoice/payment, read-only DB MES).
const SalesReportPage = lazy(() =>
  import('@/pages/reports/SalesReportPage').then((module) => ({
    default: module.SalesReportPage,
  })),
);

// H4.2 — laporan pembelian (agregat PO/bill/payment, read-only DB MES).
const PurchasesReportPage = lazy(() =>
  import('@/pages/reports/PurchasesReportPage').then((module) => ({
    default: module.PurchasesReportPage,
  })),
);

// H4.3 — laporan stok snapshot (Odoo stock.quant via I7, read-only DB MES).
const StockReportPage = lazy(() =>
  import('@/pages/reports/StockReportPage').then((module) => ({
    default: module.StockReportPage,
  })),
);

// H4.4 — laporan HPP/laba kotor (omzet - HPP simplified, read-only DB MES).
const CogsReportPage = lazy(() =>
  import('@/pages/reports/CogsReportPage').then((module) => ({
    default: module.CogsReportPage,
  })),
);

// H4.5 — laporan laba-rugi PnL (revenue - HPP - opex, read-only DB MES).
const PnlReportPage = lazy(() =>
  import('@/pages/reports/PnlReportPage').then((module) => ({
    default: module.PnlReportPage,
  })),
);

// H4.6 — laporan produksi (output/scrap/efisiensi/OTD, read-only DB MES).
const ProductionReportPage = lazy(() =>
  import('@/pages/reports/ProductionReportPage').then((module) => ({
    default: module.ProductionReportPage,
  })),
);

// H4.7 — dashboard eksekutif (orkestrasi H4.1-H4.6 + snapshot stok, read-only DB MES).
const ExecutiveDashboardPage = lazy(() =>
  import('@/pages/dashboard/ExecutiveDashboardPage').then((module) => ({
    default: module.ExecutiveDashboardPage,
  })),
);

// F9/9.3 — laporan rekonsiliasi stok MES vs Odoo (read-only, §6.2).
const ReconciliationReportPage = lazy(() =>
  import('@/pages/reports/ReconciliationReportPage').then((module) => ({
    default: module.ReconciliationReportPage,
  })),
);

const BundlingRulesPage = lazy(() =>
  import('@/pages/settings/BundlingRulesPage').then((module) => ({
    default: module.BundlingRulesPage,
  })),
);

const DeviceProfilesPage = lazy(() =>
  import('@/pages/settings/DeviceProfilesPage').then((module) => ({
    default: module.DeviceProfilesPage,
  })),
);

const LineAllocationPage = lazy(() =>
  import('@/pages/settings/LineAllocationPage').then((module) => ({
    default: module.LineAllocationPage,
  })),
);

const RoutingConfigPage = lazy(() =>
  import('@/pages/settings/RoutingConfigPage').then((module) => ({
    default: module.RoutingConfigPage,
  })),
);

const UserManagementPage = lazy(() =>
  import('@/pages/settings/UserManagementPage').then((module) => ({
    default: module.UserManagementPage,
  })),
);

// F9/9.3 — audit produk tanpa odoo_id (settings, §6.1).
const ProductAuditPage = lazy(() =>
  import('@/pages/settings/ProductAuditPage').then((module) => ({
    default: module.ProductAuditPage,
  })),
);

// F15 — monitoring SyncRecord (settings, Fase 4.4).
const SyncMonitorPage = lazy(() =>
  import('@/pages/settings/SyncMonitorPage').then((module) => ({
    default: module.SyncMonitorPage,
  })),
);

// H3.1 — Customer Invoice MES (model MES + push `account.move` draft).
const CustomerInvoicesPage = lazy(() =>
  import('@/pages/finance/InvoicesPage').then((module) => ({
    default: module.InvoicesPage,
  })),
);

const CustomerInvoiceFormPage = lazy(() =>
  import('@/pages/finance/InvoiceFormPage').then((module) => ({
    default: module.InvoiceFormPage,
  })),
);

const CustomerInvoiceDetailPage = lazy(() =>
  import('@/pages/finance/InvoiceDetailPage').then((module) => ({
    default: module.InvoiceDetailPage,
  })),
);

// H3.2 — Vendor Bill MES (model MES + push `account.move` **in_invoice** draft).
const VendorBillsPage = lazy(() =>
  import('@/pages/finance/VendorBillsPage').then((module) => ({
    default: module.VendorBillsPage,
  })),
);

const VendorBillFormPage = lazy(() =>
  import('@/pages/finance/VendorBillFormPage').then((module) => ({
    default: module.VendorBillFormPage,
  })),
);

const VendorBillDetailPage = lazy(() =>
  import('@/pages/finance/VendorBillDetailPage').then((module) => ({
    default: module.VendorBillDetailPage,
  })),
);

// H3.3 — Payment MES (satu model dua arah + push `account.payment` draft).
const PaymentsPage = lazy(() =>
  import('@/pages/finance/PaymentsPage').then((module) => ({
    default: module.PaymentsPage,
  })),
);

const PaymentFormPage = lazy(() =>
  import('@/pages/finance/PaymentFormPage').then((module) => ({
    default: module.PaymentFormPage,
  })),
);

const PaymentDetailPage = lazy(() =>
  import('@/pages/finance/PaymentDetailPage').then((module) => ({
    default: module.PaymentDetailPage,
  })),
);

// H3.4 — Journal Entry manual MES (double-entry + push `account.move`
// `move_type='entry'` draft; journal `general` saja, posting tetap di Odoo).
const JournalEntriesPage = lazy(() =>
  import('@/pages/finance/JournalEntriesPage').then((module) => ({
    default: module.JournalEntriesPage,
  })),
);

const JournalEntryFormPage = lazy(() =>
  import('@/pages/finance/JournalEntryFormPage').then((module) => ({
    default: module.JournalEntryFormPage,
  })),
);

const JournalEntryDetailPage = lazy(() =>
  import('@/pages/finance/JournalEntryDetailPage').then((module) => ({
    default: module.JournalEntryDetailPage,
  })),
);

// F15 — antrean invoice (finance, Fase 4.4; revive F10).
const InvoiceQueuePage = lazy(() =>
  import('@/pages/finance/InvoiceQueuePage').then((module) => ({
    default: module.InvoiceQueuePage,
  })),
);

const AIChatPage = lazy(() =>
  import('@/pages/ai/AIChatPage').then((module) => ({ default: module.AIChatPage })),
);

// F6.2 — halaman login: PUBLIK, di luar App Shell (full-screen card), tetap lazy.
const LoginPage = lazy(() =>
  import('@/pages/auth/LoginPage').then((module) => ({ default: module.LoginPage })),
);

/** Fallback saat chunk halaman sedang diunduh (React.lazy). */
function PageLoader() {
  return (
    <div className="flex min-h-full items-center justify-center p-8">
      <Spinner size="lg" />
    </div>
  );
}


/**
 * App.tsx - Router akhir (Fase 25): App Shell + SELURUH halaman (Fase 17-24).
 *
 * `AppShell` (Sidebar + TopBar + BottomNav) membungkus `<Suspense>` + `<Routes>`.
 * Semua halaman di-lazy per route kecuali `DashboardPage` (halaman default) sehingga
 * bundle terpecah dan warning "chunk > 500 kB" hilang.
 *
 * Penjagaan role dua lapis (FIX ROUTE — diperbarui):
 *  1. per-halaman: `RoleRoute` (role tak berhak → halaman **"Akses Ditolak"**, bukan
 *     redirect diam-diam);
 *  2. fallback `*`: `RoleGuardFallback` (path milik app yang bukan hak role → "Akses
 *     Ditolak"; path tak dikenal → `NotFoundPage`).
 * Route `*` sengaja TANPA `RoleRoute`; route `/` memakai `RootRoute` (memutuskan dari SESI,
 * bukan dari `device.bound` — lihat FIX ROUTE di `lib/auth-guard.ts`).
 *
 * FIX ROUTE — tiga tambahan:
 *  - **indeks app**: `NAV_APPS[].path` app ber-menu hanyalah PREFIX, jadi tanpa route
 *    eksplisit klik ikon app di Sidebar jatuh ke `RoleGuardFallback`. Tujuh route
 *    `AppIndexRedirect` (`/production`, `/inventory`, `/purchase`, `/quality`, `/reports`,
 *    `/settings`, `/finance`) mengarahkannya ke menu pertama app;
 *  - **error boundary per route**: setiap elemen `<Route>` dibungkus
 *    `<RouteErrorBoundary>` supaya crash halaman tidak menjadi layar putih;
 *  - **anti-loop**: TIDAK ada redirect ke `/dashboard` (dijaga `SUPERVISOR_ROLES` —
 *    role operator/qc/inventory/purchasing akan memantul). `RootRoute` memakai
 *    `firstAllowedPathForRole()`.
 *
 * F6.2 (auth hybrid) — gerbang sesi:
 *  - `<AuthProvider>` dipasang SEKALI di sini supaya `LoginPage`, `AuthGuard`, dan
 *    `TopBar` (di dalam App Shell) memakai state user yang sama;
 *  - `/login` berada DI LUAR App Shell (full-screen) dan TANPA `AuthGuard`;
 *  - seluruh route lain dibungkus `<AuthGuard>` (tanpa sesi -> `/login?redirect=<path>`).
 */

/**
 * Role alur produksi (Blueprint §5.3 / `ROLE_APPS`): app `production` dimiliki
 * operator, supervisor, dan owner. **admin TIDAK** (sidebar pun menyembunyikannya).
 *
 * Perbaikan Fase 26: sebelumnya array ini memuat `admin` dan melewatkan `owner` -
 * akibatnya admin bisa membuka `/production/*` via URL (halaman tanpa konteks TopBar)
 * dan menu Production milik owner di sidebar selalu berakhir redirect ke `/`.
 */
const PRODUCTION_ROLES: Role[] = ['operator', 'supervisor', 'owner'];

/** Role yang boleh mengisi form QC (Fase 18) - app `production` + `quality`. */
const QC_ROLES: Role[] = ['qc', 'supervisor', 'operator', 'owner'];

/**
 * Role yang boleh melihat halaman Quality (log/AQL/rework).
 * F7.1: `owner` IKUT (super-admin) — dulu owner melihat app Quality di sidebar tapi
 * ditolak `RoleRoute` ("Akses Ditolak"); `ROLE_APPS.owner` memang sudah memuat `quality`.
 */
const QUALITY_ROLES: Role[] = ['qc', 'supervisor', 'admin', 'owner'];

/** Role dashboard supervisor `/dashboard` (app `dashboard`: supervisor, admin, owner). */
const SUPERVISOR_ROLES: Role[] = ['supervisor', 'admin', 'owner'];

/** Role untuk halaman pemantauan lini - app `production` tingkat supervisor (Fase 26). */
const BUFFER_QUEUE_ROLES: Role[] = ['supervisor', 'owner'];

/** Role untuk halaman visualisasi routing - app `production` tingkat supervisor (Fase 26). */
const ROUTING_ROLES: Role[] = ['supervisor', 'owner'];

/**
 * F13/13.1 (keputusan A2) — material readiness `/production/readiness/:orderId`.
 *
 * Halaman ini milik app `production` tingkat supervisor → polanya SAMA dengan
 * `BUFFER_QUEUE_ROLES`/`ROUTING_ROLES`: `supervisor` + `owner`, **tanpa `admin`**
 * (konsisten perbaikan Fase 26 di atas: admin bukan pengguna app `production`).
 * `SUPERVISOR_ROLES` sengaja TIDAK diubah karena konstanta itu dipakai `/dashboard`
 * (app `dashboard` — admin memang boleh).
 */
const SUPERVISOR_READINESS_ROLES: Role[] = ['supervisor', 'owner'];

/** Role yang boleh melihat modul Inventory (Fase 20). */
const INVENTORY_ROLES: Role[] = ['inventory', 'admin', 'owner'];

// H2.1 — Sales Order (transaksi). TIDAK ada role `sales` di backend (role yang
// tersedia: OPERATOR/QC/SUPERVISOR/ADMIN/OWNER + PURCHASING) ⇒ halaman Sales
// dijaga ADMIN/OWNER, sama dengan izin TULIS API `/api/v1/garmen/orders/…`.
const SALES_ROLES: Role[] = ['admin', 'owner'];

/** Role yang boleh melihat modul Purchase (Fase 20). */
const PURCHASING_ROLES: Role[] = ['purchasing', 'admin', 'owner'];

/** Konfigurasi inventory = khusus admin (bukan staf inventory). */
const ADMIN_ROLES: Role[] = ['admin'];

/** Reports = supervisor ke atas (Fase 21). */
const REPORTS_ROLES: Role[] = ['supervisor', 'admin', 'owner'];

/** Konfigurasi sistem = admin + owner (Fase 22; owner ditambah pada fix role H5). */
const SETTINGS_ROLES: Role[] = ['admin', 'owner'];

/** AI Assistant = admin & owner (ROLE_APPS: `supervisor` TIDAK punya app 'ai'). */
const AI_ROLES: Role[] = ['admin', 'owner'];

/** F15 — Finance (antrean invoice) = owner + admin (ROLE_APPS keduanya punya 'finance'). */
const FINANCE_ROLES: Role[] = ['admin', 'owner'];

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* F6.2 — halaman login: publik, TANPA App Shell (kartu full-screen). */}
        <Route
          path="/login"
          element={
            <Suspense fallback={<PageLoader />}>
              {/* FIX ROUTE — crash di halaman login pun tidak boleh jadi layar putih. */}
              <RouteErrorBoundary>
                <LoginPage />
              </RouteErrorBoundary>
            </Suspense>
          }
        />

        {/* F6.2 — semua halaman lain: App Shell + gerbang sesi.
            `path="*"` (bukan `/*`) dipakai supaya pola "path tanpa route app"
            tetap satu bentuk dengan fallback lama; `<Routes>` turunan tetap sah
            karena path parent berakhiran `*` (React Router tidak memperingatkan).
            Indentasi daftar route di bawah sengaja tidak diubah (diff minimal);
            isi & urutannya identik dengan sebelum F6.2. */}
        <Route
          path="*"
          element={
            <AppShell>
              <Suspense fallback={<PageLoader />}>
                <AuthGuard>
                  <Routes>
        {/* FIX ROUTE — `/` memutuskan dari SESI (RootRoute): loading → spinner,
            belum login → /login?redirect=/, sudah login → Dashboard (atau app pertama
            kalau role-nya tidak punya app Dashboard). */}
        <Route
          path="/"
          element={
            <RouteErrorBoundary>
              <RootRoute />
            </RouteErrorBoundary>
          }
        />

        {/* FIX ROUTE — indeks app: `NAV_APPS[].path` app ber-menu hanyalah PREFIX
            (bukan route). Tanpa route ini klik ikon app di Sidebar mendarat di
            `RoleGuardFallback` (404/redirect) → halaman terasa "kosong". */}

        <Route
          path="/production"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="production" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/inventory"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="inventory" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/purchase"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="purchase" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/quality"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="quality" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/reports"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="reports" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/settings"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="settings" />
            </RouteErrorBoundary>
          }
        />
        <Route
          path="/finance"
          element={
            <RouteErrorBoundary>
              <AppIndexRedirect app="finance" />
            </RouteErrorBoundary>
          }
        />

        <Route
          path="/production/scan"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <ScanPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/shop-floor/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <ShopFloorPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/bundles/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <ProductionBundleDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 18 - QC */}
        <Route
          path="/production/qc"
          element={
            <RoleRoute roles={QC_ROLES}>
              <RouteErrorBoundary>
                <QCPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/qc/:id"
          element={
            <RoleRoute roles={QC_ROLES}>
              <RouteErrorBoundary>
                <QCPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/quality/defects"
          element={
            <RoleRoute roles={QUALITY_ROLES}>
              <RouteErrorBoundary>
                <DefectLogPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/quality/aql"
          element={
            <RoleRoute roles={QUALITY_ROLES}>
              <RouteErrorBoundary>
                <AQLDashboardPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/quality/rework"
          element={
            <RoleRoute roles={QUALITY_ROLES}>
              <RouteErrorBoundary>
                <ReworkTrackingPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 20 - inventory */}
        <Route
          path="/inventory/products"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <ProductsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/operations"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <OperationsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/reporting"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <InventoryReportingPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/config"
          element={
            <RoleRoute roles={ADMIN_ROLES}>
              <RouteErrorBoundary>
                <ConfigurationPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.5 — Inventory Adjustment (log audit + form create + detail/commit).
            Izin tulis API = IsAuthenticated; guard UI = INVENTORY_ROLES seperti
            `/inventory/*` yang sudah ada. Rute `:id` didaftarkan terakhir agar
            `/inventory/adjust` (form) tidak tertangkap pola detail. */}
        <Route
          path="/inventory/adjustments"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <InventoryAdjustmentListPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/adjust"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <InventoryAdjustmentFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/adjustments/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <InventoryAdjustmentDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.6 — Stock Transfer (log audit + form create + detail/commit).
            Izin tulis API = IsAuthenticated; guard UI = INVENTORY_ROLES. Rute `:id`
            didaftarkan terakhir agar `/inventory/transfer` (form) tidak tertangkap. */}
        <Route
          path="/inventory/transfers"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <StockTransferListPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/transfer"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <StockTransferFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/inventory/transfers/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <StockTransferDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.1 — master produk: list + form (baru/edit) + detail read-only.
            Path `/master/products*` dipetakan ke app `inventory` lewat
            `LEGACY_APP_PATHS` (`app/nav-config.ts`), jadi guard-nya INVENTORY_ROLES
            (inventory/admin/owner) — izin TULIS API juga menerima `purchasing`. */}
        <Route
          path="/master/products"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/products/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/products/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/products/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H3.5 — riwayat harga produk (read-only, audit trail `master.update_price`).
            Didaftarkan SETELAH `:id` karena path lebih spesifik (`:id/price-history`). */}
        <Route
          path="/master/products/:id/price-history"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductPriceHistoryPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.2 — master UoM: list + form (baru/edit) + detail read-only.
            Sama seperti produk: `/master/uoms*` dipetakan ke app `inventory`
            lewat `LEGACY_APP_PATHS`, guard INVENTORY_ROLES; izin TULIS API
            (POST/PUT/DELETE) hanya ADMIN/OWNER. */}
        <Route
          path="/master/uoms"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterUomsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/uoms/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterUomFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/uoms/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterUomFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/uoms/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterUomDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H3.6 — master pajak (tax): list + form (baru/edit) + detail (Set Default).
            Path `/master/taxes*` dipetakan ke app `inventory` lewat `LEGACY_APP_PATHS`,
            guard INVENTORY_ROLES; izin TULIS API (POST/PUT/DELETE/set-default) hanya
            ADMIN/OWNER. Push Odoo memakai task `erp_sync.push_master_tax`. */}
        <Route
          path="/master/taxes"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterTaxesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/taxes/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterTaxFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/taxes/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterTaxFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/taxes/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterTaxDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.3 — master gudang: list + form (baru/edit) + detail read-only.
            Path `/master/warehouses*` dipetakan ke app `inventory` lewat
            `LEGACY_APP_PATHS`, guard INVENTORY_ROLES; izin TULIS API (POST/PUT/DELETE)
            hanya ADMIN/OWNER. Push Odoo = update-only (create menunggu H1.4). */}
        <Route
          path="/master/warehouses"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWarehousesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/warehouses/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWarehouseFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/warehouses/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWarehouseFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/warehouses/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWarehouseDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.4 — master lokasi: list + form (baru/edit) + detail read-only.
            Path `/master/locations*` dipetakan ke app `inventory` lewat
            `LEGACY_APP_PATHS`, guard INVENTORY_ROLES; izin TULIS API (POST/PUT/DELETE)
            hanya ADMIN/OWNER. Push Odoo: create boleh (Odoo wajib name+usage), gagal
            kalau induk belum punya odoo_id. */}
        <Route
          path="/master/locations"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterLocationsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/locations/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterLocationFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/locations/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterLocationFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/locations/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterLocationDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.5 — master BOM: list + form (baru/edit, komponen inline) + detail.
            Path `/master/boms*` dipetakan ke app `inventory` lewat `LEGACY_APP_PATHS`,
            guard INVENTORY_ROLES; izin TULIS API (POST/PUT/DELETE) hanya ADMIN/OWNER.
            Push Odoo: create BOLEH (guard = produk harus punya odoo_tmpl_id). */}
        <Route
          path="/master/boms"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterBomsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/boms/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterBomFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/boms/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterBomFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/boms/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterBomDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.6 — master partner: list + form (baru/edit) + detail read-only.
            Path `/master/partners*` dipetakan ke app `inventory` lewat
            `LEGACY_APP_PATHS`, guard INVENTORY_ROLES; izin TULIS API (POST/PUT/DELETE)
            hanya ADMIN/OWNER. Push Odoo: create BOLEH (res.partner tidak mewajibkan
            field apa pun selain name). */}
        <Route
          path="/master/partners"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterPartnersPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/partners/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterPartnerFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/partners/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterPartnerFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/partners/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterPartnerDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.7 — master work center: list + form + detail (READ-ONLY, MES-only).
            Model = `garment.WorkCenter`; TIDAK ada push/pull Odoo (probe mrp.workcenter
            mewajibkan `resource_id` yang tidak ada di MES) → ledger sync ditulis
            `SKIPPED`. Izin TULIS API ADMIN/OWNER; DELETE = soft delete + guard bundle
            aktif (state bukan DONE/CANCELLED). */}
        <Route
          path="/master/work-centers"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWorkCentersPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/work-centers/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWorkCenterFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/work-centers/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWorkCenterFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/work-centers/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterWorkCenterDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.8 — master production line: list + form + detail (READ-ONLY, MES-only).
            Model = `garment.ProductionLine` (M2M `work_centers` dikelola di sini);
            TIDAK ada push/pull Odoo (probe: `mrp.routing` dihapus, dan
            `mrp.routing.workcenter` = Operation per-BoM) → ledger sync `SKIPPED`.
            Izin TULIS API ADMIN/OWNER; DELETE = soft delete + guard bundle aktif. */}
        <Route
          path="/master/production-lines"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductionLinesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/production-lines/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductionLineFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/production-lines/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductionLineFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/production-lines/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterProductionLineDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H1.9 — master routing DAG: list + form (editor DAG) + detail.
            Model = `garment.ProcessRouting` + `RoutingStep` (edge `allowed_next_steps`);
            endpoint = **B22 di-extend** (`/api/v1/settings/routing/<id>/`, `…/steps/`),
            bukan endpoint paralel → `/settings/routing` (F3A) tetap hidup.
            MES-only (probe: `mrp.routing` tidak ada di Odoo 17) → ledger `SKIPPED`;
            izin TULIS endpoint baru ADMIN/OWNER; DELETE = soft delete + guard
            rule tag-router aktif. */} 
        <Route
          path="/master/routings"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterRoutingsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/routings/new"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterRoutingFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/routings/:id/edit"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterRoutingFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/master/routings/:id"
          element={
            <RoleRoute roles={INVENTORY_ROLES}>
              <RouteErrorBoundary>
                <MasterRoutingDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.2 — Purchase Order MES (transaksi; sync SATU ARAH MES → Odoo).
            Endpoint `/api/v1/garmen/purchase-orders/…` (list/create/detail/update/
            delete + `confirm|done|cancel` + `sync-odoo-state` read-only); nomor dari
            Sprint C (`next_number('PO')`) dikirim sebagai `partner_ref`, push
            `purchase.order` (create draft) saat CONFIRMED. Guard PURCHASING_ROLES
            (sama dengan izin TULIS API). Path `/purchase/orders*` SENGAJA dipakai
            (B10 list `/purchase/orders` tetap hidup sebagai daftar monitoring). */}
        <Route
          path="/purchase/orders/new"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <PurchaseOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/purchase/orders/:id"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <PurchaseOrderDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/purchase/orders/:id/edit"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <PurchaseOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 20 - purchase */}
        <Route
          path="/purchase/orders"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <PurchaseOrdersPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/purchase/vendors"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <VendorsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/purchase/reporting"
          element={
            <RoleRoute roles={PURCHASING_ROLES}>
              <RouteErrorBoundary>
                <PurchaseReportingPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 21 - reports */}
        <Route
          path="/reports/line-efficiency"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <LineEfficiencyPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/reports/lead-time"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <LeadTimePage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/reports/on-time-delivery"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <OnTimeDeliveryPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/reports/wip"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <WIPPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/reports/reconciliation"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <ReconciliationReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H4.1 - laporan penjualan (read-only; endpoint /reports/sales/). */}
        <Route
          path="/reports/sales"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <SalesReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H4.2 - laporan pembelian (read-only; endpoint /reports/purchases/). */}
        <Route
          path="/reports/purchases"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <PurchasesReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H4.3 - laporan stok (read-only; endpoint /reports/stock/). */}
        <Route
          path="/reports/stock"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <StockReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H4.4 - laporan HPP/laba kotor (read-only; endpoint /reports/cogs/). */}
        <Route
          path="/reports/cogs"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <CogsReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H4.5 - laporan laba-rugi PnL (read-only; endpoint /reports/pnl/). */}
        <Route
          path="/reports/pnl"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <PnlReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H4.6 - laporan produksi (read-only; endpoint /reports/production/). */}
        <Route
          path="/reports/production"
          element={
            <RoleRoute roles={REPORTS_ROLES}>
              <RouteErrorBoundary>
                <ProductionReportPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 22 - settings (admin) */}
        <Route
          path="/settings/routing"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <RoutingConfigPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/settings/bundling"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <BundlingRulesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/settings/line-allocation"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <LineAllocationPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* Sprint C — Number Sequence: penomoran dokumen MES
            (`<PREFIX>-<YEAR>-<SEQ:04d>`, reset per tahun). Endpoint
            `/api/v1/settings/sequences/…`; MES-only (tanpa push ke Odoo — `ir.sequence`
            Odoo = counter internal dokumen Odoo), izin TULIS PUT = ADMIN/OWNER. */}
        <Route
          path="/settings/sequences"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <SequencesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.2 — Currency: mata uang MES (mirror `res.currency` Odoo lewat pull I1
            + CRUD di `/api/v1/settings/currencies/…`). MES-only (ledger `SKIPPED`,
            tanpa push ke Odoo); izin TULIS POST/PUT/DELETE/set-default = ADMIN/OWNER. */}
        <Route
          path="/settings/currencies"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <CurrenciesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.1 — Company Profile: identitas perusahaan MES (SINGLETON, greenfield) di
            `/api/v1/settings/company/` (GET boleh `null`, PUT create-on-first-PUT).
            MES-only (ledger `SKIPPED`, tanpa push ke `res.company` Odoo); izin tulis
            PUT = ADMIN/OWNER. */}
        <Route
          path="/settings/company"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <CompanyPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.6 — Integration Config: profil config MES ↔ Odoo (SINGLETON) di
            `/api/v1/settings/integration/` + uji koneksi read-only. **Opsi B**: DB
            menyimpan profil, konsumen tetap membaca `.env` (aktivasi = salin ke `.env` +
            restart worker); MES-only (ledger `SKIPPED`). Izin tulis = ADMIN/OWNER. */}
        <Route
          path="/settings/integration"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <IntegrationConfigPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.8 — WA Gateway Config: profil gateway WhatsApp (SINGLETON) di
            `/api/v1/settings/wa/` + uji gateway read-only (mock-friendly). **Opsi B**:
            DB menyimpan profil, konsumen (`get_wa_gateway`) tetap membaca `.env`
            (aktivasi = salin ke `.env` + restart worker); MES-only (ledger `SKIPPED`).
            Izin tulis = ADMIN/OWNER. */}
        <Route
          path="/settings/wa"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <WAConfigPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.5 — Audit Log Viewer: daftar + filter AuditLog (`/api/v1/settings/audit/`)
            + detail `/<id>/`. **READ-ONLY** (append-only; rahasia di payload/metadata
            sudah di-mask backend). Path frontend `/settings/audit-log` karena
            `/settings/audit` sudah dipakai F9 (audit produk tanpa `odoo_id`).
            Guard + izin = ADMIN/OWNER. */}
        <Route
          path="/settings/audit-log"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <AuditLogPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.7 — Printer Config: profil printer thermal ESC/POS (SINGLETON) di
            `/api/v1/settings/printer/` + uji printer read-only (**tidak pernah
            mencetak**). **Opsi B**: DB menyimpan profil, konsumen
            (`printing.backends.get_backend`) tetap membaca `.env` (aktivasi = salin ke
            `.env` + restart worker); MES-only (ledger `SKIPPED`). Izin tulis = ADMIN/OWNER. */}
        <Route
          path="/settings/printers"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <PrinterConfigPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* H5.4 — Permission Matrix: profil izin role × resource × action
            (`/api/v1/settings/permissions/` GET + PUT bulk per role, ADMIN/OWNER).
            **Opsi A′**: yang tersimpan = PROFIL (ledger `SKIPPED`); enforcement TETAP
            guard kode (`_require_admin`, `OPERATOR_CODE_ROLES`, daftar role frontend) —
            halaman menampilkan `effective` + banner peringatan. */}
        <Route
          path="/settings/permissions"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <PermissionMatrixPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/settings/devices"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <DeviceProfilesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/settings/users"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <UserManagementPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/settings/audit"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <ProductAuditPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* F15 — monitoring SyncRecord (settings, admin). */}
        <Route
          path="/settings/sync"
          element={
            <RoleRoute roles={SETTINGS_ROLES}>
              <RouteErrorBoundary>
                <SyncMonitorPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* F15 — Finance (owner + admin): antrean invoice Fase 4.4. */}
        <Route
          path="/finance/invoices"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <InvoiceQueuePage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H3.1 — Customer Invoice MES (model + push `account.move` draft).
            Path `/finance/customer-invoices*` BARU (F15 `/finance/invoices` tetap
            antrean I5 read-only); guard FINANCE_ROLES = admin/owner, izin tulis API
            juga ADMIN/OWNER. Nomor invoice dari Sprint C (`next_number('INV')`). */}
        <Route
          path="/finance/customer-invoices"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoicesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/customer-invoices/new"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoiceFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/customer-invoices/:id"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoiceDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* Alias H3.1: form/tombol memakai `/finance/invoices/new|:id|:id/edit` supaya
            konsisten dengan menu F15, tetapi halaman CRUD tetap di halaman BARU. */}
        <Route
          path="/finance/invoices/new"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoiceFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/invoices/:id/edit"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoiceFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/invoices/:id"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <CustomerInvoiceDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H3.2 — Vendor Bill MES (model + push `account.move` **in_invoice** draft).
            Path `/finance/vendor-bills*` BARU: `/finance/invoices` (F15),
            `/finance/customer-invoices` (H3.1), dan `/purchase/orders` (B10/H2.2)
            tetap seperti semula. Guard FINANCE_ROLES = admin/owner (izin tulis API
            sama). Nomor bill dari Sprint C (`next_number('VB')`). */}
        <Route
          path="/finance/vendor-bills"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <VendorBillsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/vendor-bills/new"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <VendorBillFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/vendor-bills/:id"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <VendorBillDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/vendor-bills/:id/edit"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <VendorBillFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H3.3 — Payment MES (satu model dua arah INBOUND/OUTBOUND + push
            `account.payment` draft). Path `/finance/payments*` BARU & bebas bentrok:
            `/finance/invoices` (F15), `/finance/customer-invoices` (H3.1), dan
            `/finance/vendor-bills` (H3.2) tetap seperti semula. Guard FINANCE_ROLES =
            admin/owner. Nomor dari Sprint C (`next_number('PAY')`); rekonsiliasi
            tetap di Odoo (MES hanya membuat payment draft). */}
        <Route
          path="/finance/payments"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <PaymentsPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/payments/new"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <PaymentFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/payments/:id"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <PaymentDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/payments/:id/edit"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <PaymentFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H3.4 — Journal Entry manual MES (double-entry + push `account.move`
            `move_type='entry'` **draft**; journal `general` saja). Path
            `/finance/journal-entries*` BARU & bebas bentrok: `/finance/invoices` (F15),
            `/finance/customer-invoices` (H3.1), `/finance/vendor-bills` (H3.2), dan
            `/finance/payments` (H3.3) tetap seperti semula. Guard FINANCE_ROLES =
            admin/owner. Nomor dari Sprint C (`next_number('JE')`); **posting bukan**
            tanggung jawab MES (akuntan Odoo yang mem-posting). */}
        <Route
          path="/finance/journal-entries"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <JournalEntriesPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/journal-entries/new"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <JournalEntryFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/journal-entries/:id"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <JournalEntryDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/finance/journal-entries/:id/edit"
          element={
            <RoleRoute roles={FINANCE_ROLES}>
              <RouteErrorBoundary>
                <JournalEntryFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 23 - AI Assistant (/ai/chat, admin & owner) */}
        <Route
          path="/ai/chat"
          element={
            <RoleRoute roles={AI_ROLES}>
              <RouteErrorBoundary>
                <AIChatPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        <Route
          path="/workshop"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleWorkshopPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/workshop/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleWorkshopPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/bundles"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleListPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/bundles/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/work-orders"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <WorkOrderListPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.4 — Bundle CRUD (MES-only sebagai objek; gerakan stok tetap WIP/FG).
            Route BARU saja: `/production/bundles/:id` (halaman operator existing) dan
            `/bundles*` (F13) TIDAK diubah. */}
        <Route
          path="/production/bundles/new"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/bundles/:id/edit"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <BundleFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.3 — Work Order MES (transaksi MES-only: probe Odoo `mrp.workorder` =
            operasi per `mrp.production`, jadi TIDAK ada push/Odoo id; jejaknya
            `SyncRecord` stage `WORK_ORDER_PUSH` status SKIPPED). Guard PRODUCTION_ROLES
            (operator/supervisor/owner — sama dengan halaman produksi lain); TULIS API
            tetap `IsAuthenticated` (tanpa role) supaya jalur F2/simulator tidak pecah.
            List `/production/work-orders` MEMAKAI halaman F13 yang sudah ada. */}
        <Route
          path="/production/work-orders"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <WorkOrderListPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/work-orders/new"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <WorkOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/work-orders/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <WorkOrderCrudDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/work-orders/:id/edit"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <WorkOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* Fase 19 - supervisor */}
        <Route
          path="/dashboard"
          element={
            <RoleRoute roles={SUPERVISOR_ROLES}>
              <RouteErrorBoundary>
                <SupervisorDashboardPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/*
          H4.7 - dashboard eksekutif (read-only; endpoint /dashboard/executive/).
          Guard = SUPERVISOR_ROLES (supervisor/admin/owner) - SAMA dengan `/dashboard`
          dan SETARA union `ADMIN_ROLES + REPORTS_ROLES`; app pemiliknya `reports`
          lewat alias path di `nav-config.ts` (B2 `/dashboard/summary/` tidak diubah).
        */}
        <Route
          path="/dashboard/executive"
          element={
            <RoleRoute roles={SUPERVISOR_ROLES}>
              <RouteErrorBoundary>
                <ExecutiveDashboardPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/buffer-queue"
          element={
            <RoleRoute roles={BUFFER_QUEUE_ROLES}>
              <RouteErrorBoundary>
                <BufferQueuePage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/routing"
          element={
            <RoleRoute roles={ROUTING_ROLES}>
              <RouteErrorBoundary>
                <RoutingVisualizationPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/production/readiness/:orderId"
          element={
            <RoleRoute roles={SUPERVISOR_READINESS_ROLES}>
              <RouteErrorBoundary>
                <MaterialReadinessPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        {/* F11/11.4a — form scrap bundle (aksi nyata; sama seperti layar operator). */}
        <Route
          path="/production/scrap/:id"
          element={
            <RoleRoute roles={PRODUCTION_ROLES}>
              <RouteErrorBoundary>
                <ScrapFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        {/* H2.1 — Sales Order MES (transaksi; sync SATU ARAH MES → Odoo).
            Endpoint `/api/v1/garmen/orders/…` (list/create/detail/update/delete +
            `confirm|done|cancel`); nomor dari Sprint C (`next_number('SO')`),
            push `sale.order` (create draft) saat CONFIRMED. Guard route SALES_ROLES
            (admin/owner — sama dengan izin tulis API). */}
        <Route
          path="/sales/orders"
          element={
            <RoleRoute roles={SALES_ROLES}>
              <RouteErrorBoundary>
                <SalesOrdersPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/sales/orders/new"
          element={
            <RoleRoute roles={SALES_ROLES}>
              <RouteErrorBoundary>
                <SalesOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/sales/orders/:id"
          element={
            <RoleRoute roles={SALES_ROLES}>
              <RouteErrorBoundary>
                <SalesOrderDetailPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />
        <Route
          path="/sales/orders/:id/edit"
          element={
            <RoleRoute roles={SALES_ROLES}>
              <RouteErrorBoundary>
                <SalesOrderFormPage />
              </RouteErrorBoundary>
            </RoleRoute>
          }
        />

        <Route
          path="*"
          element={
            <RouteErrorBoundary>
              <RoleGuardFallback />
            </RouteErrorBoundary>
          }
        />
                  </Routes>
                </AuthGuard>
              </Suspense>
            </AppShell>
          }
        />
      </Routes>
    </AuthProvider>
  );
}

