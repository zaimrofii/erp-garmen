"""App `integrations.wa_bot` — WhatsApp gateway (stub, mock-first).

Fase 5 (Sprint 5.1). Isi paket:

  * ``services.py`` : ``WAGateway`` (kontrak), ``MockWAGateway`` (implementasi
    tanpa jaringan untuk dev/test), ``WAResponse``/``WAMessage`` dan factory
    :func:`get_wa_gateway` yang memilih implementasi dari ``settings.WA_BACKEND``.

Belum ada implementasi ke penyedia WA sungguhan (Cloud API/Wablas dsb) — itu
menyusul di fase berikutnya; kontraknya sudah disiapkan supaya penukaran
implementasi tidak menyentuh kode pemanggil (notifikasi/approval HITL).
"""
