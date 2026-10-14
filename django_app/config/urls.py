"""URL routing level project `garmen`.

Semua app domain tinggal di folder `apps_industry/` (Modular Monolith),
jadi include-nya memakai dotted path, mis.
`apps_industry.garment.api.urls`.

URUTAN PENTING (Fase A) — dari yang paling spesifik ke paling umum:

  1. infrastruktur & dokumentasi: ``admin/``, ``api/schema/``, ``api/docs/``,
     ``api/health/``;
  2. kontrak core lintas industri: ``api/v1/auth/...``, ``api/v1/metadata/...``,
     ``api/v1/chatter/...``, ``api/v1/devices/me``, ``api/v1/sync/odoo/<stage>/``;
  3. terakhir: API industri (pola ``/api/v1/<industry>/<resource>/...``).

Dengan urutan ini tidak ada path kontrak yang bisa tertutup (shadowed) oleh pola
industri, dan ``/api/v1/<industry>/...`` hanya menerima industri yang lolos
whitelist (``apps_industry/garment/api/industries.py``).
"""

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps_industry.garment.api.bundles import (
    # ⚠️ Nama view mengandung `Crud` supaya tidak tertukar dengan F2
    # (`create_view.BundleCreateView`) yang tetap melayani industri lain.
    BundleDetailCrudView,
    BundleListCreateView,
    BundleMergeView,
    BundlePreviewView,
    BundleSplitView,
)
from apps_industry.garment.api.chatter.views import ChatterView
from apps_industry.garment.api.inventory_adjustments import (
    InventoryAdjustmentCommitView,
    InventoryAdjustmentDetailView,
    InventoryAdjustmentListCreateView,
    InventoryStockQtyView,
)
from apps_industry.garment.api.stock_transfers import (
    StockTransferCommitView,
    StockTransferDetailView,
    StockTransferListCreateView,
)
from apps_industry.garment.api.orders import (
    OrderActionView,
    OrderDetailView,
    OrderGenerateWorkOrdersView,
    OrdersView,
)
from apps_industry.garment.api.payments import (
    PaymentActionView,
    PaymentDetailView,
    PaymentsView,
)
from apps_industry.garment.api.journal_entries import (
    JournalEntriesView,
    JournalEntryActionView,
    JournalEntryDetailView,
)
from apps_industry.garment.api.customer_invoices import (
    CustomerInvoiceActionView,
    CustomerInvoiceDetailView,
    CustomerInvoicesView,
)
from apps_industry.garment.api.vendor_bills import (
    VendorBillActionView,
    VendorBillDetailView,
    VendorBillsView,
)
from apps_industry.garment.api.purchase_orders import (
    PurchaseOrderActionView,
    PurchaseOrderDetailView,
    PurchaseOrderSyncStateView,
    # ⚠️ Alias: `integrations.erp_sync.monitoring` juga punya `PurchaseOrdersView`
    # (B10) dan di-import SETELAH blok ini ⇒ tanpa alias, nama itu akan tertimpa.
    PurchaseOrdersView as PurchaseOrdersCrudView,
)
from apps_industry.garment.api.schema.views import MetadataView
from apps_industry.garment.api.work_orders import (
    # ⚠️ Nama view sengaja mengandung `Crud` supaya TIDAK bentrok dengan resource
    # `work-orders` bawaan F2/F3 (`create_view.WorkOrderCreateView`) maupun
    # `monitoring` (yang juga punya view berbasis WorkOrder).
    WorkOrderCreateCrudView,
    WorkOrderDetailCrudView,
    WorkOrderSplitView,
)
from apps_industry.garment.api.settings.views import (
    SettingsAuditDetailView,
    SettingsAuditView,
    SettingsBundlingView,
    SettingsCompanyView,
    SettingsCurrenciesView,
    SettingsCurrencyDefaultView,
    SettingsCurrencyDetailView,
    SettingsCurrencySetDefaultView,
    SettingsDevicesView,
    SettingsIntegrationConfigView,
    SettingsIntegrationTestConnectionView,
    SettingsLineAllocationView,
    SettingsPermissionRoleView,
    SettingsPermissionsView,
    SettingsPrinterConfigView,
    SettingsPrinterTestConnectionView,
    SettingsRolesView,
    SettingsRoutingDetailView,
    SettingsRoutingStepDetailView,
    SettingsRoutingStepsView,
    SettingsRoutingView,
    SettingsSequenceDetailView,
    SettingsSequencePreviewView,
    SettingsSequencesView,
    SettingsUserDetailView,
    SettingsUsersView,
    SettingsWAConfigView,
    SettingsWATestConnectionView,
)
from apps_industry.garment.api.views import health
from core.auth.api import (
    AuthChangePasswordView,
    AuthLoginOperatorView,
    AuthLoginView,
    AuthLogoutView,
    AuthMeView,
    AuthResetPasswordView,
)
from core.device_profile.api import DeviceBindView, DeviceMeView, DeviceUnbindView
from integrations.ai.api import AiChatView
from integrations.ai.hitl_views import HitlApproveView, HitlQueueView, HitlRejectView
from integrations.erp_sync.api import (
    OrderReadinessView,
    ProductAuditView,
    ReconciliationReportView,
    SyncMasterView,
    SyncOdooView,
    SyncScrapView,
)
from integrations.erp_sync.monitoring import (
    BufferQueueView,
    DashboardSummaryView,
    ExecutiveDashboardView,
    InventoryOperationsView,
    InventoryProductsView,
    InventoryReportingView,
    InvoiceListView,
    PurchaseOrdersView,
    PurchaseReportingView,
    PurchaseVendorsView,
    QualityAqlView,
    QualityDefectsView,
    QualityReworkView,
    ReportsCogsView,
    ReportsLeadTimeBundlesView,
    ReportsLeadTimeView,
    ReportsLineEfficiencyByWcView,
    ReportsLineEfficiencyView,
    ReportsOnTimeDeliveryOrdersView,
    ReportsOnTimeDeliveryView,
    ReportsPnlView,
    ReportsProductionView,
    ReportsPurchasesView,
    ReportsSalesView,
    ReportsStockView,
    ReportsWipByWcView,
    ReportsWipView,
    RoutingGraphView,
    SyncRecordListView,
)
# H4.8 — export laporan H4 (Excel/PDF); modul export TERPISAH dari monitoring
# (satu arah: export → monitoring, tanpa circular import).
from integrations.erp_sync.export import ExportReportView
from integrations.printing.api import PrintBundleTagView, PrintCouponView
from integrations.wa_bot.api import WASendView
from master.api import (
    MasterAccountDetailView,
    MasterAccountListView,
    MasterBomDetailView,
    MasterBomListCreateView,
    MasterJournalDetailView,
    MasterJournalListView,
    MasterLocationDetailView,
    MasterLocationListCreateView,
    MasterPartnerDetailView,
    MasterPartnerListCreateView,
    MasterProductionLineDetailView,
    MasterProductionLineListCreateView,
    MasterWorkCenterDetailView,
    MasterWorkCenterListCreateView,
    MasterProductDetailView,
    MasterProductListCreateView,
    # H3.5 — endpoint khusus harga (update + riwayat audit trail).
    MasterProductPriceHistoryView,
    MasterProductPriceView,
    # H3.6 — CRUD master Tax (`account.tax`) + pajak default MES.
    MasterTaxDefaultView,
    MasterTaxDetailView,
    MasterTaxListCreateView,
    MasterTaxSetDefaultView,
    MasterUomDetailView,
    MasterUomListCreateView,
    MasterWarehouseDetailView,
    MasterWarehouseListCreateView,
)


def root_view(request):
    """Info singkat di root agar `curl localhost:8000` tidak 404."""
    return JsonResponse(
        {
            "service": "garmen-django",
            "health": "/api/health/",
            "admin": "/admin/",
        }
    )


urlpatterns = [
    path("", root_view, name="root"),
    # 1) Infrastruktur & dokumentasi. Route ini TIDAK boleh tertutup pola industri.
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    path("api/health/", health, name="health"),
    # 2) Kontrak core lintas industri — didaftarkan SEBELUM pola industri.
    # Metadata resource (kontrak §3). Kontrak menulis tanpa trailing slash, jadi
    # kedua varian didaftarkan supaya tidak ada redirect 301 di path kontrak.
    path("api/v1/metadata/<str:resource>", MetadataView.as_view(), name="metadata"),
    path(
        "api/v1/metadata/<str:resource>/",
        MetadataView.as_view(),
        name="metadata_slash",
    ),
    # Chatter paginasi (kontrak §3/§8). Varian trailing slash didaftarkan eksplisit
    # supaya `/api/v1/chatter/bundles/1/` TIDAK jatuh ke detail resource
    # (`industry="chatter"`) — Fase A.2.
    path(
        "api/v1/chatter/<str:resource>/<int:id>",
        ChatterView.as_view(),
        name="chatter",
    ),
    path(
        "api/v1/chatter/<str:resource>/<int:id>/",
        ChatterView.as_view(),
        name="chatter_slash",
    ),
    # Alias lama di root `api/` dipertahankan (task Sprint 3.2) — tidak ambigu
    # karena didaftarkan sebelum include industri.
    path(
        "api/chatter/<str:resource>/<int:id>",
        ChatterView.as_view(),
        name="chatter_root",
    ),
    path(
        "api/chatter/<str:resource>/<int:id>/",
        ChatterView.as_view(),
        name="chatter_root_slash",
    ),
    # Resolver profil device (kontrak §5.1). Path sengaja tanpa trailing slash —
    # persis kontrak, jangan diubah.
    path("api/v1/devices/me", DeviceMeView.as_view(), name="devices_me"),
    # Fase G — device binding (cookie `device_token`). Varian trailing slash ikut
    # didaftarkan supaya klien yang menambahkan "/" tidak kena redirect 301.
    path("api/v1/devices/bind", DeviceBindView.as_view(), name="devices_bind"),
    path("api/v1/devices/bind/", DeviceBindView.as_view(), name="devices_bind_slash"),
    path("api/v1/devices/unbind", DeviceUnbindView.as_view(), name="devices_unbind"),
    path(
        "api/v1/devices/unbind/",
        DeviceUnbindView.as_view(),
        name="devices_unbind_slash",
    ),
    # Sync ERP dua tahap (kontrak §7: `POST /api/v1/sync/odoo/{stage}/`).
    path(
        "api/v1/sync/odoo/<str:stage>/",
        SyncOdooView.as_view(),
        name="sync_odoo",
    ),
    # Sync master data per entity (Fase I1.4: `POST /api/v1/sync/master/<entity>/`).
    path(
        "api/v1/sync/master/<str:entity>/",
        SyncMasterView.as_view(),
        name="sync_master",
    ),
    # Sync scrap manual (Fase I4: `POST /api/v1/sync/scrap/`) — sinkron.
    path(
        "api/v1/sync/scrap/",
        SyncScrapView.as_view(),
        name="sync_scrap",
    ),
    # F1 (B1) — ringkasan dashboard lantai produksi (read-only, agregat DB murni).
    # "dashboard" BUKAN nama industri, jadi WAJIB didaftarkan di section kontrak
    # core ini (SEBELUM `include` industri) supaya tidak tertangkap pola
    # `v1/<industry>/<resource>/` maupun guard whitelist industri.
    path(
        "api/v1/dashboard/summary/",
        DashboardSummaryView.as_view(),
        name="dashboard_summary",
    ),
    # H4.7 — dashboard eksekutif (orkestrasi H4.1–H4.6, cache 300 detik;
    # B2 `/dashboard/summary/` di atas TIDAK diubah = endpoint paralel).
    path(
        "api/v1/dashboard/executive/",
        ExecutiveDashboardView.as_view(),
        name="dashboard_executive",
    ),
    # H4.8 — export laporan H4 (Excel/PDF): POST /api/v1/export/<report>/.
    # Satu endpoint untuk 7 laporan (sales|purchases|stock|cogs|pnl|production|
    # executive); respons = file binary (Content-Disposition attachment).
    path(
        "api/v1/export/<str:report>/",
        ExportReportView.as_view(),
        name="export_report",
    ),
    # F1 (B2/B3/B4) — endpoint agregat lantai produksi (read-only, DB murni).
    # "production"/"routing"/"quality" BUKAN nama industri (whitelist industri
    # di apps_industry/garment/api/industries.py), jadi WAJIB didaftarkan di
    # section kontrak core ini SEBELUM `include` industri supaya tidak jatuh ke
    # pola `v1/<industry>/<resource>/`.
    path(
        "api/v1/production/buffer-queue/",
        BufferQueueView.as_view(),
        name="production_buffer_queue",
    ),
    path(
        "api/v1/routing/graph/",
        RoutingGraphView.as_view(),
        name="routing_graph",
    ),
    path(
        "api/v1/quality/aql/",
        QualityAqlView.as_view(),
        name="quality_aql",
    ),
    path(
        "api/v1/quality/defects/",
        QualityDefectsView.as_view(),
        name="quality_defects",
    ),
    # F1 (B6/B7/B8) — rework + inventory (read-only, DB murni). Sama seperti di
    # atas: bukan nama industri → WAJIB di section kontrak core (SEBELUM include).
    path(
        "api/v1/quality/rework/",
        QualityReworkView.as_view(),
        name="quality_rework",
    ),
    path(
        "api/v1/inventory/products/",
        InventoryProductsView.as_view(),
        name="inventory_products",
    ),
    path(
        "api/v1/inventory/operations/",
        InventoryOperationsView.as_view(),
        name="inventory_operations",
    ),
    # F1 (B12/B13/B16) — purchase + reports (read-only, DB murni).
    path(
        "api/v1/purchase/vendors/",
        PurchaseVendorsView.as_view(),
        name="purchase_vendors",
    ),
    path(
        "api/v1/purchase/orders/",
        PurchaseOrdersView.as_view(),
        name="purchase_orders",
    ),
    path(
        "api/v1/purchase/reporting/",
        PurchaseReportingView.as_view(),
        name="purchase_reporting",
    ),
    # Sub-route (lebih spesifik) didaftarkan lebih dulu — konsisten dengan
    # prinsip urutan file ini; path exact jadi urutan bukan keharusan teknis.
    path(
        "api/v1/reports/line-efficiency/by-wc/",
        ReportsLineEfficiencyByWcView.as_view(),
        name="reports_line_efficiency_by_wc",
    ),
    path(
        "api/v1/reports/line-efficiency/",
        ReportsLineEfficiencyView.as_view(),
        name="reports_line_efficiency",
    ),
    path(
        "api/v1/reports/lead-time/bundles/",
        ReportsLeadTimeBundlesView.as_view(),
        name="reports_lead_time_bundles",
    ),
    path(
        "api/v1/reports/lead-time/",
        ReportsLeadTimeView.as_view(),
        name="reports_lead_time",
    ),
    path(
        "api/v1/reports/on-time-delivery/orders/",
        ReportsOnTimeDeliveryOrdersView.as_view(),
        name="reports_on_time_delivery_orders",
    ),
    path(
        "api/v1/reports/on-time-delivery/",
        ReportsOnTimeDeliveryView.as_view(),
        name="reports_on_time_delivery",
    ),
    path(
        "api/v1/reports/wip/by-wc/",
        ReportsWipByWcView.as_view(),
        name="reports_wip_by_wc",
    ),
    path(
        "api/v1/reports/wip/",
        ReportsWipView.as_view(),
        name="reports_wip",
    ),
    # H4.1 — laporan penjualan (agregat DB murni, read-only, cache 300 detik).
    # `reports/...` BUKAN nama industri -> tetap di section kontrak core.
    path(
        "api/v1/reports/sales/",
        ReportsSalesView.as_view(),
        name="reports_sales",
    ),
    # H4.2 — laporan pembelian (agregat DB murni, read-only, cache 300 detik).
    path(
        "api/v1/reports/purchases/",
        ReportsPurchasesView.as_view(),
        name="reports_purchases",
    ),
    # H4.3 — laporan stok (snapshot Odoo via I7, read-only, cache 300 detik).
    path(
        "api/v1/reports/stock/",
        ReportsStockView.as_view(),
        name="reports_stock",
    ),
    # H4.4 — laporan HPP/laba kotor (omzet - HPP simplified, cache 300 detik).
    path(
        "api/v1/reports/cogs/",
        ReportsCogsView.as_view(),
        name="reports_cogs",
    ),
    # H4.5 — laporan laba-rugi (omzet - HPP - opex jurnal, cache 300 detik).
    path(
        "api/v1/reports/pnl/",
        ReportsPnlView.as_view(),
        name="reports_pnl",
    ),
    # H4.6 — laporan produksi (output/scrap/efisiensi/OTD per periode, cache 300 detik).
    path(
        "api/v1/reports/production/",
        ReportsProductionView.as_view(),
        name="reports_production",
    ),
    # F3A.2 (B22/B24/B25) — konfigurasi admin (GET + POST). "settings" BUKAN nama
    # industri -> WAJIB di section kontrak core (sebelum `include` industri) supaya
    # tidak tertangkap pola `v1/<industry>/<resource>/`.
    path(
        "api/v1/settings/routing/",
        SettingsRoutingView.as_view(),
        name="settings_routing",
    ),
    # H1.9 — extend B22 di tempat (TANPA endpoint paralel `/master/routings/`):
    # detail/ubah/nonaktifkan routing + CRUD step (node DAG).
    path(
        "api/v1/settings/routing/<int:pk>/",
        SettingsRoutingDetailView.as_view(),
        name="settings_routing_detail",
    ),
    path(
        "api/v1/settings/routing/<int:pk>/steps/",
        SettingsRoutingStepsView.as_view(),
        name="settings_routing_steps",
    ),
    path(
        "api/v1/settings/routing/<int:pk>/steps/<int:step_id>/",
        SettingsRoutingStepDetailView.as_view(),
        name="settings_routing_step_detail",
    ),
    # Sprint C — penomoran dokumen MES (<prefix>-<year>-<seq:04d>, reset per tahun).
    # `preview` didaftarkan SEBELUM `<code>/` (dua pola berbeda, urutan demi kejelasan).
    path(
        "api/v1/settings/sequences/",
        SettingsSequencesView.as_view(),
        name="settings_sequences",
    ),
    path(
        "api/v1/settings/sequences/<str:code>/preview/",
        SettingsSequencePreviewView.as_view(),
        name="settings_sequence_preview",
    ),
    path(
        "api/v1/settings/sequences/<str:code>/",
        SettingsSequenceDetailView.as_view(),
        name="settings_sequence_detail",
    ),
    # H5.2 — mata uang (master.Currency: mirror res.currency; MES-only SKIPPED).
    # `default` didaftarkan sebelum `<int:currency_id>/` (konverter int tidak menangkap
    # "default", urutan hanya demi kejelasan — pola H3.6 taxes).
    path(
        "api/v1/settings/currencies/",
        SettingsCurrenciesView.as_view(),
        name="settings_currencies",
    ),
    path(
        "api/v1/settings/currencies/default/",
        SettingsCurrencyDefaultView.as_view(),
        name="settings_currency_default",
    ),
    path(
        "api/v1/settings/currencies/<int:currency_id>/set-default/",
        SettingsCurrencySetDefaultView.as_view(),
        name="settings_currency_set_default",
    ),
    path(
        "api/v1/settings/currencies/<int:currency_id>/",
        SettingsCurrencyDetailView.as_view(),
        name="settings_currency_detail",
    ),
    # H5.1 — profil perusahaan MES (greenfield, SINGLETON: GET/PUT saja;
    # MES-only — ledger SKIPPED, tanpa push/pull company).
    path(
        "api/v1/settings/company/",
        SettingsCompanyView.as_view(),
        name="settings_company",
    ),
    # H5.6 — profil config integrasi MES ↔ Odoo (SINGLETON, Opsi B: konsumen tetap
    # membaca `.env`) + uji koneksi read-only. MES-only (ledger SKIPPED).
    path(
        "api/v1/settings/integration/",
        SettingsIntegrationConfigView.as_view(),
        name="settings_integration",
    ),
    path(
        "api/v1/settings/integration/test-connection/",
        SettingsIntegrationTestConnectionView.as_view(),
        name="settings_integration_test_connection",
    ),
    # H5.8 — profil gateway WhatsApp (SINGLETON, Opsi B: konsumen tetap membaca
    # `.env`) + uji gateway read-only. MES-only (ledger SKIPPED).
    path(
        "api/v1/settings/wa/",
        SettingsWAConfigView.as_view(),
        name="settings_wa",
    ),
    path(
        "api/v1/settings/wa/test-connection/",
        SettingsWATestConnectionView.as_view(),
        name="settings_wa_test_connection",
    ),
    # H5.5 — Audit Log Viewer (READ-ONLY, append-only: tidak ada write). Daftar +
    # filter ListPage; ``/<id>/`` = detail payload/metadata (rahasia di-mask).
    # Path ``/settings/audit/`` dipakai MES (BUKAN ``/audit/products-missing-odoo-id/``
    # milik F9) supaya tidak bentrok dengan kontrak audit produk.
    path(
        "api/v1/settings/audit/",
        SettingsAuditView.as_view(),
        name="settings_audit",
    ),
    path(
        "api/v1/settings/audit/<int:log_id>/",
        SettingsAuditDetailView.as_view(),
        name="settings_audit_detail",
    ),
    # H5.7 — profil printer thermal ESC/POS (SINGLETON, Opsi B: konsumen tetap membaca
    # `.env`) + uji printer read-only (TIDAK PERNAH mencetak). MES-only (ledger SKIPPED).
    path(
        "api/v1/settings/printer/",
        SettingsPrinterConfigView.as_view(),
        name="settings_printer",
    ),
    path(
        "api/v1/settings/printer/test-connection/",
        SettingsPrinterTestConnectionView.as_view(),
        name="settings_printer_test_connection",
    ),
    path(
        "api/v1/settings/bundling/",
        SettingsBundlingView.as_view(),
        name="settings_bundling",
    ),
    path(
        "api/v1/settings/line-allocation/",
        SettingsLineAllocationView.as_view(),
        name="settings_line_allocation",
    ),
    # F5.4.1 — B26/B27/B28: user (GET/POST + PUT/DELETE soft), role (GET), katalog
    # profil device (GET). Semua `IsAuthenticated`; users/devices tambahan syarat
    # admin/owner (dicek di view via `_require_admin`).
    path("api/v1/settings/users/", SettingsUsersView.as_view(), name="settings_users"),
    path(
        "api/v1/settings/users/<int:user_id>/",
        SettingsUserDetailView.as_view(),
        name="settings_user_detail",
    ),
    path("api/v1/settings/roles/", SettingsRolesView.as_view(), name="settings_roles"),
    # H5.4 — matrix izin role × resource × action (Opsi A′: profil tersimpan + viewer
    # efektif; enforcement TETAP hardcoded di kode). GET = matrix, PUT per role = bulk.
    path(
        "api/v1/settings/permissions/",
        SettingsPermissionsView.as_view(),
        name="settings_permissions",
    ),
    path(
        "api/v1/settings/permissions/<int:role_id>/",
        SettingsPermissionRoleView.as_view(),
        name="settings_permission_role",
    ),
    path(
        "api/v1/settings/devices/",
        SettingsDevicesView.as_view(),
        name="settings_devices",
    ),
    # FASE 4.4 — monitoring **read-only** (frontend): daftar SyncRecord & antrean
    # invoice. "finance" BUKAN nama industri, jadi WAJIB didaftarkan di section
    # kontrak core ini (SEBELUM `include` industri) supaya tidak tertangkap pola
    # `v1/<industry>/<resource>/`.
    path(
        "api/v1/sync/records/",
        SyncRecordListView.as_view(),
        name="sync_records",
    ),
    path(
        "api/v1/finance/invoices/",
        InvoiceListView.as_view(),
        name="finance_invoices",
    ),
    # Riwayat rekonsiliasi stok MES vs Odoo (Fase I7) — **baca** saja.
    # Route kontrak core: WAJIB sebelum include industri supaya
    # `/api/v1/reconciliation/report/` tidak dianggap pola `v1/<industry>/...`
    # (juga lolos dari guard whitelist industri).
    path(
        "api/v1/reconciliation/report/",
        ReconciliationReportView.as_view(),
        name="reconciliation_report",
    ),
    # Audit produk tanpa odoo_id (Fase I8.8) — **baca** saja; menjelaskan
    # kenapa rekonsiliasi/invoice bisa "kekurangan" data.
    path(
        "api/v1/audit/products-missing-odoo-id/",
        ProductAuditView.as_view(),
        name="audit_products_missing_odoo_id",
    ),
    # Kesiapan material per Order (Fase I3): baca + recompute manual.
    # WAJIB di sini (section kontrak core, SEBELUM include industri) supaya
    # `/api/v1/garmen/orders/<id>/readiness/` tidak tertangkap pola industri
    # `v1/<industry>/<resource>/<id>/<action>/` (ActionView) milik URL app garment.
    path(
        "api/v1/garmen/orders/<int:order_id>/readiness/",
        OrderReadinessView.as_view(),
        name="order_readiness",
    ),
    path(
        "api/v1/garmen/orders/<int:order_id>/recompute-readiness/",
        OrderReadinessView.as_view(),
        name="order_recompute_readiness",
    ),
    # Fase F — cetak thermal ESC/POS. Didaftarkan SEBELUM include industri supaya
    # `print`/`wa`/`ai` tidak pernah dianggap nama industri (guard Fase A).
    path(
        "api/v1/print/bundle-tag/",
        PrintBundleTagView.as_view(),
        name="print_bundle_tag",
    ),
    path(
        "api/v1/print/bundle-tag",
        PrintBundleTagView.as_view(),
        name="print_bundle_tag_noslash",
    ),
    path("api/v1/print/kupon/", PrintCouponView.as_view(), name="print_coupon"),
    path("api/v1/print/kupon", PrintCouponView.as_view(), name="print_coupon_noslash"),
    # Fase F — WhatsApp (gateway mock, `WA_BACKEND`).
    path("api/v1/wa/send/", WASendView.as_view(), name="wa_send"),
    path("api/v1/wa/send", WASendView.as_view(), name="wa_send_noslash"),
    # Fase F — AI chat stub: SELALU 200 `{ok:false, reason:"not_implemented"}`
    # (bukan 404) supaya `ai-chat.ts` dapat respons valid. Alias tanpa `v1`
    # disediakan karena brief menyebut jalur `POST /ai/chat`.
    path("api/v1/ai/chat", AiChatView.as_view(), name="ai_chat"),
    path("api/v1/ai/chat/", AiChatView.as_view(), name="ai_chat_slash"),
    path("api/ai/chat", AiChatView.as_view(), name="ai_chat_root"),
    # F5.4.2 / B29 — HITL queue (approval manusia). `ai` BUKAN nama industri →
    # WAJIB di section kontrak core (SEBELUM `include` industri).
    path("api/v1/ai/hitl/queue/", HitlQueueView.as_view(), name="hitl_queue"),
    path(
        "api/v1/ai/hitl/<int:request_id>/approve/",
        HitlApproveView.as_view(),
        name="hitl_approve",
    ),
    path(
        "api/v1/ai/hitl/<int:request_id>/reject/",
        HitlRejectView.as_view(),
        name="hitl_reject",
    ),
    # F5.4.2 / B30 — agregat stok per lokasi (read-only). `inventory` bukan nama
    # industri (industri = `garmen`), jadi didaftarkan di sini juga.
    path(
        "api/v1/inventory/reporting/",
        InventoryReportingView.as_view(),
        name="inventory_reporting",
    ),
    # F6.1 — auth hybrid (session login + kode operator + cookie device).
    # `auth` BUKAN nama industri → WAJIB di section kontrak core ini (SEBELUM
    # `include` industri) supaya tidak tertangkap pola
    # `v1/<industry>/<resource>/...` milik URL app garment.
    # Alias tanpa trailing slash disediakan untuk endpoint POST: redirect
    # `APPEND_SLASH` pada POST membuang body JSON-nya.
    path("api/v1/auth/login/", AuthLoginView.as_view(), name="auth_login"),
    path("api/v1/auth/login", AuthLoginView.as_view(), name="auth_login_noslash"),
    path(
        "api/v1/auth/login-operator/",
        AuthLoginOperatorView.as_view(),
        name="auth_login_operator",
    ),
    path(
        "api/v1/auth/login-operator",
        AuthLoginOperatorView.as_view(),
        name="auth_login_operator_noslash",
    ),
    path("api/v1/auth/logout/", AuthLogoutView.as_view(), name="auth_logout"),
    path("api/v1/auth/logout", AuthLogoutView.as_view(), name="auth_logout_noslash"),
    path("api/v1/auth/me/", AuthMeView.as_view(), name="auth_me"),
    path("api/v1/auth/me", AuthMeView.as_view(), name="auth_me_noslash"),
    path(
        "api/v1/auth/change-password/",
        AuthChangePasswordView.as_view(),
        name="auth_change_password",
    ),
    path(
        "api/v1/auth/change-password",
        AuthChangePasswordView.as_view(),
        name="auth_change_password_noslash",
    ),
    path(
        "api/v1/auth/reset-password/<int:user_id>/",
        AuthResetPasswordView.as_view(),
        name="auth_reset_password",
    ),
    path(
        "api/v1/auth/reset-password/<int:user_id>",
        AuthResetPasswordView.as_view(),
        name="auth_reset_password_noslash",
    ),
    # H3.4 — read-only master reference untuk form Journal Entry:
    # `/api/v1/master/accounts/` (chart of accounts, hasil pull Odoo) dan
    # `/api/v1/master/journals/` (buku besar mirror I1 + `journal_type`).
    # Keduanya GET-only (POST/PUT/DELETE → 405); "master" BUKAN nama industri.
    path(
        "api/v1/master/accounts/",
        MasterAccountListView.as_view(),
        name="master_accounts",
    ),
    path(
        "api/v1/master/accounts/<int:account_id>/",
        MasterAccountDetailView.as_view(),
        name="master_account_detail",
    ),
    path(
        "api/v1/master/journals/",
        MasterJournalListView.as_view(),
        name="master_journals",
    ),
    path(
        "api/v1/master/journals/<int:journal_id>/",
        MasterJournalDetailView.as_view(),
        name="master_journal_detail",
    ),
    # H1.1 — CRUD master Product (`/api/v1/master/products/`, MES = source of truth).
    # "master" BUKAN nama industri (whitelist `garmen`) dan "products" bukan resource
    # registry industri, jadi WAJIB didaftarkan di section kontrak core ini (SEBELUM
    # `include` industri) supaya tidak jatuh ke 404 / pola `v1/<industry>/...`.
    # GET/POST di list, GET/PUT/DELETE di detail (DELETE = soft delete `active=False`).
    path(
        "api/v1/master/products/",
        MasterProductListCreateView.as_view(),
        name="master_products",
    ),
    path(
        "api/v1/master/products/<int:product_id>/",
        MasterProductDetailView.as_view(),
        name="master_product_detail",
    ),
    # H3.5 — harga produk: update khusus + riwayat (audit trail dari AuditLog).
    # Didaftarkan SETELAH detail produk (path lebih spesifik, tidak saling menutup).
    path(
        "api/v1/master/products/<int:product_id>/price/",
        MasterProductPriceView.as_view(),
        name="master_product_price",
    ),
    path(
        "api/v1/master/products/<int:product_id>/price-history/",
        MasterProductPriceHistoryView.as_view(),
        name="master_product_price_history",
    ),
    # H3.6 — CRUD master Tax (`/api/v1/master/taxes/`, MES = source of truth).
    # Resource baru `master.tax` (SyncRecord) + task `erp_sync.push_master_tax`.
    # Izin tulis ADMIN/OWNER (master config keuangan); DELETE = soft delete
    # `active=False` (relasi tax_ids H2.1/H2.2 tetap utuh).
    path(
        "api/v1/master/taxes/",
        MasterTaxListCreateView.as_view(),
        name="master_taxes",
    ),
    # Didaftarkan SEBELUM detail (`<int:tax_id>`) supaya jelas & tidak ambigu.
    path(
        "api/v1/master/taxes/default/",
        MasterTaxDefaultView.as_view(),
        name="master_tax_default",
    ),
    path(
        "api/v1/master/taxes/<int:tax_id>/",
        MasterTaxDetailView.as_view(),
        name="master_tax_detail",
    ),
    path(
        "api/v1/master/taxes/<int:tax_id>/set-default/",
        MasterTaxSetDefaultView.as_view(),
        name="master_tax_set_default",
    ),
    # H1.2 — CRUD master UoM (`/api/v1/master/uoms/`). Resource baru
    # `master.uom` (SyncRecord) + task `erp_sync.push_master_uom`. Izin tulis
    # ADMIN/OWNER; DELETE = soft delete `active=False`.
    path(
        "api/v1/master/uoms/",
        MasterUomListCreateView.as_view(),
        name="master_uoms",
    ),
    path(
        "api/v1/master/uoms/<int:uom_id>/",
        MasterUomDetailView.as_view(),
        name="master_uom_detail",
    ),
    # H1.3 — CRUD master Warehouse (`/api/v1/master/warehouses/`). Resource baru
    # `master.warehouse` (SyncRecord) + task `erp_sync.push_master_warehouse`
    # (update-only: create butuh lokasi/company → menunggu H1.4). Izin tulis
    # ADMIN/OWNER; DELETE = soft delete `active=False`.
    path(
        "api/v1/master/warehouses/",
        MasterWarehouseListCreateView.as_view(),
        name="master_warehouses",
    ),
    path(
        "api/v1/master/warehouses/<int:warehouse_id>/",
        MasterWarehouseDetailView.as_view(),
        name="master_warehouse_detail",
    ),
    # H1.4 — CRUD master Location (`/api/v1/master/locations/`, hierarki parent/child).
    # Resource baru `master.location` (SyncRecord) + task `erp_sync.push_master_location`
    # (create BOLEH: Odoo hanya wajib name+usage). Izin tulis ADMIN/OWNER; DELETE =
    # soft delete, ditolak 400 kalau masih punya anak aktif.
    path(
        "api/v1/master/locations/",
        MasterLocationListCreateView.as_view(),
        name="master_locations",
    ),
    path(
        "api/v1/master/locations/<int:location_id>/",
        MasterLocationDetailView.as_view(),
        name="master_location_detail",
    ),
    # H1.5 — CRUD master BOM (`/api/v1/master/boms/`), baris komponen INLINE via
    # `lines[]`. Resource `master.bom` (SyncRecord) + task `erp_sync.push_master_bom`
    # (header + baris; create BOLEH, guard = product harus punya odoo_tmpl_id).
    # Izin tulis ADMIN/OWNER; DELETE = soft delete (tanpa guard dependensi).
    path(
        "api/v1/master/boms/",
        MasterBomListCreateView.as_view(),
        name="master_boms",
    ),
    path(
        "api/v1/master/boms/<int:bom_id>/",
        MasterBomDetailView.as_view(),
        name="master_bom_detail",
    ),
    # H1.6 — CRUD master Partner (`/api/v1/master/partners/`, customer + supplier).
    # Resource `master.partner` (SyncRecord) + task `erp_sync.push_master_partner`
    # (create BOLEH: res.partner tidak mewajibkan field apa pun selain name).
    # Izin tulis ADMIN/OWNER; DELETE = soft delete (Order.customer PROTECT tidak
    # pernah terpicu karena tidak ada hard delete).
    path(
        "api/v1/master/partners/",
        MasterPartnerListCreateView.as_view(),
        name="master_partners",
    ),
    path(
        "api/v1/master/partners/<int:partner_id>/",
        MasterPartnerDetailView.as_view(),
        name="master_partner_detail",
    ),
    # H1.7 — CRUD master Work Center (`/api/v1/master/work-centers/`).
    # MES-only: model `garment.WorkCenter` (dipakai bundle/routing/device/scrap).
    # TIDAK ada push/pull Odoo — probe `mrp.workcenter` Odoo 17 mewajibkan
    # `resource_id` (resource.resource, tanpa default) + `sequence` dan tidak punya
    # padanan wc_type/capability_tags/capacity_per_hour → push = mengarang data.
    # Ledger sync tetap ditulis dengan status SKIPPED (lihat `/sync/records/`).
    # Izin tulis ADMIN/OWNER; DELETE = soft delete + guard bundle aktif.
    path(
        "api/v1/master/work-centers/",
        MasterWorkCenterListCreateView.as_view(),
        name="master_work_centers",
    ),
    path(
        "api/v1/master/work-centers/<int:work_center_id>/",
        MasterWorkCenterDetailView.as_view(),
        name="master_work_center_detail",
    ),
    # H1.8 — CRUD master Production Line (`/api/v1/master/production-lines/`).
    # MES-only: model `garment.ProductionLine` (dipakai capability_allocator,
    # Bundle.production_line, LineAllocationRule). TIDAK ada push/pull Odoo — probe
    # Odoo 17: `mrp.routing` sudah dihapus, `mrp.routing.workcenter` = Operation
    # per-BoM (bom_id + workcenter_id) → tidak ada wadah "lini". Ledger sync ditulis
    # SKIPPED. M2M `work_centers` ditulis via `work_centers.set()` (atomic).
    # Izin tulis ADMIN/OWNER; DELETE = soft delete + guard bundle aktif.
    path(
        "api/v1/master/production-lines/",
        MasterProductionLineListCreateView.as_view(),
        name="master_production_lines",
    ),
    path(
        "api/v1/master/production-lines/<int:production_line_id>/",
        MasterProductionLineDetailView.as_view(),
        name="master_production_line_detail",
    ),
    # H2.1 — Sales Order MES (transaksi; sync SATU ARAH MES → Odoo). Didaftarkan
    # SEBELUM include industri supaya `/garmen/orders/<id>/confirm/` tidak jatuh ke
    # ActionView (`v1/<industry>/<resource>/<id>/<action>/`). Nomor SO dari Sprint C
    # (`next_number("SO")`); push `sale.order` create-draft saat CONFIRMED.
    path("api/v1/garmen/orders/", OrdersView.as_view(), name="orders"),
    path(
        "api/v1/garmen/orders/<int:order_id>/",
        OrderDetailView.as_view(),
        name="order_detail",
    ),
    # H2.3 — batch generate WO dari Order. ⚠️ WAJIB SEBELUM pola `<str:action>` di
    # bawah, karena "generate-wo" juga cocok dengan `<str:action>` dan akan jatuh ke
    # `OrderActionView` (404 "aksi tidak dikenal") kalau urutannya terbalik.
    path(
        "api/v1/garmen/orders/<int:order_id>/generate-wo/",
        OrderGenerateWorkOrdersView.as_view(),
        name="order_generate_wo",
    ),
    path(
        "api/v1/garmen/orders/<int:order_id>/<str:action>/",
        OrderActionView.as_view(),
        name="order_action",
    ),
    # H2.2 — Purchase Order MES (transaksi; sync SATU ARAH MES → Odoo). Path
    # `/garmen/purchase-orders/…` DIPILIH karena `/api/v1/purchase/orders/` sudah
    # dipakai B10 (monitoring read-only dari Odoo, baris di-pin 9 key oleh
    # tests/integration/test_purchase_orders.py) ⇒ tidak boleh ditimpa CRUD.
    # `sync-odoo-state/` didaftarkan SEBELUM pola `<str:action>` supaya tidak
    # tertangkap sebagai aksi transisi. Nomor PO dari Sprint C (`next_number('PO')`),
    # dikirim ke Odoo sebagai `partner_ref`; push `purchase.order` create-draft.
    path(
        "api/v1/garmen/purchase-orders/",
        PurchaseOrdersCrudView.as_view(),
        name="purchase_orders_mes",
    ),
    path(
        "api/v1/garmen/purchase-orders/<int:purchase_order_id>/sync-odoo-state/",
        PurchaseOrderSyncStateView.as_view(),
        name="purchase_order_sync_state",
    ),
    path(
        "api/v1/garmen/purchase-orders/<int:purchase_order_id>/",
        PurchaseOrderDetailView.as_view(),
        name="purchase_order_detail",
    ),
    path(
        "api/v1/garmen/purchase-orders/<int:purchase_order_id>/<str:action>/",
        PurchaseOrderActionView.as_view(),
        name="purchase_order_action",
    ),
    # H3.1 — Customer Invoice MES (transaksi; sync SATU ARAH MES → Odoo, draft).
    # Path `/finance/customer-invoices/…` DIPILIH karena `/api/v1/finance/invoices/`
    # sudah dipakai F10/F15 (`monitoring.InvoiceListView`, read-only dari SyncRecord
    # dengan amplop `has_next`) ⇒ tidak boleh ditimpa CRUD. Nomor invoice dari
    # Sprint C (`next_number('INV')`); push `account.move` create-draft + `button_cancel`
    # saat dibatalkan. Resource ledger `customer_invoice` (stage `INVOICE` di-reuse).
    path(
        "api/v1/finance/customer-invoices/",
        CustomerInvoicesView.as_view(),
        name="customer_invoices",
    ),
    path(
        "api/v1/finance/customer-invoices/<int:invoice_id>/",
        CustomerInvoiceDetailView.as_view(),
        name="customer_invoice_detail",
    ),
    path(
        "api/v1/finance/customer-invoices/<int:invoice_id>/<str:action>/",
        CustomerInvoiceActionView.as_view(),
        name="customer_invoice_action",
    ),
    # H3.2 — Vendor Bill MES (transaksi; sync SATU ARAH MES → Odoo, draft
    # `account.move` **in_invoice**). Path dipilih konsisten H3.1 & bebas bentrok:
    # `/finance/invoices/` (F10/F15) + `/purchase/*` (B10/B11/B12) + 
    # `/garmen/purchase-orders/` (H2.2) tidak tersentuh. Nomor dari Sprint C
    # (`next_number('VB')`); resource ledger `vendor_bill`, stage `VENDOR_BILL`
    # (BARU — bukan reuse `INVOICE` milik customer invoice). Jalur I6
    # (`fetch_vendor_bills` → `MaterialReadiness.vendor_bill_*`) tetap read-only:
    # tidak punya endpoint CRUD di MES, jadi tidak bertabrakan.
    path(
        "api/v1/finance/vendor-bills/",
        VendorBillsView.as_view(),
        name="vendor_bills",
    ),
    path(
        "api/v1/finance/vendor-bills/<int:bill_id>/",
        VendorBillDetailView.as_view(),
        name="vendor_bill_detail",
    ),
    path(
        "api/v1/finance/vendor-bills/<int:bill_id>/<str:action>/",
        VendorBillActionView.as_view(),
        name="vendor_bill_action",
    ),
    # H3.3 — Payment MES (transaksi; sync SATU ARAH MES → Odoo, draft
    # `account.payment` — satu model dua arah lewat `payment_type`). Path
    # `/finance/payments/…` BARU & bebas bentrok (`/finance/invoices/` F15,
    # `/finance/customer-invoices/` H3.1, `/finance/vendor-bills/` H3.2 tetap).
    # Nomor dari Sprint C (`next_number('PAY')`); resource ledger `payment`, stage
    # `PAYMENT` (keduanya baru). Rekonsiliasi TIDAK dilakukan MES (akuntan Odoo).
    path(
        "api/v1/finance/payments/",
        PaymentsView.as_view(),
        name="payments",
    ),
    path(
        "api/v1/finance/payments/<int:payment_id>/",
        PaymentDetailView.as_view(),
        name="payment_detail",
    ),
    path(
        "api/v1/finance/payments/<int:payment_id>/<str:action>/",
        PaymentActionView.as_view(),
        name="payment_action",
    ),
    # H3.4 — Journal Entry manual MES (transaksi; sync SATU ARAH MES → Odoo, draft
    # `account.move` `move_type='entry'`). Path `/finance/journal-entries/…` BARU &
    # bebas bentrok (`/finance/invoices/` F15, `/finance/customer-invoices/` H3.1,
    # `/finance/vendor-bills/` H3.2, `/finance/payments/` H3.3 tetap). Nomor dari
    # Sprint C (`next_number('JE')`); resource ledger `journal_entry`, stage
    # `JOURNAL_ENTRY` (keduanya baru). Posting/rekonsiliasi TIDAK dilakukan MES.
    path(
        "api/v1/finance/journal-entries/",
        JournalEntriesView.as_view(),
        name="journal_entries",
    ),
    path(
        "api/v1/finance/journal-entries/<int:entry_id>/",
        JournalEntryDetailView.as_view(),
        name="journal_entry_detail",
    ),
    path(
        "api/v1/finance/journal-entries/<int:entry_id>/<str:action>/",
        JournalEntryActionView.as_view(),
        name="journal_entry_action",
    ),
    # H2.3 — Work Order MES: create (POST) + list (GET delegasi F3/AllowAny). Route ini
    # MENIMPA jalur generik F2 untuk industri `garmen` (kode default memakai Sprint C
    # `next_number("WO")`, plus ledger SKIPPED + audit) sambil mempertahankan kontrak
    # F2: `order_line_id` wajib, `state="DRAFT"`, `qty_planned` default `OrderLine.qty`,
    # dan 404 kalau order line tidak ada.
    path(
        "api/v1/garmen/work-orders/",
        WorkOrderCreateCrudView.as_view(),
        name="work_order_create_crud",
    ),
    # H2.3 — PUT/DELETE/Split. Didaftarkan SEBELUM `include()` industri supaya
    # `PUT/DELETE /garmen/work-orders/<id>/` tidak tertangkap `ResourceDetailView`
    # (GET-only → 405) dan `/split/` tidak jatuh ke ActionView. `GET` pada path detail
    # ini memakai kontrak F3 (serializer + version yang sama).
    path(
        "api/v1/garmen/work-orders/<int:work_order_id>/split/",
        WorkOrderSplitView.as_view(),
        name="work_order_split",
    ),
    path(
        "api/v1/garmen/work-orders/<int:work_order_id>/",
        WorkOrderDetailCrudView.as_view(),
        name="work_order_detail_crud",
    ),
    # H2.3 — batch generate WO dari Order (lihat juga pendaftaran kanonik SEBELUM
    # pola `<str:action>` H2.1 di atas; blok di sini hanya penanda urutan).
    # H2.4 — Bundle MES: create (POST) + list ber-filter (GET). Route ini MENIMPA jalur
    # generik F2 untuk industri `garmen` (create memakai service H2.4: dukung
    # `work_order_id`, ledger SKIPPED + audit) sambil mempertahankan kontrak F2/F3:
    # baris list tetap 9 key, `order_line_id` masih diterima, guard DRAFT/idempoten sama.
    path(
        "api/v1/garmen/bundles/preview/",
        BundlePreviewView.as_view(),
        name="bundle_preview",
    ),
    path(
        "api/v1/garmen/bundles/<int:bundle_id>/split/",
        BundleSplitView.as_view(),
        name="bundle_split",
    ),
    path(
        "api/v1/garmen/bundles/<int:bundle_id>/merge/",
        BundleMergeView.as_view(),
        name="bundle_merge",
    ),
    path(
        "api/v1/garmen/bundles/<int:bundle_id>/",
        BundleDetailCrudView.as_view(),
        name="bundle_detail_crud",
    ),
    path(
        "api/v1/garmen/bundles/",
        BundleListCreateView.as_view(),
        name="bundle_list_create",
    ),
    # H2.5 — Inventory Adjustment (LOG MES → Odoo). Didaftarkan SEBELUM `include()`
    # industri supaya `POST /inventory/adjust/` & `.../commit/` tidak jatuh ke
    # `ResourceDetailView`/`ActionView` generik. TIDAK menabrak B7/B8/B30
    # (`/inventory/products/`, `/inventory/operations/`, `/inventory/reporting/`).
    path(
        "api/v1/inventory/stock-qty/",
        InventoryStockQtyView.as_view(),
        name="inventory_stock_qty",
    ),
    path(
        "api/v1/inventory/adjustments/<int:adjustment_id>/commit/",
        InventoryAdjustmentCommitView.as_view(),
        name="inventory_adjustment_commit",
    ),
    path(
        "api/v1/inventory/adjustments/<int:adjustment_id>/",
        InventoryAdjustmentDetailView.as_view(),
        name="inventory_adjustment_detail",
    ),
    path(
        "api/v1/inventory/adjustments/",
        InventoryAdjustmentListCreateView.as_view(),
        name="inventory_adjustment_list_create",
    ),
    path(
        "api/v1/inventory/adjust/",
        InventoryAdjustmentListCreateView.as_view(),
        name="inventory_adjust",
    ),
    # H2.6 — Stock Transfer (LOG MES → Odoo via stock.picking internal + button_validate).
    # Didaftarkan SEBELUM `include()` industri supaya `/transfer/` & `.../commit/` tidak
    # jatuh ke ResourceDetailView/ActionView generik. TIDAK menabrak B7/B8/B30/H2.5.
    path(
        "api/v1/inventory/transfers/<int:transfer_id>/commit/",
        StockTransferCommitView.as_view(),
        name="stock_transfer_commit",
    ),
    path(
        "api/v1/inventory/transfers/<int:transfer_id>/",
        StockTransferDetailView.as_view(),
        name="stock_transfer_detail",
    ),
    path(
        "api/v1/inventory/transfers/",
        StockTransferListCreateView.as_view(),
        name="stock_transfer_list_create",
    ),
    path(
        "api/v1/inventory/transfer/",
        StockTransferListCreateView.as_view(),
        name="stock_transfer_create",
    ),
    # 3) API industri (catch-all) — PALING AKHIR, jangan dinaikkan urutannya.
    path("api/", include("apps_industry.garment.api.urls")),
]

