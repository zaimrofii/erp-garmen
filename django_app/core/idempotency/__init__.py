"""App `core.idempotency` — penyimpan hasil aksi POST (idempotency, kontrak §5.1).

Generik (tidak tahu garmen): `resource`/`resource_id`/`action` hanya string,
sehingga app industri mana pun bisa memakai tabel & service yang sama.

Catatan: file ini sengaja TIDAK mengimpor `models`/`services` — Django memuat
paket app sebelum app registry siap, jadi mengimpor model di sini memicu
`AppRegistryNotReady`. Import langsung dari modulnya, mis.
`from core.idempotency.services import IdempotencyService`.
"""
