"""Task Celery sinkronisasi **master data** dari Odoo (read-only transport).

Isi modul ini: ``erp_sync.sync_master_*`` — menarik master data Odoo lewat
:class:`~integrations.erp_sync.transport.OdooTransport` (transport murni,
``search_read`` saja) lalu **upsert** ke model ``master.*``.

Prinsip:

* **Idempotensi via ``odoo_id``** yang sudah ada di tiap model master
  (``update_or_create(odoo_id=...)``). Repo **tidak** punya model
  ``OdooMapping`` — tidak dibuat.
* **``code`` fallback** deterministik ``f"ODOO-{id}"`` kalau baris tidak punya
  kode natural (``uom.uom``, ``res.partner``, ``account.tax``, ``res.currency``,
  atau ``product.product.default_code`` kosong) — karena ``code`` di model master
  I1.1 ``unique=True`` sehingga nilai kosong berulang akan ``IntegrityError``.
* **Tidak memanggil Odoo langsung** — selalu lewat transport.
* **Retry** hanya untuk error **transport** (``httpx.HTTPError`` /
  ``ConnectionError``); error validasi/data (mis. ``IntegrityError``) **tidak**
  di-retry.

Task bernama ``erp_sync.*`` sehingga otomatis di-route ke queue ``erp_sync``
(lihat ``CELERY_TASK_ROUTES`` di settings).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

import httpx
from celery import shared_task

from master.models import (
    BOM,
    BOMLine,
    Account,
    Currency,
    Journal,
    Location,
    Partner,
    Product,
    Tax,
    UoM,
    Warehouse,
)

from .transport import get_transport

logger = logging.getLogger(__name__)

#: Error yang layak di-retry: masalah transport/jaringan — **BUKAN** kesalahan data.
RETRY_EXCEPTIONS = (httpx.HTTPError, ConnectionError)

__all__ = (
    "RETRY_EXCEPTIONS",
    "sync_master_accounts",
    "sync_master_boms",
    "sync_master_currencies",
    "sync_master_journals",
    "sync_master_locations",
    "sync_master_partners",
    "sync_master_products",
    "sync_master_taxes",
    "sync_master_uoms",
    "sync_master_warehouses",
)


# ---------------------------------------------------------------------------
# Helper generik (upsert + pemetaan)
# ---------------------------------------------------------------------------
def _code(row, *keys):
    """Kode natural dari ``row``; fallback deterministik ``ODOO-{id}``.

    ``code`` di model master ``unique=True``, sedangkan beberapa model Odoo tidak
    punya kode natural → fallback ini mencegah ``IntegrityError``.
    """
    for key in keys:
        value = row.get(key)
        if value:
            return str(value)
    return f"ODOO-{row.get('id')}"


def _first_id(value):
    """Ambil id dari field many2one Odoo (``[id, name]`` → ``id``)."""
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value or None


def _sync(model, rows, build_defaults, skipped_when=None):
    """Upsert ``rows`` (list of dict Odoo) ke ``model`` lewat ``odoo_id``.

    Return ``{"created": N, "updated": N, "skipped": N}``. Baris tanpa ``id``
    atau yang tak bisa dipetakan (``build_defaults`` → ``None``) dihitung
    ``skipped`` (tidak melempar exception).

    ``skipped_when`` (opsional) menandai baris yang **tetap disimpan** tetapi
    dianggap belum lengkap — mis. BOM dengan ``product=None`` karena produknya
    belum tersinkron — supaya tetap muncul di laporan ``skipped``.
    """
    created = updated = skipped = 0
    for row in rows or []:
        odoo_id = row.get("id")
        defaults = build_defaults(row) if odoo_id is not None else None
        if odoo_id is None or defaults is None:
            skipped += 1
            continue
        _, was_created = model.objects.update_or_create(
            odoo_id=odoo_id, defaults=defaults
        )
        created += 1 if was_created else 0
        updated += 0 if was_created else 1
        if skipped_when is not None and skipped_when(defaults):
            skipped += 1
    return {"created": created, "updated": updated, "skipped": skipped}


def _product_unresolved(defaults):
    """True kalau ``defaults`` tidak punya ``product`` (baris disimpan tanpa FK)."""
    return defaults.get("product") is None


def _name_defaults(row, *code_keys):
    """Defaults ``{code, name}`` untuk model master sederhana."""
    return {"code": _code(row, *code_keys), "name": row.get("name") or ""}


def _product_defaults(row):
    """``product.product`` → ``master.Product`` (simpan id varian **dan** template).

    H3.5 — harga ditarik juga: ``list_price`` → ``sale_price`` dan ``standard_price``
    → ``cost_price``, **tetapi hanya diisi bila harga MES masih 0** (bootstrap produk
    baru). MES = source of truth master sedangkan beat ``sync-master-*`` berjalan
    harian (02:00) — menimpa harga MES dari Odoo = mereset harga setiap malam.
    """
    odoo_id = _first_id(row.get("id"))
    existing = Product.objects.filter(odoo_id=odoo_id).first() if odoo_id is not None else None

    defaults = {
        "code": _code(row, "default_code"),
        "name": row.get("name") or "",
        "is_active": bool(row.get("active", True)),
        "odoo_tmpl_id": _first_id(row.get("product_tmpl_id")),
    }

    for odoo_field, mes_field in (("list_price", "sale_price"), ("standard_price", "cost_price")):
        raw = row.get(odoo_field)
        if raw in (None, ""):
            continue
        if existing is not None and (getattr(existing, mes_field) or 0) > 0:
            continue
        try:
            defaults[mes_field] = Decimal(str(raw)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            logger.warning(
                "sync_master_products: harga %s produk %s tidak valid (%r) -> dilewati.",
                odoo_field,
                odoo_id,
                raw,
            )

    return defaults


def _uom_by_odoo_id(value):
    """``UoM`` dari id Odoo (``[id, name]`` / angka); ``None`` kalau belum tersinkron."""
    odoo_id = _first_id(value)

    return UoM.objects.filter(odoo_id=odoo_id).first() if odoo_id else None


def _bom_defaults(row):
    """``mrp.bom`` → ``master.BOM`` (``product`` di-resolve via ``odoo_tmpl_id``).

    ``mrp.bom.product_tmpl_id`` adalah id **template**, jadi dicari lewat
    ``Product.odoo_tmpl_id`` (bukan ``odoo_id``). Produk yang belum tersinkron
    **tidak** menggagalkan sync: BOM tetap dibuat dengan ``product=None`` (FK
    nullable) dan dihitung ``skipped`` oleh ``_sync``.

    H1.5 — sekalian memetakan ``output_qty`` (Odoo ``product_qty``), ``uom``
    (Odoo ``product_uom_id``), dan ``is_active`` (Odoo ``active``) supaya data
    tarikan sudah lengkap saat operator meng-edit BOM di MES.
    """
    tmpl_id = _first_id(row.get("product_tmpl_id"))
    product = Product.objects.filter(odoo_tmpl_id=tmpl_id).first()
    if product is None:
        logger.warning(
            "sync_master_boms: template %s belum tersinkron -> BOM %s dibuat tanpa product.",
            tmpl_id,
            row.get("id"),
        )
    return {
        "product": product,
        "code": _code(row, "code"),
        "name": row.get("name") or "",
        "output_qty": row.get("product_qty") or 1,
        "uom": _uom_by_odoo_id(row.get("product_uom_id")),
        "is_active": bool(row.get("active", True)),
    }


def _bom_line_defaults(row):
    """``mrp.bom.line`` → ``master.BOMLine`` (komponen via ``Product.odoo_id``).

    ``bom`` wajib ada (FK tidak nullable) → line tanpa BOM tetap di-*skip*.
    ``product`` nullable: kalau produk bahan belum tersinkron → ``None`` (baris
    tetap disimpan, dihitung ``skipped``).

    H1.5 — sekalian memetakan ``uom`` (Odoo ``product_uom_id``), ``sequence``, dan
    ``is_active`` (Odoo ``active``). Baris komponen yang sudah tidak aktif di Odoo
    tetap disimpan dengan ``is_active=False`` (jejak + kunci ``odoo_id`` terjaga).
    """
    bom_odoo_id = _first_id(row.get("bom_id"))
    bom = BOM.objects.filter(odoo_id=bom_odoo_id).first()
    if bom is None:
        logger.warning(
            "sync_master_boms: BOM %s belum tersinkron -> line %s dilewati.",
            bom_odoo_id,
            row.get("id"),
        )
        return None
    product = Product.objects.filter(odoo_id=_first_id(row.get("product_id"))).first()
    if product is None:
        logger.warning(
            "sync_master_boms: produk bahan %s belum tersinkron -> line %s tanpa product.",
            _first_id(row.get("product_id")),
            row.get("id"),
        )
    return {
        "bom": bom,
        "product": product,
        "product_qty": float(row.get("product_qty") or 0),
        "uom": _uom_by_odoo_id(row.get("product_uom_id")),
        "sequence": int(row.get("sequence") or 10),
        "is_active": bool(row.get("active", True)),
    }


def _partner_address(row) -> str:
    """``street`` + ``street2`` Odoo → satu alamat (baris baru sebagai pemisah)."""
    parts = [str(row.get("street") or "").strip(), str(row.get("street2") or "").strip()]

    return "\n".join(part for part in parts if part)


#: Karakter non-digit pada ``vat`` Odoo (titik/strip/spasi) — dibuang saat tarikan.
_NON_DIGIT = re.compile(r"\D")


def _normalize_npwp(value) -> str:
    """``vat`` Odoo → digit NPWP (dipakai apa adanya kalau bukan format NPWP)."""
    return _NON_DIGIT.sub("", str(value or ""))


def _partner_defaults(row):
    """``res.partner`` → ``master.Partner`` (tanpa kode natural; fallback ``ODOO-<id>``).

    H1.6 — sekalian memetakan ``email``/``phone``/``city``/``address`` (gabungan
    ``street`` + ``street2``), ``npwp`` (Odoo ``vat``), ``is_company``, dan
    ``customer_rank``/``supplier_rank``. Penanda peran ``is_customer``/``is_vendor``
    di-derive dari rank (``> 0``), sesuai semantik Odoo: rank = hitungan transaksi.
    """
    customer_rank = int(row.get("customer_rank") or 0)
    supplier_rank = int(row.get("supplier_rank") or 0)

    return {
        "code": _code(row),
        "name": row.get("name") or "",
        "email": str(row.get("email") or "").strip(),
        "phone": str(row.get("phone") or "").strip(),
        "city": str(row.get("city") or "").strip(),
        "address": _partner_address(row),
        "npwp": _normalize_npwp(row.get("vat")),
        "is_company": bool(row.get("is_company", True)),
        "is_customer": customer_rank > 0,
        "is_vendor": supplier_rank > 0,
        "customer_rank": customer_rank,
        "supplier_rank": supplier_rank,
        "is_active": bool(row.get("active", True)),
    }


def _location_usage(value) -> str:
    """``usage`` Odoo → nilai ``master.Location.Usage``; tak dikenal → ``internal``."""
    candidate = str(value or "").strip().lower()

    return candidate if candidate in Location.Usage.values else Location.Usage.INTERNAL


def _location_defaults(row):
    """``stock.location`` → ``master.Location`` (kode = ``complete_name``).

    H1.4 — sekalian memetakan ``usage``/``parent``/``warehouse``/``is_active``
    (field yang memang sudah diminta ``LOCATION_FIELDS`` sejak awal) supaya data
    tarikan lengkap. Induk/gudang yang **belum** tersinkron → ``None`` (lokasi tetap
    dibuat & dihitung ``skipped``), pola sama dengan ``_bom_defaults``.
    """
    parent_odoo_id = _first_id(row.get("location_id"))
    parent = (
        Location.objects.filter(odoo_id=parent_odoo_id).first() if parent_odoo_id else None
    )

    warehouse_odoo_id = _first_id(row.get("warehouse_id"))
    warehouse = (
        Warehouse.objects.filter(odoo_id=warehouse_odoo_id).first() if warehouse_odoo_id else None
    )

    return {
        "code": _code(row, "complete_name", "name"),
        "name": row.get("name") or "",
        "usage": _location_usage(row.get("usage")),
        "parent": parent,
        "warehouse": warehouse,
        "is_active": bool(row.get("active", True)),
    }


def _tax_defaults(row):
    """``account.tax`` → ``master.Tax`` (H3.6 — tarif & jenis ikut ditarik).

    ``account.tax`` tidak punya kode natural → ``code`` tetap ``ODOO-{id}`` dan
    **kunci pencocokan tetap ``odoo_id``** (sample dev membuktikan nama tidak aman:
    tax bernama ``'12% (Non-Luxury Good)'`` ternyata ``amount=11.0``).

    Aturan **"isi bila masih default bawaan"** (pelajaran H3.5): MES = source of truth
    master sedangkan beat ``sync-master-taxes`` berjalan harian — menimpa begitu saja
    akan mereset konfigurasi pajak yang sudah disesuaikan operator. Karena itu:

      * ``amount`` → diisi hanya bila MES masih **0** (bootstrap baris baru);
      * ``amount_type``/``type_tax_use``/``price_include`` → diisi hanya bila MES masih
        bernilai default bawaan (``percent``/``sale``/``False``), yaitu tanda belum
        pernah dikonfigurasi manual di MES;
      * ``is_default`` → **TIDAK PERNAH** ditarik (keputusan MES, dijaga
        ``tax_services.set_default_tax``);
      * ``name``/``is_active`` → tetap mengikuti Odoo (perilaku pull I1).
    """
    odoo_id = _first_id(row.get("id"))
    existing = Tax.objects.filter(odoo_id=odoo_id).first() if odoo_id is not None else None

    defaults = {
        "code": _code(row),
        "name": row.get("name") or "",
        "is_active": bool(row.get("active", True)),
    }

    raw_amount = row.get("amount")
    if raw_amount not in (None, "") and (existing is None or (existing.amount or 0) == 0):
        try:
            defaults["amount"] = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            logger.warning(
                "sync_master_taxes: amount pajak %s tidak valid (%r) -> dilewati.",
                odoo_id,
                raw_amount,
            )

    amount_type = str(row.get("amount_type") or "").strip().lower()
    if amount_type in Tax.AmountType.values and (
        existing is None or not existing.amount_type or existing.amount_type == Tax.AmountType.PERCENT
    ):
        defaults["amount_type"] = amount_type

    type_tax_use = str(row.get("type_tax_use") or "").strip().lower()
    if type_tax_use in Tax.TaxUse.values and (
        existing is None or not existing.type_tax_use or existing.type_tax_use == Tax.TaxUse.SALE
    ):
        defaults["type_tax_use"] = type_tax_use

    if "price_include" in row and (
        existing is None or not existing.price_include
    ):
        defaults["price_include"] = bool(row.get("price_include"))

    return defaults


def _uom_defaults(row):
    """``uom.uom`` → ``master.UoM`` (tanpa kode natural di Odoo)."""
    return _name_defaults(row)


def _warehouse_defaults(row):
    """``stock.warehouse`` → ``master.Warehouse`` (kode natural = ``code``)."""
    return _name_defaults(row, "code")


def _journal_defaults(row):
    """``account.journal`` → ``master.Journal`` (kode natural = ``code``).

    H3.4 — ``type`` Odoo ikut dipetakan ke ``journal_type`` (aditif) supaya MES bisa
    memfilter journal **general** untuk Journal Entry manual. Nilai tak dikenal
    (atau kosong) → ``""`` = belum dikonfigurasi ⇒ guard di service H3.4 longgar
    (baris lama yang belum pernah di-pull tetap bisa dipakai).
    """
    defaults = _name_defaults(row, "code")
    journal_type = str(row.get("type") or "").strip().lower()
    defaults["journal_type"] = journal_type if journal_type in Journal.JournalType.values else ""

    return defaults


def _account_defaults(row):
    """``account.account`` → ``master.Account`` (pull-only; H3.4).

    ``code`` natural Odoo (mis. ``11120005``) + fallback ``ODOO-{id}`` lewat `_code`
    (kolom ``code`` unique). ``is_active`` = **NOT** ``deprecated`` karena Odoo 17
    tidak punya field ``active`` di ``account.account`` (probe STEP 0 H3.4).
    """
    return {
        "code": _code(row, "code"),
        "name": row.get("name") or "",
        "account_type": str(row.get("account_type") or "").strip().lower(),
        "reconcile": bool(row.get("reconcile")),
        "is_active": not bool(row.get("deprecated")),
    }


def _currency_defaults(row):
    """``res.currency`` → ``master.Currency`` (tanpa kode natural di Odoo)."""
    return _name_defaults(row)


# ---------------------------------------------------------------------------
# Task: master sync (9 alur) — semuanya lewat transport, idempotent via odoo_id
# ---------------------------------------------------------------------------
@shared_task(
    bind=True,
    name="erp_sync.sync_master_products",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_products(self, since=None):
    """Tarik ``product.product`` Odoo → ``master.Product``."""
    transport = get_transport()
    try:
        rows = transport.fetch_products(since=since)
    finally:
        transport.close()
    return _sync(Product, rows, _product_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_boms",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_boms(self, since=None):
    """Tarik ``mrp.bom`` + ``mrp.bom.line`` → ``master.BOM`` + ``master.BOMLine``."""
    transport = get_transport()
    try:
        bom_rows = transport.fetch_boms(since=since)
        line_rows = transport.fetch_bom_lines(since=since)
    finally:
        transport.close()

    # `product` tidak ketemu -> baris tetap disimpan (product=None) & dihitung skipped.
    boms = _sync(BOM, bom_rows, _bom_defaults, skipped_when=_product_unresolved)
    lines = _sync(BOMLine, line_rows, _bom_line_defaults, skipped_when=_product_unresolved)
    return {
        "created": boms["created"] + lines["created"],
        "updated": boms["updated"] + lines["updated"],
        "skipped": boms["skipped"] + lines["skipped"],
    }


@shared_task(
    bind=True,
    name="erp_sync.sync_master_partners",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_partners(self, since=None):
    """Tarik ``res.partner`` Odoo → ``master.Partner``."""
    transport = get_transport()
    try:
        rows = transport.fetch_partners(since=since)
    finally:
        transport.close()
    return _sync(Partner, rows, _partner_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_locations",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_locations(self, since=None):
    """Tarik ``stock.location`` Odoo → ``master.Location``."""
    transport = get_transport()
    try:
        rows = transport.fetch_locations(since=since)
    finally:
        transport.close()
    return _sync(Location, rows, _location_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_taxes",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_taxes(self, since=None):
    """Tarik ``account.tax`` Odoo → ``master.Tax``."""
    transport = get_transport()
    try:
        rows = transport.fetch_taxes(since=since)
    finally:
        transport.close()
    return _sync(Tax, rows, _tax_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_uoms",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_uoms(self, since=None):
    """Tarik ``uom.uom`` Odoo → ``master.UoM``."""
    transport = get_transport()
    try:
        rows = transport.fetch_uoms(since=since)
    finally:
        transport.close()
    return _sync(UoM, rows, _uom_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_warehouses",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_warehouses(self, since=None):
    """Tarik ``stock.warehouse`` Odoo → ``master.Warehouse``."""
    transport = get_transport()
    try:
        rows = transport.fetch_warehouses(since=since)
    finally:
        transport.close()
    return _sync(Warehouse, rows, _warehouse_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_journals",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_journals(self, since=None):
    """Tarik ``account.journal`` Odoo → ``master.Journal``."""
    transport = get_transport()
    try:
        rows = transport.fetch_journals(since=since)
    finally:
        transport.close()
    return _sync(Journal, rows, _journal_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_accounts",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_accounts(self, since=None):
    """Tarik ``account.account`` Odoo → ``master.Account`` (H3.4, pull-only).

    Chart of accounts = wewenang akuntan di Odoo; MES hanya menyimpan mirror untuk
    dropdown form Journal Entry. Tidak ada push balik ke Odoo (pola I1/H3.6).
    """
    transport = get_transport()
    try:
        rows = transport.fetch_accounts(since=since)
    finally:
        transport.close()
    return _sync(Account, rows, _account_defaults)


@shared_task(
    bind=True,
    name="erp_sync.sync_master_currencies",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    max_retries=3,
)
def sync_master_currencies(self, since=None):
    """Tarik ``res.currency`` Odoo → ``master.Currency``."""
    transport = get_transport()
    try:
        rows = transport.fetch_currencies(since=since)
    finally:
        transport.close()
    return _sync(Currency, rows, _currency_defaults)
