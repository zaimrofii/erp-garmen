"""Task Celery **push master** ke Odoo (MES → Odoo) — H1.1 (Product) + H1.2 (UoM).

Arah sync master = **dua arah** (``docs/CHANGES-DETAIL-H1H5.md`` §1): MES adalah
source of truth produksi, Odoo back-office pasif. Endpoint CRUD master
(``/api/v1/master/products/``, ``/api/v1/master/uoms/``) **tidak** memanggil Odoo;
ia menulis ``SyncRecord`` lalu meng-enqueue task di modul ini. Jadi lantai
produksi tidak pernah menunggu ERP.

Isi:

  * ``push_master_product`` — ``product.product`` (H1.1);
  * ``push_master_uom`` — ``uom.uom`` + kategori ``uom.category`` (H1.2).

Alur (sama untuk keduanya):

  1. ambil record MES; hilang -> ``{"status": "not-found"}`` (bukan error);
  2. ``SyncRecord`` (resource ``master.*``, stage ``MASTER_PUSH``) biasanya sudah
     dibuat pemanggil (service CRUD) lewat ``SyncIdempotency``; kalau task
     dipanggil telanjang, record dibuat sendiri di sini;
  3. kalau record sudah ``SENT``/``DUPLICATE`` **dan payload-nya identik**
     -> ``duplicate-ignored`` (proteksi enqueue ganda untuk perubahan yang sama;
     record yang payload-nya berubah = perubahan baru -> tetap dikirim);
  4. ``ERP_ADAPTER=null`` (dev/test tanpa Odoo) -> no-op: sukses dengan
     ``erp_id = NULL-<uuid4>`` (pola sama dengan ``NullAdapter._push``);
  5. ``ERP_ADAPTER=odoo`` -> ``create``/``write`` lewat transport JSON-RPC
     (``OdooClient``); id hasil create disimpan ke ``odoo_id`` — kunci
     idempotensi sync (bukan ``code``/``name``);
  6. sukses -> ``mark_sent``; gagal -> ``mark_failed`` (``attempts`` naik) lalu
     **raise** supaya ``autoretry_for`` Celery mengulang (hanya error transport:
     ``httpx.HTTPError`` / ``ConnectionError``).

Task bernama ``erp_sync.*`` sehingga otomatis di-route ke queue ``erp_sync``
(lihat ``CELERY_TASK_ROUTES`` di settings).

Batasan yang disengaja:

  * **Product** — payload ke Odoo hanya memuat field yang pasti ada di
    ``product.product`` (``default_code``, ``name``, ``list_price``,
    ``standard_price``, ``active``, ``weight``, ``uom_id``). ``category`` di MES
    masih teks bebas (bukan FK ke ``product.category`` Odoo) sehingga **belum**
    dipetakan — dipetakan saat modul kategori masuk (H1.2+).
  * **UoM** — field WAJIB di ``uom.uom`` diverifikasi lewat ``fields_get`` pada
    Odoo dev: ``name``, ``category_id`` (m2o), ``uom_type`` (selection
    ``bigger|reference|smaller``), ``factor`` (float), ``rounding`` (float),
    ``active``. Karena itu MES H1.2 menyimpan ``category``/``uom_type``/
    ``factor``/``rounding`` — **tidak ada nilai yang dikarang**: kalau
    ``category`` kosong, push **gagal** dengan pesan jelas (``MasterPushError``)
    alih-alih diam-diam memakai default Odoo.
  * **Warehouse** — field WAJIB di ``stock.warehouse`` (probe ``fields_get``):
    ``name``, ``code`` (short_name, **size=5**), ``view_location_id`` (m2o),
    ``lot_stock_id`` (m2o), ``company_id`` (m2o, **readonly**), ``reception_steps``,
    dan ``delivery_steps``. MES H1.3 menyimpan ``reception_steps``/``delivery_steps``
    (2 field itu murni dari MES). ``view_location_id``/``lot_stock_id`` **dibuat
    sendiri oleh Odoo** di ``create()`` (sumber Odoo 17
    ``stock/models/stock_warehouse.py`` baris 109–126) dan ``company_id`` readonly +
    punya default ⇒ ketiganya **tidak** dikirim dari MES (sprint utang
    `warehouse-create-mapping`, OPSI B) sehingga ``create`` **dan** ``update``
    dua-duanya boleh.
  * **Location** — field WAJIB di ``stock.location`` (probe ``fields_get``):
    ``name``, ``usage`` (selection ``supplier|view|internal|customer|inventory|
    production|transit``); ``location_id`` (induk) & ``warehouse_id`` opsional
    (``warehouse_id`` malah diturunkan Odoo dari hierarki). MES H1.4 menyimpan
    ``usage``/``parent``/``warehouse`` ⇒ ``create`` lokasi **bisa** dilakukan
    dengan nilai MES apa adanya (tidak mengarang). Satu-satunya syarat tambahan:
    kalau induk diset di MES tapi induknya **belum punya ``odoo_id``**, push
    **gagal** (``MasterPushError``) — lokasi tidak boleh dipindah ke root Odoo.
  * **BOM** — probe ``fields_get`` ``mrp.bom`` (Odoo 17): field WAJIB =
    ``product_tmpl_id`` (**template**, bukan varian!), ``product_qty``,
    ``product_uom_id``, ``type`` (``normal|phantom``); ``product_id`` ada tapi
    opsional; ``product_uom`` **tidak ada**; ``code`` opsional. ``mrp.bom.line``
    WAJIB = ``bom_id``, ``product_id`` (varian), ``product_qty``, ``product_uom_id``;
    ``sequence`` opsional. MES H1.5 menyimpan ``output_qty`` + ``uom`` (header) dan
    ``product_qty``/``uom``/``sequence`` (baris) ⇒ push **boleh create/update**;
    guard-nya: produk BOM harus punya ``odoo_tmpl_id`` (dan ``odoo_id`` varian untuk
    komponen), satuan harus punya ``odoo_id`` — kalau tidak, ``MasterPushError``
    ("sinkronkan product/UoM dulu") alih-alih mengarang id.
  * **Partner** — probe ``fields_get`` ``res.partner`` (Odoo 17, 174 field):
    **tidak ada** field wajib untuk create (``required & !readonly`` hanya
    ``property_account_*`` yang punya default company). Writable & dipakai MES:
    ``name``, ``ref``, ``is_company`` (boolean), ``company_type`` (selection
    ``person|company``), ``email``, ``phone``, ``street``, ``street2``, ``city``,
    ``vat``, ``supplier_rank``/``customer_rank`` (integer — di Odoo berisi
    HITUNGAN transaksi), ``active``. ⇒ push **create** boleh dan mengirim rank 1/0
    sebagai penanda peran, sedangkan **update** tidak mengirim rank (agar hitungan
    Odoo tidak turun, mis. 16 → 1). ``is_company`` TIDAK di-derive dari NPWP (data
    dev membuktikan perusahaan bisa tanpa ``vat``); ``company_type`` di-derive dari
    ``is_company``; ``npwp`` dikirim sebagai ``vat`` dan ``address`` sebagai ``street``.
"""


from __future__ import annotations

import logging
from uuid import uuid4

import httpx
from celery import shared_task
from django.conf import settings

from config.middleware import clear_request_id
from master.models import BOM, BOMLine, Location, Partner, Product, Tax, UoM, Warehouse

from .audit import log_push
from .client import get_odoo_rpc_client
from .idempotency import SyncIdempotency
from .models import SyncRecord, SyncResource, SyncStage
from .tasks import _bind_request_id

logger = logging.getLogger(__name__)

__all__ = (
    "ACTION_MASTER_BOM_PUSH",
    "ACTION_MASTER_LOCATION_PUSH",
    "ACTION_MASTER_PARTNER_PUSH",
    "ACTION_MASTER_PUSH",
    "ACTION_MASTER_TAX_PUSH",
    "ACTION_MASTER_UOM_PUSH",
    "ACTION_MASTER_WAREHOUSE_PUSH",
    "ODOO_BOM_LINE_MODEL",
    "ODOO_BOM_MODEL",
    "ODOO_LOCATION_MODEL",
    "ODOO_MODEL",
    "ODOO_PARTNER_MODEL",
    "ODOO_TAX_MODEL",
    "ODOO_UOM_MODEL",
    "ODOO_WAREHOUSE_MODEL",
    "MasterPushError",
    "bom_payload",
    "is_noop_mode",
    "location_payload",
    "partner_payload",
    "product_payload",
    "push_master_bom",
    "push_master_location",
    "push_master_partner",
    "push_master_product",
    "push_master_tax",
    "push_master_uom",
    "push_master_warehouse",
    "tax_payload",
    "uom_payload",
    "warehouse_payload",
)

#: Error yang layak di-retry (transport/jaringan) — **bukan** error data.
RETRY_EXCEPTIONS = (httpx.HTTPError, ConnectionError)


class MasterPushError(ValueError):
    """Data master tidak cukup untuk dipush (mis. `category` UoM kosong).

    Sengaja **bukan** error transport: `autoretry_for` hanya mengulang
    ``httpx.HTTPError``/``ConnectionError``, jadi record-nya langsung
    ``FAILED`` dengan pesan jelas (tidak mengulang-ulang tanpa guna) —
    operator bisa melengkapi datanya lalu menyimpan ulang dari MES.
    """


#: Action audit percobaan push (pola ``audit.py``: ``erp_sync.push_*``).
ACTION_MASTER_PUSH = "erp_sync.push_master_product"
ACTION_MASTER_UOM_PUSH = "erp_sync.push_master_uom"
ACTION_MASTER_WAREHOUSE_PUSH = "erp_sync.push_master_warehouse"
ACTION_MASTER_LOCATION_PUSH = "erp_sync.push_master_location"
ACTION_MASTER_BOM_PUSH = "erp_sync.push_master_bom"
ACTION_MASTER_PARTNER_PUSH = "erp_sync.push_master_partner"
#: H3.6 — master Tax (`account.tax`).
ACTION_MASTER_TAX_PUSH = "erp_sync.push_master_tax"

#: Model Odoo tujuan (varian produk; ``product.template`` dibuat otomatis Odoo).
ODOO_MODEL = "product.product"

#: Model Odoo tujuan untuk UoM + kategorinya (keduanya wajib di ``uom.uom``).
ODOO_UOM_MODEL = "uom.uom"
ODOO_UOM_CATEGORY_MODEL = "uom.category"

#: H3.6 — model Odoo tujuan master Tax. ``tax_group_id`` **tidak** dikirim: di Odoo
#: field itu ``required=True`` tetapi ``compute='_compute_tax_group_id'``
#: (``account/models/account_tax.py`` baris 134–139 & 227–239) sehingga Odoo
#: mengisinya sendiri dari (``country_id``, ``company_id``) — sama pola dengan
#: ``stock.warehouse.view_location_id`` di H1.3.
ODOO_TAX_MODEL = "account.tax"

#: Model Odoo tujuan untuk gudang (``stock.warehouse``).
ODOO_WAREHOUSE_MODEL = "stock.warehouse"

#: Panjang maksimum ``short_name`` Odoo (`stock.warehouse.code`, size=5 hasil probe).
ODOO_WAREHOUSE_CODE_MAX_LENGTH = 5

#: Model Odoo tujuan untuk lokasi (``stock.location``).
ODOO_LOCATION_MODEL = "stock.location"

#: Model Odoo tujuan untuk BOM + barisnya (``mrp.bom`` / ``mrp.bom.line``).
ODOO_BOM_MODEL = "mrp.bom"
ODOO_BOM_LINE_MODEL = "mrp.bom.line"

#: ``type`` BOM Odoo yang dipakai MES (selection Odoo: ``normal`` | ``phantom``).
ODOO_BOM_TYPE = "normal"

#: Model Odoo tujuan untuk partner (``res.partner``: customer + supplier).
ODOO_PARTNER_MODEL = "res.partner"

#: Nilai ``company_type`` Odoo (selection hasil probe) — di-derive dari ``is_company``.
ODOO_COMPANY_TYPE_COMPANY = "company"
ODOO_COMPANY_TYPE_PERSON = "person"


def product_payload(product: Product) -> dict:
    """Payload master product (disimpan di ``SyncRecord.payload`` & dikirim ke ERP).

    Sengaja JSON-safe (float/str/bool/None saja) supaya bisa ditampilkan di
    halaman monitoring sync tanpa konversi tambahan.
    """
    uom = product.uom if product.uom_id else None

    return {
        "ref": product.code,
        "code": product.code,
        "name": product.name,
        "category": product.category,
        "sale_price": float(product.sale_price or 0),
        "cost_price": float(product.cost_price or 0),
        "weight": product.weight,
        "uom_id": uom.odoo_id if uom is not None else None,
        "active": bool(product.is_active),
        "image_url": product.image_url,
    }


def is_noop_mode() -> bool:
    """True kalau ``ERP_ADAPTER`` bukan ``"odoo"`` (mis. ``null``) -> push disimulasikan.

    Sumber kebenaran **hanya** settings, sama seperti ``adapters/factory.py`` /
    ``transport/factory.py`` (tidak ada nilai vendor hardcode di pemanggil).
    """
    return (getattr(settings, "ERP_ADAPTER", "") or "").strip().lower() != "odoo"


def _odoo_values(payload: dict) -> dict:
    """Petakan payload MES -> nilai ``product.product`` Odoo (field konservatif)."""
    values: dict = {
        "default_code": payload.get("code"),
        "name": payload.get("name") or payload.get("code"),
        "list_price": payload.get("sale_price") or 0,
        "standard_price": payload.get("cost_price") or 0,
        "active": bool(payload.get("active", True)),
    }

    if payload.get("weight") is not None:
        values["weight"] = payload["weight"]
    if payload.get("uom_id"):
        values["uom_id"] = payload["uom_id"]

    return values


def _push_to_odoo(product: Product, payload: dict) -> str:
    """``create``/``write`` produk di Odoo; kembalikan ``product.product.id`` (str)."""
    client = get_odoo_rpc_client()
    try:
        values = _odoo_values(payload)
        if product.odoo_id:
            client.transport.write(ODOO_MODEL, [int(product.odoo_id)], values)
            return str(product.odoo_id)

        return str(client.transport.create(ODOO_MODEL, values))
    finally:
        client.close()



@shared_task(
    bind=True,
    name="erp_sync.push_master_product",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_product(self, product_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.Product`` ke ERP (lihat docstring modul)."""
    _bind_request_id(self)
    resource = SyncResource.MASTER_PRODUCT.value

    try:
        product = Product.objects.select_related("uom").filter(pk=product_id).first()
        if product is None:
            logger.warning("erp_sync.push_master_product: produk %s tidak ada.", product_id)
            return {"status": "not-found", "product_id": product_id}

        payload = product_payload(product)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, product.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_product: produk %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                product.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(product.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_product: ERP_ADAPTER=%s -> no-op push produk %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    product.pk,
                    erp_id,
                )
            else:
                erp_id = _push_to_odoo(product, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_PUSH,
                resource,
                product.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not product.odoo_id and str(erp_id).isdigit():
            product.odoo_id = int(erp_id)
            product.save(update_fields=("odoo_id", "updated_at"))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_PUSH,
            resource,
            product.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(product.pk),
            "odoo_id": product.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H1.2 — master UoM (`uom.uom` + `uom.category`)
# ---------------------------------------------------------------------------
def uom_payload(uom: UoM) -> dict:
    """Payload master UoM (disimpan di ``SyncRecord.payload`` & dikirim ke ERP)."""
    return {
        "ref": uom.code,
        "code": uom.code,
        "name": uom.name,
        "category": uom.category,
        "uom_type": uom.uom_type,
        "factor": float(uom.factor or 0),
        "rounding": float(uom.rounding or 0),
        "active": bool(uom.is_active),
    }


def _uom_odoo_values(payload: dict) -> dict:
    """Petakan payload MES -> nilai ``uom.uom`` Odoo (field wajib terverifikasi)."""
    factor = float(payload.get("factor") or 0)
    rounding = float(payload.get("rounding") or 0)

    if factor <= 0:
        raise MasterPushError("factor UoM harus > 0 (Odoo menolak rasio 0).")
    if rounding <= 0:
        raise MasterPushError("rounding UoM harus > 0 (Odoo menolak presisi 0).")

    uom_type = str(payload.get("uom_type") or UoM.UomType.REFERENCE).strip().lower()
    if uom_type not in UoM.UomType.values:
        raise MasterPushError(
            f"uom_type {uom_type!r} tidak dikenal. Pilihan: {', '.join(UoM.UomType.values)}."
        )

    return {
        "name": payload.get("name") or payload.get("code"),
        "uom_type": uom_type,
        "factor": factor,
        "rounding": rounding,
        "active": bool(payload.get("active", True)),
    }


def _resolve_uom_category_id(transport, category: str) -> int:
    """ID ``uom.category`` untuk ``category`` (dicari dulu, dibuat kalau belum ada).

    Nama kategori MES = sumber kebenaran (``master.UoM.category``); pencarian
    memakai ``=ilike`` supaya kategori kembar (beda huruf besar/kecil) tidak
    menumpuk. Kategori kosong -> ``MasterPushError`` (TIDAK memakai default Odoo:
    biar jelas datanya kurang, bukan diam-diam salah rasio).
    """
    name = str(category or "").strip()
    if not name:
        raise MasterPushError(
            "category UoM wajib diisi untuk push ke Odoo (kategori menentukan unit "
            "referensi & rasio); lengkapi di MES lalu simpan ulang."
        )

    found = transport.search_read(
        ODOO_UOM_CATEGORY_MODEL, [["name", "=ilike", name]], ["id"], 1
    )
    if found:
        return int(found[0]["id"])

    created = transport.create(ODOO_UOM_CATEGORY_MODEL, {"name": name})
    logger.info("erp_sync.push_master_uom: kategori Odoo '%s' dibuat (#%s).", name, created)

    return int(created)


def _push_uom_to_odoo(uom: UoM, payload: dict) -> str:
    """``create``/``write`` UoM di Odoo; kembalikan ``uom.uom.id`` (str)."""
    client = get_odoo_rpc_client()
    try:
        transport = client.transport
        values = _uom_odoo_values(payload)
        category = str(payload.get("category") or "").strip()

        if uom.odoo_id:
            # Update: `category_id` HANYA dikirim kalau MES punya nilainya —
            # jangan menimpa kategori Odoo dengan nilai kosong.
            if category:
                values["category_id"] = _resolve_uom_category_id(transport, category)
            else:
                logger.warning(
                    "erp_sync.push_master_uom: UoM %s tanpa kategori — category_id "
                    "tidak dikirim (kategori Odoo dibiarkan apa adanya).",
                    uom.pk,
                )
            transport.write(ODOO_UOM_MODEL, [int(uom.odoo_id)], values)
            return str(uom.odoo_id)

        values["category_id"] = _resolve_uom_category_id(transport, category)
        return str(transport.create(ODOO_UOM_MODEL, values))
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_uom",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_uom(self, uom_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.UoM`` ke ERP (lihat docstring modul)."""
    _bind_request_id(self)
    resource = SyncResource.MASTER_UOM.value

    try:
        uom = UoM.objects.filter(pk=uom_id).first()
        if uom is None:
            logger.warning("erp_sync.push_master_uom: UoM %s tidak ada.", uom_id)
            return {"status": "not-found", "uom_id": uom_id}

        payload = uom_payload(uom)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, uom.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_uom: UoM %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                uom.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(uom.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_uom: ERP_ADAPTER=%s -> no-op push UoM %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    uom.pk,
                    erp_id,
                )
            else:
                erp_id = _push_uom_to_odoo(uom, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_UOM_PUSH,
                resource,
                uom.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not uom.odoo_id and str(erp_id).isdigit():
            uom.odoo_id = int(erp_id)
            uom.save(update_fields=("odoo_id",))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_UOM_PUSH,
            resource,
            uom.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(uom.pk),
            "odoo_id": uom.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H1.3 — master Warehouse (`stock.warehouse`)
# ---------------------------------------------------------------------------
def warehouse_payload(warehouse: Warehouse) -> dict:
    """Payload master Warehouse (disimpan di ``SyncRecord.payload`` & dikirim ke ERP)."""
    return {
        "ref": warehouse.code,
        "code": warehouse.code,
        "name": warehouse.name,
        "reception_steps": warehouse.reception_steps,
        "delivery_steps": warehouse.delivery_steps,
        "active": bool(warehouse.is_active),
    }


def _warehouse_odoo_values(payload: dict) -> dict:
    """Petakan payload MES -> nilai ``stock.warehouse`` Odoo (field terverifikasi).

    ``code`` = ``short_name`` Odoo: WAJIB ada dan maks **5** karakter (probe
    ``fields_get``: ``size=5``). MES sendiri membolehkan 64 karakter, jadi guard-nya
    di sini (``MasterPushError``) — bukan 400 di API — supaya data MES tetap boleh
    panjang untuk keperluan internal.
    """
    code = str(payload.get("code") or "").strip()
    if not code:
        raise MasterPushError("code (short_name) gudang wajib diisi untuk push ke Odoo.")
    if len(code) > ODOO_WAREHOUSE_CODE_MAX_LENGTH:
        raise MasterPushError(
            f"code '{code}' terlalu panjang untuk Odoo (short_name maks "
            f"{ODOO_WAREHOUSE_CODE_MAX_LENGTH} karakter)."
        )

    reception = str(payload.get("reception_steps") or "").strip().lower()
    if reception not in Warehouse.ReceptionSteps.values:
        raise MasterPushError(
            "reception_steps "
            f"{reception!r} tidak dikenal. Pilihan: "
            f"{', '.join(Warehouse.ReceptionSteps.values)}."
        )

    delivery = str(payload.get("delivery_steps") or "").strip().lower()
    if delivery not in Warehouse.DeliverySteps.values:
        raise MasterPushError(
            "delivery_steps "
            f"{delivery!r} tidak dikenal. Pilihan: "
            f"{', '.join(Warehouse.DeliverySteps.values)}."
        )

    return {
        "name": payload.get("name") or code,
        "code": code,
        "reception_steps": reception,
        "delivery_steps": delivery,
        "active": bool(payload.get("active", True)),
    }


def _push_warehouse_to_odoo(warehouse: Warehouse, payload: dict) -> str:
    """``create``/``write`` gudang di Odoo; kembalikan ``stock.warehouse.id`` (str).

    **Create BOLEH** (sprint utang `warehouse-create-mapping`, OPSI B):
    ``view_location_id`` & ``lot_stock_id`` memang ``required=True`` di Odoo, tetapi
    **dibuat sendiri oleh Odoo di dalam ``create()``** — bukti sumber Odoo 17
    ``stock/models/stock_warehouse.py`` (baris 109–126):

    * ``vals['view_location_id'] = stock.location.create({'name': code, 'usage':
      'view', 'location_id': ref('stock.stock_location_locations')})``;
    * sub-lokasi (termasuk ``lot_stock_id``) dibuat dari ``_get_locations_values(vals)``
      dengan induk = ``view_location_id``.

    ``company_id`` juga **``readonly=True``** di Odoo (probe ``fields_get``) dan punya
    default dari company user (``default_get``) ⇒ MES tetap **tidak** mengirim ketiga
    field itu: mengirim ``company_id`` sia-sia, sedangkan menurunkan
    ``view_location_id``/``lot_stock_id`` dari MES = mengarang data (MES tidak punya
    relasi Warehouse→Location; arah relasinya ``Location.warehouse``).

    Jadi payload tetap 6 field (``name``/``code``/``reception_steps``/``delivery_steps``/
    ``active``) untuk create maupun update; pengaman ``MasterPushError`` untuk
    ``code``/steps tetap berlaku.
    """
    client = get_odoo_rpc_client()
    try:
        values = _warehouse_odoo_values(payload)

        if warehouse.odoo_id:
            client.transport.write(ODOO_WAREHOUSE_MODEL, [int(warehouse.odoo_id)], values)
            return str(warehouse.odoo_id)

        return str(client.transport.create(ODOO_WAREHOUSE_MODEL, values))
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_warehouse",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_warehouse(self, warehouse_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.Warehouse`` ke ERP (lihat docstring modul).

    Update-only: kalau ``odoo_id`` kosong, task langsung ``FAILED`` dengan pesan
    syarat create (lihat ``_push_warehouse_to_odoo``) — bukan menunggu retry.
    """
    _bind_request_id(self)
    resource = SyncResource.MASTER_WAREHOUSE.value

    try:
        warehouse = Warehouse.objects.filter(pk=warehouse_id).first()
        if warehouse is None:
            logger.warning("erp_sync.push_master_warehouse: gudang %s tidak ada.", warehouse_id)
            return {"status": "not-found", "warehouse_id": warehouse_id}

        payload = warehouse_payload(warehouse)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, warehouse.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_warehouse: gudang %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                warehouse.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(warehouse.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_warehouse: ERP_ADAPTER=%s -> no-op push gudang %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    warehouse.pk,
                    erp_id,
                )
            else:
                erp_id = _push_warehouse_to_odoo(warehouse, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_WAREHOUSE_PUSH,
                resource,
                warehouse.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not warehouse.odoo_id and str(erp_id).isdigit():
            warehouse.odoo_id = int(erp_id)
            warehouse.save(update_fields=("odoo_id",))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_WAREHOUSE_PUSH,
            resource,
            warehouse.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(warehouse.pk),
            "odoo_id": warehouse.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H1.4 — master Location (`stock.location`)
# ---------------------------------------------------------------------------
def location_payload(location: Location) -> dict:
    """Payload master Location (disimpan di ``SyncRecord.payload`` & dikirim ke ERP)."""
    return {
        "ref": location.code,
        "code": location.code,
        "name": location.name,
        "usage": location.usage,
        "parent_id": location.parent_id,
        "warehouse_id": location.warehouse_id,
        "active": bool(location.is_active),
    }


def _location_odoo_values(location: Location, payload: dict) -> dict:
    """Petakan payload MES -> nilai ``stock.location`` Odoo (field terverifikasi).

    ``name`` + ``usage`` = field WAJIB di Odoo (probe ``fields_get``); ``usage``
    tak dikenal ditolak (``MasterPushError``) supaya nilai ngawur tidak pernah
    sampai ke Odoo. ``location_id`` (induk) hanya dikirim kalau induknya **sudah**
    tersinkron (punya ``odoo_id``) — kalau belum, push **gagal** dengan pesan jelas:
    mengirim tanpa ``location_id`` akan menaruh lokasi di root Odoo (hierarki salah).
    ``warehouse_id`` TIDAK dikirim (Odoo menurunkannya dari hierarki lokasi).
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise MasterPushError("name lokasi wajib diisi untuk push ke Odoo.")

    usage = str(payload.get("usage") or "").strip().lower()
    if usage not in Location.Usage.values:
        raise MasterPushError(
            f"usage {usage!r} tidak dikenal. Pilihan: {', '.join(Location.Usage.values)}."
        )

    values: dict = {
        "name": name,
        "usage": usage,
        "active": bool(payload.get("active", True)),
    }

    if location.parent_id:
        parent = location.parent
        if parent is None or not parent.odoo_id:
            raise MasterPushError(
                f"induk '{parent.code if parent is not None else location.parent_id}' belum "
                "punya odoo_id — sinkronkan (push) induk lebih dulu supaya hierarki lokasi "
                "di Odoo tetap benar."
            )
        values["location_id"] = int(parent.odoo_id)

    return values


def _push_location_to_odoo(location: Location, payload: dict) -> str:
    """``create``/``write`` lokasi di Odoo; kembalikan ``stock.location.id`` (str).

    Berbeda dari warehouse: ``create`` lokasi **boleh** (Odoo hanya mewajibkan
    ``name`` + ``usage``, keduanya ada di MES), jadi tidak ada data yang dikarang.
    """
    client = get_odoo_rpc_client()
    try:
        values = _location_odoo_values(location, payload)

        if location.odoo_id:
            client.transport.write(ODOO_LOCATION_MODEL, [int(location.odoo_id)], values)
            return str(location.odoo_id)

        return str(client.transport.create(ODOO_LOCATION_MODEL, values))
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_location",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_location(self, location_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.Location`` ke ERP (lihat docstring modul)."""
    _bind_request_id(self)
    resource = SyncResource.MASTER_LOCATION.value

    try:
        location = Location.objects.select_related("parent", "warehouse").filter(pk=location_id).first()
        if location is None:
            logger.warning("erp_sync.push_master_location: lokasi %s tidak ada.", location_id)
            return {"status": "not-found", "location_id": location_id}

        payload = location_payload(location)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, location.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_location: lokasi %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                location.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(location.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_location: ERP_ADAPTER=%s -> no-op push lokasi %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    location.pk,
                    erp_id,
                )
            else:
                erp_id = _push_location_to_odoo(location, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_LOCATION_PUSH,
                resource,
                location.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not location.odoo_id and str(erp_id).isdigit():
            location.odoo_id = int(erp_id)
            location.save(update_fields=("odoo_id",))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_LOCATION_PUSH,
            resource,
            location.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(location.pk),
            "odoo_id": location.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H1.5 — master BOM (`mrp.bom` + `mrp.bom.line`)
# ---------------------------------------------------------------------------
def bom_payload(bom: BOM) -> dict:
    """Payload master BOM (disimpan di ``SyncRecord.payload`` & dikirim ke ERP).

    Memuat header **dan** baris aktif — perubahan komponen ikut mengubah payload
    sehingga idempotensi ``is_already_sent`` tidak salah menganggap "sudah terkirim".
    """
    product = bom.product if bom.product_id else None
    uom = bom.uom if bom.uom_id else None

    return {
        "ref": bom.code,
        "code": bom.code,
        "name": bom.name,
        "product_id": bom.product_id,
        "product_code": product.code if product is not None else None,
        "product_odoo_id": product.odoo_id if product is not None else None,
        "product_tmpl_id": product.odoo_tmpl_id if product is not None else None,
        "output_qty": float(bom.output_qty or 0),
        "uom_id": bom.uom_id,
        "uom_odoo_id": uom.odoo_id if uom is not None else None,
        "active": bool(bom.is_active),
        "lines": [
            {
                "id": line.pk,
                "odoo_id": line.odoo_id,
                "product_id": line.product_id,
                "product_odoo_id": line.product.odoo_id if line.product_id else None,
                "qty": float(line.product_qty or 0),
                "uom_id": line.uom_id,
                "uom_odoo_id": line.uom.odoo_id if line.uom_id else None,
                "sequence": line.sequence,
            }
            for line in bom.lines.filter(is_active=True).order_by("sequence", "id")
        ],
    }


def _uom_odoo_id(own_uom: UoM | None, product: Product | None, label: str):
    """``uom.uom.id`` Odoo untuk BOM/baris: satuan eksplisit → satuan produk.

    Odoo mewajibkan ``product_uom_id``; memakai satuan **produk** (data MES sendiri)
    bukan mengarang. Kalau keduanya tidak ada / belum tersinkron → ``MasterPushError``.
    """
    candidate = own_uom if own_uom is not None else (product.uom if product is not None else None)

    if candidate is None:
        raise MasterPushError(
            f"{label}: satuan belum dipilih dan produk tidak punya satuan — "
            "lengkapi di MES dulu."
        )
    if not candidate.odoo_id:
        raise MasterPushError(
            f"{label}: satuan '{candidate.code}' belum punya odoo_id — "
            "sinkronkan (push) UoM dulu."
        )

    return int(candidate.odoo_id)


def _bom_odoo_values(bom: BOM, payload: dict) -> dict:
    """Petakan payload MES → nilai ``mrp.bom`` Odoo (field terverifikasi probe).

    ``product_tmpl_id`` **wajib** di Odoo dan nilainya adalah id *template*, jadi
    guard-nya ``Product.odoo_tmpl_id`` (bukan ``odoo_id``). ``product_id`` (varian)
    ikut dikirim kalau tersinkron supaya BOM menunjuk varian yang tepat; ``code``
    dikirim sebagai ``reference`` (Odoo boleh punya penomoran sendiri).
    """
    product = bom.product if bom.product_id else None
    if product is None:
        raise MasterPushError(
            "BOM belum punya produk — pilih produk BOM di MES dulu (BOM hasil tarikan "
            "Odoo pun boleh tidak berproduk sampai produknya tersinkron)."
        )
    if not product.odoo_tmpl_id:
        raise MasterPushError(
            f"produk '{product.code}' belum punya odoo_tmpl_id — sinkronkan (push) "
            "product dulu supaya BOM bisa dibuat di Odoo."
        )

    output_qty = float(bom.output_qty or 0)
    if output_qty <= 0:
        raise MasterPushError("output_qty BOM harus lebih besar dari 0 untuk push ke Odoo.")

    values: dict = {
        "product_tmpl_id": int(product.odoo_tmpl_id),
        "product_qty": output_qty,
        "product_uom_id": _uom_odoo_id(bom.uom if bom.uom_id else None, product, "BOM"),
        "type": ODOO_BOM_TYPE,
        "active": bool(payload.get("active", True)),
    }

    if product.odoo_id:
        values["product_id"] = int(product.odoo_id)
    if bom.code:
        values["code"] = bom.code

    return values


def _bom_line_odoo_values(line: BOMLine, bom_odoo_id) -> dict:
    """Petakan satu ``BOMLine`` → nilai ``mrp.bom.line`` Odoo.

    Guard: komponen harus sudah tersinkron (punya ``Product.odoo_id``) dan qty > 0 —
    kalau tidak, ``MasterPushError`` (BOM di MES tetap utuh, operator melengkapi dulu).
    """
    product = line.product if line.product_id else None
    if product is None:
        raise MasterPushError(
            f"baris '{line.pk}': komponen belum punya produk — pilih produk komponen dulu."
        )
    if not product.odoo_id:
        raise MasterPushError(
            f"baris '{line.pk}': komponen '{product.code}' belum punya odoo_id — "
            "sinkronkan (push) product dulu."
        )

    qty = float(line.product_qty or 0)
    if qty <= 0:
        raise MasterPushError(f"baris '{line.pk}': qty komponen harus lebih besar dari 0.")

    return {
        "bom_id": int(bom_odoo_id),
        "product_id": int(product.odoo_id),
        "product_qty": qty,
        "product_uom_id": _uom_odoo_id(
            line.uom if line.uom_id else None, product, f"baris '{line.pk}'"
        ),
        "sequence": line.sequence,
    }


def _push_bom_to_odoo(bom: BOM, payload: dict) -> dict:
    """``create``/``write`` BOM + seluruh baris aktif di Odoo.

    Return ``{"erp_id": <id mrp.bom>, "lines": [(line_pk, odoo_id), …]}``.
    Header ditulis lebih dulu (create kalau belum pernah) supaya baris punya
    ``bom_id``; setiap baris lalu ``write`` (kalau sudah punya ``odoo_id``) atau
    ``create`` — jadi BOM yang sama tidak pernah menghasilkan baris duplikat.
    """
    client = get_odoo_rpc_client()
    try:
        header_values = _bom_odoo_values(bom, payload)

        if bom.odoo_id:
            client.transport.write(ODOO_BOM_MODEL, [int(bom.odoo_id)], header_values)
            erp_id = int(bom.odoo_id)
        else:
            erp_id = int(client.transport.create(ODOO_BOM_MODEL, header_values))

        pushed_lines: list[tuple[int, int]] = []
        for line in bom.lines.filter(is_active=True).order_by("sequence", "id"):
            values = _bom_line_odoo_values(line, erp_id)
            if line.odoo_id:
                client.transport.write(ODOO_BOM_LINE_MODEL, [int(line.odoo_id)], values)
                pushed_lines.append((line.pk, int(line.odoo_id)))
            else:
                created = int(client.transport.create(ODOO_BOM_LINE_MODEL, values))
                pushed_lines.append((line.pk, created))

        return {"erp_id": erp_id, "lines": pushed_lines}
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_bom",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_bom(self, bom_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.BOM`` (header + baris aktif) ke ERP.

    Lihat docstring modul untuk guard-nya. Baris tanpa ``odoo_id`` yang berhasil
    dibuat di Odoo langsung disimpan kembali ke MES supaya push berikutnya
    me-*update* (bukan menduplikasi) baris yang sama.
    """
    _bind_request_id(self)
    resource = SyncResource.MASTER_BOM.value

    try:
        bom = BOM.objects.select_related("product", "uom").filter(pk=bom_id).first()
        if bom is None:
            logger.warning("erp_sync.push_master_bom: BOM %s tidak ada.", bom_id)
            return {"status": "not-found", "bom_id": bom_id}

        payload = bom_payload(bom)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, bom.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_bom: BOM %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                bom.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(bom.pk),
            }

        try:
            if is_noop_mode():
                result = {"erp_id": f"NULL-{uuid4()}", "lines": []}
                logger.info(
                    "erp_sync.push_master_bom: ERP_ADAPTER=%s -> no-op push BOM %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    bom.pk,
                    result["erp_id"],
                )
            else:
                result = _push_bom_to_odoo(bom, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_BOM_PUSH,
                resource,
                bom.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        erp_id = result["erp_id"]
        if not bom.odoo_id and str(erp_id).isdigit():
            bom.odoo_id = int(erp_id)
            bom.save(update_fields=("odoo_id",))

        lines_synced = 0
        for line_pk, line_odoo_id in result.get("lines") or []:
            lines_synced += BOMLine.objects.filter(pk=line_pk, odoo_id__isnull=True).update(
                odoo_id=line_odoo_id
            )

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_BOM_PUSH,
            resource,
            bom.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "lines_synced": lines_synced,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(bom.pk),
            "odoo_id": bom.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H1.6 — master Partner (`res.partner`: customer + supplier)
# ---------------------------------------------------------------------------
def partner_payload(partner: Partner) -> dict:
    """Payload master Partner (disimpan di ``SyncRecord.payload`` & dikirim ke ERP).

    Memuat penanda peran (``is_customer``/``is_vendor``) supaya perubahan peran di
    MES ikut mengubah payload → idempotensi ``is_already_sent`` tidak salah
    menganggap "sudah terkirim".
    """
    return {
        "ref": partner.code,
        "code": partner.code,
        "name": partner.name,
        "is_customer": bool(partner.is_customer),
        "is_vendor": bool(partner.is_vendor),
        "is_company": bool(partner.is_company),
        "email": partner.email,
        "phone": partner.phone,
        "city": partner.city,
        "address": partner.address,
        "npwp": partner.npwp,
        "active": bool(partner.is_active),
    }


def _partner_odoo_values(partner: Partner, payload: dict) -> dict:
    """Petakan payload MES → nilai ``res.partner`` Odoo (field terverifikasi probe).

    * ``name`` satu-satunya nilai yang wajib ada;
    * ``company_type`` di-derive dari ``is_company`` (``company``/``person``);
    * ``npwp`` → ``vat``, ``address`` → ``street``;
    * teks kosong **tidak** dikirim (tidak menghapus data Odoo hanya karena MES
      belum diisi) — tarikan (pull) tetap menyamakan arah sebaliknya;
    * ``customer_rank``/``supplier_rank`` dikirim **hanya saat create** (1/0 sebagai
      penanda customer/vendor). Pada update rank tidak dikirim karena di Odoo field
      itu adalah hitungan transaksi (mis. 16) yang akan turun bila ditimpa 1.
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise MasterPushError("name partner wajib diisi untuk push ke Odoo.")

    is_company = bool(payload.get("is_company", True))
    values: dict = {
        "name": name,
        "is_company": is_company,
        "company_type": (
            ODOO_COMPANY_TYPE_COMPANY if is_company else ODOO_COMPANY_TYPE_PERSON
        ),
        "active": bool(payload.get("active", True)),
    }

    if partner.code:
        values["ref"] = partner.code

    for source, target in (
        ("email", "email"),
        ("phone", "phone"),
        ("address", "street"),
        ("city", "city"),
        ("npwp", "vat"),
    ):
        text = str(payload.get(source) or "").strip()
        if text:
            values[target] = text

    if not partner.odoo_id:
        values["customer_rank"] = 1 if payload.get("is_customer") else 0
        values["supplier_rank"] = 1 if payload.get("is_vendor") else 0

    return values


def _push_partner_to_odoo(partner: Partner, payload: dict) -> str:
    """``create``/``write`` partner di Odoo; kembalikan ``res.partner.id`` (str).

    ``create`` **boleh** (probe: tidak ada field wajib selain ``name`` yang dimiliki
    MES), jadi tidak ada data yang dikarang.
    """
    client = get_odoo_rpc_client()
    try:
        values = _partner_odoo_values(partner, payload)

        if partner.odoo_id:
            client.transport.write(ODOO_PARTNER_MODEL, [int(partner.odoo_id)], values)
            return str(partner.odoo_id)

        return str(client.transport.create(ODOO_PARTNER_MODEL, values))
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_partner",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_partner(self, partner_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.Partner`` ke ERP (lihat docstring modul)."""
    _bind_request_id(self)
    resource = SyncResource.MASTER_PARTNER.value

    try:
        partner = Partner.objects.filter(pk=partner_id).first()
        if partner is None:
            logger.warning("erp_sync.push_master_partner: partner %s tidak ada.", partner_id)
            return {"status": "not-found", "partner_id": partner_id}

        payload = partner_payload(partner)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, partner.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_partner: partner %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                partner.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(partner.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_partner: ERP_ADAPTER=%s -> no-op push partner %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    partner.pk,
                    erp_id,
                )
            else:
                erp_id = _push_partner_to_odoo(partner, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_PARTNER_PUSH,
                resource,
                partner.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not partner.odoo_id and str(erp_id).isdigit():
            partner.odoo_id = int(erp_id)
            partner.save(update_fields=("odoo_id",))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_PARTNER_PUSH,
            resource,
            partner.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(partner.pk),
            "odoo_id": partner.odoo_id,
        }
    finally:
        clear_request_id()


# ---------------------------------------------------------------------------
# H3.6 — master Tax (`account.tax`)
# ---------------------------------------------------------------------------
def tax_payload(tax: Tax) -> dict:
    """Payload master Tax (disimpan di ``SyncRecord.payload`` & dikirim ke ERP).

    ``tax_group_id`` **tidak** ada di payload: Odoo mengisinya sendiri lewat
    ``_compute_tax_group_id`` (probe STEP 0 + sumber Odoo 17) — mengirim nilai
    karangan justru berisiko salah grup.
    """
    return {
        "ref": tax.code,
        "code": tax.code,
        "name": tax.name,
        "amount": float(tax.amount or 0),
        "amount_type": tax.amount_type,
        "type_tax_use": tax.type_tax_use,
        "price_include": bool(tax.price_include),
        "active": bool(tax.is_active),
    }


def _tax_odoo_values(payload: dict) -> dict:
    """Petakan payload MES -> nilai ``account.tax`` Odoo (field tervalidasi probe)."""
    amount = float(payload.get("amount") or 0)
    if amount < 0:
        # Guard terakhir sebelum menembak Odoo (service sudah menahan 400).
        raise MasterPushError("amount pajak tidak boleh negatif.")

    amount_type = str(payload.get("amount_type") or Tax.AmountType.PERCENT).strip().lower()
    if amount_type not in Tax.AmountType.values:
        raise MasterPushError(
            f"amount_type {amount_type!r} tidak dikenal. "
            f"Pilihan: {', '.join(Tax.AmountType.values)}."
        )

    type_tax_use = str(payload.get("type_tax_use") or Tax.TaxUse.SALE).strip().lower()
    if type_tax_use not in Tax.TaxUse.values:
        raise MasterPushError(
            f"type_tax_use {type_tax_use!r} tidak dikenal. "
            f"Pilihan: {', '.join(Tax.TaxUse.values)}."
        )

    name = str(payload.get("name") or payload.get("code") or "").strip()
    if not name:
        raise MasterPushError("name pajak wajib diisi untuk push ke Odoo.")

    return {
        "name": name,
        "amount": amount,
        "amount_type": amount_type,
        "type_tax_use": type_tax_use,
        "price_include": bool(payload.get("price_include", False)),
        "active": bool(payload.get("active", True)),
    }


def _push_tax_to_odoo(tax: Tax, payload: dict) -> str:
    """``create``/``write`` pajak di Odoo; kembalikan ``account.tax.id`` (str)."""
    client = get_odoo_rpc_client()
    try:
        transport = client.transport
        values = _tax_odoo_values(payload)

        if tax.odoo_id:
            transport.write(ODOO_TAX_MODEL, [int(tax.odoo_id)], values)
            return str(tax.odoo_id)

        return str(transport.create(ODOO_TAX_MODEL, values))
    finally:
        client.close()


@shared_task(
    bind=True,
    name="erp_sync.push_master_tax",
    autoretry_for=RETRY_EXCEPTIONS,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def push_master_tax(self, tax_id: int, sync_record_id: int | None = None) -> dict:
    """Kirim satu ``master.Tax`` ke ERP (lihat docstring modul)."""
    _bind_request_id(self)
    resource = SyncResource.MASTER_TAX.value

    try:
        tax = Tax.objects.filter(pk=tax_id).first()
        if tax is None:
            logger.warning("erp_sync.push_master_tax: Tax %s tidak ada.", tax_id)
            return {"status": "not-found", "tax_id": tax_id}

        payload = tax_payload(tax)
        sync = SyncIdempotency()

        record = (
            SyncRecord.objects.filter(pk=sync_record_id).first()
            if sync_record_id is not None
            else None
        )
        if record is None:
            record = sync.get_or_create_sync_record(
                resource, tax.pk, SyncStage.MASTER_PUSH.value, payload
            )

        if sync.is_already_sent(record) and dict(record.payload or {}) == payload:
            logger.info(
                "erp_sync.push_master_tax: Tax %s sudah terkirim & payload sama "
                "-> enqueue diabaikan.",
                tax.pk,
            )
            return {
                "status": "duplicate-ignored",
                "erp_id": record.erp_id,
                "sync_record_id": record.pk,
                "resource": resource,
                "resource_id": str(tax.pk),
            }

        try:
            if is_noop_mode():
                erp_id = f"NULL-{uuid4()}"
                logger.info(
                    "erp_sync.push_master_tax: ERP_ADAPTER=%s -> no-op push Tax %s (%s).",
                    getattr(settings, "ERP_ADAPTER", "") or "-",
                    tax.pk,
                    erp_id,
                )
            else:
                erp_id = _push_tax_to_odoo(tax, payload)
        except Exception as exc:  # noqa: BLE001 - dicatat dulu, lalu di-raise utk retry
            sync.mark_failed(record, exc)
            log_push(
                ACTION_MASTER_TAX_PUSH,
                resource,
                tax.pk,
                status="failed",
                error=exc,
                task_id=self.request.id,
                payload=payload,
            )
            raise

        if not tax.odoo_id and str(erp_id).isdigit():
            tax.odoo_id = int(erp_id)
            tax.save(update_fields=("odoo_id",))

        sync.mark_sent(record, erp_id)
        log_push(
            ACTION_MASTER_TAX_PUSH,
            resource,
            tax.pk,
            status="sent",
            erp_id=erp_id,
            task_id=self.request.id,
            payload=payload,
        )

        return {
            "status": "sent",
            "erp_id": erp_id,
            "sync_record_id": record.pk,
            "resource": resource,
            "resource_id": str(tax.pk),
            "odoo_id": tax.odoo_id,
        }
    finally:
        clear_request_id()

