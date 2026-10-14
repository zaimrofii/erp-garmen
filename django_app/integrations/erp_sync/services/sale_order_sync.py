"""Service sync Sales Order Odoo → ``Order``/``OrderLine`` MES (fase I2).

Read-only lewat :class:`~integrations.erp_sync.transport.OdooTransport`;
idempotensi lewat field ``odoo_id`` di ``Order``/``OrderLine`` — repo **tidak**
punya model ``OdooMapping``. Tidak memanggil Odoo langsung & tidak memakai Celery.

Pemetaan (hanya field yang SUDAH ADA di model — tanpa menambah field baru):

* ``sale.order.partner_id`` → ``Partner.odoo_id`` → ``Order.customer``;
* ``sale.order.line.product_id`` = id ``product.product`` (**varian**) →
  ``Product.odoo_id`` → ``OrderLine.product``;
* FK yang tidak ketemu → baris **tetap disimpan** dengan FK ``None`` dan
  dihitung ``skipped`` (konsisten gaya ``_sync`` di ``tasks_master``).

H2.1 menambah dua pemetaan **aditif** (yang sebelumnya sengaja dilewati):

* ``sale.order.client_order_ref`` → ``Order.client_order_ref`` (nomor MES yang
  dikirim saat push); kalau ``client_order_ref`` order sudah berisi nomor MES
  (``SO-2026-0001``), **``Order.code`` TIDAK ditimpa** nama Odoo (``S00033``);
* ``sale.order.line.price_unit`` → ``OrderLine.price_unit`` (Decimal).

Field Odoo lain yang tetap tidak dipetakan (tidak ada padanannya di MES):
``amount_total``, ``currency_id``, ``date_order``, ``product_uom``, ``state`` Odoo.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal, InvalidOperation

from apps_industry.garment.models import Order, OrderLine
from master.models import Partner, Product

from ..transport import get_transport

logger = logging.getLogger(__name__)

__all__ = ("MES_ORDER_REF_PATTERN", "SaleOrderSyncService")

#: Pola nomor MES (Sprint C): ``<PREFIX>-<TAHUN>-<SEQ>``, mis. ``SO-2026-0001``.
#: Dipakai H2.1 untuk **tidak menimpa** ``Order.code`` milik order yang lahir di MES:
#: tanpa guard ini, pull akan mengganti ``SO-2026-0001`` dengan nama Odoo (``S00033``).
MES_ORDER_REF_PATTERN = re.compile(r"^[A-Z]{2,6}-\d{4}-\d{1,10}$")


def is_mes_order_ref(value) -> bool:
    """True kalau ``value`` berbentuk nomor MES Sprint C (``SO-2026-0001``)."""
    return bool(MES_ORDER_REF_PATTERN.match(str(value or "").strip()))



def _first_id(value):
    """Ambil id dari field many2one Odoo (``[id, name]`` → ``id``)."""
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value or None


def _order_code(row):
    """Kode order (``unique``): ``sale.order.name`` atau fallback deterministik."""
    return str(row.get("name") or f"ODOO-SO-{row.get('id')}")


def _int_qty(value):
    """``product_uom_qty`` (float Odoo) → ``OrderLine.qty`` (PositiveIntegerField)."""
    try:
        return max(int(float(value or 0)), 0)
    except (TypeError, ValueError):
        return 0


def _decimal_price(value) -> Decimal:
    """``price_unit`` (float Odoo) → ``OrderLine.price_unit`` (Decimal 2 desimal)."""
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


class SaleOrderSyncService:
    """Tarik SO Odoo (``state='sale'``) → ``Order`` + ``OrderLine`` MES."""

    def __init__(self, transport=None):
        """``transport`` opsional (untuk test); ``None`` → :func:`get_transport`."""
        self.transport = transport

    # ------------------------------------------------------------------- public
    def sync(self, since=None):
        """Sinkronkan SO → upsert ``Order`` + ``OrderLine`` lewat ``odoo_id``.

        Return ``{"created": N, "updated": N, "skipped": N}`` (gaya ``_sync``).
        """
        transport = self.transport if self.transport is not None else get_transport()
        try:
            order_rows = transport.fetch_sale_orders(since=since)
            created = updated = skipped = 0

            for row in order_rows or []:
                order_odoo_id = row.get("id")
                if order_odoo_id is None:
                    skipped += 1
                    continue

                partner = self._resolve_partner(row)
                odoo_ref = str(row.get("client_order_ref") or "").strip()
                order = Order.objects.filter(odoo_id=order_odoo_id).first()
                if order is None:
                    order = Order.objects.create(
                        odoo_id=order_odoo_id,
                        code=_order_code(row),
                        customer=partner,
                        client_order_ref=odoo_ref,
                    )
                    created += 1
                else:
                    # H2.1 — order yang lahir di MES menyimpan nomornya di
                    # `client_order_ref`; nama Odoo (`S00033`) TIDAK boleh menimpa
                    # `SO-2026-0001` (kalau ditimpa, jejak nomor MES hilang).
                    if not is_mes_order_ref(order.client_order_ref):
                        order.code = _order_code(row)
                    if not order.client_order_ref and odoo_ref:
                        order.client_order_ref = odoo_ref
                    order.customer = partner
                    order.save(update_fields=("code", "customer", "client_order_ref", "updated_at"))
                    updated += 1
                if partner is None:
                    skipped += 1

                lines = self._sync_lines(transport, order, order_odoo_id, since)
                created += lines["created"]
                updated += lines["updated"]
                skipped += lines["skipped"]

            return {"created": created, "updated": updated, "skipped": skipped}
        finally:
            if self.transport is None:  # tutup hanya kalau kita yang membangunnya
                transport.close()

    # ---------------------------------------------------------------- internal
    @staticmethod
    def _resolve_partner(row):
        """``res.partner`` Odoo → ``master.Partner`` (``None`` kalau belum tersinkron)."""
        partner_odoo_id = _first_id(row.get("partner_id"))
        partner = Partner.objects.filter(odoo_id=partner_odoo_id).first()
        if partner is None:
            logger.warning(
                "sale_order_sync: partner %s belum tersinkron -> Order %s tanpa customer.",
                partner_odoo_id,
                row.get("id"),
            )
        return partner

    def _sync_lines(self, transport, order, order_odoo_id, since):
        """Upsert ``sale.order.line`` milik satu SO → counter ``{created,...}``."""
        rows = transport.fetch_sale_order_lines([order_odoo_id], since=since)
        created = updated = skipped = 0

        for row in rows or []:
            line_odoo_id = row.get("id")
            if line_odoo_id is None:
                skipped += 1
                continue

            product = self._resolve_product(row)
            line_defaults = {
                "order": order,
                "product": product,
                "qty": _int_qty(row.get("product_uom_qty")),
                "price_unit": _decimal_price(row.get("price_unit")),
            }
            _, was_created = OrderLine.objects.update_or_create(
                odoo_id=line_odoo_id,
                defaults=line_defaults,
            )
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
            if product is None:
                skipped += 1

        return {"created": created, "updated": updated, "skipped": skipped}

    @staticmethod
    def _resolve_product(row):
        """``product.product`` (varian) → ``master.Product`` via ``Product.odoo_id``."""
        product_odoo_id = _first_id(row.get("product_id"))
        product = Product.objects.filter(odoo_id=product_odoo_id).first()
        if product is None:
            logger.warning(
                "sale_order_sync: produk %s belum tersinkron -> line %s tanpa product.",
                product_odoo_id,
                row.get("id"),
            )
        return product
