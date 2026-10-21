"""Repository partner (customer/vendor)."""

from __future__ import annotations

from master.models import Partner

from .base import BaseRepository


class PartnerRepository(BaseRepository):
    model = Partner
    order_by = ["name"]
    serialize_fields = ["id", "code", "name", "is_customer", "is_vendor", "city"]


__all__ = ("PartnerRepository",)
