"""Task Celery untuk sinkronisasi master data dari Odoo.

Masih kosong: belum ada task bisnis. Task di modul ini memakai nama default
Celery (``master.tasks.<nama>``) sehingga masuk queue ``default``;
task khusus sinkronisasi ERP ditulis di
`integrations/erp_sync/tasks.py` dan otomatis di-route ke queue
``erp_sync`` (lihat `CELERY_TASK_ROUTES` di settings).
"""


import logging

logger = logging.getLogger(__name__)

# TODO: task sinkronisasi master data (product, partner, uom, workcenter, ...)
# menyusul setelah mapping data Django <-> Odoo disepakati.
