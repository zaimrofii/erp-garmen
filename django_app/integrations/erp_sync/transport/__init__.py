"""Transport master data Odoo (read-only) — lihat :mod:`.odoo_transport`."""

from .factory import get_transport
from .odoo_transport import OdooTransport

__all__ = ("OdooTransport", "get_transport")
