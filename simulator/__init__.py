"""Simulator garmen — klien API murni untuk Django (fase M1).

Paket ini SENGAJA terpisah dari ``django_app``: ia tidak mengimpor Django dan
tidak menyentuh database, hanya "berbicara" ke REST API Django seperti klien
biasa. Lihat ``konsep-dasar.md`` untuk prinsip dan batasannya.
"""
