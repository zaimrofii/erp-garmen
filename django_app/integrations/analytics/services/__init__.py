"""Service layer analytics — SATU pintu evaluasi toggle (TOGGLE-CONTRACT §5–§6).

Modul ini satu-satunya tempat yang boleh membaca `AnalyticsConfig` untuk
keperluan keputusan (endpoint, MCP, AI). Pemanggil lain DILARANG query model
langsung atau memanggil endpoint HTTP.
"""

__all__: tuple[str, ...] = ()
