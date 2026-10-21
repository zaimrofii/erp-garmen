"""Repository customer invoice (JOIN customer)."""

from __future__ import annotations

from apps_industry.garment.models import CustomerInvoice

from .base import BaseRepository


class InvoiceRepository(BaseRepository):
    model = CustomerInvoice
    join_spec = ["customer"]
    order_by = ["-created_at"]
    serialize_fields = [
        "id",
        "code",
        "state",
        "invoice_date",
        "amount_total",
    ]
    serialize_joins = {
        "customer_id": "customer.id",
        "customer_name": "customer.name",
        "customer_code": "customer.code",
    }


__all__ = ("InvoiceRepository",)
