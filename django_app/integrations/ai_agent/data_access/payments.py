"""Repository payment (inbound/outbound)."""

from __future__ import annotations

from apps_industry.garment.models import Payment

from .base import BaseRepository


class PaymentRepository(BaseRepository):
    model = Payment
    order_by = ["-created_at"]
    serialize_fields = [
        "id",
        "code",
        "payment_type",
        "state",
        "amount",
        "payment_date",
    ]


__all__ = ("PaymentRepository",)
