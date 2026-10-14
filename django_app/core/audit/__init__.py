"""App `core.audit` — audit trail aksi penting (Fase 6, hardening).

Isi paket:

  * ``models.py``   : ``AuditLog`` (siapa melakukan apa, kapan, dari mana);
  * ``services.py`` : ``AuditLogger`` (helper menulis log dari request/view);
  * ``admin.py``    : tampilan audit read-only (tanpa tambah/ubah/hapus).

Catatan penting: file ini SENGAJA tidak mengimpor models apa pun (Django memuat
paket app sebelum app registry siap -> AppRegistryNotReady).
"""
