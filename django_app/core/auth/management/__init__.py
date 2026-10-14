"""Kode operator (F6.1) — generate + backfill `User.operator_code`.

Isi file ini paralel dengan `core/auth/models.py`: logika generate ada di
`generate_unique_operator_code()` (dipakai `User.save()`), perintah ini hanya
menjalankannya untuk user lama yang belum punya kode.
"""
