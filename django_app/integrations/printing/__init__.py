"""App `integrations.printing` — cetak thermal ESC/POS (bundle tag + kupon).

Fase 5 (Sprint 5.1). Isi paket:

  * ``escpos.py``      : driver ESC/POS minimal (tanpa library eksternal — paket
    ``python-escpos`` butuh libusb sehingga akan memaksa perubahan Dockerfile);
  * ``bundle_tag.py``  : layout **BUNDLE TAG** (QR + barcode + info bundle);
  * ``coupon.py``      : layout **KUPON** piece-rate (dari OrderLine);
  * ``backends/``      : tujuan pengiriman bytes (mock / usb stub / network);
  * ``models.py``      : ``PrintJob`` = audit trail setiap percobaan cetak.

Modul ini TIDAK memuat aturan bisnis dan tidak menyentuh app domain: ia hanya
mengubah objek domain menjadi bytes ESC/POS lalu menyerahkannya ke backend.
"""
