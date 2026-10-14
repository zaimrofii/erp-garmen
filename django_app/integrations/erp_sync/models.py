"""Model jejak sinkronisasi ERP dua tahap — `SyncRecord` (Fase 4).

Satu baris = satu pergerakan stok yang **harus** dikirim ke ERP untuk
kombinasi (resource, resource_id, stage) tertentu.

Unique constraint ``(resource, resource_id, stage)`` adalah kunci idempotensi
two-stage sync:

* satu bundle boleh punya maksimal **satu** record ``WIP`` dan **satu** record
  ``FG`` (dua tahap stok berbeda);
* satu ``ScrapAccumulator`` = satu record ``SCRAP`` dan satu ``Order`` = satu
  record ``INVOICE`` (Fase I4/I5);
* retry pengiriman meng-update baris yang sama (``attempts`` naik, ``status``
  berubah) — **bukan** membuat baris/kiriman baru. Ini yang mencegah stok
  dobel di Odoo waktu jaringan lantai produksi putus lalu request diulang.

Tabel ini juga jadi audit trail: kapan dikirim, id record di ERP, dan error
terakhir kalau gagal.
"""

from __future__ import annotations

from django.db import models

from .adapters.base import STAGE_FG, STAGE_WIP
from .adapters.odoo import STAGE_INVOICE, STAGE_SCRAP


#: Stage sinkronisasi **master data** (dua arah: MES → Odoo & Odoo → MES).
#: Nilainya di kedua arah dibedakan supaya jejak `SyncRecord` bisa dibaca
#: (\"baris ini MES yang push atau hasil tarikan Odoo\").
STAGE_MASTER_PUSH = "MASTER_PUSH"
STAGE_MASTER_PULL = "MASTER_PULL"


#: H2.1 — stage transaksi **Sales Order MES → Odoo** (satu arah, resource `order`).
#: Dipisah dari `MASTER_PUSH` (jejak master H1) dan dari `INVOICE` (invoice Fase I4)
#: supaya monitor sync bisa membedakan jenis pengiriman.
STAGE_SALE_ORDER_PUSH = "SALE_ORDER_PUSH"

#: H2.2 — stage transaksi **Purchase Order MES → Odoo** (satu arah, resource
#: `purchase_order`). Panjangnya 19 karakter ⇒ kolom `stage` diperlebar ke 24
#: (migration `erp_sync.0015`), karena sebelumnya `max_length=16`.
STAGE_PURCHASE_ORDER_PUSH = "PURCHASE_ORDER_PUSH"

#: H2.3 — jejak CUD **Work Order** (MES-only). Ledger tetap ditulis dengan status
#: `SKIPPED`: Odoo `mrp.workorder` = operasi per `mrp.production` (`production_id`
#: required & readonly) dan `sale.order.line` tidak punya field workorder ⇒ TIDAK ada
#: padanan WO MES (probe STEP 0). Stage dipisah dari `WIP`/`FG` yang sudah memakai
#: resource yang sama (`work_order`) untuk pergerakan stok dua tahap.
STAGE_WORK_ORDER_PUSH = "WORK_ORDER_PUSH"

#: H2.4 — jejak CUD **Bundle** (MES-only). Ledger ditulis `SKIPPED`: probe H2.4
#: membuktikan Odoo **tidak punya model bundle** (`garment.bundle`/`mrp.bundle`/
#: `stock.bundle` tidak ada) dan tidak ada field `bundle` di `stock.move`/`stock.picking`.
#: PENTING: stage ini HANYA untuk perubahan **OBJEK** bundle (create/update/delete/
#: split/merge); **pergerakan stok** bundle tetap memakai stage `WIP`/`FG` yang sudah
#: ada (jangan dibongkar) — itu sebabnya stage-nya dipisah walau resourcenya sama.
STAGE_BUNDLE_PUSH = "BUNDLE_PUSH"

#: H2.5 — **Inventory Adjustment** MES → Odoo (transaksi NYATA, bukan MES-only).
#: Jejak ledger memakai siklus penuh `PENDING → SENT/FAILED` (pola H2.1/H2.2), karena
#: adjustment benar-benar dikirim ke Odoo lewat jalur resmi
#: `stock.quant` (context `inventory_mode=True`, tulis `inventory_quantity`) →
#: `action_apply_inventory()` yang di dalamnya membuat `stock.move` + `_action_done()`.
#: Panjangnya 16 karakter ⇒ masih muat kolom `stage` (max_length 24).
STAGE_INVENTORY_ADJUST = "INVENTORY_ADJUST"

#: H3.2 — **Vendor Bill** MES → Odoo (transaksi: `account.move` `in_invoice` draft).
#: Stage BARU (bukan reuse `INVOICE` milik I5/H3.1) karena konsep beda: `INVOICE`
#: berlabel "Customer Invoice" (`out_invoice`) sedangkan H3.2 mengirim **tagihan
#: vendor** (`in_invoice`) — dipisah supaya monitor sync tidak ambigu. 11 karakter ⇒
#: masih muat kolom `stage` (`max_length=24`).
STAGE_VENDOR_BILL = "VENDOR_BILL"

#: H3.3 — **Payment** MES → Odoo (transaksi: `account.payment` draft, satu model dua
#: arah lewat `payment_type` `inbound`/`outbound`). Stage BARU (bukan reuse stage lain)
#: supaya monitor sync bisa membedakan pembayaran dari invoice/bill; 7 karakter ⇒ muat
#: kolom `stage` (`max_length=24`).
STAGE_PAYMENT = "PAYMENT"

#: H2.6 — **Stock Transfer** MES → Odoo (internal transfer antar lokasi internal).
#: Transaksi NYATA (bukan MES-only) ⇒ ledger memakai siklus penuh `PENDING → SENT/FAILED`.
#: Jalur Odoo 17 (probe STEP 0 + sumber `stock/models/stock_picking.py`): `stock.picking`
#: + `button_validate()` (method PUBLIK yang di dalamnya `action_confirm()` →
#: auto-isi `quantity` → auto-`picked` → `_action_done()`); `stock.move` + `_action_done()`
#: langsung TIDAK bisa via RPC karena `_action_done` private. 14 karakter.
STAGE_STOCK_TRANSFER = "STOCK_TRANSFER"


#: H3.4 — **Journal Entry manual** MES → Odoo (transaksi: `account.move`
#: `move_type='entry'` **draft**). Stage BARU (bukan reuse `INVOICE`/`VENDOR_BILL`
#: yang membawa dokumen dagang) supaya monitor sync tidak ambigu: entry ini murni
#: double-entry akuntan (tanpa partner/total dokumen), `move_type='entry'`.
STAGE_JOURNAL_ENTRY = "JOURNAL_ENTRY"


class SyncResource(models.TextChoices):
    """Resource domain yang disinkronkan ke ERP."""

    BUNDLE = "bundle", "Bundle"
    WORK_ORDER = "work_order", "Work Order"
    SCRAP_ACCUMULATOR = "scrap_accumulator", "Scrap Accumulator"
    ORDER = "order", "Order"
    # H2.5 — Inventory Adjustment (log adjustment MES; stok tetap di Odoo).
    INVENTORY_ADJUSTMENT = "inventory_adjustment", "Inventory Adjustment"
    # H2.6 — Stock Transfer (log transfer antar lokasi internal; stok tetap di Odoo).
    STOCK_TRANSFER = "stock_transfer", "Stock Transfer"
    # H1.1 — master Product (MES = source of truth; Odoo = back-office pasif).
    MASTER_PRODUCT = "master.product", "Master Product"
    # H1.2 — master UoM (`uom.uom` Odoo).
    MASTER_UOM = "master.uom", "Master UoM"
    # H1.3 — master Warehouse (`stock.warehouse` Odoo).
    MASTER_WAREHOUSE = "master.warehouse", "Master Warehouse"
    # H1.4 — master Location (`stock.location` Odoo).
    MASTER_LOCATION = "master.location", "Master Location"
    # H1.5 — master BOM (`mrp.bom` Odoo; baris `mrp.bom.line` di-push menyatu
    # dengan header-nya, jadi TIDAK ada resource terpisah untuk baris).
    MASTER_BOM = "master.bom", "Master BOM"
    # H1.6 — master Partner (`res.partner` Odoo: customer + supplier).
    MASTER_PARTNER = "master.partner", "Master Partner"
    # H1.7 — master Work Center (MES-only: `mrp.workcenter` Odoo butuh
    # `resource_id` yang tidak ada di MES → ledger ditulis dengan status SKIPPED).
    MASTER_WORK_CENTER = "master.work_center", "Master Work Center"
    # H1.8 — master Production Line (MES-only: Odoo 17 tidak punya wadah lini —
    # `mrp.routing` sudah dihapus, `mrp.routing.workcenter` = Operation per-BoM).
    MASTER_PRODUCTION_LINE = "master.production_line", "Master Production Line"
    # H1.9 — master Process Routing / DAG (MES-only: `mrp.routing` tidak ada di
    # Odoo 17; `mrp.routing.workcenter` = Operation per-BoM, bukan DAG routing).
    MASTER_PROCESS_ROUTING = "master.process_routing", "Master Process Routing"
    # H3.6 — master Tax (`account.tax` Odoo): CRUD pajak + tarif/jenis dari MES.
    MASTER_TAX = "master.tax", "Master Tax"
    # H3.1 — Customer Invoice MES (`account.move` out_invoice). Resource BARU untuk
    # model `CustomerInvoice` (jalur MANUAL); I5 tetap memakai resource `order`
    # dengan stage `INVOICE` yang sama (dua jalur coexist, tidak saling menimpa).
    CUSTOMER_INVOICE = "customer_invoice", "Customer Invoice"
    # Sprint C — penomoran dokumen MES (<prefix>-<year>-<seq:04d>). MES-only:
    # `ir.sequence` Odoo = counter internal dokumen Odoo sendiri (37 record hidup),
    # format & reset-per-tahun berbeda ⇒ nomor MES tidak dikirim (ledger SKIPPED).
    MASTER_NUMBER_SEQUENCE = "master.number_sequence", "Master Number Sequence"
    # H2.2 — Purchase Order MES (transaksi satu arah: `purchase.order.create`,
    # `partner_ref` = nomor MES `PO-<TAHUN>-<SEQ>`; cancel lewat `action_cancel`).
    PURCHASE_ORDER = "purchase_order", "Purchase Order"
    # H3.2 — Vendor Bill MES (`account.move` **in_invoice**). Resource BARU untuk
    # model `VendorBill` (jalur MANUAL/dorong); I6 tetap memakai transport
    # `fetch_vendor_bills` (tarik, read-only) + `MaterialReadiness.vendor_bill_*`
    # dan TIDAK menyentuh ledger ini (dua jalur coexist, arah berlawanan).
    VENDOR_BILL = "vendor_bill", "Vendor Bill"
    # H3.3 — Payment MES (`account.payment`, dua arah lewat `payment_type`). Resource
    # BARU untuk model `Payment`; invoice (`customer_invoice`) & bill (`vendor_bill`)
    # tetap resource-nya sendiri (payment tidak menulis ledger mereka).
    PAYMENT = "payment", "Payment"
    # H3.4 — Journal Entry manual MES (`account.move` `move_type='entry'` draft).
    # Resource BARU untuk model `JournalEntry` (jalur double-entry akuntan);
    # invoice/bill/payment tetap resource-nya sendiri (tidak saling menimpa).
    JOURNAL_ENTRY = "journal_entry", "Journal Entry"
    # H3.4 — master Account / chart of accounts (`account.account` Odoo) — **pull-only**
    # (pola I1: MES mirror untuk dropdown form; tidak pernah di-push ke Odoo).
    MASTER_ACCOUNT = "master.account", "Master Account"
    # H5.2 — master Currency (`res.currency` Odoo; mirror I1). **MES-only**: tidak ada
    # konsumen MES yang mengirim mata uang ke Odoo (`Payment.currency` = teks bebas;
    # invoice/journal TIDAK mengirim `currency_id` — Odoo menghitungnya) dan `rate`
    # di-maintain Odoo ⇒ ledger ditulis `SKIPPED` (pola Sprint C/H1.7–H1.9).
    MASTER_CURRENCY = "master.currency", "Master Currency"
    # H5.1 — Company Profile MES (greenfield, **singleton**). **MES-only**: tidak ada
    # konsumen MES yang memakai `res.company` dan tidak ada transport company ⇒ ledger
    # ditulis `SKIPPED` (pola H5.2/Sprint C). `res.company` = konfigurasi akuntansi Odoo.
    MASTER_COMPANY = "master.company", "Master Company"
    # H5.6 — profil konfigurasi integrasi MES ↔ Odoo (greenfield, **singleton**).
    # **MES-only**: konsumen tetap membaca `.env` (Opsi B) ⇒ ledger ditulis `SKIPPED`.
    MASTER_INTEGRATION_CONFIG = "master.integration_config", "Master Integration Config"
    # H5.8 — profil gateway WhatsApp (greenfield, **singleton**). **MES-only**:
    # konsumen (`integrations/wa_bot/services.get_wa_gateway`) tetap membaca `.env`
    # (Opsi B) ⇒ ledger ditulis `SKIPPED`.
    MASTER_WA_CONFIG = "master.wa_config", "Master WA Config"
    # H5.7 — profil printer thermal ESC/POS (greenfield, **singleton**). **MES-only**:
    # konsumen (`integrations/printing/backends.get_backend`) tetap membaca `.env`
    # (Opsi B) ⇒ ledger ditulis `SKIPPED`.
    MASTER_PRINTER_CONFIG = "master.printer_config", "Master Printer Config"
    # H5.4 — profil izin role × resource × action (greenfield, multi-row **overlay**).
    # **MES-only**: enforcement tetap hardcoded di kode (lihat model RolePermission) ⇒
    # ledger ditulis `SKIPPED`.
    ROLE_PERMISSION_MATRIX = "core_auth.role_permission", "Role Permission Matrix"


class SyncStage(models.TextChoices):
    """Tahap sync: stok (WIP/FG) + scrap + invoice + master (push/pull)."""

    WIP = STAGE_WIP, "WIP Issue"
    FG = STAGE_FG, "FG Receipt"
    SCRAP = STAGE_SCRAP, "Scrap (TX-SCRAP)"
    INVOICE = STAGE_INVOICE, "Customer Invoice"
    # H1.1 — master push (MES → Odoo) & master pull (Odoo → MES). `max_length`
    # kolom `stage` naik 8 → 16 (migration erp_sync.0004) karena "MASTER_PUSH"
    # panjangnya 11 karakter.
    MASTER_PUSH = STAGE_MASTER_PUSH, "Master Push (MES → Odoo)"
    MASTER_PULL = STAGE_MASTER_PULL, "Master Pull (Odoo → MES)"
    # H2.1 — transaksi Sales Order MES → Odoo (`sale.order.create`; cancel lewat
    # `action_cancel`). Satu arah; pull tetap memakai resource `order` tanpa stage ini.
    SALE_ORDER_PUSH = STAGE_SALE_ORDER_PUSH, "Sale Order Push (MES → Odoo)"
    # H2.2 — transaksi Purchase Order MES → Odoo (`purchase.order.create`;
    # `partner_ref` = nomor MES; cancel lewat `action_cancel`).
    PURCHASE_ORDER_PUSH = STAGE_PURCHASE_ORDER_PUSH, "Purchase Order Push (MES → Odoo)"
    # H2.3 — Work Order MES: MES-only ⇒ ledger ditulis `SKIPPED` (Odoo `mrp.workorder`
    # = operasi per `mrp.production`, bukan WO per OrderLine).
    WORK_ORDER_PUSH = STAGE_WORK_ORDER_PUSH, "Work Order (MES-only)"
    # H2.4 — Bundle MES: perubahan OBJEK (create/update/delete/split/merge) ⇒ SKIPPED;
    # pergerakan stok tetap stage WIP/FG (resource sama, stage beda).
    BUNDLE_PUSH = STAGE_BUNDLE_PUSH, "Bundle (MES-only)"
    # H2.5 — Inventory Adjustment MES → Odoo (transaksi nyata: quant + apply).
    INVENTORY_ADJUST = STAGE_INVENTORY_ADJUST, "Inventory Adjustment (MES → Odoo)"
    # H2.6 — Stock Transfer MES → Odoo (internal transfer via stock.picking).
    STOCK_TRANSFER = STAGE_STOCK_TRANSFER, "Stock Transfer (MES → Odoo)"
    # H3.2 — Vendor Bill MES → Odoo (`account.move` in_invoice draft; cancel lewat
    # `button_cancel`). Stage TERPISAH dari `INVOICE` (customer invoice, out_invoice)
    # supaya monitor sync tidak ambigu — lihat catatan `STAGE_VENDOR_BILL` di atas.
    VENDOR_BILL = STAGE_VENDOR_BILL, "Vendor Bill (MES → Odoo)"
    # H3.3 — Payment MES → Odoo (`account.payment` draft; cancel lewat `action_cancel`).
    # Satu stage untuk dua arah — arahnya ada di field `payment_type`
    # (`INBOUND`/`OUTBOUND`), bukan di stage (keputusan STEP 0).
    PAYMENT = STAGE_PAYMENT, "Payment (MES → Odoo)"
    # H3.4 — Journal Entry manual MES → Odoo (`account.move` `move_type='entry'`
    # draft; cancel lewat `button_cancel`). Satu arah; posting/rekonsiliasi di Odoo.
    JOURNAL_ENTRY = STAGE_JOURNAL_ENTRY, "Journal Entry (MES → Odoo)"


class SyncStatus(models.TextChoices):
    """Status pengiriman satu record sync."""

    PENDING = "PENDING", "Menunggu dikirim"
    SENT = "SENT", "Terkirim ke ERP"
    FAILED = "FAILED", "Gagal (boleh di-retry)"
    DUPLICATE = "DUPLICATE", "Sudah ada di ERP (duplikat diabaikan)"
    #: H1.7 — resource yang memang **tidak punya** padanan aman di ERP (mis.
    #: `master.work_center`: `mrp.workcenter` Odoo mewajibkan `resource_id` yang
    #: tidak dimiliki MES). Ledger tetap ditulis supaya setiap CUD master
    #: terlihat di monitor sync, tetapi tidak pernah di-enqueue.
    SKIPPED = "SKIPPED", "Dilewati (MES-only)"


class SyncRecord(models.Model):
    """Ledger pengiriman stok ke ERP per (resource, id, stage)."""

    resource = models.CharField(
        "resource",
        max_length=32,
        choices=SyncResource.choices,
        db_index=True,
        help_text=(
            'Domain asal data: "bundle", "work_order", "scrap_accumulator", '
            '"order", "inventory_adjustment", "stock_transfer", "vendor_bill", '
            '"payment", "journal_entry", "master.account", atau "master.product".'
        ),
    )
    resource_id = models.CharField(
        "id resource",
        max_length=64,
        db_index=True,
        help_text="PK resource domain (disimpan sebagai string agar generik).",
    )
    stage = models.CharField(
        "tahap",
        # H2.2 — `PURCHASE_ORDER_PUSH` (19 karakter) melebihi 16 ⇒ diperlebar ke 24
        # (migration `erp_sync.0015_purchase_order_push_stage`, ADITIF: nilai lama
        # tetap sah, hanya batas panjangnya naik).
        max_length=24,
        choices=SyncStage.choices,
        help_text=(
            'Tahap: "WIP", "FG", "SCRAP", "INVOICE", "MASTER_PUSH", "MASTER_PULL", '
            '"SALE_ORDER_PUSH", "PURCHASE_ORDER_PUSH", "WORK_ORDER_PUSH", '
            '"BUNDLE_PUSH", "INVENTORY_ADJUST", "STOCK_TRANSFER", "VENDOR_BILL", '
            '"PAYMENT", atau "JOURNAL_ENTRY".'
        ),
    )
    status = models.CharField(
        "status",
        max_length=16,
        choices=SyncStatus.choices,
        default=SyncStatus.PENDING,
        db_index=True,
    )
    erp_id = models.CharField(
        "id di ERP",
        max_length=64,
        null=True,
        blank=True,
        help_text="ID stock.move / picking yang dibuat di ERP (untuk rekonsiliasi).",
    )
    attempts = models.PositiveIntegerField(
        "jumlah percobaan",
        default=0,
        help_text="Dinaikkan setiap kali pengiriman gagal (dipakai backoff/alert).",
    )
    last_error = models.TextField(
        "error terakhir",
        blank=True,
        default="",
        help_text="Pesan error terakhir; dikosongkan lagi kalau sudah sukses.",
    )
    payload = models.JSONField(
        "payload",
        default=dict,
        blank=True,
        help_text="Payload yang dikirim (hasil TwoStageAggregator) — untuk replay/audit.",
    )
    sent_at = models.DateTimeField("terkirim pada", null=True, blank=True)
    created_at = models.DateTimeField("dibuat pada", auto_now_add=True)
    updated_at = models.DateTimeField("diperbarui pada", auto_now=True)

    class Meta:
        verbose_name = "Sync Record"
        verbose_name_plural = "Sync Records"
        ordering = ("id",)
        constraints = (
            models.UniqueConstraint(
                fields=("resource", "resource_id", "stage"),
                name="uniq_sync_record_resource_stage",
            ),
        )

    def __str__(self) -> str:
        return f"{self.resource}#{self.resource_id}:{self.stage} [{self.status}]"
